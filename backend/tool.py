from __future__ import annotations

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
from app.data_mappers.schemas import ImageSchema, MemeSchema
from app.tools.base import BaseTool, ToolInputSchema, ToolResult
from app.tools.registry import ToolRegistry


logger = setup_logger(__name__)

LIBRARY_PATH = STICKERS_DIR / "sticker_library.json"
ASSET_URL_PREFIX = "/api/stickers/assets"
SEND_URL_PREFIX = "/api/stickers/send"
IMAGE_TAG_RE = re.compile(r"\[image,\s*url=(?P<url>[^\],\s]+)(?:[^\]]*?summary=(?P<summary>[^\]]+))?\]")
SEND_WEBP_MAX_SIZE = 384
SEND_WEBP_QUALITY = 72
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


def _make_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


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
    if not sticker_id:
        sticker_id = hashlib.sha1(content).hexdigest()[:12]
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


def _compress_image_bytes(content: bytes, max_size: int = SEND_WEBP_MAX_SIZE) -> Optional[bytes]:
    try:
        from PIL import Image, ImageSequence
    except Exception:
        return None

    try:
        with Image.open(BytesIO(content)) as img:
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS
            if getattr(img, "is_animated", False):
                frames = []
                durations = []
                for frame in ImageSequence.Iterator(img):
                    current = frame.convert("RGBA")
                    current.thumbnail((max_size, max_size), resample)
                    frames.append(current.copy())
                    durations.append(int(frame.info.get("duration", 90)))
                    if len(frames) >= 48:
                        break
                if not frames:
                    return None
                buffer = BytesIO()
                frames[0].save(
                    buffer,
                    format="WEBP",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=0,
                    quality=SEND_WEBP_QUALITY,
                    method=6,
                )
                return buffer.getvalue()

            img.thumbnail((max_size, max_size), resample)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            buffer = BytesIO()
            img.save(buffer, format="WEBP", quality=SEND_WEBP_QUALITY, method=6)
            return buffer.getvalue()
    except Exception as e:
        logger.debug(f"表情包发送图压缩失败: {e}")
        return None


def _get_send_url(item: Dict[str, Any]) -> str:
    cached_send_url = str(item.get("send_url") or "")
    if cached_send_url:
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
    compressed = _compress_image_bytes(content)
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
    item["updated_at"] = _now()
    return send_url


def _extract_recent_image(session_ctx: Any) -> Optional[Dict[str, str]]:
    history = getattr(session_ctx, "history", []) or []
    for msg in reversed(history[-12:]):
        content = str(getattr(msg, "content", "") or getattr(msg, "raw_content", "") or "")
        match = IMAGE_TAG_RE.search(content)
        if match:
            return {
                "url": match.group("url") or "",
                "summary": (match.group("summary") or "").strip(),
            }
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

    if session_ctx is not None:
        state = getattr(session_ctx, "session_notes", {}).setdefault("meme_sticker_state", {})
        state["turns_since_sticker"] = 0
        state["prompt_active"] = False
        state["prompt_turns"] = 0
        state["last_sticker_at"] = datetime.now().timestamp()
        state["next_after"] = 0

    return selected


def resolve_meme_schema(schema: MemeSchema, session_ctx: Any = None) -> Optional[ImageSchema]:
    selected = _select_sticker(
        sticker_id=schema.id or "",
        query=schema.query or "",
        emotion=schema.emotion or "",
        tags=schema.tags,
        summary=schema.summary or "",
        session_ctx=session_ctx,
    )
    if not selected:
        return None
    return ImageSchema(
        url=str(selected.get("send_url") or selected.get("url") or ""),
        summary=str(schema.summary or selected.get("summary") or "表情包"),
    )


