from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Type
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from app.logger import setup_logger
from app.runtime.paths import STICKER_ASSETS_DIR, STICKER_SEND_DIR, STICKERS_DIR
from app.message import ExtensionSegment, Image, MediaRef
from app.tools.base import BaseTool, ToolInputSchema, ToolResult
from app.tools.registry import ToolRegistry

from .config import MemeStickerSendingConfig, load_config


logger = setup_logger(__name__)

LIBRARY_PATH = STICKERS_DIR / "sticker_library.json"
ASSET_URL_PREFIX = "/api/stickers/assets"
SEND_URL_PREFIX = "/api/stickers/send"
# Same shape as the host tag codec: ``summary=[动画表情]`` keeps its brackets.
IMAGE_TAG_RE = re.compile(
    r"\[image,\s*url=(?P<url>[^,\]\s]+?)(?:\s*,\s*summary=(?P<summary>\[[^\]]*\]|[^\]]+?))?\s*\]"
)
MAX_STICKER_BYTES = 15 * 1024 * 1024


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_library() -> Dict[str, Any]:
    if not LIBRARY_PATH.exists():
        return {"version": 1, "stickers": []}
    try:
        with LIBRARY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "stickers": []}
        stickers = data.get("stickers")
        if not isinstance(stickers, list):
            data["stickers"] = []
        data.setdefault("version", 1)
        return data
    except Exception as e:
        logger.warning(f"读取表情包库失败，将使用空库: {e}")
        return {"version": 1, "stickers": []}


def _save_library(data: Dict[str, Any]) -> None:
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LIBRARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _normalize_tags(tags: Optional[List[str]]) -> List[str]:
    seen = set()
    result: List[str] = []
    for tag in tags or []:
        clean = str(tag).strip().lower()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def to_absolute_url(url: str) -> str:
    if url.startswith("/"):
        try:
            from app.config.web_api_config import get_public_base_url
            base = get_public_base_url()
            return f"{base}{url}"
        except Exception:
            pass
    return url


def build_sticker_asset_url(filename: str) -> str:
    return f"{ASSET_URL_PREFIX}/{filename}"


def build_sticker_send_url(filename: str) -> str:
    return f"{SEND_URL_PREFIX}/{filename}"


def _safe_filename(value: str, fallback: str = "sticker") -> str:
    name = Path(value or "").name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")
    return name[:120] or fallback


def _ext_from_content_type(content_type: str, filename: str = "") -> str:
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip().lower())
    ext = guessed or Path(filename).suffix or ".bin"
    return ext[:12]


def _read_sticker_source(url: str) -> tuple[bytes, str, str]:
    url = (url or "").strip()
    if not url:
        raise ValueError("缺少表情包 URL")

    asset_path, _kind = resolve_sticker_storage_url(url)
    if asset_path:
        return asset_path.read_bytes(), mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream", asset_path.name

    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        request = Request(url, headers={"User-Agent": "FoxranStickerStore/1.0"})
        with urlopen(request, timeout=20) as response:
            content = response.read(MAX_STICKER_BYTES + 1)
            content_type = response.headers.get("Content-Type", "application/octet-stream")
        if len(content) > MAX_STICKER_BYTES:
            raise ValueError("表情包文件过大")
        return content, content_type, _safe_filename(Path(parsed.path).name, "remote_sticker")

    if parsed.scheme == "file":
        path = Path(parsed.path)
    else:
        path = Path(url)
    if not path.exists() or not path.is_file():
        raise ValueError(f"表情包源文件不存在: {url}")
    content = path.read_bytes()
    if len(content) > MAX_STICKER_BYTES:
        raise ValueError("表情包文件过大")
    return content, mimetypes.guess_type(path.name)[0] or "application/octet-stream", path.name


def persist_sticker_source(url: str, sticker_id: str = "") -> Dict[str, Any]:
    content, content_type, original_filename = _read_sticker_source(url)
    return persist_sticker_bytes(content, content_type, original_filename, sticker_id=sticker_id)


