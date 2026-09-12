import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from rosticcerie_clean import pipeline
from rosticcerie_clean.config import RosticceriaConfig


class ParallelExtractionTests(unittest.TestCase):
    def test_parallel_limit_order_and_fallback(self):
        configs = [RosticceriaConfig(str(i), "https://example.test", "facebook_image") for i in range(4)]
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = 0
        maximum = 0

        def extract(config):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                barrier.wait(timeout=5)
                if config.name == "1":
                    raise RuntimeError("Source unavailable")
                return {"name": config.name, "text": "current"}
            finally:
                with lock:
                    active -= 1

        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pipeline, "ROSTICCERIE", configs), \
             patch.object(pipeline, "_extract_facebook_image", side_effect=extract), \
             patch.object(pipeline, "_existing", return_value={"name": "1", "text": "previous"}), \
             patch.object(pipeline.legacy, "publish_dir", return_value=folder):
            panels = pipeline.extract_all()
            self.assertEqual(maximum, 2)
            self.assertEqual([p["name"] for p in panels], ["0", "1", "2", "3"])
            self.assertEqual(panels[1]["text"], "previous")
            report = json.loads((Path(folder) / "extraction-timings.json").read_text())
            self.assertEqual(report["restaurants"][1]["outcome"], "fallback")
            self.assertEqual(len(report["restaurants"]), 4)


if __name__ == "__main__":
    unittest.main()
