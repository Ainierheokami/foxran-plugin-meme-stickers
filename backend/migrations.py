"""One-time upgrades of ``sticker_library.json``; each is safe to run again.

The plugin runs them at startup (host ADR 0005: migrate stored data once, read
only the new format afterwards).
"""

from __future__ import annotations

import hashlib

from app.logger import setup_logger

from .tool import _load_library, _resolve_sticker_source_path, _save_library


logger = setup_logger(__name__)


def backfill_content_sha1() -> int:
    """2026-10-13: give every stored sticker the ``content_sha1`` used to dedupe collections."""
    library = _load_library()
    updated = 0
    for item in library["stickers"]:
        if item.get("content_sha1"):
            continue
        path = _resolve_sticker_source_path(item)
        if path is None:
            continue
        item["content_sha1"] = hashlib.sha1(path.read_bytes()).hexdigest()
        updated += 1
    if updated:
        _save_library(library)
        logger.info(f"[表情包插件] 已为 {updated} 张表情包补充内容哈希")
    return updated


def run_migrations() -> None:
    backfill_content_sha1()
