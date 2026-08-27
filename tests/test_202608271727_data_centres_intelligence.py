from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "0939e3c735f4c9cacefb3acad00b35b6e07e62c2"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = load_module(
    "dcgb_builder_202608271727",
    ROOT / "build/python/202608271727-build-data-centres-intelligence.py",
)
VERIFIER = load_module(
    "dcgb_verifier_202608271727",
    ROOT / "build/python/202608271727-verify-data-centres-intelligence.py",
)


class DataCentresIntelligenceCandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="dcgb-1727-test-")
        self.temp_root = Path(self.temporary.name)
        self.first = self.temp_root / "first"
        self.second = self.temp_root / "second"
        BUILDER.build(ROOT, self.first, SOURCE_COMMIT)
        BUILDER.build(ROOT, self.second, SOURCE_COMMIT)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_two_builds_are_byte_identical_and_independently_verified(self) -> None:
        first = VERIFIER.verify(self.first, ROOT, SOURCE_COMMIT)
        second = VERIFIER.verify(self.second, ROOT, SOURCE_COMMIT)
        comparison = VERIFIER.compare(self.first, self.second)
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(second["status"], "PASS")
        self.assertEqual(first["rows"], 3)
        self.assertEqual(first["rows"], first["distinct_record_ids"])
        self.assertEqual(first["null_record_ids"], 0)
        self.assertEqual(first["duplicate_record_id_groups"], 0)
        self.assertEqual(first["context_records_eligible_for_project_signal"], 0)
        self.assertEqual(first["compression_codecs"], ["ZSTD"])
        self.assertEqual(len(comparison["byte_identical_outputs"]), 3)

    def test_export_is_ordered_and_keeps_usage_separate_from_source_rights(self) -> None:
        export = json.loads((self.first / BUILDER.EXPORT_REL).read_text(encoding="utf-8"))
        records = export["records"]
        self.assertEqual(export["usage_context"], "NON_COMMERCIAL_OPEN_SOURCE")
        self.assertEqual(export["source_rights"]["repository_code_licence"], "MIT")
        self.assertEqual(
            export["source_rights"]["upstream_source_licence"],
            "NOT_DECLARED_IN_REPOSITORY",
        )
        self.assertNotEqual(
            export["source_rights"]["repository_code_licence"],
            export["source_rights"]["upstream_source_licence"],
        )
        self.assertEqual([record["display_rank"] for record in records], [1, 2, 3])
        self.assertEqual([record["value_min"] for record in records], [564.0, 125.0, 237500.0])
        self.assertEqual(records[2]["value_max"], 712500.0)
        self.assertTrue(all(record["eligible_for_project_signal"] is False for record in records))

        audit = json.loads((self.first / BUILDER.AUDIT_REL).read_text(encoding="utf-8"))
        schema = audit["landed_file_readback"]["schema"]
        self.assertEqual(len(schema), 23)
        self.assertTrue(all(column["logical_required"] is True for column in schema))
        self.assertTrue(all(column["parquet_repetition"] == "OPTIONAL" for column in schema))
        self.assertTrue(all(column["duckdb_describe_nullability"] == "YES" for column in schema))

    def test_land_replaces_only_the_touched_partition(self) -> None:
        destination = self.temp_root / "destination"
        old_partition = (destination / BUILDER.PARQUET_REL).parent
        old_partition.mkdir(parents=True)
        (old_partition / "obsolete.parquet").write_bytes(b"obsolete")
        sentinel = destination / "data/intelligence/generation=OTHER/section=DATA_CENTRES/keep.txt"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("keep", encoding="utf-8")
        BUILDER.land_candidate(self.first, destination, SOURCE_COMMIT)
        self.assertFalse((old_partition / "obsolete.parquet").exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        landed = VERIFIER.verify(destination, ROOT, SOURCE_COMMIT)
        self.assertEqual(landed["status"], "PASS")

    def test_export_tamper_is_rejected(self) -> None:
        tampered = self.temp_root / "tampered"
        shutil.copytree(self.first, tampered)
        export_path = tampered / BUILDER.EXPORT_REL
        export = json.loads(export_path.read_text(encoding="utf-8"))
        export["records"][0]["value_min"] = 999.0
        export_path.write_text(json.dumps(export), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            VERIFIER.verify(tampered, ROOT, SOURCE_COMMIT)

    def test_partition_escape_and_symlink_are_rejected(self) -> None:
        guarded = self.temp_root / "guarded"
        guarded.mkdir()
        with self.assertRaises(RuntimeError):
            BUILDER.confined_output_path(guarded, Path("../escape.parquet"))

        outside = self.temp_root / "outside"
        outside.mkdir()
        (guarded / "data").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            BUILDER.build(ROOT, guarded, SOURCE_COMMIT)
        self.assertEqual(list(outside.iterdir()), [])

        land_destination = self.temp_root / "land-guarded"
        land_destination.mkdir()
        (land_destination / "data").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            BUILDER.land_candidate(self.first, land_destination, SOURCE_COMMIT)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
