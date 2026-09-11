import unittest
import tempfile
import json
from unittest.mock import patch
from rosticcerie_clean import quick_check as q, pipeline
from rosticcerie_clean.config import ROSTICCERIE

class QuickTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        p=patch.object(q.legacy,"publish_dir",return_value=t.name);p.start();self.addCleanup(p.stop)
    def test_signed_url_ignored_content_change_detected(self):
        a={"src":"https://scontent.fbcdn.net/menu.jpg?token=a","alt":"menu"}
        b=dict(a,src="https://scontent.fbcdn.net/menu.jpg?token=b")
        self.assertEqual(q.fingerprint([a]),q.fingerprint([b]))
        self.assertNotEqual(q.fingerprint([a]),q.fingerprint([dict(b,alt="new menu")]))
        self.assertIsNone(q.fingerprint([]))
    def test_expiry_and_unknown_force_full(self):
        q.remember("X","same")
        state=json.loads(q.state_path("X").read_text())
        self.assertTrue(q.unchanged("X","same",state["full_checked_at"]+10))
        self.assertFalse(q.unchanged("X","same",state["full_checked_at"]+3600))
        self.assertFalse(q.unchanged("X",None))
        self.assertFalse(q.unchanged("X","changed"))
    def test_unchanged_skips_full_extraction(self):
        c=next(c for c in ROSTICCERIE if c.name=="Impastamò")
        saved={"image_bytes":b"saved"}
        q.remember(c.name,"same")
        with patch.object(pipeline,"_existing",return_value=saved),patch.object(q,"probe",return_value="same"),patch.object(pipeline,"_extract_facebook_image_full",side_effect=AssertionError("slow path")):
            self.assertIs(pipeline._extract_facebook_image(c),saved)
    def test_failure_does_not_seed_cache(self):
        c=next(c for c in ROSTICCERIE if c.name=="Impastamò")
        with patch.object(pipeline,"_existing",return_value=None),patch.object(q,"probe",return_value="same"),patch.object(pipeline,"_extract_facebook_image_full",side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):pipeline._extract_facebook_image(c)
        self.assertFalse(q.state_path(c.name).exists())
