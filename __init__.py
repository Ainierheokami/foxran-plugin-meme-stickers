import asyncio
import json
from .backend.tool import MemeStickerTool, resolve_meme_schema, load_tools
from .backend.api import router
from app.utils.hooks import plugin_hooks
from app.logger import setup_logger

logger = setup_logger(__name__)

# 注册 Hook：拦截并处理表情包发送
@plugin_hooks.register("process_outbound_message_chain")
async def process_outbound_message_chain(message_chain, session_ctx=None, **kwargs):
    from app.data_mappers.schemas import MessageSegments, MemeSchema
    if not isinstance(message_chain, MessageSegments):
        return message_chain

    has_meme = any(isinstance(seg, MemeSchema) for seg in message_chain)
    if not has_meme:
        return message_chain

    resolved_chain = MessageSegments()
    for seg in message_chain:
        if isinstance(seg, MemeSchema):
            try:
                image_seg = await asyncio.to_thread(resolve_meme_schema, seg, session_ctx)
            except Exception as e:
                logger.warning(f"[表情包插件] 片段解析失败: {seg}, {e}")
                image_seg = None
            if image_seg:
                resolved_chain.append(image_seg)
            else:
                logger.warning(f"[表情包插件] 未匹配到可用表情包，已丢弃片段: {seg}")
            continue
        resolved_chain.append(seg)
    return resolved_chain

# 注册 Hook：注入 Prompt
@plugin_hooks.register("before_prompt_build")
async def before_prompt_build(context_vars, session_ctx=None, current_message=None, tool_manager=None, **kwargs):
    from .backend.tool import _load_library
    import time
    
    if not current_message or current_message.role != "user":
        return context_vars
    if session_ctx.is_subagent:
        return context_vars
    if not tool_manager or not tool_manager.get_tool("meme_sticker"):
        return context_vars

    try:
        from app.config import load_meme_sticker_config
        meme_cfg = load_meme_sticker_config().prompt
    except Exception as e:
        logger.debug(f"[表情包插件] 读取配置失败: {e}")
        return context_vars

    if not meme_cfg.enabled:
        return context_vars

    platform = (session_ctx.platform or "").lower()
    allowed_platforms = [str(item).lower() for item in meme_cfg.allowed_platforms or []]
    if allowed_platforms and not any(item in platform for item in allowed_platforms):
        return context_vars

    state = session_ctx.session_notes.setdefault("meme_sticker_state", {})
    if state.get("opt_out"):
        return context_vars

    try:
        stickers = [
            item for item in _load_library().get("stickers", [])
            if item.get("enabled", True) and item.get("url")
        ]
    except Exception:
        return context_vars
    if not stickers:
        return context_vars

    now = time.time()
    cooldown_seconds = max(0, int(meme_cfg.cooldown_seconds or 0))
    if now - float(state.get("last_sticker_at") or 0) < cooldown_seconds:
        return context_vars

    text = str(current_message.content or "").lower()
    blocked_keywords = [str(keyword).lower() for keyword in meme_cfg.blocked_keywords or []]
    if any(keyword and keyword in text for keyword in blocked_keywords):
        state["prompt_active"] = False
        state["prompt_turns"] = 0
        return context_vars

    prompt_active = bool(state.get("prompt_active")) and bool(meme_cfg.persist_until_sent)
    if prompt_active:
        prompt_turns = int(state.get("prompt_turns") or 0)
        max_persistent_turns = max(0, int(meme_cfg.max_persistent_turns or 0))
        if max_persistent_turns and prompt_turns >= max_persistent_turns:
            state["prompt_active"] = False
            state["prompt_turns"] = 0
            state["turns_since_sticker"] = 0
            return context_vars
    else:
        turns = int(state.get("turns_since_sticker") or 0) + 1
        state["turns_since_sticker"] = turns
        min_messages = max(1, int(meme_cfg.min_messages_between_prompts or 1))
        if turns < min_messages:
            return context_vars

    tool_instance = tool_manager.get_tool("meme_sticker")
    schema = tool_instance.get_input_schema_for_llm()
    tool_block = f"""
- meme_sticker:
  功能说明: {tool_instance.description}
  参数定义 (JSON): {json.dumps(schema, ensure_ascii=False)}
"""
    light_prompt = """
[表情包机会提示]
本轮对话气氛允许使用表情包。你可以在自然回复后，酌情追加 1 个 `[meme, emotion=..., tags=...]` 片段增强语气；系统会自动从表情包库选图发送，不要手写图片 URL。
使用边界：
- 只在轻松、感谢、庆祝、调侃、安慰、缓和尴尬、表达赞同等场景使用。
- 严肃求助、隐私话题、争执、用户不耐烦、密集技术排障、医疗/法律/金融风险话题不要使用。
- 一次回复最多 1 张；如果文字表达已经足够自然，可以不使用。
- 推荐格式：`[meme, emotion=thanks, tags=感谢,捧场]` 或 `[meme, query=当前语境和想表达的语气]`。
- emotion 可用 happy、thanks、agree、tease、awkward、surprised、comfort、sorry、confused。
"""
    combined = f"{context_vars.get('recommended_tools', '')}\n{tool_block}{light_prompt}"
    context_vars["recommended_tools"] = combined.strip()
    state["last_prompt_at"] = now
    if meme_cfg.persist_until_sent:
        state["prompt_active"] = True
        state["prompt_turns"] = int(state.get("prompt_turns") or 0) + 1
    else:
        state["prompt_active"] = False
        state["prompt_turns"] = 0
        state["turns_since_sticker"] = 0
        
    return context_vars

# 导出供外部使用的核心模块
__all__ = ["MemeStickerTool", "router", "load_tools"]
