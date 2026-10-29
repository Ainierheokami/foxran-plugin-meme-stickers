"""WebUI endpoints for drawing and remaking stickers.

Run from the Foxran host root: ``PYTHONPATH=. pytest app/tools/plugins/meme_stickers/tests``.
"""

import time
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints.auth import require_auth
from app.tools.plugins.meme_stickers.backend import api as meme_api
from app.tools.plugins.meme_stickers.backend import generation
from app.tools.plugins.meme_stickers.backend import tool as meme_tool


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_tool, "LIBRARY_PATH", tmp_path / "stickers.json")
    monkeypatch.setattr(meme_tool, "STICKER_ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(meme_tool, "STICKER_SEND_DIR", tmp_path / "send")
    cfg = SimpleNamespace(enabled=True, style_prompt="卡通", size="512x512", max_per_day=3, hint_enabled=True)
    monkeypatch.setattr(generation, "load_generation_config", lambda: cfg)
    monkeypatch.setattr(generation, "model_available", lambda tag: tag == "image_edit")
    app = FastAPI()
    app.include_router(meme_api.router)
    app.dependency_overrides[require_auth] = lambda: True
    # 绘图任务在后台跑，要整个测试共用一个事件循环
    with TestClient(app) as test_client:
        yield test_client


def wait_job(client, response):
    """POST 返回 202 + job，轮询到结束。"""
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    deadline = time.time() + 5
    while job["status"] == "running" and time.time() < deadline:
        time.sleep(0.02)
        job = client.get(f"/api/stickers/jobs/{job['id']}").json()["job"]
    return job


def test_status_reports_models_and_quota(client):
    status = client.get("/api/stickers/generation/status").json()

    assert status == {
        "enabled": True,
        "can_generate": False,
        "can_remake": True,
        "used_today": 0,
        "max_per_day": 3,
        "size": "512x512",
        "persona_roles": [],
        "default_role": generation.DEFAULT_ROLE_ID,
    }


def test_generate_then_remake_by_id_and_filter_by_source(client, tmp_path, monkeypatch):
    drawn = tmp_path / "drawn.png"
    drawn.write_bytes(b"drawn")
    redrawn = tmp_path / "redrawn.png"
    redrawn.write_bytes(b"redrawn")
    seen = {}

    async def fake_draw(prompt, size):
        return str(drawn)

    async def fake_redraw(prompt, image_bytes, size):
        seen.update(prompt=prompt, image_bytes=image_bytes)
        return str(redrawn)

    monkeypatch.setattr(generation, "draw_sticker", fake_draw)
    monkeypatch.setattr(generation, "redraw_sticker", fake_redraw)

    made = wait_job(client, client.post("/api/stickers/generate", json={"prompt": "开心的狐狸", "emotion": "happy", "tags": ["开心"]}))
    assert made["status"] == "done", made
    original = made["item"]
    assert original["source"] == "generated"
    assert original["thumb_url"].startswith("/api/stickers/thumb/assets/")

    remade = wait_job(client, client.post(f"/api/stickers/{original['id']}/remake", json={"prompt": "换成猫"}))
    assert remade["status"] == "done", remade
    copy = remade["item"]
    assert copy["source"] == "remade"
    assert copy["reference_id"] == original["id"]
    assert copy["emotion"] == "happy" and copy["tags"] == ["开心"]
    assert seen["image_bytes"] == b"drawn"
    assert "开心的狐狸" in seen["prompt"]

    listing = client.get("/api/stickers", params={"source": "remade"}).json()
    assert [item["id"] for item in listing["items"]] == [copy["id"]]
    assert listing["sources"] == ["generated", "remade"]


def test_generate_errors_are_reported(client, monkeypatch):
    missing = client.post("/api/stickers/generate", json={})
    assert missing.status_code == 400

    async def broken(prompt, size):
        raise RuntimeError("no model")

    monkeypatch.setattr(generation, "draw_sticker", broken)
    failed = wait_job(client, client.post("/api/stickers/generate", json={"prompt": "x"}))
    assert failed["status"] == "error"
    assert "no model" in failed["error"]

    assert client.post("/api/stickers/nope/remake", json={}).status_code == 404
    assert client.get("/api/stickers/jobs/nope").status_code == 404


def test_as_self_without_persona_images_is_rejected(client, monkeypatch):
    monkeypatch.setattr(generation, "persona_ref_count", lambda role_id: 0)

    response = client.post("/api/stickers/generate", json={"prompt": "比心", "as_self": True})

    assert response.status_code == 400
    assert "形象参考图" in response.json()["detail"]


def test_as_self_draws_from_persona_images(client, tmp_path, monkeypatch):
    drawn = tmp_path / "self.png"
    drawn.write_bytes(b"self")
    seen = {}

    async def fake_redraw(prompt, image_bytes, size, extra_images=None):
        seen.update(prompt=prompt, image_bytes=image_bytes, extra=extra_images)
        return str(drawn)

    monkeypatch.setattr(generation, "persona_ref_count", lambda role_id: 2)
    monkeypatch.setattr(generation, "load_persona_refs", lambda role_id: [
        {"id": "a", "note": "正面立绘", "bytes": b"front"},
        {"id": "b", "note": "", "bytes": b"side"},
    ])
    monkeypatch.setattr(generation, "redraw_sticker", fake_redraw)

    job = wait_job(client, client.post("/api/stickers/generate", json={"prompt": "比心", "as_self": True, "role_id": "狐狐"}))

    assert job["status"] == "done", job
    assert seen["image_bytes"] == b"front" and seen["extra"] == [b"side"]
    assert "狐狐" in seen["prompt"] and "正面立绘" in seen["prompt"]
    assert "狐狐" in job["item"]["tags"]


def test_upload_dedupes_by_content(client):
    files = [("files", ("a.png", b"same bytes", "image/png"))]

    first = client.post("/api/stickers/upload", files=files, data={"tags": "开心"}).json()
    second = client.post("/api/stickers/upload", files=files, data={"tags": "捧场"}).json()

    assert first["items"][0]["id"] == second["items"][0]["id"]
    assert second["items"][0]["tags"] == ["开心", "捧场"]
    assert second["items"][0]["source"] == "upload"
