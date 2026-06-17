from __future__ import annotations

import base64
import json
import mimetypes
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.endpoints.auth import require_auth
from app.logger import setup_logger
from app.runtime.paths import STICKER_ASSETS_DIR
from app.tools.plugins.meme_stickers.tool import (
    build_sticker_asset_url,
    build_sticker_send_url,
    persist_sticker_source,
    resolve_sticker_storage_url,
    _load_library,
    _make_id,
    _normalize_tags,
    _now,
    _save_library,
)


logger = setup_logger(__name__)
router = APIRouter()


class StickerCreateRequest(BaseModel):
    url: str = Field(..., min_length=1)
    summary: str = ""
    emotion: str = ""
    tags: List[str] = Field(default_factory=list)


class StickerUpdateRequest(BaseModel):
    url: Optional[str] = None
    summary: Optional[str] = None
    emotion: Optional[str] = None
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = None


class StickerBulkTagRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    emotion: str = ""
    mode: str = Field("merge", description="merge 覆盖追加标签；replace 替换标签。")


class StickerAutoTagRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)
    overwrite: bool = Field(False, description="是否覆盖已有 summary/emotion/tags。默认只补空字段并合并标签。")


def _decorate(item: Dict[str, Any]) -> Dict[str, Any]:
    decorated = dict(item)
    url = str(decorated.get("url") or "")
    if url.startswith("/api/stickers/assets/") or url.startswith("/api/stickers/send/"):
        decorated.setdefault("thumb_url", url)
    return decorated


def _upsert_sticker(
    *,
    url: str,
    summary: str = "",
    emotion: str = "",
    tags: Optional[List[str]] = None,
    source: str = "",
    sticker_id: str = "",
    storage_filename: str = "",
) -> Dict[str, Any]:
    if not url:
        raise ValueError("缺少表情包 URL")

    library = _load_library()
    stickers = library["stickers"]
    sticker_id = sticker_id.strip() or _make_id(url)
    normalized_tags = _normalize_tags(tags)
    existing = next((item for item in stickers if item.get("id") == sticker_id or item.get("url") == url), None)

    if existing:
        existing["tags"] = _normalize_tags(list(existing.get("tags") or []) + normalized_tags)
        if summary:
            existing["summary"] = summary
        if emotion:
            existing["emotion"] = emotion.strip().lower()
        if storage_filename:
            existing["storage_filename"] = storage_filename
        existing["updated_at"] = _now()
        _save_library(library)
        return existing

    item = {
        "id": sticker_id,
        "url": url,
        "summary": summary or "表情包",
        "tags": normalized_tags,
        "emotion": emotion.strip().lower(),
        "usage_count": 0,
        "enabled": True,
        "source": source,
        "storage_filename": storage_filename,
        "created_at": _now(),
        "updated_at": _now(),
        "last_used_at": "",
    }
    stickers.append(item)
    _save_library(library)
    return item


def _patch_sticker_metadata(sticker_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    library = _load_library()
    item = next((entry for entry in library["stickers"] if entry.get("id") == sticker_id), None)
    if not item:
        return metadata
    item.update({k: v for k, v in metadata.items() if v is not None})
    item["updated_at"] = _now()
    _save_library(library)
    return item


def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    content = (text or "").strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    try:
        data = json.loads(content)
    except Exception:
        match = re.search(r"\[[\s\S]*\]", content)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError("模型未返回 JSON 数组")
    return [item for item in data if isinstance(item, dict)]


def _safe_tag_text(value: Any, max_len: int = 24) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\[\]{}<>\"'`]", "", text)
    text = re.sub(r"\s+", "_", text)
    return text[:max_len]


def _normalize_llm_tags(tags: Any) -> List[str]:
    if not isinstance(tags, list):
        return []
    result = []
    for tag in tags:
        clean = _safe_tag_text(tag)
        if clean and clean not in result:
            result.append(clean)
    return result[:8]


def _merge_auto_tag(item: Dict[str, Any], suggestion: Dict[str, Any], overwrite: bool) -> None:
    summary = str(suggestion.get("summary") or "").strip()[:80]
    emotion = _safe_tag_text(suggestion.get("emotion"), max_len=20)
    tags = _normalize_llm_tags(suggestion.get("tags"))

    if overwrite or not str(item.get("summary") or "").strip() or str(item.get("summary") or "").strip() == "表情包":
        if summary:
            item["summary"] = summary
    if overwrite or not str(item.get("emotion") or "").strip():
        if emotion:
            item["emotion"] = emotion
    if tags:
        if overwrite:
            item["tags"] = tags
        else:
            item["tags"] = _normalize_tags(list(item.get("tags") or []) + tags)
    item["updated_at"] = _now()


