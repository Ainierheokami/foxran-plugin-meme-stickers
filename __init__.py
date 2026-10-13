import asyncio
from .backend.segment import is_meme_segment, register_meme_segment, unregister_meme_segment
from .backend.tool import MemeStickerTool, resolve_meme_segment, load_tools
from .backend.api import router
from app.utils.hooks import plugin_hooks
from app.logger import setup_logger

logger = setup_logger(__name__)

# 注册 Hook：拦截并处理表情包发送
async def process_outbound_message_chain(message_chain, session_ctx=None, **kwargs):
    from app.message import MessageChain
    if not isinstance(message_chain, MessageChain):
        return message_chain

    if not any(is_meme_segment(seg) for seg in message_chain):
        return message_chain

    resolved_chain = MessageChain()
    for seg in message_chain:
        if is_meme_segment(seg):
            try:
                image_seg = await asyncio.to_thread(resolve_meme_segment, seg, session_ctx)
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
async def before_prompt_build(context_vars, session_ctx=None, current_message=None, tool_manager=None, **kwargs):
    from .backend import generation, prompt
    from .backend.config import load_config

    if not current_message or current_message.role != "user":
        return context_vars
    if session_ctx is None or session_ctx.is_subagent:
        return context_vars
    tool_instance = tool_manager.get_tool("meme_sticker") if tool_manager else None
    if not tool_instance:
        return context_vars

    try:
        meme_cfg = load_config()
    except Exception as e:
        logger.debug(f"[表情包插件] 读取配置失败: {e}")
        return context_vars

    prompt_cfg = meme_cfg.prompt
    if not prompt_cfg.enabled:
        return context_vars

    platform = (session_ctx.platform or "").lower()
    allowed_platforms = [str(item).lower() for item in prompt_cfg.allowed_platforms or []]
    if allowed_platforms and not any(item in platform for item in allowed_platforms):
        return context_vars

    state = session_ctx.session_notes.setdefault("meme_sticker_state", {})
    if state.get("opt_out"):
        return context_vars

    try:
        summary = prompt.library_summary()
    except Exception as e:
        logger.debug(f"[表情包插件] 读取表情包库失败: {e}")
        return context_vars

    can_draw = meme_cfg.generation.hint_enabled and generation.generation_available()
    hints, needs_tool = prompt.build_hints(
        prompt_cfg=prompt_cfg,
        collection_cfg=meme_cfg.collection,
        state=state,
        text=str(current_message.content or ""),
        summary=summary,
        can_draw=can_draw,
    )
    if not hints:
        return context_vars

    if needs_tool:
        hints.insert(0, prompt.tool_block(tool_instance))
    # Rendered by the host as <plugin-hints> inside the runtime <tools> block.
    plugin_hints = context_vars.get("plugin_prompt_hints")
    if not isinstance(plugin_hints, list):
        plugin_hints = []
    plugin_hints.extend({"source": "meme_stickers", "text": hint} for hint in hints)
    context_vars["plugin_prompt_hints"] = plugin_hints
    return context_vars


# Chat platforms fetch sticker images without logging in.
PUBLIC_GET_PREFIXES = ("/api/stickers/assets/", "/api/stickers/send/", "/api/stickers/thumb/")


def _register_hooks() -> None:
    """Register plugin callbacks idempotently."""
    from app.api.public_paths import register_public_get_prefix

    for prefix in PUBLIC_GET_PREFIXES:
        register_public_get_prefix(prefix, owner=__name__)
    register_meme_segment()
    plugin_hooks.register("process_outbound_message_chain", process_outbound_message_chain)
    plugin_hooks.register("before_prompt_build", before_prompt_build)


async def startup() -> None:
    """Initialize module resources after the plugin is loaded."""
    from .backend.migrations import run_migrations

    await asyncio.to_thread(run_migrations)
    logger.info("Meme sticker plugin started")


async def enable() -> None:
    """Expose plugin callbacks while the installed plugin is enabled."""
    _register_hooks()
    logger.info("Meme sticker plugin enabled")


async def disable() -> None:
    """Withdraw plugin callbacks without uninstalling plugin files."""
    plugin_hooks.unregister("process_outbound_message_chain", process_outbound_message_chain)
    plugin_hooks.unregister("before_prompt_build", before_prompt_build)
    unregister_meme_segment()
    from app.api.public_paths import unregister_owner

    unregister_owner(__name__)
    logger.info("Meme sticker plugin disabled")


async def shutdown() -> None:
    """Release runtime integrations before the plugin is hot-unloaded."""
    await disable()
    logger.info("Meme sticker plugin stopped")

# 导出供外部使用的核心模块
__all__ = ["MemeStickerTool", "router", "load_tools", "startup", "enable", "disable", "shutdown"]
