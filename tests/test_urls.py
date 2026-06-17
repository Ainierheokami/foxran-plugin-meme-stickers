import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_NAME = "app.tools.plugins.meme_stickers"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
HOST_ROOT = os.environ.get("FOXRAN_PROJECT_ROOT")
if HOST_ROOT:
    sys.path.insert(0, str(Path(HOST_ROOT).resolve()))


def load_tool_module():
    try:
        import app  # noqa: F401
    except ImportError as exc:
        raise unittest.SkipTest("Foxran host is required; set FOXRAN_PROJECT_ROOT") from exc
    package_spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        PACKAGE_ROOT / "__init__.py",
        submodule_search_locations=[str(PACKAGE_ROOT)],
    )
    package = importlib.util.module_from_spec(package_spec)
    sys.modules[PACKAGE_NAME] = package
    package_spec.loader.exec_module(package)
    return sys.modules[f"{PACKAGE_NAME}.backend.tool"]


class StickerUrlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_cwd = Path.cwd()
        if HOST_ROOT:
            os.chdir(HOST_ROOT)
        try:
            cls.tool = load_tool_module()
        except Exception:
            os.chdir(cls.original_cwd)
            raise

    @classmethod
    def tearDownClass(cls):
        for module_name in list(sys.modules):
            if module_name == PACKAGE_NAME or module_name.startswith(PACKAGE_NAME + "."):
                sys.modules.pop(module_name, None)
        os.chdir(cls.original_cwd)

    def test_storage_urls_remain_relative(self):
        self.assertEqual(self.tool.build_sticker_asset_url("asset.png"), "/api/stickers/assets/asset.png")
        self.assertEqual(self.tool.build_sticker_send_url("send.webp"), "/api/stickers/send/send.webp")

    def test_relative_url_is_externalized_only_at_output_boundary(self):
        with patch("app.config.web_api_config.get_public_base_url", return_value="https://new.example"):
            self.assertEqual(
                self.tool.to_absolute_url("/api/stickers/send/send.webp"),
                "https://new.example/api/stickers/send/send.webp",
            )
        self.assertEqual(self.tool.to_absolute_url("https://cdn.example/image.webp"), "https://cdn.example/image.webp")

    def test_absolute_storage_url_resolves_by_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            send_dir = Path(temp_dir)
            image_path = send_dir / "send.webp"
            image_path.write_bytes(b"test")
            with patch.object(self.tool, "STICKER_SEND_DIR", send_dir):
                resolved, kind = self.tool.resolve_sticker_storage_url(
                    "https://old.example/api/stickers/send/send.webp"
                )
            self.assertEqual(resolved, image_path.resolve())
            self.assertEqual(kind, "send")


if __name__ == "__main__":
    unittest.main()