def persist_sticker_bytes(
    content: bytes,
    content_type: str,
    original_filename: str = "",
    sticker_id: str = "",
) -> Dict[str, Any]:
    content_sha1 = hashlib.sha1(content).hexdigest()
    if not sticker_id:
        sticker_id = content_sha1[:12]
    ext = _ext_from_content_type(content_type, original_filename)
    filename = f"{sticker_id}{ext}"
    STICKER_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    path = STICKER_ASSETS_DIR / filename
    path.write_bytes(content)
    return {
        "id": sticker_id,
        "url": build_sticker_asset_url(filename),
        "storage_filename": filename,
        "content_type": (content_type or "").split(";", 1)[0].strip().lower() or "application/octet-stream",
        "size": len(content),
        "original_filename": original_filename,
        "content_sha1": content_sha1,
    }


def resolve_sticker_storage_url(url: str) -> tuple[Optional[Path], str]:
    parsed = urlparse(url or "")
    path = parsed.path if parsed.scheme else (url or "")
    for prefix, root, kind in (
        (ASSET_URL_PREFIX + "/", STICKER_ASSETS_DIR, "asset"),
        (SEND_URL_PREFIX + "/", STICKER_SEND_DIR, "send"),
    ):
        if path.startswith(prefix):
            filename = _safe_filename(path[len(prefix):], "")
            if not filename:
                return None, kind
            target = (root / filename).resolve()
            try:
                if target.exists() and target.is_relative_to(root.resolve()):
                    return target, kind
            except AttributeError:
                if target.exists() and str(root.resolve()).lower() in str(target).lower():
                    return target, kind
            return None, kind
    return None, ""


def _resolve_sticker_source_path(item: Dict[str, Any]) -> Optional[Path]:
    storage_filename = str(item.get("storage_filename") or "")
    if storage_filename:
        path = (STICKER_ASSETS_DIR / _safe_filename(storage_filename, "")).resolve()
        if path.exists() and STICKER_ASSETS_DIR.resolve() in path.parents:
            return path
    path, _kind = resolve_sticker_storage_url(str(item.get("url") or ""))
    if path:
        return path
    return None


def _encode_webp(img: Any, side: int, quality: int, max_frames: int) -> Optional[bytes]:
    from PIL import Image, ImageSequence

    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.LANCZOS
    buffer = BytesIO()
    if getattr(img, "is_animated", False):
        frames = []
        durations = []
        for frame in ImageSequence.Iterator(img):
            current = frame.convert("RGBA")
            current.thumbnail((side, side), resample)
            frames.append(current.copy())
            durations.append(int(frame.info.get("duration", 90)))
            if len(frames) >= max_frames:
                break
        if not frames:
            return None
        frames[0].save(
            buffer,
            format="WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            quality=quality,
            method=6,
        )
        return buffer.getvalue()

    still = img.copy()
    still.thumbnail((side, side), resample)
    if still.mode not in ("RGB", "RGBA"):
        still = still.convert("RGBA")
    still.save(buffer, format="WEBP", quality=quality, method=6)
    return buffer.getvalue()


def _compress_image_bytes(content: bytes, sending: Optional[MemeStickerSendingConfig] = None) -> Optional[bytes]:
    """WebP send copy within ``sending``'s limits.

    Over ``max_kb`` the quality steps down to 40 first, then the longest side
    shrinks by 20% at a time (not below 64px); the smallest result is returned
    even if it is still over the limit.
    """
    try:
        from PIL import Image
    except Exception:
        return None

    cfg = (sending or MemeStickerSendingConfig()).clamped()
    limit = cfg.max_kb * 1024
    try:
        with Image.open(BytesIO(content)) as img:
            side = min(cfg.max_side, max(img.size))
            quality = cfg.quality
            best: Optional[bytes] = None
            while True:
                encoded = _encode_webp(img, side, quality, cfg.max_frames)
                if not encoded:
                    return best
                if best is None or len(encoded) < len(best):
                    best = encoded
                if not limit or len(encoded) <= limit:
                    return encoded
                if quality > 40:
                    quality = max(40, quality - 12)
                elif side > 64:
                    side = max(64, int(side * 0.8))
                else:
                    logger.warning(f"表情包发送图压到最小仍有 {len(best) // 1024}KB，超过上限 {cfg.max_kb}KB")
                    return best
    except Exception as e:
        logger.debug(f"表情包发送图压缩失败: {e}")
        return None


def _send_profile(sending: MemeStickerSendingConfig) -> str:
    cfg = sending.clamped()
    return f"webp:{cfg.max_side}:{cfg.quality}:{cfg.max_kb}:{cfg.max_frames}"


