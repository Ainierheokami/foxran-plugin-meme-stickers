"""Meme segment, tag codec and sticker library behaviour.

Run from the Foxran host root: ``PYTHONPATH=. pytest app/tools/plugins/meme_stickers/tests``.
Replaces the host tests archived in Foxran core-refactor R0
(``tests/archive/plugins/test_meme_stickers.py`` / ``test_sticker_storage.py``).
"""

from pathlib import Path

import pytest

pytest.importorskip("app.message")

from app.agent.codec import tag_codec
from app.message import ExtensionSegment, Image, MessageChain, Text, segment_registry
from app.tools.plugins import meme_stickers
from app.tools.plugins.meme_stickers.backend import segment as meme_segment
from app.tools.plugins.meme_stickers.backend import tool as meme_tool
from app.utils.message_parts import message_segments_to_parts


@pytest.fixture
def registered():
    meme_segment.register_meme_segment()
    yield
    meme_segment.unregister_meme_segment()


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_tool, "LIBRARY_PATH", tmp_path / "stickers.json")
    meme_tool._save_library({
        "version": 1,
        "stickers": [
            {
                "id": "happy01",
                "url": "/api/stickers/assets/HAPPY01.png",
                "summary": "happy nod",
                "emotion": "happy",
                "tags": ["高兴", "捧场"],
                "usage_count": 0,
                "enabled": True,
                "last_used_at": "",
            }
        ],
    })
    monkeypatch.setattr(meme_tool, "to_absolute_url", lambda url: url)


# Rows from the host golden fixture (tests/fixtures/message_model/golden_v1.json):
# the agent text must stay byte-identical to the pre-R1 MemeSchema output.
@pytest.mark.parametrize(
    ("source", "rendered"),
    [
        ("[meme, emotion=Happy, tags=高兴,捧场, query=好耶]", "[meme, emotion=happy, tags=高兴,捧场, query=好耶]"),
        ("[meme, id=s1, summary=开心]", "[meme, id=s1, summary=开心]"),
        ("[meme]", "[meme]"),
    ],
)
def test_meme_tag_round_trips_like_the_old_schema(registered, source, rendered):
    chain = tag_codec.parse(source)

    assert tag_codec.render(chain) == rendered
    # The WebUI shows extension segments through their registered fallback, not agent syntax.
    expected_parts = [{"type": "text", "text": "[表情包]"}] if rendered != "[meme]" else [{"type": "text", "text": rendered}]
    assert message_segments_to_parts(chain) == expected_parts


def test_meme_tag_parses_to_namespaced_extension_segment(registered):
    chain = tag_codec.parse("好耶 [meme, emotion=happy, tags=高兴,捧场, summary=星星眼]")

    assert len(chain) == 2
    segment = chain[1]
    assert isinstance(segment, ExtensionSegment)
    assert segment.type == "meme_stickers.meme"
    assert segment.data == {"emotion": "happy", "tags": ["高兴", "捧场"], "summary": "星星眼"}
    assert MessageChain.from_dict(chain.to_dict()) == chain


def test_meme_without_selector_stays_plain_text(registered):
    assert [type(seg) for seg in tag_codec.parse("[meme]")] == [Text]


def test_unregistering_removes_tag_and_segment_type(registered):
    meme_segment.unregister_meme_segment()

    assert segment_registry.get("meme_stickers.meme") is None
    assert [type(seg) for seg in tag_codec.parse("[meme, id=s1]")] == [Text]
    meme_segment.register_meme_segment()


def test_unresolved_meme_degrades_to_placeholder_not_agent_syntax(registered):
    segment = meme_segment.make_meme_segment(id="missing")

    assert segment_registry.fallback(segment) == [Text(text="[表情包]")]
    assert MessageChain([segment]).summary() == "[表情包]"


def test_resolve_meme_by_id_and_by_tags(library):
    by_id = meme_tool.resolve_meme_segment(meme_segment.make_meme_segment(id="happy01"))
    assert isinstance(by_id, Image)
    assert by_id.media.url == "/api/stickers/assets/HAPPY01.png"

    by_tags = meme_tool.resolve_meme_segment(meme_segment.make_meme_segment(emotion="happy", tags=["捧场"]))
    assert isinstance(by_tags, Image)
    assert by_tags.summary_text == "happy nod"


