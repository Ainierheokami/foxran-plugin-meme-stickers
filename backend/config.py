"""The plugin's settings, stored in the host config directory as ``meme_sticker.yaml``.

The WebUI edits them through ``/api/stickers/config`` (visual editor) or the
host's raw config editor; either way the next ``load_config()`` sees the new
file because the cache is keyed on its mtime.
"""

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field

from app.logger import setup_logger
from app.runtime.paths import CONFIG_DIR
from app.utils.yaml_utils import load_yaml_config_with_template


logger = setup_logger(__name__)

CONFIG_FILENAME = "meme_sticker.yaml"
CONFIG_PATH = CONFIG_DIR / CONFIG_FILENAME
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "config_template.yaml"


class MemeStickerPromptConfig(BaseModel):
    """表情包机会提示配置"""

    enabled: bool = Field(True, description="是否启用表情包机会提示。启用后，系统会在合适轮次向 Agent 暴露表情包发送提示。")
    always_show_capability: bool = Field(
        True,
        description="每轮都向 Agent 简短说明可以用 [meme,...] 发表情包，让它在冷却外也能自己决定发不发。",
    )
    min_messages_between_prompts: int = Field(2, description="距离上次表情包提示或发送后，至少经过多少条用户消息才再次注入“建议发表情包”提示。")
    cooldown_seconds: int = Field(60, description="发送表情包后冷却多少秒，冷却期间不注入“建议发表情包”提示。")
    persist_until_sent: bool = Field(True, description="注入提示后是否持续提示，直到 Agent 发送一条表情包。")
    max_persistent_turns: int = Field(3, description="当 persist_until_sent 为 true 时，最多连续提示多少轮；0 表示不限制。")
    allowed_platforms: List[str] = Field(
        default_factory=list,
        description="允许注入表情包机会提示的平台关键词列表。留空表示所有平台都允许。",
    )
    blocked_keywords: List[str] = Field(
        default_factory=lambda: [
            "traceback", "exception", "崩溃", "隐私", "密码", "证件", "银行卡", "医疗", "法律",
            "投诉", "吵架", "抑郁", "自杀", "紧急", "事故", "报警", "去世", "节哀",
        ],
        description="当用户消息包含这些关键词时，不注入“建议发表情包”提示。英文关键词按整词匹配。",
    )


class MemeStickerGenerationConfig(BaseModel):
    """表情包生成/复刻配置"""

    enabled: bool = Field(True, description="是否允许 Agent 调用 image_generation / image_edit 模型生成或复刻表情包。")
    style_prompt: str = Field(
        "聊天表情包，单个主体居中，夸张生动的表情和动作，简洁干净的纯色或透明背景，粗描边卡通风格，"
        "适合缩小到 128px 仍然清晰；如果有配字，文字简短、字号大、清晰可读",
        description="生成表情包时附加在描述前的风格提示词。",
    )
    size: str = Field("1024x1024", description="生成尺寸，交给模型按自身规则就近修正。")
    max_per_day: int = Field(20, description="每天最多生成/复刻多少张表情包；0 表示不限制。")
    hint_enabled: bool = Field(True, description="是否在 prompt 中提示 Agent 库里没有合适表情包时可以生成。")


class MemeStickerCollectionConfig(BaseModel):
    """表情包收集配置"""

    suggest_collect: bool = Field(True, description="用户发来表情包时，提示 Agent 可以把合适的表情包收进库。")
    sticker_summary_keywords: List[str] = Field(
        default_factory=lambda: ["表情", "sticker", "meme", "emoji"],
        description="图片 summary 包含这些词时视为表情包（QQ 表情一般是 [动画表情]）。",
    )


class MemeStickerConfig(BaseModel):
    """表情包插件配置"""

    prompt: MemeStickerPromptConfig = Field(default_factory=MemeStickerPromptConfig, description="表情包机会提示相关配置。")
    generation: MemeStickerGenerationConfig = Field(
        default_factory=MemeStickerGenerationConfig,
        description="表情包生成/复刻相关配置。",
    )
    collection: MemeStickerCollectionConfig = Field(
        default_factory=MemeStickerCollectionConfig,
        description="表情包收集相关配置。",
    )


class _ConfigCache:
    config: Optional[MemeStickerConfig] = None
    mtime: float = 0.0
    path: Optional[Path] = None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime if path.exists() else 0.0
    except OSError as e:
        logger.warning(f"获取表情包配置文件修改时间失败: {e}")
        return 0.0


