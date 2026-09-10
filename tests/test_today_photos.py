import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
import Rosticceria_legacy as legacy

class PhotoDatesTests(unittest.TestCase):
    def test_only_explicit_today_and_deduplication(self):
        context = MagicMock()
        page = context.new_page.return_value
        def photo(alt, id):
            return {"image_alt": alt, "image_url": f"https://cdn/{id}.jpg", "photo_url": f"https://www.facebook.com/photo.php?fbid={id}"}
        today = photo("Menu del giorno Giovedi 10/09 Antipasti Primi",1)
        page.locator.return_value.evaluate_all.return_value = [today, dict(today), photo("Menu 28/08",2),photo("Menu senza data",3),photo("Menu 10/09/2025",4)]
        with patch.object(legacy,"rome_now",return_value=datetime(2026,9,10,14)):
            result = legacy.find_today_photos(context,"https://www.facebook.com/profile.php?id=61560452176728")
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["published_at"],"10/09/2026")
        page.close.assert_called_once()

if __name__ == "__main__": unittest.main()
