"""Draw new stickers with the host's image models.

``generate`` uses the ``image_generation`` model tag (text to image) and
``remake`` uses ``image_edit`` (image to image) to redraw an existing sticker.
The host returns either a remote URL or a local temp file; both are read back
as bytes so the plugin can store them in its own asset directory.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

from app.logger import setup_logger

from .config import MemeStickerGenerationConfig, load_config


logger = setup_logger(__name__)

GENERATED_SOURCES = ("generated", "remade")
_AVAILABILITY_TTL_SECONDS = 60.0
_availability_cache: Dict[str, tuple[float, bool]] = {}


def load_generation_config() -> MemeStickerGenerationConfig:
    """The ``generation`` section of ``meme_sticker.yaml``."""
    return load_config().generation


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
    if not cfg.enabled:
        return False
    return model_available("image_generation") or model_available("image_edit")


def generated_today(stickers: list[Dict[str, Any]]) -> int:
    today = datetime.now().date().isoformat()
    return sum(
        1
        for item in stickers
        if item.get("source") in GENERATED_SOURCES and str(item.get("created_at") or "").startswith(today)
    )


DEFAULT_ROLE_ID = "语星灵繎"
# Persona images sent with each drawing: the primary one plus one more angle.
PERSONA_REFS_PER_DRAW = 2


def session_role_id(session_ctx: Any) -> str:
    """The role the session speaks as; hosts before role refs fall back to ``bot_name``."""
    try:
        from app.prompts.role_refs import role_id_for_session
    except ImportError:
        return str(getattr(session_ctx, "bot_name", "") or DEFAULT_ROLE_ID)
    return role_id_for_session(session_ctx)


def load_persona_refs(role_id: str) -> List[Dict[str, Any]]:
    """The role's reference images for the model (``bytes``/``note``/``id``); empty on older hosts."""
    try:
        from app.prompts.role_refs import load_ref_images
    except ImportError:
        return []
    try:
        return load_ref_images(role_id, PERSONA_REFS_PER_DRAW)
    except ValueError:
        return []


def persona_ref_count(role_id: str) -> int:
    try:
        from app.prompts.role_refs import count_refs
    except ImportError:
        return 0
    return count_refs(role_id)


def persona_roles() -> List[Dict[str, Any]]:
    """Roles that have reference images, for the WebUI generator."""
    try:
        from app.prompts.role_refs import count_refs
        from app.runtime.paths import ROLE_REFS_DIR
    except ImportError:
        return []
    if not ROLE_REFS_DIR.exists():
        return []
    roles = []
    for directory in sorted(ROLE_REFS_DIR.iterdir()):
        if directory.is_dir():
            count = count_refs(directory.name)
            if count:
                roles.append({"id": directory.name, "ref_count": count})
    return roles


def build_sticker_prompt(
    *,
    style_prompt: str,
    description: str,
    caption: str = "",
    emotion: str = "",
    reference_summary: str = "",
    remake: bool = False,
    persona: str = "",
    persona_notes: Optional[List[str]] = None,
) -> str:
    parts = []
    notes = "；".join(note for note in persona_notes or [] if note)
    if remake:
        parts.append("复刻参考图里的表情包：保留角色、构图、动作和情绪，重新绘制成清晰的新表情包。")
        if reference_summary:
            parts.append(f"参考图内容：{reference_summary}。")
        if persona:
            parts.append(
                f"第一张图是要复刻的表情包，后面的图是角色「{persona}」的形象参考图：把表情包里的主角换成这个角色，"
                "外貌（发型发色、瞳色、耳朵尾巴、服装配饰）以形象参考图为准，动作、表情和构图沿用第一张。"
            )
    elif persona:
        parts.append(
            f"参考图是角色「{persona}」的形象设定图。画一张以她为主角的新表情包：外貌（发型发色、瞳色、耳朵尾巴、服装配饰）"
            "必须和参考图一致，一眼能认出是同一个角色；动作和表情按下面的画面要求重新画，不要照搬参考图的姿势和背景。"
        )
    if persona and notes:
        parts.append(f"形象参考图说明：{notes}。")
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


async def redraw_sticker(
    prompt: str,
    image_bytes: bytes,
    size: str,
    extra_images: Optional[List[bytes]] = None,
) -> str:
    from app.openai_client import ask_model_for_image_edit

    kwargs: Dict[str, Any] = {}
    if extra_images:
        # 宿主 4.9.21 起 image edit 才收多张参考图
        if "extra_images" in inspect.signature(ask_model_for_image_edit).parameters:
            kwargs["extra_images"] = extra_images
        else:
            logger.info("[表情包插件] 宿主版本不支持多图参考，只发送第一张")
    result = await ask_model_for_image_edit(
        prompt=prompt,
        image_bytes=await asyncio.to_thread(to_png, image_bytes),
        size=size,  # type: ignore[arg-type]
        **kwargs,
    )
    if not result or not result.url:
        raise RuntimeError("图像编辑模型没有返回图片。")
    return result.url


def daily_limit_reached(stickers: list[Dict[str, Any]], cfg: MemeStickerGenerationConfig) -> bool:
    limit = int(cfg.max_per_day or 0)
    return limit > 0 and generated_today(stickers) >= limit
