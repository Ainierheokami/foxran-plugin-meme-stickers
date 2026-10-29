"""Prompt hints that tell the agent when it can send, collect or draw stickers.

Three kinds of hint, from cheapest to strongest:

* capability: every turn, one short line that ``[meme, ...]`` exists and what
  the library holds, so the agent can send stickers on its own;
* opportunity: on paced turns (spacing, cooldown, no serious keywords) a
  direct suggestion to attach one sticker this turn;
* collect: when the user's message, or a recent message the agent did not
  answer, carries a sticker image, a suggestion to save it with
  ``meme_sticker collect``.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from .tool import IMAGE_TAG_RE, LIBRARY_PATH, _load_library, find_image_tags


EMOTIONS = "happy、thanks、agree、tease、awkward、surprised、comfort、sorry、confused、sleepy"
# Explicit asks for a sticker skip the pacing rules.
REQUEST_PATTERNS = ("表情包", "发个表情", "来个表情", "来张表情", "斗图", "发张图", "sticker", "meme")
MAX_COLLECT_HINTS_PER_SESSION = 30
# 群聊里她不回的消息不会生成提示词，表情包只留在历史里；开口时回看这么多条
RECENT_MESSAGES_FOR_COLLECT = 20

_library_cache: Dict[str, Any] = {"mtime": None, "summary": None}


def library_summary() -> Dict[str, Any]:
    """Enabled sticker count plus the most common emotions and tags (cached by mtime)."""
    try:
        mtime = LIBRARY_PATH.stat().st_mtime if LIBRARY_PATH.exists() else 0.0
    except OSError:
        mtime = 0.0
    if _library_cache["summary"] is not None and _library_cache["mtime"] == mtime:
        return _library_cache["summary"]

    stickers = [
        item for item in _load_library().get("stickers", [])
        if item.get("enabled", True) and item.get("url")
    ]
    emotions = Counter(str(item.get("emotion") or "").lower() for item in stickers if item.get("emotion"))
    tags = Counter(str(tag) for item in stickers for tag in (item.get("tags") or []) if str(tag).strip())
    summary = {
        "count": len(stickers),
        "emotions": [name for name, _ in emotions.most_common(10)],
        "tags": [name for name, _ in tags.most_common(16)],
    }
    _library_cache.update(mtime=mtime, summary=summary)
    return summary


def keyword_hit(text: str, keywords: Iterable[str]) -> bool:
    """Substring match for CJK keywords; whole-word match for ASCII ones (so ``error`` misses ``terror``)."""
    lowered = (text or "").lower()
    for raw in keywords or []:
        keyword = str(raw or "").strip().lower()
        if not keyword:
            continue
        if keyword.isascii():
            if re.search(rf"(?<![a-z0-9_]){re.escape(keyword)}(?![a-z0-9_])", lowered):
                return True
        elif keyword in lowered:
            return True
    return False


def sticker_images(text: str, summary_keywords: Iterable[str]) -> List[Dict[str, str]]:
    """Images in the message whose summary marks them as stickers (QQ: ``[动画表情]``)."""
    keywords = [str(word).lower() for word in summary_keywords or [] if str(word).strip()]
    found = []
    for image in find_image_tags(text):
        summary = image.get("summary", "").lower()
        url = image.get("url", "").lower()
        if any(word in summary for word in keywords) or url.split("?", 1)[0].endswith(".gif"):
            found.append(image)
    return found


def _library_line(summary: Dict[str, Any]) -> str:
    parts = [f"库里共 {summary['count']} 张"]
    if summary["emotions"]:
        parts.append("已有情绪：" + "、".join(summary["emotions"]))
    if summary["tags"]:
        parts.append("常用标签：" + "、".join(summary["tags"]))
    return "；".join(parts) + "。"


def capability_hint(summary: Dict[str, Any]) -> str:
    return (
        "[表情包] 你可以像真人一样斗图：在回复文字后追加一个 `[meme, emotion=..., tags=...]` 片段，"
        "系统会自动从表情包库挑图发送（不要手写图片 URL，每条回复最多 1 张）。"
        f"{_library_line(summary)}闲聊、玩笑、感谢、安慰时可以主动用；严肃话题不要用。"
    )


def opportunity_hint(summary: Dict[str, Any], *, requested: bool, can_draw: bool, can_draw_self: bool = False) -> str:
    lines = ["[表情包机会]"]
    if summary["count"]:
        if requested:
            lines.append("用户在要表情包或刚发来表情包想斗图，这轮请回 1 张。")
        else:
            lines.append(
                "这轮气氛适合发表情包：请在文字回复后附 1 个 `[meme, ...]` 片段，"
                "只有内容严肃、用户情绪低落或文字里已经发过图时才省略。"
            )
        lines.append("格式：`[meme, emotion=thanks, tags=感谢,捧场]` 或 `[meme, query=当前语境和想表达的语气]`。")
        lines.append(f"emotion 可用：{EMOTIONS}；尽量用库里已有的情绪和标签。")
    else:
        lines.append("表情包库还是空的，暂时不能用 `[meme, ...]`。")
    if can_draw:
        lines.append(
            "库里没有贴切的图、或用户想要定制表情包时，可以调用 meme_sticker operation=generate"
            "（prompt=画面描述, caption=简短配字, emotion, tags）现画一张，画好会直接发送并入库；"
            "operation=remake 可以复刻/改画用户发来的表情包。绘图较慢，别每轮都画。"
        )
    if can_draw and can_draw_self:
        lines.append(
            "要画你自己（比如“画个你自己的表情包”、用你的形象复刻别人的梗图）时加 as_self=true，"
            "会照你人设卡的形象参考图画，长得才是你。"
        )
    return "\n".join(lines)


def collect_hint(images: List[Dict[str, str]]) -> str:
    refs = "\n".join(f"- url={image['url']} summary={image.get('summary') or '-'}" for image in images[:3])
    return (
        "[表情包收集] 这条消息或最近的聊天里有表情包：\n"
        f"{refs}\n"
        "如果它有趣、可复用且不含隐私（不是私人照片、证件、聊天截图），可以调用 meme_sticker operation=collect, "
        "url=上面的地址，并用你看到的画面填写 summary、emotion、tags 收进表情包库，以后斗图用；"
        "收集结果只有你看得到。也可以顺手回一张表情包。"
    )


def tool_block(tool_instance: Any) -> str:
    schema = tool_instance.get_input_schema_for_llm()
    return (
        "- meme_sticker:\n"
        f"  功能说明: {tool_instance.description}\n"
        f"  参数定义 (JSON): {json.dumps(schema, ensure_ascii=False)}"
    )


def build_hints(
    *,
    prompt_cfg: Any,
    collection_cfg: Any,
    state: Dict[str, Any],
    text: str,
    summary: Dict[str, Any],
    can_draw: bool,
    now: Optional[float] = None,
    recent_texts: Iterable[str] = (),
    can_draw_self: bool = False,
) -> tuple[List[str], bool]:
    """Pick this turn's hints and advance the pacing state.

    ``recent_texts`` are earlier user messages, newest first; stickers in them
    are offered for collection too, but only this message's stickers invite a
    sticker back.

    Returns ``(hints, needs_tool_schema)``; the schema is only needed when a
    hint asks the agent to call ``meme_sticker``.
    """
    now = time.time() if now is None else now
    hints: List[str] = []
    needs_tool = False

    keywords = collection_cfg.sticker_summary_keywords
    incoming = sticker_images(text, keywords)
    if collection_cfg.suggest_collect:
        seen = state.setdefault("collect_hinted_urls", [])
        candidates = incoming + [image for earlier in recent_texts for image in sticker_images(earlier, keywords)]
        fresh: List[Dict[str, str]] = []
        for image in candidates:
            if image["url"] not in seen and all(image["url"] != item["url"] for item in fresh):
                fresh.append(image)
        # 一次只提 3 张，其余留到下一轮
        fresh = fresh[:3]
        if fresh:
            hints.append(collect_hint(fresh))
            needs_tool = True
            seen.extend(image["url"] for image in fresh)
            del seen[:-MAX_COLLECT_HINTS_PER_SESSION]

    if not summary["count"] and not can_draw:
        return hints, needs_tool

    # Image URLs and summaries are not the user's words.
    words = IMAGE_TAG_RE.sub(" ", text or "")
    blocked = keyword_hit(words, prompt_cfg.blocked_keywords or [])
    # A sticker from the user invites one back, like an explicit ask.
    requested = not blocked and (keyword_hit(words, REQUEST_PATTERNS) or bool(incoming))
    opportunity = False
    if requested:
        opportunity = True
    elif blocked:
        state["prompt_active"] = False
        state["prompt_turns"] = 0
    else:
        cooldown = max(0, int(prompt_cfg.cooldown_seconds or 0))
        cooling = now - float(state.get("last_sticker_at") or 0) < cooldown
        if bool(state.get("prompt_active")) and prompt_cfg.persist_until_sent:
            prompt_turns = int(state.get("prompt_turns") or 0)
            max_turns = max(0, int(prompt_cfg.max_persistent_turns or 0))
            if max_turns and prompt_turns >= max_turns:
                state["prompt_active"] = False
                state["prompt_turns"] = 0
                state["turns_since_sticker"] = 0
            else:
                opportunity = not cooling
        else:
            turns = int(state.get("turns_since_sticker") or 0) + 1
            state["turns_since_sticker"] = turns
            spacing = max(1, int(prompt_cfg.min_messages_between_prompts or 1))
            opportunity = turns >= spacing and not cooling

    if opportunity:
        hints.append(opportunity_hint(summary, requested=requested, can_draw=can_draw, can_draw_self=can_draw_self))
        needs_tool = needs_tool or can_draw
        state["last_prompt_at"] = now
        if prompt_cfg.persist_until_sent:
            state["prompt_active"] = True
            state["prompt_turns"] = int(state.get("prompt_turns") or 0) + 1
        else:
            state["prompt_active"] = False
            state["prompt_turns"] = 0
            state["turns_since_sticker"] = 0
    elif summary["count"] and prompt_cfg.always_show_capability and not blocked:
        hints.append(capability_hint(summary))

    return hints, needs_tool
