#!/usr/bin/env python3
"""Indexed-query successor for the quarantined 202608281626 Overpass fetch."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


REPAIR_GENERATION = "202608281702"
PARENT_PATH = Path(__file__).with_name("202608281626-osm-overpass-retry.py")
QUERY_REL = Path("queries/202608281702-gb-data-centres-indexed.overpassql")
CONTRACT_REL = Path("contracts/202608281702-osm-overpass-indexed.json")
QUERY_SHA256 = "57976c38c2cb71f2c88343b9d0d486b3316d73f7123d85c4f99d09f7699db374"
FAILED_RUN_ID = 33186567222
FAILED_JOB_ID = 98901064333
FAILURE_ARTIFACT_ID = 9692172935
FAILURE_ARTIFACT_DIGEST = (
    "sha256:3fc0117f7860e9f985144c84fd83e5b79fc648654b5b2e65fb09ad9ace662cd7"
)


def load_parent():
    spec = importlib.util.spec_from_file_location(
        "osm_overpass_retry_202608281626", PARENT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load pinned parent repair: {PARENT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARENT = load_parent()
BASE = PARENT.BASE
ORIGINAL_QUERY_REL = BASE.QUERY_REL
PARENT_DOCTOR = PARENT.doctor
PARENT_BUILD = PARENT.build
PARENT_VERIFY = PARENT.verify
PARENT_REPAIR_GENERATION = PARENT.REPAIR_GENERATION


def activate_query() -> None:
    BASE.QUERY_REL = QUERY_REL


def receipt() -> dict[str, Any]:
    return {
        "repair_generation": REPAIR_GENERATION,
        "failed_run_id": FAILED_RUN_ID,
        "failed_job_id": FAILED_JOB_ID,
        "failure_artifact_id": FAILURE_ARTIFACT_ID,
        "failure_artifact_digest": FAILURE_ARTIFACT_DIGEST,
        "query_path": QUERY_REL.as_posix(),
        "query_sha256": QUERY_SHA256,
        "request_partitioning": "SINGLE_POST",
        "parallel_requests": 0,
        "bounded_attempts": len(PARENT.BACKOFFS),
        "selector_method": "EXACT_INDEXED_KEY_VALUE",
        "geometry_mode": "CENTER_NOT_FULL_GEOMETRY",
        "candidate_only": True,
    }


def doctor(root: Path) -> dict[str, Any]:
    active_repair_generation = PARENT.REPAIR_GENERATION
    BASE.QUERY_REL = ORIGINAL_QUERY_REL
    PARENT.REPAIR_GENERATION = PARENT_REPAIR_GENERATION
    try:
        result = PARENT_DOCTOR(root)
    finally:
        activate_query()
        PARENT.REPAIR_GENERATION = active_repair_generation
    contract = BASE.load_json(root / CONTRACT_REL)
    if contract != {
        "schema": "data-centres-osm-indexed-query-repair-v1",
        **receipt(),
    }:
        raise RuntimeError("Indexed-query repair contract drifted")
    if BASE.sha256_file(root / QUERY_REL) != QUERY_SHA256:
        raise RuntimeError("Indexed Overpass query hash drifted")
    query = (root / QUERY_REL).read_text(encoding="utf-8")
    if (
        '["telecom"~' in query
        or '["building"~' in query
        or '["industrial"~' in query
        or '[~"' in query
        or "out meta geom" in query
        or query.count("nwr(area.gb)") != 42
        or "out meta center qt;" not in query
    ):
        raise RuntimeError("Indexed Overpass query law drifted")
    return {
        **result,
        "query_repair_generation": REPAIR_GENERATION,
        "query_path": QUERY_REL.as_posix(),
    }


def build(
    root: Path, input_path: Path, output_root: Path, source_commit: str
) -> dict[str, Any]:
    audit = PARENT_BUILD(root, input_path, output_root, source_commit)
    audit["query_repair"] = receipt()
    (output_root / BASE.AUDIT_REL).write_text(
        BASE.pretty_json(audit), encoding="utf-8"
    )
    return audit


def verify(
    root: Path, source_root: Path, input_path: Path, expected_source_commit: str
) -> dict[str, Any]:
    result = PARENT_VERIFY(root, source_root, input_path, expected_source_commit)
    audit = BASE.load_json(root / BASE.AUDIT_REL)
    if audit.get("query_repair") != receipt():
        raise RuntimeError("Indexed-query audit receipt drifted")
    return {
        **result,
        "query_repair_generation": REPAIR_GENERATION,
        "indexed_query": "PASS",
    }


def main() -> int:
    activate_query()
    PARENT.REPAIR_GENERATION = REPAIR_GENERATION
    PARENT.doctor = doctor
    PARENT.build = build
    PARENT.verify = verify
    return PARENT.main()


if __name__ == "__main__":
    raise SystemExit(main())