def _get_send_url(item: Dict[str, Any]) -> str:
    sending = load_config().sending
    profile = _send_profile(sending)
    cached_send_url = str(item.get("send_url") or "")
    if cached_send_url and item.get("send_profile") == profile:
        path, _kind = resolve_sticker_storage_url(cached_send_url)
        if path:
            return cached_send_url

    url = str(item.get("url") or "")
    if not url:
        return ""

    source_path = _resolve_sticker_source_path(item)
    if not source_path or not source_path.exists():
        return url

    content = source_path.read_bytes()
    compressed = _compress_image_bytes(content, sending)
    if not compressed:
        return url

    original_id = str(item.get("id") or source_path.stem)
    STICKER_SEND_DIR.mkdir(parents=True, exist_ok=True)
    send_filename = f"{original_id}.webp"
    send_path = STICKER_SEND_DIR / send_filename
    send_path.write_bytes(compressed)
    send_url = build_sticker_send_url(send_filename)
    item["send_url"] = send_url
    item["send_content_type"] = "image/webp"
    item["send_size"] = len(compressed)
    item["send_profile"] = profile
    item["updated_at"] = _now()
    return send_url


def find_image_tags(text: str) -> List[Dict[str, str]]:
    """``[image,url=..., summary=...]`` references in agent tag text, in order."""
    return [
        {"url": match.group("url") or "", "summary": (match.group("summary") or "").strip()}
        for match in IMAGE_TAG_RE.finditer(text or "")
        if match.group("url")
    ]


def _extract_recent_image(session_ctx: Any) -> Optional[Dict[str, str]]:
    history = getattr(session_ctx, "history", []) or []
    for msg in reversed(history[-12:]):
        content = str(getattr(msg, "content", "") or getattr(msg, "raw_content", "") or "")
        images = find_image_tags(content)
        if images:
            return images[-1]
    return None


def _tokenize(text: str) -> set[str]:
    text = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{1,4}", text))
    return {token for token in tokens if token.strip()}


def _select_sticker(
    *,
    sticker_id: str = "",
    query: str = "",
    emotion: str = "",
    tags: Optional[List[str]] = None,
    summary: str = "",
    session_ctx: Any = None,
) -> Optional[Dict[str, Any]]:
    library = _load_library()
    enabled = [item for item in library["stickers"] if item.get("enabled", True) and item.get("url")]
    if not enabled:
        return None

    wanted_id = str(sticker_id or "").strip()
    selected: Optional[Dict[str, Any]] = None
    if wanted_id:
        selected = next((item for item in enabled if str(item.get("id") or "") == wanted_id), None)
        if selected is None:
            return None

    if selected is None:
        search_text = " ".join(part for part in [query, summary] if part)
        query_tokens = _tokenize(search_text)
        wanted_tags = set(_normalize_tags(tags or []))
        wanted_emotion = str(emotion or "").strip().lower()

        def score(item: Dict[str, Any]) -> float:
            item_tags = set(_normalize_tags(item.get("tags") or []))
            text = " ".join([str(item.get("summary") or ""), str(item.get("emotion") or ""), " ".join(item_tags)])
            text_tokens = _tokenize(text)
            value = 0.0
            value += len(query_tokens & text_tokens) * 2.0
            value += len(wanted_tags & item_tags) * 3.0
            if wanted_emotion and wanted_emotion == str(item.get("emotion") or "").lower():
                value += 4.0
            value -= min(float(item.get("usage_count") or 0), 8.0) * 0.08
            if item.get("last_used_at"):
                value -= 0.2
            return value

        selected = max(enabled, key=score)

    selected["usage_count"] = int(selected.get("usage_count") or 0) + 1
    selected["last_used_at"] = _now()
    selected["send_url"] = _get_send_url(selected)
    _save_library(library)
    mark_sticker_sent(session_ctx)
    return selected


def mark_sticker_sent(session_ctx: Any) -> None:
    """Reset the prompt hook's pacing after a sticker goes out."""
    if session_ctx is None:
        return
    state = getattr(session_ctx, "session_notes", {}).setdefault("meme_sticker_state", {})
    state["turns_since_sticker"] = 0
    state["prompt_active"] = False
    state["prompt_turns"] = 0
    state["last_sticker_at"] = datetime.now().timestamp()
    state["next_after"] = 0


