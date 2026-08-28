from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "build/python/202608281053-osm-data-centres.py"
SPEC = importlib.util.spec_from_file_location("osm_data_centres_202608281053", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SOURCE_COMMIT = "a" * 40


class OSMDataCentresTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = MODULE.load_json(ROOT / MODULE.FIXTURE_REL)

    def test_doctor_and_query_rights_boundary(self) -> None:
        result = MODULE.doctor(ROOT)
        self.assertEqual(result["status"], "PASS")
        manifest = MODULE.load_json(ROOT / MODULE.MANIFEST_REL)
        self.assertEqual(manifest["excluded_sources"]["datacentermap"]["network_requests"], 0)
        self.assertEqual(manifest["excluded_sources"]["datacentermap"]["rows_copied"], 0)
        self.assertEqual(manifest["visual_validation"]["openinframap"]["network_requests"], 0)
        self.assertEqual(manifest["overpass"]["query_sha256"], MODULE.query_sha(ROOT))

    def test_normalisation_preserves_source_identity_and_abstains(self) -> None:
        elements, relationships = MODULE.normalise(self.fixture, ROOT)
        self.assertEqual(
            [row[0] for row in elements],
            ["DCGB-OSM-NODE-1001", "DCGB-OSM-RELATION-3003", "DCGB-OSM-WAY-2002"],
        )
        self.assertEqual(len(relationships), len(elements) * 2)
        relationship_columns = {name: index for index, (name, _type, _required) in enumerate(MODULE.RELATIONSHIP_SCHEMA)}
        for row in relationships:
            self.assertIsNone(row[relationship_columns["data_centre_id"]])
            self.assertIsNone(row[relationship_columns["company_number"]])
            self.assertIsNone(row[relationship_columns["match_score"]])
            self.assertEqual(row[relationship_columns["score_method"]], "NOT_SCORED")
            self.assertEqual(row[relationship_columns["adjudication_decision"]], "ABSTAIN")
            self.assertFalse(row[relationship_columns["eligible_for_join"]])

        renamed = copy.deepcopy(self.fixture)
        renamed["payload"]["elements"][0]["tags"]["name"] = "Renamed without identity drift"
        renamed_elements, _ = MODULE.normalise(renamed, ROOT)
        self.assertEqual([row[0] for row in elements], [row[0] for row in renamed_elements])

    def test_contributor_identity_is_not_in_published_schema_or_rows(self) -> None:
        names = {name for name, _type, _required in MODULE.ELEMENT_SCHEMA}
        self.assertTrue({"user", "uid", "changeset"}.isdisjoint(names))
        elements, _relationships = MODULE.normalise(self.fixture, ROOT)
        columns = {name: index for index, (name, _type, _required) in enumerate(MODULE.ELEMENT_SCHEMA)}
        for row in elements:
            tags = json.loads(row[columns["tags_json"]])
            self.assertTrue({"user", "uid", "changeset"}.isdisjoint(tags))

    def test_build_verify_and_double_compile_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            left, right = base / "left", base / "right"
            MODULE.build(ROOT, ROOT / MODULE.FIXTURE_REL, left, SOURCE_COMMIT)
            MODULE.build(ROOT, ROOT / MODULE.FIXTURE_REL, right, SOURCE_COMMIT)
            verified = MODULE.verify(left, ROOT, ROOT / MODULE.FIXTURE_REL, SOURCE_COMMIT)
            compared = MODULE.compare(left, right)
            self.assertEqual(verified["element_rows"], 3)
            self.assertEqual(verified["relationship_rows"], 6)
            self.assertEqual(verified["company_numbers_asserted"], 0)
            self.assertEqual(compared["status"], "PASS")
            audit = MODULE.load_json(left / MODULE.AUDIT_REL)
            self.assertFalse(audit["raw_fetch_landed"])
            self.assertEqual(audit["network"]["companies_fetch_requests"], 0)
            self.assertEqual(audit["rights"]["datacentermap_ingestion"], "PROHIBITED")
            self.assertLess(
                (left / MODULE.ELEMENTS_REL).stat().st_size,
                len(json.dumps(self.fixture).encode("utf-8")) * 10,
            )

    def test_rejects_empty_partial_wrong_endpoint_and_duplicate_payloads(self) -> None:
        empty = copy.deepcopy(self.fixture)
        empty["payload"]["elements"] = []
        with self.assertRaises(RuntimeError):
            MODULE.normalise(empty, ROOT)

        partial = copy.deepcopy(self.fixture)
        partial["payload"]["remark"] = "runtime error: query timed out"
        with self.assertRaises(RuntimeError):
            MODULE.normalise(partial, ROOT)

        wrong_endpoint = copy.deepcopy(self.fixture)
        wrong_endpoint["endpoint"] = "https://www.datacentermap.com/api"
        with self.assertRaises(RuntimeError):
            MODULE.normalise(wrong_endpoint, ROOT)

        duplicate = copy.deepcopy(self.fixture)
        duplicate["payload"]["elements"].append(
            copy.deepcopy(duplicate["payload"]["elements"][0])
        )
        with self.assertRaises(RuntimeError):
            MODULE.normalise(duplicate, ROOT)

    def test_bbc_record_is_link_only_and_not_project_bound(self) -> None:
        evidence = MODULE.load_json(ROOT / MODULE.EVIDENCE_REL)
        self.assertIsNone(evidence["summary"])
        self.assertEqual(evidence["raw_html_bytes"], 0)
        self.assertEqual(evidence["article_body_bytes"], 0)
        self.assertEqual(evidence["project_binding_count"], 0)
        self.assertFalse(evidence["eligible_for_news_signal"])


if __name__ == "__main__":
    unittest.main()
