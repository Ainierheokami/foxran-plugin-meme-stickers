"""The ``meme_stickers.meme`` extension segment and its ``[meme, ...]`` agent tag.

The plugin owns this segment type (host ADR 0003). The model writes
``[meme, emotion=..., tags=a,b, ...]``; the outbound hook resolves it to an
image from the sticker library before any adapter encodes the message.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Union

from app.message import ExtensionSegment, Segment, Text, segment_registry
from app.message.registry import register_segment_type


MEME_SEGMENT_TYPE = "meme_stickers.meme"
MEME_TAG = "meme"
MEME_FALLBACK_TEXT = "[表情包]"
_SELECTOR_KEYS = ("id", "emotion", "tags", "summary", "query")


def normalize_meme_tags(tags: Optional[Union[str, Iterable[str]]]) -> list[str]:
    if tags is None:
        return []
    raw_tags = tags.split(",") if isinstance(tags, str) else list(tags)
    seen: set[str] = set()
    result: list[str] = []
    for tag in raw_tags:
        clean = str(tag).strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def make_meme_segment(
    *,
    id: Optional[str] = None,
    emotion: Optional[str] = None,
    tags: Optional[Union[str, Iterable[str]]] = None,
    summary: Optional[str] = None,
    query: Optional[str] = None,
) -> ExtensionSegment:
    data: dict[str, Any] = {}
    if id is not None and str(id).strip():
        data["id"] = str(id).strip()
    if emotion:
        data["emotion"] = str(emotion).strip().lower()
    normalized_tags = normalize_meme_tags(tags)
    if normalized_tags:
        data["tags"] = normalized_tags
    if summary:
        data["summary"] = str(summary).strip()
    if query:
        data["query"] = str(query).strip()
    return ExtensionSegment(type=MEME_SEGMENT_TYPE, data=data, fallback_text=MEME_FALLBACK_TEXT)


def is_meme_segment(segment: Any) -> bool:
    return isinstance(segment, ExtensionSegment) and segment.type == MEME_SEGMENT_TYPE


def has_selector(segment: ExtensionSegment) -> bool:
    return any(segment.data.get(key) for key in _SELECTOR_KEYS)


def _parse_meme_params(params_str: str) -> dict[str, Any]:
    """Parse meme parameters; ``tags=高兴,捧场`` continues across commas."""
    params: dict[str, Any] = {}
    current_key = ""
    for part in params_str.split(","):
        clean = part.strip()
        if not clean:
            continue
        if "=" in clean:
            key, value = clean.split("=", 1)
            current_key = key.strip()
            value = value.strip()
            if current_key == "tags":
                params.setdefault("tags", [])
                if value:
                    params["tags"].append(value)
            else:
                params[current_key] = value
            continue
        if current_key == "tags":
            params.setdefault("tags", [])
            params["tags"].append(clean)
    return params


def parse_meme_tag(params_str: str) -> Optional[ExtensionSegment]:
    params = _parse_meme_params(params_str)
    segment = make_meme_segment(
        id=params.get("id"),
        emotion=params.get("emotion"),
        tags=params.get("tags") or [],
        summary=params.get("summary"),
        query=params.get("query"),
    )
    return segment if has_selector(segment) else None


def render_meme_tag(segment: ExtensionSegment) -> str:
    data = segment.data
    params = []
    if data.get("id"):
        params.append(f"id={data['id']}")
    if data.get("emotion"):
        params.append(f"emotion={data['emotion']}")
    if data.get("tags"):
        params.append(f"tags={','.join(data['tags'])}")
    if data.get("summary"):
        params.append(f"summary={data['summary']}")
    if data.get("query"):
        params.append(f"query={data['query']}")
    return f"[meme, {', '.join(params)}]" if params else "[meme]"


def meme_fallback(segment: ExtensionSegment) -> list[Segment]:
    """Used only if a meme reaches an adapter unresolved; never touches the library."""
    return [Text(text=MEME_FALLBACK_TEXT)]


def register_meme_segment() -> None:
    from app.agent.codec import tag_codec

    register_segment_type(MEME_SEGMENT_TYPE, owner=__name__, fallback=meme_fallback)
    tag_codec.register_tag(
        MEME_TAG,
        segment_type=MEME_SEGMENT_TYPE,
        owner=__name__,
        parse=parse_meme_tag,
        render=render_meme_tag,
    )


def unregister_meme_segment() -> None:
    from app.agent.codec import tag_codec

    segment_registry.unregister_package(__name__)
    tag_codec.unregister_package(__name__)