def load_config(force_reload: bool = False) -> MemeStickerConfig:
    """Current settings; re-read when the file changed on disk."""
    path = CONFIG_PATH
    current = _mtime(path)
    cache = _ConfigCache
    if cache.config is not None and not force_reload and cache.path == path and current <= cache.mtime:
        return cache.config

    default_config = MemeStickerConfig()
    try:
        data = load_yaml_config_with_template(path, TEMPLATE_PATH, default_config.model_dump())
        cache.config = MemeStickerConfig.model_validate(data)
    except Exception as e:
        logger.error(f"加载表情包配置失败，将使用默认配置: {e}")
        cache.config = default_config
    cache.mtime = _mtime(path)
    cache.path = path
    return cache.config


def save_config(config: MemeStickerConfig) -> MemeStickerConfig:
    path = CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_config_yaml(config), encoding="utf-8")
    _ConfigCache.config = config
    _ConfigCache.mtime = _mtime(path)
    _ConfigCache.path = path
    logger.info("表情包插件配置已保存")
    return config


def _yaml_scalar(value: str) -> str:
    dumped = yaml.safe_dump(value, allow_unicode=True, default_flow_style=True, sort_keys=False, width=1_000_000)
    return dumped.strip().splitlines()[0]


def _render_string_list(values: List[str], indent: int) -> str:
    if not values:
        return " " * indent + "[]\n"
    prefix = " " * indent
    return "".join(f"{prefix}- {_yaml_scalar(value)}\n" for value in values)


def render_config_yaml(config: MemeStickerConfig) -> str:
    prompt = config.prompt
    generation = config.generation
    collection = config.collection
    return (
        "# 表情包插件配置。\n"
        "prompt:\n"
        "  # 是否启用表情包机会提示。启用后，系统会在合适轮次向 Agent 暴露表情包发送提示。\n"
        f"  enabled: {str(prompt.enabled).lower()}\n\n"
        "  # 每轮都向 Agent 简短说明可以用 [meme,...] 发表情包，让它在冷却外也能自己决定发不发。\n"
        f"  always_show_capability: {str(prompt.always_show_capability).lower()}\n\n"
        "  # 距离上次表情包提示或发送后，至少经过多少条用户消息才再次注入“建议发表情包”提示。\n"
        f"  min_messages_between_prompts: {prompt.min_messages_between_prompts}\n\n"
        "  # 发送表情包后冷却多少秒，冷却期间不注入“建议发表情包”提示。\n"
        f"  cooldown_seconds: {prompt.cooldown_seconds}\n\n"
        "  # 注入提示后是否持续提示，直到 Agent 发送一条表情包。\n"
        f"  persist_until_sent: {str(prompt.persist_until_sent).lower()}\n\n"
        "  # 当 persist_until_sent 为 true 时，最多连续提示多少轮；0 表示不限制。\n"
        f"  max_persistent_turns: {prompt.max_persistent_turns}\n\n"
        "  # 允许注入表情包机会提示的平台关键词列表。留空表示所有平台都允许。\n"
        "  allowed_platforms:\n"
        f"{_render_string_list(prompt.allowed_platforms, 4)}\n"
        "  # 当用户消息包含这些关键词时，不注入“建议发表情包”提示。英文关键词按整词匹配。\n"
        "  blocked_keywords:\n"
        f"{_render_string_list(prompt.blocked_keywords, 4)}\n"
        "generation:\n"
        "  # 是否允许 Agent 调用 image_generation / image_edit 模型生成或复刻表情包。\n"
        f"  enabled: {str(generation.enabled).lower()}\n\n"
        "  # 生成表情包时附加在描述前的风格提示词。\n"
        f"  style_prompt: {_yaml_scalar(generation.style_prompt)}\n\n"
        "  # 生成尺寸，交给模型按自身规则就近修正。\n"
        f"  size: {_yaml_scalar(generation.size)}\n\n"
        "  # 每天最多生成/复刻多少张表情包；0 表示不限制。\n"
        f"  max_per_day: {generation.max_per_day}\n\n"
        "  # 是否在 prompt 中提示 Agent 库里没有合适表情包时可以生成。\n"
        f"  hint_enabled: {str(generation.hint_enabled).lower()}\n\n"
        "collection:\n"
        "  # 用户发来表情包时，提示 Agent 可以把合适的表情包收进库。\n"
        f"  suggest_collect: {str(collection.suggest_collect).lower()}\n\n"
        "  # 图片 summary 包含这些词时视为表情包（QQ 表情一般是 [动画表情]）。\n"
        "  sticker_summary_keywords:\n"
        f"{_render_string_list(collection.sticker_summary_keywords, 4)}"
    )
