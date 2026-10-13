"""Draw new stickers with the host's image models.

``generate`` uses the ``image_generation`` model tag (text to image) and
``remake`` uses ``image_edit`` (image to image) to redraw an existing sticker.
The host returns either a remote URL or a local temp file; both are read back
as bytes so the plugin can store them in its own asset directory.
"""

from __future__ import annotations

import time
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional

from app.logger import setup_logger


logger = setup_logger(__name__)

GENERATED_SOURCES = ("generated", "remade")
_AVAILABILITY_TTL_SECONDS = 60.0
_availability_cache: Dict[str, tuple[float, bool]] = {}


def load_generation_config() -> Any:
    """The host's ``generation`` section, or ``None`` on hosts that predate it."""
    try:
        from app.config import load_meme_sticker_config

        return getattr(load_meme_sticker_config(), "generation", None)
    except Exception as e:
        logger.debug(f"[表情包插件] 读取生成配置失败: {e}")
        return None


def model_available(tag: str) -> bool:
    """Whether models.yaml has a usable model with ``tag``; cached briefly per turn."""
    now = time.monotonic()
    cached = _availability_cache.get(tag)
    if cached and now - cached[0] < _AVAILABILITY_TTL_SECONDS:
        return cached[1]
    try:
        from app.config import load_model_configs
        from app.openai_client.model_pool import ModelPool

        available = bool(ModelPool(load_model_configs()).get_available_models(tags=[tag]))
    except Exception as e:
        logger.debug(f"[表情包插件] 检查 {tag} 模型失败: {e}")
        available = False
    _availability_cache[tag] = (now, available)
    return available


def generation_available() -> bool:
    cfg = load_generation_config()
    if cfg is None or not cfg.enabled:
        return False
    return model_available("image_generation") or model_available("image_edit")


def generated_today(stickers: list[Dict[str, Any]]) -> int:
    today = datetime.now().date().isoformat()
    return sum(
        1
        for item in stickers
        if item.get("source") in GENERATED_SOURCES and str(item.get("created_at") or "").startswith(today)
    )


def build_sticker_prompt(
    *,
    style_prompt: str,
    description: str,
    caption: str = "",
    emotion: str = "",
    reference_summary: str = "",
    remake: bool = False,
) -> str:
    parts = []
    if remake:
        parts.append("复刻参考图里的表情包：保留角色、构图、动作和情绪，重新绘制成清晰的新表情包。")
        if reference_summary:
            parts.append(f"参考图内容：{reference_summary}。")
    if style_prompt:
        parts.append(f"风格：{style_prompt}。")
    if description:
        parts.append(f"画面：{description}。" if not remake else f"修改要求：{description}。")
    if emotion:
        parts.append(f"情绪：{emotion}。")
    if caption:
        parts.append(f"图上配字（必须一字不差）：「{caption}」。")
    else:
        parts.append("图上不要出现文字。" if not remake else "")
    return "".join(part for part in parts if part)


def to_png(content: bytes) -> bytes:
    """Image edit endpoints take a still PNG; animated stickers use their first frame."""
    try:
        from PIL import Image
    except Exception:
        return content
    try:
        with Image.open(BytesIO(content)) as img:
            img.seek(0)
            frame = img.convert("RGBA")
            buffer = BytesIO()
            frame.save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception as e:
        logger.debug(f"[表情包插件] 参考图转 PNG 失败，使用原图: {e}")
        return content


async def draw_sticker(prompt: str, size: str) -> str:
    from app.openai_client import ask_model_for_image_generation

    result = await ask_model_for_image_generation(prompt=prompt, size=size)  # type: ignore[arg-type]
    if not result or not result.url:
        raise RuntimeError("图像生成模型没有返回图片。")
    return result.url


async def redraw_sticker(prompt: str, image_bytes: bytes, size: str) -> str:
    from app.openai_client import ask_model_for_image_edit

    result = await ask_model_for_image_edit(
        prompt=prompt,
        image_bytes=to_png(image_bytes),
        size=size,  # type: ignore[arg-type]
    )
    if not result or not result.url:
        raise RuntimeError("图像编辑模型没有返回图片。")
    return result.url


def daily_limit_reached(stickers: list[Dict[str, Any]], cfg: Optional[Any]) -> bool:
    limit = int(getattr(cfg, "max_per_day", 0) or 0)
    return limit > 0 and generated_today(stickers) >= limit
