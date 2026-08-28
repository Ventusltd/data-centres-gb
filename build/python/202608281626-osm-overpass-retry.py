#!/usr/bin/env python3
"""Bounded, fail-closed Overpass acquisition successor for generation 202608281053."""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import requests


REPAIR_GENERATION = "202608281626"
BASE_PATH = Path(__file__).with_name("202608281053-osm-data-centres.py")
REPAIR_CONTRACT_REL = Path("contracts/202608281626-osm-overpass-retry-privacy.json")
BACKOFFS = (0, 30, 60)
CONNECT_TIMEOUT_SECONDS = 20
READ_TIMEOUT_SECONDS = 150
MAX_REMARK_CHARACTERS = 4096
RETRYABLE_HTTP = {406, 408, 425, 429}


def load_base():
    spec = importlib.util.spec_from_file_location("osm_data_centres_202608281053", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load pinned base producer: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_base()
ORIGINAL_DOCTOR = BASE.doctor
ORIGINAL_NORMALISE = BASE.normalise
ORIGINAL_BUILD = BASE.build
ORIGINAL_VERIFY = BASE.verify

SAFE_TAG_KEYS = frozenset(
    list(BASE.FEATURE_KEYS)
    + [
        f"{lifecycle}:{feature}"
        for lifecycle in BASE.LIFECYCLES
        for feature in BASE.FEATURE_KEYS
    ]
)
PRIVATE_ELEMENT_FIELDS = (
    "name_raw",
    "operator_raw",
    "owner_raw",
    "ref_raw",
    "wikidata_raw",
    "operator_wikidata_raw",
    "uprn_raw",
)


def doctor(root: Path) -> dict[str, Any]:
    base_result = ORIGINAL_DOCTOR(root)
    contract = BASE.load_json(root / REPAIR_CONTRACT_REL)
    expected = {
        "schema": "data-centres-osm-acquisition-repair-v1",
        "repair_generation": REPAIR_GENERATION,
        "base_generation": BASE.GENERATION,
        "failed_run_id": 33161947627,
        "failed_job_id": 98818333965,
        "failed_step": "Fetch OpenStreetMap once through Overpass",
        "bounded_attempts": len(BACKOFFS),
        "backoff_seconds": list(BACKOFFS),
        "connect_timeout_seconds": CONNECT_TIMEOUT_SECONDS,
        "read_timeout_seconds": READ_TIMEOUT_SECONDS,
        "raw_response_landed": False,
        "private_names_landed": False,
        "unverified_company_names_landed": False,
        "candidate_only": True,
        "base_blob_pins": {
            "producer": "ef33bd6e8ce1563f51dcef5df4c56bf520aab02c",
            "query": "f159dd173b5a49024bcf574266d7ec4ae7012441",
            "contract": "430a242882a7e902e6e598a4b916b08185e73ffb",
            "source_manifest": "820141b97e461ae460d23ce8a9116fad909f5d57",
            "fixture": "6e21a52c04b28bf195ed1d0a02367f11b1cd7e92",
            "tests": "9a0941cfc33ab3f4a51feeeae85bacc7a1641978",
        },
        "privacy": privacy_receipt(),
    }
    if contract != expected:
        raise RuntimeError("Acquisition repair contract drifted")
    return {
        **base_result,
        "repair_generation": REPAIR_GENERATION,
        "repair_contract": REPAIR_CONTRACT_REL.as_posix(),
    }


def privacy_normalise(
    envelope: dict[str, Any], root: Path
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    element_rows, relationship_rows = ORIGINAL_NORMALISE(envelope, root)
    element_index = {
        name: position
        for position, (name, _type_name, _required) in enumerate(BASE.ELEMENT_SCHEMA)
    }
    relationship_index = {
        name: position
        for position, (name, _type_name, _required) in enumerate(BASE.RELATIONSHIP_SCHEMA)
    }

    safe_elements: list[tuple[Any, ...]] = []
    for row in element_rows:
        values = list(row)
        raw_tags = json.loads(str(values[element_index["tags_json"]]))
        safe_tags = {}
        for key in sorted(SAFE_TAG_KEYS):
            value = raw_tags.get(key)
            if isinstance(value, str) and BASE.DATA_CENTRE_VALUE.fullmatch(value):
                safe_tags[key] = value
        for field in PRIVATE_ELEMENT_FIELDS:
            values[element_index[field]] = None
        values[element_index["tags_json"]] = BASE.canonical_json(safe_tags)
        safe_elements.append(tuple(values))

    safe_relationships: list[tuple[Any, ...]] = []
    for row in relationship_rows:
        values = list(row)
        values[relationship_index["company_name_raw"]] = None
        values[relationship_index["evidence_status"]] = "SOURCE_PARTY_WITHHELD_PRIVACY"
        values[relationship_index["abstention_reason"]] = "VERIFIED_COMPANY_NUMBER_REQUIRED"
        safe_relationships.append(tuple(values))
    return safe_elements, safe_relationships


def privacy_receipt() -> dict[str, Any]:
    return {
        "nulled_element_columns": list(PRIVATE_ELEMENT_FIELDS),
        "tags_json_allowed_keys": sorted(SAFE_TAG_KEYS),
        "tags_json_value_grammar": "^(?:data_center|data_centre)$",
        "relationship_slots_per_element": 2,
        "relationship_null_columns": [
            "data_centre_id",
            "company_number",
            "company_name_raw",
            "match_score",
        ],
        "relationship_evidence_status": "SOURCE_PARTY_WITHHELD_PRIVACY",
        "relationship_abstention_reason": "VERIFIED_COMPANY_NUMBER_REQUIRED",
        "relationship_eligible_for_join": False,
        "raw_party_name_contact_identifiers_landed": False,
    }


def build(
    root: Path, input_path: Path, output_root: Path, source_commit: str
) -> dict[str, Any]:
    audit = ORIGINAL_BUILD(root, input_path, output_root, source_commit)
    audit["repair"] = {
        "repair_generation": REPAIR_GENERATION,
        "privacy": privacy_receipt(),
        "element_rows_checked": audit["element_rows"],
        "relationship_rows_checked": audit["relationship_rows"],
        "private_strings_landed": 0,
        "unverified_company_names_landed": 0,
    }
    audit_path = output_root / BASE.AUDIT_REL
    audit_path.write_text(BASE.pretty_json(audit), encoding="utf-8")
    return audit


def verify(
    root: Path, source_root: Path, input_path: Path, expected_source_commit: str
) -> dict[str, Any]:
    result = ORIGINAL_VERIFY(root, source_root, input_path, expected_source_commit)
    audit = BASE.load_json(root / BASE.AUDIT_REL)
    expected_repair = {
        "repair_generation": REPAIR_GENERATION,
        "privacy": privacy_receipt(),
        "element_rows_checked": result["element_rows"],
        "relationship_rows_checked": result["relationship_rows"],
        "private_strings_landed": 0,
        "unverified_company_names_landed": 0,
    }
    if audit.get("repair") != expected_repair:
        raise RuntimeError("Privacy repair receipt drifted")

    duckdb = BASE.load_duckdb()
    connection = duckdb.connect(":memory:")
    try:
        elements = (
            f"read_parquet('{BASE.sql_path(root / BASE.ELEMENTS_REL)}', "
            "hive_partitioning=false)"
        )
        relationships = (
            f"read_parquet('{BASE.sql_path(root / BASE.RELATIONSHIPS_REL)}', "
            "hive_partitioning=false)"
        )
        private_predicate = " OR ".join(
            f'"{field}" IS NOT NULL' for field in PRIVATE_ELEMENT_FIELDS
        )
        if int(
            connection.execute(
                f"SELECT count(*) FROM {elements} WHERE {private_predicate}"
            ).fetchone()[0]
        ):
            raise RuntimeError("Private or unverified element strings reached Parquet")
        for (tags_text,) in connection.execute(
            f'SELECT "tags_json" FROM {elements}'
        ).fetchall():
            tags = json.loads(str(tags_text))
            if set(tags) - SAFE_TAG_KEYS or any(
                not isinstance(value, str)
                or BASE.DATA_CENTRE_VALUE.fullmatch(value) is None
                for value in tags.values()
            ):
                raise RuntimeError("Untrusted OSM tag reached Parquet")
        relationship_gate = (
            '"data_centre_id" IS NOT NULL OR "company_number" IS NOT NULL OR '
            '"company_name_raw" IS NOT NULL OR "match_score" IS NOT NULL OR '
            '"eligible_for_join" OR '
            '"evidence_status" <> \'SOURCE_PARTY_WITHHELD_PRIVACY\' OR '
            '"abstention_reason" <> \'VERIFIED_COMPANY_NUMBER_REQUIRED\''
        )
        if int(
            connection.execute(
                f"SELECT count(*) FROM {relationships} WHERE {relationship_gate}"
            ).fetchone()[0]
        ):
            raise RuntimeError("Unverified company relationship reached Parquet")
        element_count = int(
            connection.execute(f"SELECT count(*) FROM {elements}").fetchone()[0]
        )
        relationship_count = int(
            connection.execute(f"SELECT count(*) FROM {relationships}").fetchone()[0]
        )
        if relationship_count != element_count * 2:
            raise RuntimeError("Privacy-safe relationship slots are incomplete")
    finally:
        connection.close()

    geojson = BASE.load_json(root / BASE.GEOJSON_REL)
    for feature in geojson.get("features", []):
        properties = feature.get("properties", {})
        if any(
            properties.get(field) is not None
            for field in ("name_raw", "operator_raw", "owner_raw")
        ):
            raise RuntimeError("Private or unverified string reached GeoJSON")
    return {**result, "repair_generation": REPAIR_GENERATION, "privacy": "PASS"}


def iso_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def failure_evidence_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}-failure.json")


def response_receipt(response: Any) -> dict[str, Any]:
    body = bytes(response.content)
    return {
        "http_status": int(response.status_code),
        "content_type": str(response.headers.get("Content-Type", ""))[:256],
        "response_bytes": len(body),
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "response_body_retained": False,
    }


def remark_receipt(remark: Any) -> dict[str, Any]:
    if isinstance(remark, str):
        text = remark
    else:
        text = BASE.canonical_json(remark)
    encoded = text.encode("utf-8")
    return {
        "remark": text[:MAX_REMARK_CHARACTERS],
        "remark_bytes": len(encoded),
        "remark_sha256": hashlib.sha256(encoded).hexdigest(),
        "remark_truncated": len(text) > MAX_REMARK_CHARACTERS,
    }


def write_failure_evidence(
    output: Path,
    root: Path,
    attempts: list[dict[str, Any]],
) -> Path:
    evidence_path = failure_evidence_path(output)
    evidence = {
        "schema": "overpass-data-centres-fetch-failure-v1",
        "status": "FAILED",
        "generation": BASE.GENERATION,
        "repair_generation": REPAIR_GENERATION,
        "endpoint": BASE.ENDPOINT,
        "query_sha256": BASE.query_sha(root),
        "attempt_limit": len(BACKOFFS),
        "attempts_performed": len(attempts),
        "attempts": attempts,
        "raw_overpass_response_landed": False,
        "contributor_identity_retained": False,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(BASE.pretty_json(evidence), encoding="utf-8")
    return evidence_path


def fetch(root: Path, output: Path) -> dict[str, Any]:
    doctor(root)
    query = (root / BASE.QUERY_REL).read_text(encoding="utf-8")
    headers = {
        "User-Agent": (
            "Ventusltd-data-centres-gb/1.0 "
            "(+https://github.com/Ventusltd/data-centres-gb)"
        ),
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    attempts: list[dict[str, Any]] = []
    evidence_path = failure_evidence_path(output)

    for attempt_number, delay in enumerate(BACKOFFS, start=1):
        if delay:
            time.sleep(delay)
        started = time.monotonic()
        attempt: dict[str, Any] = {
            "attempt": attempt_number,
            "backoff_seconds": delay,
            "observed_at": iso_now(),
        }
        try:
            response = requests.post(
                BASE.ENDPOINT,
                data={"data": query},
                headers=headers,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
        except requests.RequestException as exc:
            attempt.update(
                {
                    "classification": "NETWORK_ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1024],
                }
            )
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            attempts.append(attempt)
            continue

        attempt.update(response_receipt(response))
        status = int(response.status_code)
        if status in RETRYABLE_HTTP or 500 <= status < 600:
            attempt["classification"] = "RETRYABLE_HTTP"
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            attempts.append(attempt)
            continue
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            attempt.update(
                {
                    "classification": "NON_RETRYABLE_HTTP",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1024],
                }
            )
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            attempts.append(attempt)
            break

        try:
            payload = response.json()
        except ValueError:
            attempt["classification"] = "NON_JSON_RESPONSE"
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            attempts.append(attempt)
            continue
        if not isinstance(payload, dict):
            attempt["classification"] = "NON_OBJECT_RESPONSE"
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            attempts.append(attempt)
            continue
        if payload.get("remark"):
            attempt["classification"] = "OVERPASS_REMARK"
            attempt.update(remark_receipt(payload["remark"]))
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            attempts.append(attempt)
            continue

        fetched_at = iso_now()
        envelope = {
            "schema": "overpass-data-centres-fetch-v1",
            "endpoint": BASE.ENDPOINT,
            "query_sha256": BASE.query_sha(root),
            "fetched_at": fetched_at,
            "network_request_attempts": attempt_number,
            "network_successful_requests": 1,
            "payload": payload,
        }
        try:
            BASE.validate_envelope(envelope, root)
        except RuntimeError as exc:
            attempt.update(
                {
                    "classification": "INVALID_OR_PARTIAL_ENVELOPE",
                    "error": str(exc)[:1024],
                }
            )
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            attempts.append(attempt)
            continue

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(BASE.pretty_json(envelope), encoding="utf-8")
        if evidence_path.exists():
            evidence_path.unlink()
        return {
            "status": "PASS",
            "generation": BASE.GENERATION,
            "repair_generation": REPAIR_GENERATION,
            "fetched_at": fetched_at,
            "elements": len(payload["elements"]),
            "network_request_attempts": attempt_number,
            "query_sha256": envelope["query_sha256"],
            "output_sha256": BASE.sha256_file(output),
        }

    retained = write_failure_evidence(output, root, attempts)
    raise RuntimeError(
        f"Bounded Overpass fetch failed after {len(attempts)} attempts; "
        f"retained evidence: {retained}"
    )


def main() -> int:
    BASE.doctor = doctor
    BASE.fetch = fetch
    BASE.normalise = privacy_normalise
    BASE.build = build
    BASE.verify = verify
    return BASE.main()


if __name__ == "__main__":
    raise SystemExit(main())