class StickerPackInput(ToolInputSchema):
    operation: Literal["select", "collect", "list", "delete", "update"] = Field(
        ...,
        description="操作类型：select 选择合适表情包；collect 收集表情包；list 查看素材；delete 删除素材；update 修改标签/说明。",
    )
    query: str = Field("", description="当前聊天语境、想表达的语气或筛选关键词。select/list/update 时可用。")
    emotion: str = Field("", description="希望匹配的情绪，如 happy、tease、comfort、surprised、awkward、thanks、sleepy。")
    tags: List[str] = Field(default_factory=list, description="表情包标签，如 开心、捧场、疑惑、摸鱼、道歉。")
    url: str = Field("", description="collect/update 时的图片 URL 或文件地址；collect 留空时会尝试从最近消息里收集图片。")
    summary: str = Field("", description="表情包含义或画面摘要，发送时会作为图片 summary。")
    sticker_id: str = Field("", description="delete/update 指定素材 ID。")
    limit: int = Field(5, description="list 返回数量，默认 5。")
    allow_send: bool = Field(
        True,
        description="select 时是否返回可直接发送的 [image,...] 片段；为 false 时只返回候选说明。",
    )


class MemeStickerTool(BaseTool):
    name: str = "meme_sticker"
    description: str = (
        "管理和选择聊天表情包。可从对话图片中收集表情包，按语境/情绪/标签挑选一个合适的表情包，"
        "并返回内部 [meme, id=..., emotion=..., tags=...] 消息片段。"
    )
    usage: str = (
        "用于让 Agent 在轻松、庆祝、感谢、调侃、缓和尴尬等场景适度附上表情包。"
        "严肃求助、隐私话题、争执升级、用户明确不想要时不要使用；一次回复最多使用一张。"
        "收集图片前应确认它适合复用，不要收集私人照片、证件、聊天截图等敏感图片。"
    )
    manual_tags: List[str] = ["sticker", "meme", "表情包", "拟人感", "聊天", "onebot", "qq"]
    args_schema: Type[BaseModel] = StickerPackInput

    async def execute(self, session_ctx: Any = None, status_callback: Any = None, **kwargs: Any) -> ToolResult:
        try:
            args = StickerPackInput(**kwargs)
        except Exception as e:
            return ToolResult(tool_name=self.name, success=False, error=f"参数验证失败: {e}", parameters=kwargs)

        try:
            if args.operation == "collect":
                data = self._collect(args, session_ctx)
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

        library = _load_library()
        stickers = library["stickers"]
        sticker_id = _make_id(url)
        stored = persist_sticker_source(url, sticker_id=sticker_id)
        existing = next((item for item in stickers if item.get("id") == sticker_id or item.get("url") == url), None)
        tags = _normalize_tags(args.tags)
        if existing:
            existing["url"] = stored["url"]
            existing["storage_filename"] = stored["storage_filename"]
            existing["content_type"] = stored["content_type"]
            existing["size"] = stored["size"]
            existing["tags"] = _normalize_tags(list(existing.get("tags") or []) + tags)
            if args.emotion:
                existing["emotion"] = args.emotion.strip().lower()
            if summary:
                existing["summary"] = summary
            existing["updated_at"] = _now()
            _save_library(library)
            return f"已更新表情包 {existing['id']}：{existing.get('summary') or existing.get('url')}"

        target = getattr(session_ctx, "session_notes", {}) if session_ctx is not None else {}
        item = {
            "id": sticker_id,
            "url": stored["url"],
            "summary": summary or "表情包",
            "tags": tags,
            "emotion": args.emotion.strip().lower() or "",
            "usage_count": 0,
            "enabled": True,
            "source_session_id": getattr(session_ctx, "session_id", "") if session_ctx is not None else "",
            "source_user_id": target.get("current_user_id", ""),
            "storage_filename": stored["storage_filename"],
            "content_type": stored["content_type"],
            "size": stored["size"],
            "original_filename": stored.get("original_filename", ""),
            "created_at": _now(),
            "updated_at": _now(),
            "last_used_at": "",
        }
        stickers.append(item)
        _save_library(library)
        return f"已收集表情包 {sticker_id}：{item['summary']}"

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

        selected_tags = ",".join(_normalize_tags(selected.get("tags") or []))
        meme = MemeSchema(
            id=str(selected.get("id") or ""),
            emotion=str(selected.get("emotion") or ""),
            tags=selected_tags,
            summary=str(selected.get("summary") or "表情包"),
        )
        if args.allow_send:
            send_url = str(selected.get("send_url") or selected.get("url") or "")
            if send_url.startswith("/"):
                try:
                    from app.config.web_api_config import get_public_base_url
                    base_url = get_public_base_url()
                    send_url = f"{base_url}{send_url}"
                except Exception:
                    pass
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
