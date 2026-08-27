#!/usr/bin/env python3
"""Build and land the quarantined 202608271727 DATA_CENTRES intelligence closure."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

GENERATION = "202608271727"
SECTION = "DATA_CENTRES"
FIXED_GENERATED_AT = "2026-08-27T16:27:00Z"
USAGE_CONTEXT = "NON_COMMERCIAL_OPEN_SOURCE"
DEPLOYMENT_STATE = "not-authorised"
DUCKDB_VERSION = "1.3.2"
SOURCE_MANIFEST = Path("manifests/202608271727-data-centres-intelligence-source.json")
FIXTURE = Path("data/source-fixtures/202608271727-repository-context.json")
CONTRACT = Path("contracts/202608271727-data-centres-intelligence.json")
PARQUET_REL = Path(
    "data/intelligence/generation=202608271727/section=DATA_CENTRES/part-000.parquet"
)
EXPORT_REL = Path("exports/202608271727-pipelinenews-data-centres.json")
AUDIT_REL = Path("reports/202608271727-data-centres-intelligence-audit.json")
OUTPUT_PATHS = (PARQUET_REL, EXPORT_REL, AUDIT_REL)
SOURCE_BOUNDARY_PATHS = (
    ".github/workflows/202608271727-data-centres-intelligence-candidate.yml",
    "build/python/202608271727-build-data-centres-intelligence.py",
    "build/python/202608271727-verify-data-centres-intelligence.py",
    "contracts/202608271727-data-centres-intelligence.json",
    "data/source-fixtures/202608271727-repository-context.json",
    "manifests/202608271727-data-centres-intelligence-source.json",
    "tests/test_202608271727_data_centres_intelligence.py",
)
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
HTTPS_URL = re.compile(r"^https://[^\s]+$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pretty_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def load_duckdb():
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised by Actions setup
        raise RuntimeError(f"duckdb=={DUCKDB_VERSION} is required") from exc
    if duckdb.__version__ != DUCKDB_VERSION:
        raise RuntimeError(
            f"DuckDB version drift: expected {DUCKDB_VERSION}, received {duckdb.__version__}"
        )
    return duckdb


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected an object in {path}")
    return value


def require_exact_keys(value: dict[str, Any], required: set[str], label: str) -> None:
    actual = set(value)
    if actual != required:
        raise RuntimeError(
            f"{label} keys drifted: missing={sorted(required - actual)!r} "
            f"unexpected={sorted(actual - required)!r}"
        )


def physical_schema(
    contract: dict[str, Any],
) -> list[tuple[str, str, bool, str, str, str | None]]:
    rows = contract.get("physical_schema")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Contract physical_schema must be a non-empty list")
    result: list[tuple[str, str, bool, str, str, str | None]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Every physical_schema entry must be an object")
        require_exact_keys(
            row,
            {
                "name",
                "duckdb_type",
                "logical_required",
                "parquet_primitive_type",
                "parquet_repetition",
                "parquet_converted_type",
            },
            "physical_schema entry",
        )
        name = str(row["name"])
        type_name = str(row["duckdb_type"]).upper()
        logical_required = bool(row["logical_required"])
        primitive_type = str(row["parquet_primitive_type"]).upper()
        repetition = str(row["parquet_repetition"]).upper()
        converted = row["parquet_converted_type"]
        converted_type = None if converted is None else str(converted).upper()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise RuntimeError(f"Unsafe column name {name!r}")
        if type_name not in {"VARCHAR", "DOUBLE", "DATE", "BOOLEAN", "INTEGER"}:
            raise RuntimeError(f"Unapproved physical type {type_name!r}")
        if repetition != "OPTIONAL":
            raise RuntimeError("DuckDB 1.3.2 physical scalar repetition must be declared OPTIONAL")
        result.append(
            (name, type_name, logical_required, primitive_type, repetition, converted_type)
        )
    if len({row[0] for row in result}) != len(result):
        raise RuntimeError("Physical schema contains duplicate column names")
    return result


def validate_source_boundary(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_path = root / SOURCE_MANIFEST
    fixture_path = root / FIXTURE
    contract_path = root / CONTRACT
    manifest = load_json(manifest_path)
    fixture = load_json(fixture_path)
    contract = load_json(contract_path)
    if (
        manifest.get("schema") != "data-centres-intelligence-source-manifest-v1"
        or manifest.get("generation") != GENERATION
        or manifest.get("usage_context") != USAGE_CONTEXT
        or manifest.get("deployment_state") != DEPLOYMENT_STATE
        or manifest.get("promotion_eligible") is not False
    ):
        raise RuntimeError("Source manifest governance drifted")
    if (
        contract.get("schema") != "data-centres-intelligence-contract-v1"
        or contract.get("generation") != GENERATION
        or contract.get("section") != SECTION
        or contract.get("usage_context") != USAGE_CONTEXT
        or contract.get("deployment_state") != DEPLOYMENT_STATE
        or contract.get("promotion_eligible") is not False
        or contract.get("declared_key") != ["record_id"]
        or contract.get("outputs", {}).get("parquet") != PARQUET_REL.as_posix()
        or contract.get("outputs", {}).get("browser_export") != EXPORT_REL.as_posix()
        or contract.get("outputs", {}).get("audit_report") != AUDIT_REL.as_posix()
    ):
        raise RuntimeError("Data law contract drifted")
    physical_schema(contract)
    if (
        fixture.get("schema") != "data-centres-repository-context-fixture-v1"
        or fixture.get("generation") != GENERATION
        or fixture.get("fixture_class") != "REPOSITORY_CONTEXT_TRANSCRIPTION"
        or fixture.get("usage_context") != USAGE_CONTEXT
        or fixture.get("repository_code_licence") != "MIT"
        or not COMMIT_SHA.fullmatch(str(fixture.get("parent_commit", "")))
        or not COMMIT_SHA.fullmatch(str(fixture.get("parent_tree", "")))
    ):
        raise RuntimeError("Repository-context fixture governance drifted")
    inputs = manifest.get("inputs", {})
    if (
        inputs.get("fixture", {}).get("path") != FIXTURE.as_posix()
        or inputs.get("fixture", {}).get("sha256") != sha256_file(fixture_path)
        or inputs.get("contract", {}).get("path") != CONTRACT.as_posix()
        or inputs.get("contract", {}).get("sha256") != sha256_file(contract_path)
    ):
        raise RuntimeError("Pinned fixture or contract receipt failed")
    boundary = manifest.get("source_boundary")
    if (
        not isinstance(boundary, dict)
        or boundary.get("file_count") != 7
        or boundary.get("paths") != list(SOURCE_BOUNDARY_PATHS)
        or boundary.get("parent_commit") != fixture.get("parent_commit")
    ):
        raise RuntimeError("Source manifest must declare the exact seven-file boundary")
    self_exclusion = manifest.get("manifest_self_exclusion")
    if (
        not isinstance(self_exclusion, dict)
        or self_exclusion.get("path") != SOURCE_MANIFEST.as_posix()
        or self_exclusion.get("authenticated_by") != "EXACT_GIT_COMMIT_AND_TREE"
        or not str(self_exclusion.get("reason", "")).strip()
    ):
        raise RuntimeError("Manifest self-exclusion rule is absent or dishonest")
    hashed_source_files = manifest.get("hashed_source_files")
    if not isinstance(hashed_source_files, list) or len(hashed_source_files) != 6:
        raise RuntimeError("Source manifest must hash the six non-self source files")
    hashed_paths = {str(receipt.get("path", "")) for receipt in hashed_source_files if isinstance(receipt, dict)}
    if hashed_paths != set(SOURCE_BOUNDARY_PATHS) - {SOURCE_MANIFEST.as_posix()}:
        raise RuntimeError("Hashed source files differ from the boundary minus the manifest itself")
    for receipt in hashed_source_files:
        if not isinstance(receipt, dict) or set(receipt) != {"path", "sha256"}:
            raise RuntimeError("Malformed source-file receipt")
        path = root / str(receipt["path"])
        if path.is_symlink() or not path.is_file() or sha256_file(path) != receipt["sha256"]:
            raise RuntimeError(f"Source-file receipt failed for {receipt.get('path')!r}")
    for receipt in fixture.get("repository_evidence", []):
        path = root / str(receipt.get("path", "__missing__"))
        if not path.is_file() or sha256_file(path) != receipt.get("sha256"):
            raise RuntimeError(f"Pinned repository evidence drifted: {receipt!r}")
    source = fixture.get("source")
    if not isinstance(source, dict):
        raise RuntimeError("Fixture source must be an object")
    if (
        not HTTPS_URL.fullmatch(str(source.get("url", "")))
        or source.get("source_licence") != "NOT_DECLARED_IN_REPOSITORY"
        or source.get("source_rights_status")
        != "REPOSITORY_TRANSCRIBED_CONTEXT_WITH_ATTRIBUTION_AND_LINK_ONLY"
    ):
        raise RuntimeError("Upstream source rights or URL contract drifted")
    if source.get("source_licence") == fixture.get("repository_code_licence"):
        raise RuntimeError("Repository code licence must not be inferred for upstream content")
    return manifest, fixture, contract


def evidence_digest(fixture: dict[str, Any], record: dict[str, Any]) -> str:
    payload = {
        "parent_commit": fixture["parent_commit"],
        "repository_evidence": fixture["repository_evidence"],
        "source": fixture["source"],
        "record": record,
    }
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def record_id(source_url: str, source_record_key: str) -> str:
    identity = f"{source_url}\0{source_record_key}".encode("utf-8")
    return "DCGB-INTEL-" + sha256_bytes(identity)[:16].upper()


def canonical_rows(fixture: dict[str, Any]) -> list[tuple[Any, ...]]:
    source = fixture["source"]
    records = fixture.get("records")
    if not isinstance(records, list) or not records:
        raise RuntimeError("Fixture records must be a non-empty list")
    required = {
        "source_record_key",
        "record_kind",
        "title",
        "summary",
        "geography",
        "metric_name",
        "value_min",
        "value_max",
        "unit",
        "eligible_for_project_signal",
        "display_rank",
    }
    rows: list[tuple[Any, ...]] = []
    keys: set[str] = set()
    ranks: set[int] = set()
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise RuntimeError(f"Fixture record {index} must be an object")
        require_exact_keys(item, required, f"fixture record {index}")
        source_record_key = str(item["source_record_key"])
        rid = record_id(str(source["url"]), source_record_key)
        rank = int(item["display_rank"])
        value_min = float(item["value_min"])
        value_max = float(item["value_max"])
        if not re.fullmatch(r"[a-z][a-z0-9_]*", source_record_key):
            raise RuntimeError(f"Invalid source_record_key {source_record_key!r}")
        if rid in keys or rank in ranks:
            raise RuntimeError("Fixture record IDs and display ranks must be unique")
        if rank < 1 or value_min > value_max:
            raise RuntimeError("Invalid display rank or metric range")
        if item["record_kind"] != "CONTEXT_METRIC" or item["eligible_for_project_signal"] is not False:
            raise RuntimeError("Context metrics must never be eligible for a project signal")
        if len(str(item["summary"])) > 300:
            raise RuntimeError("Retained summaries are capped at 300 characters")
        keys.add(rid)
        ranks.add(rank)
        rows.append(
            (
                rid,
                GENERATION,
                SECTION,
                str(item["record_kind"]),
                source_record_key,
                str(item["title"]),
                str(item["summary"]),
                str(item["geography"]),
                str(item["metric_name"]),
                value_min,
                value_max,
                str(item["unit"]),
                str(source["source_id"]),
                str(source["url"]),
                str(source["source_date"]),
                str(fixture["parent_commit"]),
                str(source["source_licence"]),
                str(source["source_rights_status"]),
                str(source["source_attribution"]),
                USAGE_CONTEXT,
                False,
                rank,
                evidence_digest(fixture, item),
            )
        )
    return sorted(rows, key=lambda row: (int(row[21]), str(row[0])))


def rows_digest(rows: Iterable[tuple[Any, ...]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        serialisable = [value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else value for value in row]
        digest.update(canonical_json(serialisable).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def inspect_parquet(
    connection: Any,
    parquet_path: Path,
    schema: list[tuple[str, str, bool, str, str, str | None]],
) -> dict[str, Any]:
    escaped = sql_path(parquet_path)
    relation = f"read_parquet('{escaped}', hive_partitioning=false)"
    described = [
        (str(row[0]), str(row[1]).upper(), str(row[2]).upper())
        for row in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    ]
    expected = [
        (name, type_name, "YES" if repetition == "OPTIONAL" else "NO")
        for name, type_name, _required, _primitive, repetition, _converted in schema
    ]
    if described != expected:
        raise RuntimeError(f"Parquet schema drifted: expected={expected!r} actual={described!r}")
    physical_rows = connection.execute(
        f"SELECT name, type, repetition_type, converted_type FROM parquet_schema('{escaped}')"
    ).fetchall()
    physical = {
        str(name): (
            None if primitive_type is None else str(primitive_type).upper(),
            None if repetition is None else str(repetition).upper(),
            None if converted is None else str(converted).upper(),
        )
        for name, primitive_type, repetition, converted in physical_rows
        if str(name) != "duckdb_schema"
    }
    expected_physical = {
        name: (primitive_type, repetition, converted_type)
        for name, _duckdb_type, _required, primitive_type, repetition, converted_type in schema
    }
    if physical != expected_physical:
        raise RuntimeError(
            f"Parquet physical schema drifted: expected={expected_physical!r} actual={physical!r}"
        )
    codecs = sorted(
        {str(row[0]).upper() for row in connection.execute(
            f"SELECT DISTINCT compression FROM parquet_metadata('{escaped}')"
        ).fetchall()}
    )
    if codecs != ["ZSTD"]:
        raise RuntimeError(f"Parquet compression must be exactly ZSTD, received {codecs!r}")
    stats = connection.execute(
        f"""
        SELECT
          count(*)::BIGINT AS rows,
          count(DISTINCT record_id)::BIGINT AS distinct_keys,
          count(*) FILTER (WHERE record_id IS NULL OR record_id = '')::BIGINT AS null_keys,
          count(*) FILTER (WHERE eligible_for_project_signal)::BIGINT AS signal_eligible
        FROM {relation}
        """
    ).fetchone()
    duplicate_groups = int(
        connection.execute(
            f"SELECT count(*) FROM (SELECT record_id FROM {relation} GROUP BY record_id HAVING count(*) > 1)"
        ).fetchone()[0]
    )
    null_counts: dict[str, int] = {}
    for name, _type_name, logical_required, _primitive, _repetition, _converted in schema:
        if not logical_required:
            continue
        count = int(connection.execute(f'SELECT count(*) FROM {relation} WHERE "{name}" IS NULL').fetchone()[0])
        null_counts[name] = count
    rows = int(stats[0])
    distinct_keys = int(stats[1])
    null_keys = int(stats[2])
    signal_eligible = int(stats[3])
    if (
        rows < 1
        or rows != distinct_keys
        or null_keys != 0
        or duplicate_groups != 0
        or signal_eligible != 0
        or any(null_counts.values())
    ):
        raise RuntimeError("Landed Parquet key, nullability or context-signal law failed")
    selected = connection.execute(
        f"SELECT * FROM {relation} ORDER BY display_rank ASC, record_id ASC"
    ).fetchall()
    return {
        "schema": [
            {
                "name": name,
                "duckdb_type": type_name,
                "logical_required": logical_required,
                "parquet_primitive_type": primitive_type,
                "parquet_repetition": repetition,
                "parquet_converted_type": converted_type,
                "duckdb_describe_nullability": "YES" if repetition == "OPTIONAL" else "NO",
            }
            for name, type_name, logical_required, primitive_type, repetition, converted_type in schema
        ],
        "compression_codecs": codecs,
        "rows": rows,
        "distinct_keys": distinct_keys,
        "null_keys": null_keys,
        "duplicate_key_groups": duplicate_groups,
        "context_records_eligible_for_project_signal": signal_eligible,
        "required_column_null_counts": null_counts,
        "record_universe_sha256": rows_digest(selected),
        "ordered_rows": selected,
    }


def serialise_value(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def confined_output_path(root: Path, relative: Path) -> Path:
    """Resolve one generation-owned path without following a writable symlink."""
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise RuntimeError(f"Output path must be a clean relative path: {relative}")
    root.mkdir(parents=True, exist_ok=True)
    resolved_root = root.resolve(strict=True)
    cursor = resolved_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RuntimeError(f"Output path crosses a symlink: {cursor}")
    resolved_target = cursor.resolve(strict=False)
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise RuntimeError(
            f"Output path escapes resolved root: root={resolved_root} target={resolved_target}"
        )
    return cursor


def write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build(root: Path, output_root: Path, source_commit: str) -> dict[str, Any]:
    if not COMMIT_SHA.fullmatch(source_commit):
        raise RuntimeError("source_commit must be an exact lowercase 40-character Git SHA")
    _manifest, fixture, contract = validate_source_boundary(root)
    schema = physical_schema(contract)
    rows = canonical_rows(fixture)
    duckdb = load_duckdb()
    output_root.mkdir(parents=True, exist_ok=True)
    output_root = output_root.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix=f"dcgb-{GENERATION}-", dir=output_root) as temporary_name:
        temporary_root = Path(temporary_name)
        staged_parquet = temporary_root / "part-000.parquet"
        connection = duckdb.connect(":memory:")
        try:
            connection.execute("SET threads = 1")
            fields = ",".join(
                f'"{name}" {type_name}' + (" NOT NULL" if logical_required else "")
                for name, type_name, logical_required, _primitive, _repetition, _converted in schema
            )
            connection.execute(f"CREATE TABLE staged ({fields}, PRIMARY KEY(record_id))")
            placeholders = ",".join("?" for _ in schema)
            connection.executemany(f"INSERT INTO staged VALUES ({placeholders})", rows)
            connection.execute(
                f"COPY (SELECT * FROM staged ORDER BY display_rank ASC, record_id ASC) "
                f"TO '{sql_path(staged_parquet)}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 10000)"
            )
            staged_readback = inspect_parquet(connection, staged_parquet, schema)
        finally:
            connection.close()
        expected_universe = rows_digest(rows)
        if staged_readback["record_universe_sha256"] != expected_universe:
            raise RuntimeError("Staged Parquet differs from canonical typed rows")

        landed_parquet = confined_output_path(output_root, PARQUET_REL)
        partition_dir = confined_output_path(output_root, PARQUET_REL.parent)
        if partition_dir.exists():
            shutil.rmtree(partition_dir)
        partition_dir.mkdir(parents=True, exist_ok=False)
        os.replace(staged_parquet, landed_parquet)

    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        landed = inspect_parquet(connection, landed_parquet, schema)
        escaped = sql_path(landed_parquet)
        relation = f"read_parquet('{escaped}', hive_partitioning=false)"
        cursor = connection.execute(
            f"SELECT * FROM {relation} ORDER BY display_rank ASC, record_id ASC"
        )
        names = [str(column[0]) for column in cursor.description]
        export_records = [
            {name: serialise_value(value) for name, value in zip(names, row)}
            for row in cursor.fetchall()
        ]
    finally:
        connection.close()
    if landed["record_universe_sha256"] != expected_universe:
        raise RuntimeError("Landed-file DuckDB readback differs from canonical typed rows")

    source = fixture["source"]
    export = {
        "schema": "pipelinenews-data-centres-intelligence-v1",
        "generation": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": DEPLOYMENT_STATE,
        "promotion_eligible": False,
        "usage_context": USAGE_CONTEXT,
        "section": SECTION,
        "grain": contract["grain"],
        "declared_key": ["record_id"],
        "display_order": contract["display_order"],
        "record_count": len(export_records),
        "source_rights": {
            "repository_code_licence": fixture["repository_code_licence"],
            "upstream_source_licence": source["source_licence"],
            "upstream_source_rights_status": source["source_rights_status"],
            "retained_content": source["retained_content"],
        },
        "records": export_records,
    }
    export_path = confined_output_path(output_root, EXPORT_REL)
    write_atomic(export_path, pretty_json(export).encode("utf-8"))
    parquet_receipt = {
        "path": PARQUET_REL.as_posix(),
        "bytes": landed_parquet.stat().st_size,
        "sha256": sha256_file(landed_parquet),
    }
    export_receipt = {
        "path": EXPORT_REL.as_posix(),
        "bytes": export_path.stat().st_size,
        "sha256": sha256_file(export_path),
    }
    audit = {
        "schema": "data-centres-intelligence-audit-v1",
        "generation": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "status": "PASS",
        "deployment_state": DEPLOYMENT_STATE,
        "promotion_eligible": False,
        "usage_context": USAGE_CONTEXT,
        "source_commit": source_commit,
        "source_input": {
            "fixture": {
                "path": FIXTURE.as_posix(),
                "sha256": sha256_file(root / FIXTURE),
                "fixture_class": fixture["fixture_class"],
            },
            "repository_evidence": fixture["repository_evidence"],
            "upstream_source_url": source["url"],
            "upstream_source_licence": source["source_licence"],
            "upstream_source_rights_status": source["source_rights_status"],
            "repository_code_licence": fixture["repository_code_licence"],
        },
        "data_law": {
            "owner": contract["owner"],
            "grain": contract["grain"],
            "declared_key": ["record_id"],
            "partition_law": contract["partition_law"],
            "correction_policy": contract["correction_policy"],
            "physical_schema": landed["schema"],
        },
        "landed_file_readback": {
            key: value for key, value in landed.items() if key != "ordered_rows"
        },
        "browser_export": {
            "source": "DuckDB query over the physically landed Parquet file",
            "order_by": contract["display_order"],
            "record_count": len(export_records),
        },
        "deterministic_rebuild_contract": {
            "required": "Two isolated builds from the same source commit must be byte-identical for every output.",
            "enforced_by": "202608271727-data-centres-intelligence-candidate.yml",
        },
        "outputs": {
            "parquet": parquet_receipt,
            "browser_export": export_receipt,
            "audit_report": {"path": AUDIT_REL.as_posix(), "self_hash_excluded": True},
        },
        "engine": {"name": "duckdb", "version": DUCKDB_VERSION, "threads": 1},
    }
    audit_path = confined_output_path(output_root, AUDIT_REL)
    write_atomic(audit_path, pretty_json(audit).encode("utf-8"))
    return audit


def receipt_matches(root: Path, receipt: dict[str, Any], expected: Path) -> bool:
    if receipt.get("path") != expected.as_posix():
        return False
    path = confined_output_path(root, expected)
    return (
        path.is_file()
        and path.stat().st_size == receipt.get("bytes")
        and sha256_file(path) == receipt.get("sha256")
    )


def land_candidate(candidate_root: Path, destination_root: Path, source_commit: str) -> None:
    candidate_root.mkdir(parents=True, exist_ok=True)
    destination_root.mkdir(parents=True, exist_ok=True)
    candidate_root = candidate_root.resolve(strict=True)
    destination_root = destination_root.resolve(strict=True)
    candidate_paths = {path: confined_output_path(candidate_root, path) for path in OUTPUT_PATHS}
    audit = load_json(candidate_paths[AUDIT_REL])
    if (
        audit.get("schema") != "data-centres-intelligence-audit-v1"
        or audit.get("generation") != GENERATION
        or audit.get("status") != "PASS"
        or audit.get("deployment_state") != DEPLOYMENT_STATE
        or audit.get("promotion_eligible") is not False
        or audit.get("source_commit") != source_commit
    ):
        raise RuntimeError("Candidate audit is not eligible to be landed in quarantine")
    if not receipt_matches(
        candidate_root, audit.get("outputs", {}).get("parquet", {}), PARQUET_REL
    ):
        raise RuntimeError("Candidate Parquet receipt failed before landing")
    if not receipt_matches(
        candidate_root, audit.get("outputs", {}).get("browser_export", {}), EXPORT_REL
    ):
        raise RuntimeError("Candidate export receipt failed before landing")
    for path in OUTPUT_PATHS:
        if not candidate_paths[path].is_file():
            raise RuntimeError(f"Candidate output missing: {path}")

    destination_paths = {
        path: confined_output_path(destination_root, path) for path in OUTPUT_PATHS
    }
    partition_dir = confined_output_path(destination_root, PARQUET_REL.parent)
    if partition_dir.exists():
        shutil.rmtree(partition_dir)
    partition_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(candidate_paths[PARQUET_REL], destination_paths[PARQUET_REL])
    for path in (EXPORT_REL, AUDIT_REL):
        write_atomic(destination_paths[path], candidate_paths[path].read_bytes())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--root", type=Path, default=Path("."))
    build_parser.add_argument("--output-root", type=Path, required=True)
    build_parser.add_argument("--source-commit", required=True)
    land_parser = subparsers.add_parser("land")
    land_parser.add_argument("--candidate-root", type=Path, required=True)
    land_parser.add_argument("--destination-root", type=Path, default=Path("."))
    land_parser.add_argument("--source-commit", required=True)
    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--root", type=Path, default=Path("."))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "build":
        audit = build(args.root.resolve(), args.output_root.resolve(), args.source_commit)
        print(pretty_json({"status": "PASS", "generation": GENERATION, "rows": audit["landed_file_readback"]["rows"]}), end="")
    elif args.command == "land":
        land_candidate(args.candidate_root.resolve(), args.destination_root.resolve(), args.source_commit)
        print(pretty_json({"status": "PASS", "generation": GENERATION, "landed": [path.as_posix() for path in OUTPUT_PATHS]}), end="")
    else:
        validate_source_boundary(args.root.resolve())
        print(pretty_json({"status": "PASS", "generation": GENERATION, "source_boundary": "verified"}), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