def resolve_meme_segment(segment: ExtensionSegment, session_ctx: Any = None) -> Optional[Image]:
    data = segment.data
    selected = _select_sticker(
        sticker_id=data.get("id") or "",
        query=data.get("query") or "",
        emotion=data.get("emotion") or "",
        tags=list(data.get("tags") or []),
        summary=data.get("summary") or "",
        session_ctx=session_ctx,
    )
    if not selected:
        return None
    return Image(
        media=MediaRef(url=to_absolute_url(str(selected.get("send_url") or selected.get("url") or ""))),
        summary=str(data.get("summary") or selected.get("summary") or "表情包"),
    )


def _store_sticker(
    content: bytes,
    content_type: str,
    original_filename: str,
    *,
    source_url: str,
    summary: str,
    emotion: str,
    tags: List[str],
    source: str,
    session_ctx: Any = None,
    extra: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], bool]:
    """Add image bytes to the library, merging into an existing copy of the same image.

    QQ hands out a fresh URL every time a sticker is sent, so duplicates are
    found by content hash. Returns ``(item, created)``.
    """
    if len(content) > MAX_STICKER_BYTES:
        raise ValueError("表情包文件过大")
    content_sha1 = hashlib.sha1(content).hexdigest()
    library = _load_library()
    stickers = library["stickers"]
    existing = next((item for item in stickers if item.get("content_sha1") == content_sha1), None)
    clean_tags = _normalize_tags(tags)
    clean_emotion = (emotion or "").strip().lower()
    clean_summary = (summary or "").strip()

    if existing:
        stored = persist_sticker_bytes(content, content_type, original_filename, sticker_id=str(existing["id"]))
        existing.update({key: stored[key] for key in ("url", "storage_filename", "content_type", "size", "content_sha1")})
        existing["tags"] = _normalize_tags(list(existing.get("tags") or []) + clean_tags)
        if clean_emotion:
            existing["emotion"] = clean_emotion
        if clean_summary and existing.get("summary") in ("", "表情包", None):
            existing["summary"] = clean_summary
        existing["enabled"] = True
        existing["updated_at"] = _now()
        _save_library(library)
        return existing, False

    stored = persist_sticker_bytes(content, content_type, original_filename, sticker_id=content_sha1[:12])
    notes = getattr(session_ctx, "session_notes", {}) if session_ctx is not None else {}
    item = {
        "id": stored["id"],
        "url": stored["url"],
        "summary": clean_summary or "表情包",
        "tags": clean_tags,
        "emotion": clean_emotion,
        "usage_count": 0,
        "enabled": True,
        "source": source,
        "source_url": source_url,
        "source_session_id": getattr(session_ctx, "session_id", "") if session_ctx is not None else "",
        "source_user_id": notes.get("current_user_id", "") if isinstance(notes, dict) else "",
        "storage_filename": stored["storage_filename"],
        "content_type": stored["content_type"],
        "size": stored["size"],
        "content_sha1": content_sha1,
        "original_filename": stored.get("original_filename", ""),
        "created_at": _now(),
        "updated_at": _now(),
        "last_used_at": "",
    }
    item.update(extra or {})
    stickers.append(item)
    _save_library(library)
    return item, True


def _prepare_send_url(sticker_id: str) -> str:
    """Count a send of ``sticker_id`` and return its compressed send URL."""
    library = _load_library()
    item = next((entry for entry in library["stickers"] if entry.get("id") == sticker_id), None)
    if item is None:
        raise ValueError(f"没有找到表情包 {sticker_id}")
    item["usage_count"] = int(item.get("usage_count") or 0) + 1
    item["last_used_at"] = _now()
    send_url = _get_send_url(item) or str(item.get("url") or "")
    _save_library(library)
    return send_url


