import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from rosticcerie_clean import local_menu, pipeline
from rosticcerie_clean.config import ROSTICCERIE

class LocalMenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.today = datetime(2026, 9, 10, 14)
        for target, value in [("script_dir", str(self.root)), ("rome_now", self.today)]:
            mock = patch.object(local_menu.legacy, target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.source = self.root / "input.png"
        Image.new("RGB", (400, 800), "white").save(self.source)

    def test_today_skips_facebook_even_with_cached_menu(self):
        local_menu.import_image(self.source, self.today.date())
        config = next(c for c in ROSTICCERIE if c.name == local_menu.NAME)
        with patch.object(pipeline, "_existing", side_effect=AssertionError("cache read")), patch.object(local_menu.legacy, "extract_first_facebook_image", side_effect=AssertionError("Facebook called")):
            panel = pipeline._extract_facebook_image(config)
        self.assertEqual(panel["published_at"], "10/09/2026")

    def test_yesterday_not_marked_as_today(self):
        local_menu.import_image(self.source, self.today.date() - timedelta(days=1))
        self.assertIsNone(local_menu.local_panel())

    def test_corrupt_file_falls_back(self):
        path = local_menu.menu_path(self.today.date())
        path.parent.mkdir()
        path.write_bytes(b"not an image")
        self.assertIsNone(local_menu.local_panel())

    def test_failed_import_preserves_previous_file(self):
        path = local_menu.import_image(self.source, self.today.date())
        before = path.read_bytes()
        self.source.write_bytes(b"invalid")
        with self.assertRaises(OSError):
            local_menu.import_image(self.source, self.today.date())
        self.assertEqual(path.read_bytes(), before)

    def test_future_date_rejected(self):
        with self.assertRaises(ValueError):
            local_menu.import_image(self.source, self.today.date() + timedelta(days=1))

if __name__ == "__main__":
    unittest.main()
