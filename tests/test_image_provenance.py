"""Generation records must describe actual files, including skipped assets."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from scripts.prepare_images import prepare
from scripts.treat_instrument import main as instrument_command


class ImageProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "catalog").mkdir()
        self.catalog = self.root / "catalog/images.json"
        self.audit = self.root / "assets/treated/manifest.json"
        self.source = self.root / "source.png"
        Image.new("RGB", (64, 40), (100, 100, 100)).save(self.source)
        self.manifest = {
            "schema_version": 1, "treatment_version": "rosa-reticle-0.1.0",
            "defaults": {"width": 32},
            "family_tones": {"voice": {"shadow": "#000000", "highlight": "#D6A8C8"}},
            "images": [{"slug": "voice", "family_slug": "voice", "input": "source.png",
                        "output": "assets/treated/voice.png"}],
        }
        self.save_catalog()

    def save_catalog(self):
        self.catalog.write_text(json.dumps(self.manifest))

    def read_audit(self):
        return json.loads(self.audit.read_text())

    def test_generation_records_effective_options_hashes_and_dimensions(self):
        self.assertEqual(prepare(self.catalog), 1)
        audit = self.read_audit()
        entry = audit["images"][0]
        self.assertEqual(audit["status"], "complete")
        self.assertEqual(audit["generated_images"], 1)
        self.assertEqual(entry["family_slug"], "voice")
        self.assertEqual(entry["treatment"]["parameters"],
                         {"width": 32, "shadow": "#000000", "highlight": "#D6A8C8"})
        self.assertEqual(entry["source"]["sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        output = self.root / entry["output"]["path"]
        self.assertEqual(entry["output"]["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual(entry["source"]["dimensions"], [64, 40])
        self.assertEqual(entry["output"]["dimensions"], [32, 20])
        self.assertIn("scripts/rosa_reticle.py", entry["treatment"]["implementation"])
        self.assertTrue(entry["treatment"]["runtime"]["pillow"])

    def test_skip_preserves_provenance_and_marks_changed_request(self):
        prepare(self.catalog)
        original = self.read_audit()["images"][0]
        self.assertEqual(prepare(self.catalog), 0)
        entry = self.read_audit()["images"][0]
        self.assertTrue(entry["matches_current_request"])
        self.assertEqual(entry["generated_at"], original["generated_at"])
        Image.new("RGB", (64, 40), "white").save(self.source)
        prepare(self.catalog)
        entry = self.read_audit()["images"][0]
        self.assertFalse(entry["matches_current_request"])
        self.assertEqual(entry["source"], original["source"])
        self.assertNotEqual(entry["current_request"]["source"]["sha256"], entry["source"]["sha256"])
        self.assertEqual(entry["run_action"], "skipped")

    def test_unrecorded_output_is_not_given_invented_generation_history(self):
        output = self.root / self.manifest["images"][0]["output"]
        output.parent.mkdir(parents=True)
        Image.new("RGB", (8, 8), "red").save(output)
        prepare(self.catalog)
        entry = self.read_audit()["images"][0]
        self.assertEqual(entry["provenance"], "unknown")
        self.assertNotIn("generated_at", entry)
        self.assertNotIn("treatment", entry)
        self.assertEqual(entry["output"]["dimensions"], [8, 8])

    def test_failed_batch_keeps_successful_records(self):
        self.manifest["images"].append({"slug": "missing", "input": "missing.png", "output": "assets/treated/missing.png"})
        self.save_catalog()
        with self.assertRaises(FileNotFoundError):
            prepare(self.catalog)
        audit = self.read_audit()
        self.assertEqual(audit["status"], "failed")
        self.assertEqual(audit["processed_images"], 1)
        self.assertEqual(audit["images"][0]["provenance"], "recorded")
        self.assertEqual(audit["images"][1]["run_action"], "pending")

    def test_single_instrument_exports_matching_sidecar(self):
        destination = self.root / "single.png"
        instrument_command([str(self.source), str(destination), "--width", "32"])
        record = json.loads(destination.with_suffix(".json").read_text())
        self.assertEqual(record["provenance"], "recorded")
        self.assertEqual(record["output"]["sha256"], hashlib.sha256(destination.read_bytes()).hexdigest())
        self.assertEqual(record["treatment"]["treatment_version"], "rosa-reticle-0.1.0")


if __name__ == "__main__":
    unittest.main()
