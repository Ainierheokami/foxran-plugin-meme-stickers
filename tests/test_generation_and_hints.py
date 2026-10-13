"""Sticker generation/remake, collection dedup and the prompt hint pacing.

Run from the Foxran host root: ``PYTHONPATH=. pytest app/tools/plugins/meme_stickers/tests``.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("app.message")

from app.agent.codec import tag_codec
from app.message import Image
from app.tools.plugins.meme_stickers.backend import generation
from app.tools.plugins.meme_stickers.backend import prompt as meme_prompt
from app.tools.plugins.meme_stickers.backend import tool as meme_tool


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_tool, "LIBRARY_PATH", tmp_path / "stickers.json")
    monkeypatch.setattr(meme_prompt, "LIBRARY_PATH", tmp_path / "stickers.json")
    monkeypatch.setattr(meme_tool, "STICKER_ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(meme_tool, "STICKER_SEND_DIR", tmp_path / "send")
    monkeypatch.setattr(meme_tool, "to_absolute_url", lambda url: url)
    meme_prompt._library_cache.update(mtime=None, summary=None)
    return tmp_path


def _generation_cfg(**overrides):
    values = {"enabled": True, "style_prompt": "卡通", "size": "1024x1024", "max_per_day": 5, "hint_enabled": True}
    values.update(overrides)
    return SimpleNamespace(**values)


def _prompt_cfg(**overrides):
    values = {
        "enabled": True,
        "always_show_capability": True,
        "min_messages_between_prompts": 2,
        "cooldown_seconds": 60,
        "persist_until_sent": True,
        "max_persistent_turns": 2,
        "allowed_platforms": [],
        "blocked_keywords": ["traceback", "隐私"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


COLLECTION = SimpleNamespace(suggest_collect=True, sticker_summary_keywords=["表情"])
LIBRARY = {"count": 2, "emotions": ["happy"], "tags": ["开心"]}
EMPTY = {"count": 0, "emotions": [], "tags": []}


@pytest.mark.asyncio
async def test_collect_dedups_the_same_image_from_different_urls(store):
    first = store / "a.png"
    second = store / "b.png"
    first.write_bytes(b"same bytes")
    second.write_bytes(b"same bytes")
    tool = meme_tool.MemeStickerTool()

    one = await tool.execute(operation="collect", url=str(first), summary="猫猫点头", tags=["点头"])
    two = await tool.execute(operation="collect", url=str(second), emotion="agree", tags=["赞同"])

    assert "已收集表情包" in one.data
    assert "已更新表情包" in two.data
    (item,) = meme_tool._load_library()["stickers"]
    assert item["summary"] == "猫猫点头"
    assert item["emotion"] == "agree"
    assert item["tags"] == ["点头", "赞同"]
    assert item["source"] == "collected"


def test_find_image_tags_keeps_bracketed_summary():
    text = "看 [image,url=https://q.qq.com/x.gif, summary=[动画表情]] 哈哈"

    assert meme_tool.find_image_tags(text) == [{"url": "https://q.qq.com/x.gif", "summary": "[动画表情]"}]


@pytest.mark.asyncio
async def test_generate_draws_stores_and_sends(store, monkeypatch):
    drawn = store / "drawn.png"
    drawn.write_bytes(b"generated sticker")
    calls = []

    async def fake_draw(prompt, size):
        calls.append((prompt, size))
        return str(drawn)

    monkeypatch.setattr(generation, "load_generation_config", lambda: _generation_cfg())
    monkeypatch.setattr(generation, "draw_sticker", fake_draw)
    session = SimpleNamespace(session_id="s1", session_notes={}, history=[])
    tool = meme_tool.MemeStickerTool()

    result = await tool.execute(
        session_ctx=session, operation="generate", prompt="一只叉腰的狐狸", caption="就这？", emotion="tease", tags=["嘲讽"]
    )

    assert result.success, result
    (image,) = tag_codec.parse(result.data)
    assert isinstance(image, Image)
    assert image.summary_text == "就这？"
    prompt_text, size = calls[0]
    assert "一只叉腰的狐狸" in prompt_text and "「就这？」" in prompt_text and size == "1024x1024"
    (item,) = meme_tool._load_library()["stickers"]
    assert item["source"] == "generated"
    assert item["tags"] == ["嘲讽", "就这？"]
    assert item["usage_count"] == 1
    assert session.session_notes["meme_sticker_state"]["prompt_active"] is False


@pytest.mark.asyncio
async def test_remake_uses_recent_image_and_respects_daily_limit(store, monkeypatch):
    reference = store / "ref.gif"
    reference.write_bytes(b"reference")
    redrawn = store / "redrawn.png"
    redrawn.write_bytes(b"redrawn")
    seen = {}

    async def fake_redraw(prompt, image_bytes, size):
        seen.update(prompt=prompt, image_bytes=image_bytes)
        return str(redrawn)

    monkeypatch.setattr(generation, "load_generation_config", lambda: _generation_cfg(max_per_day=1))
    monkeypatch.setattr(generation, "redraw_sticker", fake_redraw)
    history = [SimpleNamespace(role="user", content=f"[image,url={reference}, summary=[动画表情]]")]
    session = SimpleNamespace(session_id="s1", session_notes={}, history=history)
    tool = meme_tool.MemeStickerTool()

    first = await tool.execute(session_ctx=session, operation="remake", prompt="换成狐狸", allow_send=False)
    second = await tool.execute(session_ctx=session, operation="remake")

    assert first.success, first
    assert "已生成并收进表情包库" in first.data
    assert seen["image_bytes"] == b"reference"
    assert "复刻" in seen["prompt"] and "换成狐狸" in seen["prompt"]
    assert meme_tool._load_library()["stickers"][0]["reference_url"] == str(reference)
    assert not second.success
    assert "次数已用完" in second.error


def test_sending_operations_are_user_visible():
    tool = meme_tool.MemeStickerTool()
    visibility = lambda **params: tool.get_execution_contract(params)["visibility"]

    assert visibility(operation="generate") == "user_visible"
    assert visibility(operation="remake") == "user_visible"
    assert visibility(operation="generate", allow_send=False) == "agent_only"


def test_keyword_hit_matches_ascii_as_whole_words():
    assert meme_prompt.keyword_hit("got a Traceback here", ["traceback"])
    assert not meme_prompt.keyword_hit("terror movie", ["error"])
    assert meme_prompt.keyword_hit("这是隐私", ["隐私"])


def test_hints_pace_opportunity_and_show_capability_between():
    state = {}
    cfg = _prompt_cfg()
    build = lambda text, now: meme_prompt.build_hints(
        prompt_cfg=cfg, collection_cfg=COLLECTION, state=state, text=text, summary=LIBRARY, can_draw=False, now=now
    )

    first, _ = build("哈哈", 1000)
    second, _ = build("好耶", 1001)

    assert first == [meme_prompt.capability_hint(LIBRARY)]
    assert second[0].startswith("[表情包机会]")
    assert state["prompt_active"] is True

    state["last_sticker_at"] = 1002
    state.update(prompt_active=False, prompt_turns=0, turns_since_sticker=5)
    cooling, _ = build("再来", 1010)
    assert cooling == [meme_prompt.capability_hint(LIBRARY)]


def test_blocked_keywords_suppress_everything_but_explicit_asks_bypass_spacing():
    state = {"turns_since_sticker": 0, "last_sticker_at": 0}
    cfg = _prompt_cfg(min_messages_between_prompts=10)

    blocked, _ = meme_prompt.build_hints(
        prompt_cfg=cfg, collection_cfg=COLLECTION, state=state, text="这是隐私", summary=LIBRARY, can_draw=False, now=1000
    )
    asked, _ = meme_prompt.build_hints(
        prompt_cfg=cfg, collection_cfg=COLLECTION, state=state, text="来个表情包", summary=LIBRARY, can_draw=False, now=1000
    )

    assert blocked == []
    assert "用户在要表情包" in asked[0]


def test_incoming_sticker_suggests_collect_once_and_invites_a_reply():
    state = {}
    text = "[image,url=https://q.qq.com/cat.gif, summary=[动画表情]]"
    build = lambda: meme_prompt.build_hints(
        prompt_cfg=_prompt_cfg(), collection_cfg=COLLECTION, state=state, text=text, summary=LIBRARY, can_draw=False, now=1000
    )

    first, needs_tool = build()
    again, _ = build()

    assert first[0].startswith("[表情包收集]") and "https://q.qq.com/cat.gif" in first[0]
    assert needs_tool
    assert first[1].startswith("[表情包机会]")
    assert not any(hint.startswith("[表情包收集]") for hint in again)


def test_empty_library_only_hints_when_drawing_is_possible():
    hints, needs_tool = meme_prompt.build_hints(
        prompt_cfg=_prompt_cfg(), collection_cfg=None, state={}, text="嗨", summary=EMPTY, can_draw=False, now=1000
    )
    assert hints == [] and not needs_tool

    state = {"turns_since_sticker": 5}
    hints, needs_tool = meme_prompt.build_hints(
        prompt_cfg=_prompt_cfg(), collection_cfg=None, state=state, text="嗨", summary=EMPTY, can_draw=True, now=1000
    )
    assert "operation=generate" in hints[0] and "还是空的" in hints[0]
    assert needs_tool


def test_library_summary_counts_enabled_stickers(store):
    meme_tool._save_library({
        "version": 1,
        "stickers": [
            {"id": "a", "url": "/a.png", "emotion": "happy", "tags": ["开心"], "enabled": True},
            {"id": "b", "url": "/b.png", "emotion": "happy", "tags": ["开心", "捧场"]},
            {"id": "c", "url": "/c.png", "emotion": "sorry", "enabled": False},
        ],
    })

    summary = meme_prompt.library_summary()

    assert summary == {"count": 2, "emotions": ["happy"], "tags": ["开心", "捧场"]}