async def create_drawn_sticker(
    *,
    remake: bool,
    reference_url: str = "",
    reference_summary: str = "",
    prompt: str = "",
    caption: str = "",
    summary: str = "",
    emotion: str = "",
    tags: Optional[List[str]] = None,
    session_ctx: Any = None,
    progress: Any = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Draw (``remake=False``) or redraw a reference sticker and add it to the library.

    Shared by the ``generate``/``remake`` tool operations and the WebUI API.
    Raises ``ValueError`` for anything the caller can fix (disabled, quota,
    missing prompt or reference).
    """
    from . import generation

    cfg = generation.load_generation_config()
    if not cfg.enabled:
        raise ValueError("表情包生成已在 meme_sticker.yaml 中关闭。")
    if generation.daily_limit_reached(_load_library()["stickers"], cfg):
        raise ValueError("今天生成表情包的次数已用完，请改用 select 从库里挑一张。")

    prompt = (prompt or "").strip()
    caption = (caption or "").strip()
    summary = (summary or "").strip()
    reference_url = (reference_url or "").strip()
    if remake and not reference_url:
        raise ValueError("remake 需要参考图：传入 url，或在最近消息里有图片。")
    if not remake and not (prompt or summary):
        raise ValueError("generate 需要 prompt（画面描述）。")

    full_prompt = generation.build_sticker_prompt(
        style_prompt=cfg.style_prompt,
        description=prompt or (summary if not remake else ""),
        caption=caption,
        emotion=(emotion or "").strip(),
        reference_summary=(reference_summary or "").strip("[] "),
        remake=remake,
    )

    async def report(percent: int, message: str) -> None:
        if progress is not None:
            await progress(percent, message)

    await report(10, "正在绘制表情包...")
    if remake:
        reference, _type, _name = await asyncio.to_thread(_read_sticker_source, reference_url)
        image_url = await generation.redraw_sticker(full_prompt, reference, cfg.size)
    else:
        image_url = await generation.draw_sticker(full_prompt, cfg.size)
    await report(80, "正在存入表情包库...")

    content, content_type, original_filename = await asyncio.to_thread(_read_sticker_source, image_url)
    metadata = {"prompt": full_prompt}
    if remake:
        metadata["reference_url"] = reference_url
    metadata.update(extra or {})
    item, _created = await asyncio.to_thread(
        _store_sticker,
        content,
        content_type,
        original_filename,
        source_url="",
        summary=summary or caption or prompt[:40] or (reference_summary or "").strip("[] ") or "表情包",
        emotion=emotion,
        tags=list(tags or []) + ([caption] if caption else []),
        source="remade" if remake else "generated",
        session_ctx=session_ctx,
        extra=metadata,
    )
    return item


SENDING_OPERATIONS = ("select", "generate", "remake")


class StickerPackInput(ToolInputSchema):
    operation: Literal["select", "collect", "generate", "remake", "list", "delete", "update"] = Field(
        ...,
        description=(
            "操作类型：select 从库里选一张合适的表情包；collect 把聊天里的图片收进表情包库；"
            "generate 用绘图模型按描述画一张新表情包（自动入库）；remake 参考一张已有表情包复刻/改画（自动入库）；"
            "list 查看素材；delete 删除素材；update 修改标签/说明。"
        ),
    )
    query: str = Field("", description="当前聊天语境、想表达的语气或筛选关键词。select/list/update 时可用。")
    emotion: str = Field("", description="情绪，如 happy、thanks、agree、tease、awkward、surprised、comfort、sorry、confused、sleepy。")
    tags: List[str] = Field(default_factory=list, description="表情包标签，如 开心、捧场、疑惑、摸鱼、道歉。")
    url: str = Field(
        "",
        description="collect/remake/update 时的图片 URL 或文件地址；collect/remake 留空时取最近消息里的图片。",
    )
    summary: str = Field("", description="表情包含义或画面摘要，发送时会作为图片 summary。")
    prompt: str = Field(
        "",
        description="generate 时的画面描述（角色、动作、表情）；remake 时的修改要求（如 换成猫猫、改成哭脸），可留空表示原样复刻。",
    )
    caption: str = Field("", description="generate/remake 时图上的配字，尽量 2~8 个字；留空表示不加字。")
    sticker_id: str = Field("", description="delete/update 指定素材 ID。")
    limit: int = Field(5, description="list 返回数量，默认 5。")
    allow_send: bool = Field(
        True,
        description="select/generate/remake 时是否把图片直接发给用户；为 false 时只入库或只返回候选说明。",
    )


class MemeStickerTool(BaseTool):
    name: str = "meme_sticker"
    description: str = (
        "管理、收集和生成聊天表情包。可把聊天里别人发的表情包收进库（collect），按语境/情绪/标签从库里挑一张（select），"
        "库里没有合适的时用绘图模型现画一张（generate）或复刻别人的表情包（remake）。"
        "日常发表情包更推荐直接在回复里写 [meme, emotion=..., tags=...] 片段。"
    )
    usage: str = (
        "用于让 Agent 在轻松、庆祝、感谢、调侃、缓和尴尬等场景附上表情包。"
        "严肃求助、隐私话题、争执升级、用户明确不想要时不要使用；一次回复最多使用一张。"
        "收集图片前应确认它适合复用，不要收集私人照片、证件、聊天截图等敏感图片。"
        "generate/remake 要调用绘图模型，比较慢，只在库里确实没有合适表情包或用户想要定制表情包时使用。"
        "select/generate/remake（allow_send=true）的结果会作为图片直接发给用户；list、collect、update、delete "
        "以及 allow_send=false 的结果只返回给你自己参考，不会展示给用户。"
    )
    manual_tags: List[str] = ["sticker", "meme", "表情包", "斗图", "拟人感", "聊天", "onebot", "qq"]
    args_schema: Type[BaseModel] = StickerPackInput

    def get_execution_contract(self, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Only a sticker that is actually sent is shown to the user.

        ``list``/``collect``/``update``/``delete`` and any operation with
        ``allow_send=false`` return library details for the agent to read, not
        a message for the chat.
        """
        contract = super().get_execution_contract(parameters)
        params = parameters or {}
        operation = str(params.get("operation") or "").strip().lower()
        allow_send = params.get("allow_send", True)
        if isinstance(allow_send, str):
            allow_send = allow_send.strip().lower() not in {"false", "0", "no", ""}
        sends_sticker = operation in SENDING_OPERATIONS and bool(allow_send)
        contract["visibility"] = "user_visible" if sends_sticker else "agent_only"
        return contract

    async def execute(self, session_ctx: Any = None, status_callback: Any = None, **kwargs: Any) -> ToolResult:
        try:
            args = StickerPackInput(**kwargs)
        except Exception as e:
            return ToolResult(tool_name=self.name, success=False, error=f"参数验证失败: {e}", parameters=kwargs)

        try:
            if args.operation == "collect":
                data = await asyncio.to_thread(self._collect, args, session_ctx)
            elif args.operation in ("generate", "remake"):
                data = await self._draw(args, session_ctx, status_callback)
            elif args.operation == "select":
                data = self._select(args, session_ctx)
            elif args.operation == "list":
                data = self._list(args)
            elif args.operation == "delete":
                data = self._delete(args)
            elif args.operation == "update":
                data = self._update(args)
            else:
                return ToolResult(tool_name=self.name, success=False, error="未知操作", parameters=kwargs)
            return ToolResult(tool_name=self.name, success=True, data=data, parameters=kwargs)
        except Exception as e:
            logger.error(f"表情包工具执行失败: {e}", exc_info=True)
            return ToolResult(tool_name=self.name, success=False, error=str(e), parameters=kwargs)

    def _collect(self, args: StickerPackInput, session_ctx: Any) -> str:
        url = args.url.strip()
        summary = args.summary.strip()
        if not url and session_ctx is not None:
            recent = _extract_recent_image(session_ctx)
            if recent:
                url = recent["url"]
                summary = summary or recent.get("summary", "")
        if not url:
            raise ValueError("没有提供图片 URL，也没有在最近消息中找到可收集图片。")

        content, content_type, original_filename = _read_sticker_source(url)
        item, created = _store_sticker(
            content,
            content_type,
            original_filename,
            source_url=url,
            summary=summary,
            emotion=args.emotion,
            tags=args.tags,
            source="collected",
            session_ctx=session_ctx,
        )
        if created:
            return f"已收集表情包 {item['id']}：{item['summary']}"
        return f"已更新表情包 {item['id']}：{item.get('summary') or item.get('url')}"

    async def _draw(self, args: StickerPackInput, session_ctx: Any, status_callback: Any) -> str:
        remake = args.operation == "remake"
        reference_url = args.url.strip()
        reference_summary = ""
        if remake and not reference_url and session_ctx is not None:
            recent = _extract_recent_image(session_ctx)
            if recent:
                reference_url = recent["url"]
                reference_summary = recent.get("summary", "")

        async def progress(percent: int, message: str) -> None:
            await self.report_progress(percent, message, status_callback)

        item = await create_drawn_sticker(
            remake=remake,
            reference_url=reference_url,
            reference_summary=reference_summary,
            prompt=args.prompt,
            caption=args.caption,
            summary=args.summary,
            emotion=args.emotion,
            tags=args.tags,
            session_ctx=session_ctx,
            progress=progress,
        )
        if not args.allow_send:
            return f"已生成并收进表情包库 {item['id']}：{item['summary']}"
        send_url = await asyncio.to_thread(_prepare_send_url, item["id"])
        mark_sticker_sent(session_ctx)
        return f"[image,url={to_absolute_url(send_url)},summary={item['summary']}]"

    def _select(self, args: StickerPackInput, session_ctx: Any = None) -> str:
        selected = _select_sticker(
            query=args.query,
            emotion=args.emotion,
            tags=args.tags,
            summary=args.summary,
            session_ctx=session_ctx,
        )
        if not selected:
            return "表情包库还是空的；可以先用 meme_sticker collect 收集一张合适的图片。"

        if args.allow_send:
            send_url = to_absolute_url(str(selected.get("send_url") or selected.get("url") or ""))
            summary = str(selected.get("summary") or "")
            return f"[image,url={send_url},summary={summary}]"
        tags = ", ".join(selected.get("tags") or [])
        return f"{selected['id']} | {selected.get('summary') or ''} | {selected.get('emotion') or ''} | {tags} | {selected['url']}"

    def _list(self, args: StickerPackInput) -> str:
        library = _load_library()
        query_tokens = _tokenize(args.query)
        wanted_tags = set(_normalize_tags(args.tags))
        items = library["stickers"]
        if query_tokens or wanted_tags or args.emotion:
            emotion = args.emotion.strip().lower()
            items = [
                item for item in items
                if (
                    (not emotion or emotion == str(item.get("emotion") or "").lower())
                    and (not wanted_tags or wanted_tags & set(_normalize_tags(item.get("tags") or [])))
                    and (not query_tokens or query_tokens & _tokenize(
                        " ".join([str(item.get("summary") or ""), " ".join(item.get("tags") or [])])
                    ))
                )
            ]
        limit = max(1, min(args.limit, 30))
        lines = []
        for item in items[:limit]:
            tags = ", ".join(item.get("tags") or [])
            state = "on" if item.get("enabled", True) else "off"
            lines.append(f"{item.get('id')} [{state}] {item.get('emotion') or '-'} | {tags} | {item.get('summary') or item.get('url')}")
        return "\n".join(lines) if lines else "没有找到匹配的表情包。"

    def _delete(self, args: StickerPackInput) -> str:
        if not args.sticker_id:
            raise ValueError("delete 需要 sticker_id。")
        library = _load_library()
        before = len(library["stickers"])
        library["stickers"] = [item for item in library["stickers"] if item.get("id") != args.sticker_id]
        if len(library["stickers"]) == before:
            return f"没有找到表情包 {args.sticker_id}。"
        _save_library(library)
        return f"已删除表情包 {args.sticker_id}。"

    def _update(self, args: StickerPackInput) -> str:
        if not args.sticker_id:
            raise ValueError("update 需要 sticker_id。")
        library = _load_library()
        item = next((entry for entry in library["stickers"] if entry.get("id") == args.sticker_id), None)
        if not item:
            return f"没有找到表情包 {args.sticker_id}。"
        if args.url:
            item["url"] = args.url.strip()
        if args.summary:
            item["summary"] = args.summary.strip()
        if args.tags:
            item["tags"] = _normalize_tags(args.tags)
        if args.emotion:
            item["emotion"] = args.emotion.strip().lower()
        item["updated_at"] = _now()
        _save_library(library)
        return f"已更新表情包 {args.sticker_id}。"


def load_tools(registry: Optional[ToolRegistry] = None):
    if not registry:
        logger.error("MemeStickerTool: 注册表实例未提供给 load_tools 函数。")
        return
    registry.register_tool_class(MemeStickerTool)
    logger.info("MemeStickerTool 已成功注册。")