BAD_AUTO_TAG_WORDS = ("占位", "待识别", "未识别", "未见画面", "空白", "无法识别", "默认占位")


def _make_vision_preview_bytes(file_path: Path, content_type: str) -> tuple[bytes, str]:
    """生成给视觉模型用的小尺寸预览，避免把原图 base64 整体塞进请求。"""
    try:
        from PIL import Image

        with Image.open(file_path) as img:
            if getattr(img, "is_animated", False):
                img.seek(0)
            img.thumbnail((512, 512))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buffer = BytesIO()
            img.save(buffer, format="WEBP", quality=72, method=6)
            return buffer.getvalue(), "image/webp"
    except Exception as e:
        logger.debug(f"生成视觉预览图失败，回退原图: {e}")

    data = file_path.read_bytes()
    return data, content_type if content_type.startswith("image/") else "image/png"


def _cache_item_to_data_url(item: Dict[str, Any]) -> str:
    file_path, _kind = resolve_sticker_storage_url(str(item.get("url") or ""))
    if not file_path:
        return ""
    if not file_path.exists() or not file_path.is_file():
        return ""
    content_type = str(item.get("content_type") or "") or mimetypes.guess_type(file_path.name)[0] or "image/png"
    if not content_type.startswith("image/"):
        return ""
    image_bytes, preview_type = _make_vision_preview_bytes(file_path, content_type)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{preview_type};base64,{encoded}"


def _image_url_for_vision(item: Dict[str, Any]) -> str:
    data_url = _cache_item_to_data_url(item)
    if data_url:
        return data_url
    url = str(item.get("url") or "")
    if url.startswith("http://") or url.startswith("https://") or url.startswith("data:image/"):
        return url
    return ""


@router.get("/api/stickers/assets/{filename:path}")
async def get_sticker_asset(filename: str):
    path, _kind = resolve_sticker_storage_url(build_sticker_asset_url(filename))
    if not path:
        raise HTTPException(status_code=404, detail="表情包素材不存在")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


@router.get("/api/stickers/send/{filename:path}")
async def get_sticker_send_asset(filename: str):
    path, _kind = resolve_sticker_storage_url(build_sticker_send_url(filename))
    if not path:
        raise HTTPException(status_code=404, detail="表情包发送素材不存在")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


def _is_bad_auto_tag(suggestion: Dict[str, Any]) -> bool:
    text = " ".join([
        str(suggestion.get("summary") or ""),
        str(suggestion.get("emotion") or ""),
        " ".join(str(tag) for tag in suggestion.get("tags") or [] if tag is not None),
    ])
    return any(word in text for word in BAD_AUTO_TAG_WORDS)


@router.get("/api/stickers")
async def list_stickers(
    q: str = "",
    tag: str = "",
    emotion: str = "",
    limit: int = 200,
    _: bool = Depends(require_auth),
):
    library = _load_library()
    items = list(library["stickers"])
    q_lower = q.strip().lower()
    tag_lower = tag.strip().lower()
    emotion_lower = emotion.strip().lower()

    if q_lower or tag_lower or emotion_lower:
        filtered = []
        for item in items:
            item_tags = _normalize_tags(item.get("tags") or [])
            haystack = " ".join([
                str(item.get("id") or ""),
                str(item.get("url") or ""),
                str(item.get("summary") or ""),
                str(item.get("emotion") or ""),
                " ".join(item_tags),
            ]).lower()
            if q_lower and q_lower not in haystack:
                continue
            if tag_lower and tag_lower not in item_tags:
                continue
            if emotion_lower and emotion_lower != str(item.get("emotion") or "").lower():
                continue
            filtered.append(item)
        items = filtered

    items.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    capped = items[: max(1, min(limit, 500))]
    tags = sorted({tag for item in library["stickers"] for tag in _normalize_tags(item.get("tags") or [])})
    emotions = sorted({str(item.get("emotion") or "").lower() for item in library["stickers"] if item.get("emotion")})
    return {
        "total": len(items),
        "items": [_decorate(item) for item in capped],
        "tags": tags,
        "emotions": emotions,
    }


