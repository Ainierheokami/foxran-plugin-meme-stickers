"""Send copies follow ``sending`` in ``meme_sticker.yaml``.

Run from the Foxran host root: ``PYTHONPATH=. pytest app/tools/plugins/meme_stickers/tests``.
"""

import os
from io import BytesIO

import pytest

Image = pytest.importorskip("PIL.Image")

from app.tools.plugins.meme_stickers.backend import config as meme_config
from app.tools.plugins.meme_stickers.backend import tool as meme_tool


def _noisy_png(size: int) -> bytes:
    """Random pixels compress badly, so the size limit actually has to work."""
    img = Image.frombytes("RGB", (size, size), os.urandom(size * size * 3))
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def test_longest_side_follows_max_side():
    sending = meme_config.MemeStickerSendingConfig(max_side=128, max_kb=0)

    out = meme_tool._compress_image_bytes(_noisy_png(400), sending)

    with Image.open(BytesIO(out)) as img:
        assert img.format == "WEBP"
        assert max(img.size) == 128


def test_over_max_kb_steps_quality_then_size_down():
    content = _noisy_png(512)
    unlimited = meme_tool._compress_image_bytes(content, meme_config.MemeStickerSendingConfig(max_side=512, max_kb=0))
    assert len(unlimited) > 60 * 1024

    limited = meme_tool._compress_image_bytes(content, meme_config.MemeStickerSendingConfig(max_side=512, max_kb=60))

    assert len(limited) <= 60 * 1024
    with Image.open(BytesIO(limited)) as img:
        assert max(img.size) < 512


def test_out_of_range_values_are_clamped():
    cfg = meme_config.MemeStickerSendingConfig(max_side=5, quality=500, max_kb=-3, max_frames=0).clamped()

    assert (cfg.max_side, cfg.quality, cfg.max_kb, cfg.max_frames) == (64, 95, 0, 1)


def test_changed_settings_regenerate_the_send_copy(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    send_dir = tmp_path / "send"
    assets.mkdir()
    (assets / "a.png").write_bytes(_noisy_png(300))
    monkeypatch.setattr(meme_tool, "STICKER_ASSETS_DIR", assets)
    monkeypatch.setattr(meme_tool, "STICKER_SEND_DIR", send_dir)
    monkeypatch.setattr(meme_tool, "resolve_sticker_storage_url", lambda url: (send_dir / url.rsplit("/", 1)[-1], "send"))
    current = meme_config.MemeStickerConfig()
    monkeypatch.setattr(meme_tool, "load_config", lambda: current)
    item = {"id": "a", "url": "/api/stickers/assets/a.png", "storage_filename": "a.png"}

    meme_tool._get_send_url(item)
    first_profile = item["send_profile"]
    with Image.open(send_dir / "a.webp") as img:
        assert max(img.size) == 300

    current.sending.max_side = 96
    meme_tool._get_send_url(item)

    assert item["send_profile"] != first_profile
    with Image.open(send_dir / "a.webp") as img:
        assert max(img.size) == 96
