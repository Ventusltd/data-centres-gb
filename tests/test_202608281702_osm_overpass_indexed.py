from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "build/python/202608281702-osm-overpass-indexed.py"
SPEC = importlib.util.spec_from_file_location("osm_overpass_indexed_202608281702", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IndexedOverpassTests(unittest.TestCase):
    def test_doctor_and_exact_selector_closure(self) -> None:
        result = MODULE.doctor(ROOT)
        self.assertEqual(result["status"], "PASS")
        query = (ROOT / MODULE.QUERY_REL).read_text(encoding="utf-8")
        actual = {
            line.strip()
            for line in query.splitlines()
            if line.strip().startswith("nwr(area.gb)")
        }
        expected = {
            f'nwr(area.gb)["{prefix}{feature}"="{value}"];'
            for prefix in ("", *[f"{name}:" for name in MODULE.BASE.LIFECYCLES])
            for feature in MODULE.BASE.FEATURE_KEYS
            for value in ("data_center", "data_centre")
        }
        self.assertEqual(actual, expected)
        self.assertNotIn('[~"', query)
        self.assertNotIn("out meta geom", query)
        self.assertIn("out meta center qt;", query)

    def test_center_only_fixture_builds_and_verifies_through_successor(self) -> None:
        envelope = MODULE.BASE.load_json(ROOT / MODULE.BASE.FIXTURE_REL)
        envelope["query_sha256"] = MODULE.QUERY_SHA256
        for element in envelope["payload"]["elements"]:
            if element["type"] != "node":
                element.pop("geometry", None)
                element.pop("members", None)
                self.assertIn("center", element)
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            input_path = temporary_path / "center-only.json"
            candidate = temporary_path / "candidate"
            input_path.write_text(MODULE.BASE.pretty_json(envelope), encoding="utf-8")
            source_commit = "b" * 40
            base_command = [sys.executable, str(MODULE_PATH)]
            subprocess.run(
                [
                    *base_command,
                    "build",
                    "--root",
                    str(ROOT),
                    "--input",
                    str(input_path),
                    "--output-root",
                    str(candidate),
                    "--source-commit",
                    source_commit,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            verified = subprocess.run(
                [
                    *base_command,
                    "verify",
                    "--root",
                    str(candidate),
                    "--source-root",
                    str(ROOT),
                    "--input",
                    str(input_path),
                    "--expected-source-commit",
                    source_commit,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            receipt = json.loads(verified.stdout)
            self.assertEqual(receipt["indexed_query"], "PASS")
            self.assertEqual(receipt["privacy"], "PASS")
            audit = MODULE.BASE.load_json(candidate / MODULE.BASE.AUDIT_REL)
            self.assertEqual(audit["query_repair"], MODULE.receipt())
            self.assertEqual(
                audit["query_repair"]["failure_artifact_digest"],
                MODULE.FAILURE_ARTIFACT_DIGEST,
            )


if __name__ == "__main__":
    unittest.main()
