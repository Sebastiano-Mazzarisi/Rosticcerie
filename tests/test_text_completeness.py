import unittest
from unittest.mock import MagicMock, patch
import Rosticceria_legacy as m

class TextTests(unittest.TestCase):
    def test_multilingual_truncation(self):
        for label in ["Ver más","See more","Mostra altro","Voir plus","Mehr anzeigen"]:
            self.assertTrue(m.has_see_more_marker("PRIMI PIATTI ... "+label))
    def test_missing_required_section_not_accepted(self):
        page=MagicMock();post=MagicMock()
        page.locator.return_value.all.return_value=[post]
        post.inner_text.return_value="MENU DI GIOVEDI\nPRIMI PIATTI\nPasta al forno"
        with patch.object(m,"expand_facebook_see_more"),patch.object(m,"best_published_time_from_post",return_value="10/09/2026"):
            self.assertIsNone(m.find_first_text_menu_post(page,["secondi piatti"]))
    def test_truncated_with_sections_not_accepted(self):
        page=MagicMock();post=MagicMock()
        page.locator.return_value.all.return_value=[post]
        post.inner_text.return_value="PRIMI PIATTI\nPasta\nSECONDI PIATTI\nPollo... Ver más"
        with patch.object(m,"expand_facebook_see_more"),patch.object(m,"best_published_time_from_post",return_value="10/09/2026"):
            self.assertIsNone(m.find_first_text_menu_post(page,["secondi piatti"]))