@pytest.mark.asyncio
async def test_outbound_hook_replaces_meme_with_library_image(registered, library):
    chain = tag_codec.parse("收到 [meme, id=happy01]")

    resolved = await meme_stickers.process_outbound_message_chain(chain)

    assert [type(seg) for seg in resolved] == [Text, Image]
    assert resolved[1].media.url == "/api/stickers/assets/HAPPY01.png"


@pytest.mark.asyncio
async def test_outbound_hook_drops_meme_without_match(registered, library):
    resolved = await meme_stickers.process_outbound_message_chain(tag_codec.parse("收到 [meme, id=nope]"))

    assert resolved == MessageChain(["收到 "])


def test_persist_sticker_source_uses_asset_dir(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(b"not really png")
    asset_dir = tmp_path / "data" / "stickers" / "assets"
    monkeypatch.setattr(meme_tool, "STICKER_ASSETS_DIR", asset_dir)

    stored = meme_tool.persist_sticker_source(str(source), sticker_id="abc123")

    assert stored["url"] == "/api/stickers/assets/abc123.png"
    assert stored["storage_filename"] == "abc123.png"
    assert (asset_dir / "abc123.png").read_bytes() == b"not really png"


def test_resolve_sticker_storage_url_normalizes_nested_path(monkeypatch, tmp_path: Path):
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "ok.png").write_bytes(b"ok")
    monkeypatch.setattr(meme_tool, "STICKER_ASSETS_DIR", asset_dir)

    path, kind = meme_tool.resolve_sticker_storage_url("/api/stickers/assets/../ok.png")

    assert kind == "asset"
    assert path == asset_dir / "ok.png"