@router.post("/api/stickers")
async def create_sticker(payload: StickerCreateRequest, _: bool = Depends(require_auth)):
    try:
        stored = persist_sticker_source(payload.url.strip(), sticker_id=_make_id(payload.url.strip()))
        item = _upsert_sticker(
            url=stored["url"],
            summary=payload.summary.strip(),
            emotion=payload.emotion.strip(),
            tags=payload.tags,
            source="url",
            sticker_id=stored["id"],
            storage_filename=stored["storage_filename"],
        )
        item = _patch_sticker_metadata(item["id"], {
            "content_type": stored["content_type"],
            "size": stored["size"],
            "original_filename": stored.get("original_filename", ""),
        })
        return {"item": _decorate(item)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/stickers/upload")
async def upload_stickers(
    files: List[UploadFile] = File(...),
    summary: str = Form(""),
    emotion: str = Form(""),
    tags: str = Form(""),
    _: bool = Depends(require_auth),
):
    tag_list = [part.strip() for part in tags.split(",") if part.strip()]
    created = []
    failures = []
    for file in files:
        try:
            content = await file.read()
            if not content:
                failures.append({"filename": file.filename, "error": "空文件"})
                continue
            original_name = file.filename or "upload_sticker"
            sticker_id = _make_id(f"{original_name}:{len(content)}:{hash(content)}")
            ext = mimetypes.guess_extension((file.content_type or "").split(";", 1)[0]) or Path(original_name).suffix or ".bin"
            storage_filename = f"{sticker_id}{ext[:12]}"
            STICKER_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            (STICKER_ASSETS_DIR / storage_filename).write_bytes(content)
            access_url = build_sticker_asset_url(storage_filename)
            item_summary = summary.strip() or original_name or "表情包"
            item = _upsert_sticker(
                url=access_url,
                summary=item_summary,
                emotion=emotion.strip(),
                tags=tag_list,
                source="upload",
                sticker_id=sticker_id,
                storage_filename=storage_filename,
            )
            item = _patch_sticker_metadata(item["id"], {
                "content_type": (file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower(),
                "size": len(content),
                "original_filename": original_name,
            })
            decorated = _decorate(item)
            created.append(decorated)
        except Exception as e:
            logger.warning(f"表情包上传失败: {file.filename}: {e}")
            failures.append({"filename": file.filename, "error": str(e)})
    return {"items": created, "failures": failures}


@router.patch("/api/stickers/{sticker_id}")
async def update_sticker(sticker_id: str, payload: StickerUpdateRequest, _: bool = Depends(require_auth)):
    library = _load_library()
    item = next((entry for entry in library["stickers"] if entry.get("id") == sticker_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="表情包不存在")
    if payload.url is not None:
        try:
            stored = persist_sticker_source(payload.url.strip(), sticker_id=sticker_id)
            item["url"] = stored["url"]
            item["storage_filename"] = stored["storage_filename"]
            item["content_type"] = stored["content_type"]
            item["size"] = stored["size"]
            item["original_filename"] = stored.get("original_filename", "")
            item.pop("send_url", None)
            item.pop("send_content_type", None)
            item.pop("send_size", None)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if payload.summary is not None:
        item["summary"] = payload.summary.strip()
    if payload.emotion is not None:
        item["emotion"] = payload.emotion.strip().lower()
    if payload.tags is not None:
        item["tags"] = _normalize_tags(payload.tags)
    if payload.enabled is not None:
        item["enabled"] = payload.enabled
    item["updated_at"] = _now()
    _save_library(library)
    return {"item": _decorate(item)}


@router.post("/api/stickers/bulk-tag")
async def bulk_tag_stickers(payload: StickerBulkTagRequest, _: bool = Depends(require_auth)):
    ids = set(payload.ids)
    if not ids:
        raise HTTPException(status_code=400, detail="请选择表情包")
    tags = _normalize_tags(payload.tags)
    library = _load_library()
    updated = []
    for item in library["stickers"]:
        if item.get("id") not in ids:
            continue
        if payload.mode == "replace":
            item["tags"] = tags
        else:
            item["tags"] = _normalize_tags(list(item.get("tags") or []) + tags)
        if payload.emotion:
            item["emotion"] = payload.emotion.strip().lower()
        item["updated_at"] = _now()
        updated.append(item)
    _save_library(library)
    return {"updated": len(updated), "items": [_decorate(item) for item in updated]}


@router.post("/api/stickers/auto-tag")
async def auto_tag_stickers(payload: StickerAutoTagRequest, _: bool = Depends(require_auth)):
    ids = set(payload.ids)
    if not ids:
        raise HTTPException(status_code=400, detail="请选择表情包")

    library = _load_library()
    targets = [item for item in library["stickers"] if item.get("id") in ids]
    if not targets:
        raise HTTPException(status_code=404, detail="未找到可打标表情包")
    if len(targets) > 12:
        raise HTTPException(status_code=400, detail="一次最多自动视觉打标 12 个表情包")

    sticker_payload = [
        {
            "id": item.get("id"),
            "url": item.get("url"),
            "summary": item.get("summary") or "",
            "emotion": item.get("emotion") or "",
            "tags": item.get("tags") or [],
            "source": item.get("source") or "",
            "storage_filename": item.get("storage_filename") or "",
        }
        for item in targets
    ]

    content_parts: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "你是聊天机器人表情包素材库的视觉标注员。请看每一张表情包图片，并结合其 ID、已有说明和标签，"
                "生成适合聊天发送策略使用的标注。\n\n"
                "字段要求：\n"
                "- summary: 8-24 个中文字符，描述画面或语气，不要照抄 ID、URL 或 image.png 这类通用文件名。\n"
                "- emotion: 一个短英文或中文情绪/语气分类，例如 happy, thanks, agree, tease, awkward, surprised, comfort, sorry, sleepy, angry, confused, proud, cute。\n"
                "- tags: 3-6 个短标签，用中文或短英文，描述用途，如 开心、赞同、捧场、疑惑、安慰、调侃、道歉、震惊、卖萌、摸鱼。\n"
                "- 禁止在已看到画面的情况下输出“占位、待识别、空白、未见画面内容”。\n\n"
                "只返回 JSON 数组，不要解释，不要 Markdown。每项格式："
                '{"id":"...","summary":"...","emotion":"...","tags":["..."]}\n\n'
                f"待标注表情包元数据：\n{json.dumps(sticker_payload, ensure_ascii=False, indent=2)}"
            ),
        }
    ]
    missing_images = []
    for item in targets:
        image_url = _image_url_for_vision(item)
        if not image_url:
            missing_images.append(str(item.get("id") or ""))
            continue
        content_parts.append({"type": "text", "text": f"表情包 ID: {item.get('id')}"})
        content_parts.append({"type": "image_url", "image_url": {"url": image_url, "detail": "low"}})

    if missing_images:
        raise HTTPException(status_code=400, detail=f"以下表情包没有可供视觉模型读取的图片: {', '.join(missing_images)}")

    try:
        from app.openai_client import ask_model
        from app.openai_client.model_config import ModelOverrideParams

        content = await ask_model(
            messages=[
                {"role": "system", "content": "你只输出可解析 JSON，禁止输出解释文字。"},
                {"role": "user", "content": content_parts},
            ],
            override=ModelOverrideParams(temperature=0.1, max_tokens=1800),
            tags=["vision"],
        )
        suggestions = _extract_json_array(content)
    except Exception as e:
        logger.warning(f"LLM 自动打标失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"LLM 自动打标失败: {e}")

    by_id = {str(item.get("id") or ""): item for item in targets}
    applied = []
    skipped = []
    for suggestion in suggestions:
        sticker_id = str(suggestion.get("id") or "")
        item = by_id.get(sticker_id)
        if not item:
            continue
        if _is_bad_auto_tag(suggestion):
            skipped.append({"id": sticker_id, "reason": "模型未能识别画面，已跳过写回"})
            continue
        _merge_auto_tag(item, suggestion, payload.overwrite)
        applied.append(item)

    if not applied:
        detail = "模型没有返回可写回的有效标注"
        if skipped:
            detail += "，疑似视觉模型未能识别图片"
        raise HTTPException(status_code=500, detail=detail)

    _save_library(library)
    return {"updated": len(applied), "items": [_decorate(item) for item in applied], "skipped": skipped}


@router.delete("/api/stickers/{sticker_id}")
async def delete_sticker(sticker_id: str, _: bool = Depends(require_auth)):
    library = _load_library()
    before = len(library["stickers"])
    removed = next((item for item in library["stickers"] if item.get("id") == sticker_id), None)
    library["stickers"] = [item for item in library["stickers"] if item.get("id") != sticker_id]
    if len(library["stickers"]) == before:
        raise HTTPException(status_code=404, detail="表情包不存在")
    if removed:
        for url in (str(removed.get("url") or ""), str(removed.get("send_url") or "")):
            path, _kind = resolve_sticker_storage_url(url)
            if path:
                try:
                    path.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"删除表情包素材失败 {path}: {e}")
    _save_library(library)
    return {"deleted": True, "id": sticker_id}
