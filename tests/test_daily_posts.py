import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from rosticcerie_clean import daily_posts as daily

class DailyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        for name, value in [("publish_dir", self.temp.name), ("rome_now", datetime(2026,9,10,14))]:
            p = patch.object(daily.legacy, name, return_value=value); p.start(); self.addCleanup(p.stop)
        p = patch.object(daily.legacy, "download_image", return_value=b"image"); self.download = p.start(); self.addCleanup(p.stop)
    def post(self, id, text):
        return {"photo_url": f"https://www.facebook.com/photo.php?fbid={id}", "image_url": f"https://cdn.test/{id}.jpg?token=1", "text": text, "published_at": "10/09/2026 10:00"}
    def test_later_ad_preserves_menu_and_ad(self):
        daily.merge_today("Impastamò", [self.post(1,"Menu")])
        result = daily.merge_today("Impastamò", [self.post(2,"Pubblicita")])
        self.assertEqual({p["text"] for p in result}, {"Menu", "Pubblicita"})
    def test_partial_or_failed_read_keeps_both(self):
        daily.merge_today("Impastamò", [self.post(1,"Menu"),self.post(2,"Pubblicita")])
        self.assertEqual(len(daily.merge_today("Impastamò", [])),2)
    def test_signed_url_change_does_not_duplicate_post(self):
        p = self.post(1,"Menu"); daily.merge_today("Impastamò",[p])
        p["image_url"] += "changed"; self.assertEqual(len(daily.merge_today("Impastamò",[p])),1)
        self.assertEqual(self.download.call_count,1)
    def test_new_day_does_not_relabel_yesterday(self):
        daily.merge_today("Impastamò",[self.post(1,"Menu")])
        with patch.object(daily.legacy,"rome_now",return_value=datetime(2026,9,11,9)):
            self.assertEqual(daily.merge_today("Impastamò",[]),[])
    def test_failed_new_download_keeps_menu(self):
        daily.merge_today("Impastamò",[self.post(1,"Menu")])
        self.download.side_effect = OSError("failed")
        self.assertEqual(len(daily.merge_today("Impastamò",[self.post(2,"Ad")])),1)

if __name__ == "__main__": unittest.main()