@pytest.mark.asyncio
async def test_collect_select_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_tool, "LIBRARY_PATH", tmp_path / "stickers.json")
    monkeypatch.setattr(meme_tool, "STICKER_ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(meme_tool, "STICKER_SEND_DIR", tmp_path / "send")
    source = tmp_path / "happy.png"
    source.write_bytes(b"fake png")
    tool = meme_tool.MemeStickerTool()

    collected = await tool.execute(operation="collect", url=str(source), summary="happy nod", emotion="happy", tags=["happy", "agree"])
    assert collected.success, collected
    assert "已收集表情包" in collected.data

    monkeypatch.setattr(meme_tool, "to_absolute_url", lambda url: url)
    sendable = await tool.execute(operation="select", query="happy agree", emotion="happy", tags=["agree"])
    assert sendable.success, sendable
    (image,) = tag_codec.parse(sendable.data)
    assert isinstance(image, Image)
    assert image.media.url.startswith("/api/stickers/assets/")
    assert image.summary_text == "happy nod"

    candidate = await tool.execute(operation="select", query="happy agree", emotion="happy", tags=["agree"], allow_send=False)
    assert candidate.success, candidate
    sticker_id, summary, emotion, tags, _url = [part.strip() for part in candidate.data.split("|")]
    assert (summary, emotion, tags) == ("happy nod", "happy", "happy, agree")

    deleted = await tool.execute(operation="delete", sticker_id=sticker_id)
    assert deleted.success, deleted
    assert f"已删除表情包 {sticker_id}" in deleted.data


def test_only_sendable_select_results_are_shown_to_the_user():
    from app.tools.plugins.meme_stickers.backend.tool import MemeStickerTool

    tool = MemeStickerTool()
    visibility = lambda **params: tool.get_execution_contract(params)["visibility"]

    assert visibility(operation="select") == "user_visible"
    assert visibility(operation="select", allow_send=True) == "user_visible"
    assert visibility(operation="select", allow_send=False) == "agent_only"
    assert visibility(operation="select", allow_send="false") == "agent_only"
    for operation in ("list", "collect", "update", "delete"):
        assert visibility(operation=operation) == "agent_only"


def test_tags_written_as_a_list_do_not_leave_a_bracket_behind(registered):
    chain = tag_codec.parse('哎呀 这么黏 [meme, emotion=shy, tags=["害羞","撒娇"]]')

    assert len(chain) == 2
    assert chain[0] == Text(text="哎呀 这么黏 ")
    assert chain[1].data == {"emotion": "shy", "tags": ["害羞", "撒娇"]}


def test_a_big_animation_from_the_media_cache_is_shrunk_into_the_library(tmp_path, monkeypatch):
    """2026-11-03：video_gen 出的 28MB GIF 收藏时报「表情包文件过大」，还绕公网下载了 47 秒。"""
    import io
    import json
    import os

    from PIL import Image as PILImage

    from app.media import cache_store

    frames = [PILImage.frombytes("RGB", (600, 600), os.urandom(600 * 600 * 3)) for _ in range(3)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=80, loop=0)
    (tmp_path / "ABC.gif").write_bytes(buffer.getvalue())
    monkeypatch.setattr(cache_store, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache_store, "load_index", lambda: {"ABC": {"filename": "ABC.gif"}})
    monkeypatch.setattr(meme_tool, "MAX_STICKER_BYTES", len(buffer.getvalue()) // 2)
    monkeypatch.setattr(meme_tool, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该走网络")))

    content, content_type, name = meme_tool._read_sticker_source("https://api.example.test/api/media/cache/ABC")

    assert content_type == "image/webp" and name == "ABC.webp"
    assert len(content) <= meme_tool.MAX_STICKER_BYTES
    with PILImage.open(io.BytesIO(content)) as stored:
        assert stored.n_frames == 3 and max(stored.size) <= 512


def test_collect_compression_follows_the_settings(monkeypatch):
    import io
    import os

    from PIL import Image as PILImage

    from app.tools.plugins.meme_stickers.backend import config as meme_config

    frames = [PILImage.frombytes("RGB", (800, 800), os.urandom(800 * 800 * 3)) for _ in range(2)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=80, loop=0)
    gif = buffer.getvalue()

    def settings(**collection):
        cfg = meme_config.MemeStickerConfig()
        cfg.collection = cfg.collection.model_copy(update=collection)
        monkeypatch.setattr(meme_tool, "load_config", lambda: cfg)

    settings(compress=True, max_side=300, max_kb=64)
    content, content_type, _ = meme_tool._fit_library(gif, "image/gif", "a.gif")
    assert content_type == "image/webp"
    with PILImage.open(io.BytesIO(content)) as stored:
        assert stored.n_frames == 2 and max(stored.size) <= 300

    # 小图、或者关掉压缩时原样存
    settings(compress=True, max_kb=len(gif) // 1024 + 1)
    assert meme_tool._fit_library(gif, "image/gif", "a.gif")[0] is gif
    settings(compress=False)
    assert meme_tool._fit_library(gif, "image/gif", "a.gif")[0] is gif


def test_sent_sticker_reads_as_its_meme_tag_with_url(registered, library):
    image = meme_tool.resolve_meme_segment(meme_segment.make_meme_segment(emotion="happy", tags=["捧场"]))
    assert image.media.url == "/api/stickers/assets/HAPPY01.png"
    assert tag_codec.render(image) == "[meme, id=happy01, summary=happy nod, url=/api/stickers/assets/HAPPY01.png]"


def test_written_as_a_list_still_reads_back_canonical(registered, library):
    chain = tag_codec.parse('收到 [meme, emotion=happy, tags=["捧场"]]')
    import asyncio

    resolved = asyncio.run(meme_stickers.process_outbound_message_chain(chain))
    assert tag_codec.render(resolved) == "收到 [meme, id=happy01, summary=happy nod, url=/api/stickers/assets/HAPPY01.png]"


def test_meme_by_url_sends_that_image(registered, library):
    segment = tag_codec.parse("[meme, url=https://x/old.png]")[0]
    image = meme_tool.resolve_meme_segment(segment)
    assert isinstance(image, Image) and image.media.url == "https://x/old.png"
    assert tag_codec.render(image) == "[meme, summary=表情包, url=https://x/old.png]"


def test_summary_with_brackets_or_commas_keeps_the_tag_parseable(registered):
    tag = meme_segment.sent_meme_tag("s1", "见到[酱油],就回这张", "https://x/a.png")
    segment = tag_codec.parse(tag)[0]
    assert meme_segment.is_meme_segment(segment) and segment.data["id"] == "s1"
