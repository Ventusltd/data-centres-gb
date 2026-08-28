from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "build/python/202608281626-osm-overpass-retry.py"
SPEC = importlib.util.spec_from_file_location("osm_overpass_retry_202608281626", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, status: int, payload: object | None = None, raw: bytes | None = None):
        self.status_code = status
        self._payload = payload
        self.content = raw if raw is not None else json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return copy.deepcopy(self._payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class OverpassRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = MODULE.BASE.load_json(ROOT / MODULE.BASE.FIXTURE_REL)
        self.valid_payload = fixture["payload"]

    def test_remarked_response_is_retried_then_valid_response_lands(self) -> None:
        remarked = {"remark": "runtime error: query timed out", "elements": []}
        responses = [FakeResponse(200, remarked), FakeResponse(200, self.valid_payload)]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "overpass-fetch.json"
            with mock.patch.object(MODULE.requests, "post", side_effect=responses) as post, mock.patch.object(
                MODULE.time, "sleep"
            ) as sleep:
                result = MODULE.fetch(ROOT, output)
            self.assertEqual(post.call_count, 2)
            sleep.assert_called_once_with(30)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["network_request_attempts"], 2)
            self.assertTrue(output.is_file())
            envelope = MODULE.BASE.load_json(output)
            self.assertEqual(envelope["network_request_attempts"], 2)
            self.assertEqual(envelope["network_successful_requests"], 1)
            self.assertFalse(MODULE.failure_evidence_path(output).exists())

    def test_repeated_remarks_fail_closed_with_sanitised_receipt(self) -> None:
        remark = "runtime error: query timed out"
        responses = [
            FakeResponse(200, {"remark": remark, "elements": []}),
            FakeResponse(200, {"remark": remark, "elements": []}),
            FakeResponse(200, {"remark": remark, "elements": []}),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "overpass-fetch.json"
            with mock.patch.object(MODULE.requests, "post", side_effect=responses), mock.patch.object(
                MODULE.time, "sleep"
            ):
                with self.assertRaises(RuntimeError):
                    MODULE.fetch(ROOT, output)
            self.assertFalse(output.exists())
            evidence = MODULE.BASE.load_json(MODULE.failure_evidence_path(output))
            self.assertEqual(evidence["status"], "FAILED")
            self.assertEqual(evidence["attempts_performed"], 3)
            self.assertEqual(
                [attempt["classification"] for attempt in evidence["attempts"]],
                ["OVERPASS_REMARK", "OVERPASS_REMARK", "OVERPASS_REMARK"],
            )
            self.assertEqual(evidence["attempts"][0]["remark"], remark)
            self.assertFalse(evidence["attempts"][0]["response_body_retained"])
            self.assertFalse(evidence["raw_overpass_response_landed"])
            self.assertNotIn("payload", evidence)

    def test_retryable_http_then_valid_response_lands(self) -> None:
        responses = [FakeResponse(429, {"error": "busy"}), FakeResponse(200, self.valid_payload)]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "overpass-fetch.json"
            with mock.patch.object(MODULE.requests, "post", side_effect=responses), mock.patch.object(
                MODULE.time, "sleep"
            ):
                result = MODULE.fetch(ROOT, output)
            self.assertEqual(result["network_request_attempts"], 2)
            self.assertTrue(output.is_file())

    def test_network_exception_then_valid_response_lands(self) -> None:
        responses = [requests.Timeout("timed out"), FakeResponse(200, self.valid_payload)]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "overpass-fetch.json"
            with mock.patch.object(MODULE.requests, "post", side_effect=responses), mock.patch.object(
                MODULE.time, "sleep"
            ):
                result = MODULE.fetch(ROOT, output)
            self.assertEqual(result["network_request_attempts"], 2)
            self.assertTrue(output.is_file())

    def test_private_and_unverified_party_strings_never_reach_outputs(self) -> None:
        envelope = MODULE.BASE.load_json(ROOT / MODULE.BASE.FIXTURE_REL)
        tags = envelope["payload"]["elements"][0]["tags"]
        tags.update(
            {
                "name": "Private Person",
                "operator": "Private Person",
                "owner": "Private Person",
                "operator:wikidata": "Q123456",
                "building": "Private Person",
                "contact:email": "private@example.invalid",
                "description": "Private Person private@example.invalid",
                "phone": "+44 0000 000000",
                "input:electricity": "Private Person",
                "user": "Private Person",
                "ref": "private-reference",
                "ref:GB:uprn": "private-property-reference",
                "wikidata": "Q654321",
            }
        )
        elements, relationships = MODULE.privacy_normalise(envelope, ROOT)
        element_index = {
            name: position
            for position, (name, _type_name, _required) in enumerate(
                MODULE.BASE.ELEMENT_SCHEMA
            )
        }
        relationship_index = {
            name: position
            for position, (name, _type_name, _required) in enumerate(
                MODULE.BASE.RELATIONSHIP_SCHEMA
            )
        }
        self.assertEqual(len(relationships), len(elements) * 2)
        for row in elements:
            for field in MODULE.PRIVATE_ELEMENT_FIELDS:
                self.assertIsNone(row[element_index[field]])
            retained_tags = json.loads(row[element_index["tags_json"]])
            self.assertTrue(set(retained_tags).issubset(MODULE.SAFE_TAG_KEYS))
            self.assertNotIn("Private Person", json.dumps(row, default=str))
            self.assertNotIn("private@example.invalid", json.dumps(row, default=str))
        for row in relationships:
            self.assertIsNone(row[relationship_index["company_name_raw"]])
            self.assertEqual(
                row[relationship_index["evidence_status"]],
                "SOURCE_PARTY_WITHHELD_PRIVACY",
            )
            self.assertEqual(
                row[relationship_index["abstention_reason"]],
                "VERIFIED_COMPANY_NUMBER_REQUIRED",
            )
            self.assertNotIn("Private Person", json.dumps(row))

    def test_hostile_build_duckdb_and_geojson_readback_are_privacy_safe(self) -> None:
        envelope = MODULE.BASE.load_json(ROOT / MODULE.BASE.FIXTURE_REL)
        sentinel = "PRIVATE-SENTINEL private@example.invalid"
        for element in envelope["payload"]["elements"]:
            element["user"] = sentinel
            element["uid"] = 999999
            element["changeset"] = 888888
            element["tags"].update(
                {
                    "name": sentinel,
                    "operator": sentinel,
                    "owner": sentinel,
                    "ref": sentinel,
                    "wikidata": sentinel,
                    "operator:wikidata": sentinel,
                    "ref:GB:uprn": sentinel,
                    "contact:email": sentinel,
                    "phone": sentinel,
                    "description": sentinel,
                    "note": sentinel,
                    "arbitrary": sentinel,
                    "input:electricity": sentinel,
                }
            )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            input_path = temporary_path / "hostile.json"
            candidate = temporary_path / "candidate"
            input_path.write_text(MODULE.BASE.pretty_json(envelope), encoding="utf-8")
            source_commit = "a" * 40
            build_command = [
                sys.executable,
                str(MODULE_PATH),
                "build",
                "--root",
                str(ROOT),
                "--input",
                str(input_path),
                "--output-root",
                str(candidate),
                "--source-commit",
                source_commit,
            ]
            verify_command = [
                sys.executable,
                str(MODULE_PATH),
                "verify",
                "--root",
                str(candidate),
                "--source-root",
                str(ROOT),
                "--input",
                str(input_path),
                "--expected-source-commit",
                source_commit,
            ]
            subprocess.run(build_command, check=True, capture_output=True, text=True)
            verified = subprocess.run(
                verify_command, check=True, capture_output=True, text=True
            )
            self.assertEqual(json.loads(verified.stdout)["privacy"], "PASS")

            duckdb = MODULE.BASE.load_duckdb()
            connection = duckdb.connect(":memory:")
            try:
                for relative_path in (
                    MODULE.BASE.ELEMENTS_REL,
                    MODULE.BASE.RELATIONSHIPS_REL,
                ):
                    rows = connection.execute(
                        "SELECT * FROM read_parquet(?, hive_partitioning=false)",
                        [str(candidate / relative_path)],
                    ).fetchall()
                    self.assertNotIn(sentinel, json.dumps(rows, default=str))
            finally:
                connection.close()
            for relative_path in (MODULE.BASE.GEOJSON_REL, MODULE.BASE.AUDIT_REL):
                self.assertNotIn(
                    sentinel,
                    (candidate / relative_path).read_text(encoding="utf-8"),
                )

    def test_malformed_empty_and_missing_provenance_never_land(self) -> None:
        invalid_payloads = [
            None,
            {"elements": [], "osm3s": self.valid_payload["osm3s"]},
            {"elements": self.valid_payload["elements"]},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "overpass-fetch.json"
                responses = [FakeResponse(200, payload) for _ in MODULE.BACKOFFS]
                with mock.patch.object(
                    MODULE.requests, "post", side_effect=responses
                ), mock.patch.object(MODULE.time, "sleep"):
                    with self.assertRaises(RuntimeError):
                        MODULE.fetch(ROOT, output)
                self.assertFalse(output.exists())
                self.assertTrue(MODULE.failure_evidence_path(output).is_file())


if __name__ == "__main__":
    unittest.main()
