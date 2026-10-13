"""The plugin owns ``meme_sticker.yaml``: model, template, API and reload on edit.

Run from the Foxran host root: ``PYTHONPATH=. pytest app/tools/plugins/meme_stickers/tests``.
"""

import os

import pytest
import yaml

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints.auth import require_auth
from app.tools.plugins.meme_stickers.backend import api as meme_api
from app.tools.plugins.meme_stickers.backend import config as meme_config


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "meme_sticker.yaml"
    monkeypatch.setattr(meme_config, "CONFIG_PATH", path)
    monkeypatch.setattr(meme_config._ConfigCache, "config", None)
    return path


def test_template_is_the_rendered_defaults():
    rendered = meme_config.render_config_yaml(meme_config.MemeStickerConfig())

    assert meme_config.TEMPLATE_PATH.read_text(encoding="utf-8") == rendered


def test_missing_file_is_created_from_template(config_path):
    config = meme_config.load_config()

    assert config == meme_config.MemeStickerConfig()
    assert config_path.exists()


def test_long_strings_survive_a_save(config_path):
    config = meme_config.MemeStickerConfig()
    config.generation.style_prompt = "长 " * 300 + ": x # y"

    meme_config.save_config(config)
    meme_config._ConfigCache.config = None

    assert meme_config.load_config() == config


def test_raw_file_edits_are_picked_up(config_path):
    meme_config.load_config()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["prompt"]["cooldown_seconds"] = 5
    config_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    stat = config_path.stat()
    os.utime(config_path, (stat.st_atime, stat.st_mtime + 10))

    assert meme_config.load_config().prompt.cooldown_seconds == 5


def test_config_api_round_trip(config_path):
    app = FastAPI()
    app.include_router(meme_api.router)
    app.dependency_overrides[require_auth] = lambda: True
    client = TestClient(app)

    payload = client.get("/api/stickers/config").json()["config"]
    payload["generation"]["max_per_day"] = 3
    payload["prompt"]["allowed_platforms"] = ["qq"]
    saved = client.post("/api/stickers/config", json=payload)

    assert saved.status_code == 200, saved.text
    on_disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert on_disk["generation"]["max_per_day"] == 3
    assert on_disk["prompt"]["allowed_platforms"] == ["qq"]
