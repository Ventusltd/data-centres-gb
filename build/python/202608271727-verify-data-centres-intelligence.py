#!/usr/bin/env python3
"""Independent verifier for the 202608271727 DATA_CENTRES intelligence closure."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

GENERATION = "202608271727"
SECTION = "DATA_CENTRES"
USAGE_CONTEXT = "NON_COMMERCIAL_OPEN_SOURCE"
DUCKDB_VERSION = "1.3.2"
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
FIXTURE = Path("data/source-fixtures/202608271727-repository-context.json")
CONTRACT = Path("contracts/202608271727-data-centres-intelligence.json")
SOURCE_MANIFEST = Path("manifests/202608271727-data-centres-intelligence-source.json")
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


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pretty_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    return value


def load_duckdb():
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"duckdb=={DUCKDB_VERSION} is required") from exc
    if duckdb.__version__ != DUCKDB_VERSION:
        raise RuntimeError(
            f"DuckDB version drift: expected {DUCKDB_VERSION}, received {duckdb.__version__}"
        )
    return duckdb


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def serialise(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def rows_digest(rows: list[tuple[Any, ...]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(canonical_json([serialise(value) for value in row]).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def source_schema(
    contract: dict[str, Any],
) -> list[tuple[str, str, bool, str, str, str | None]]:
    schema: list[tuple[str, str, bool, str, str, str | None]] = []
    for row in contract.get("physical_schema", []):
        if not isinstance(row, dict) or set(row) != {
            "name",
            "duckdb_type",
            "logical_required",
            "parquet_primitive_type",
            "parquet_repetition",
            "parquet_converted_type",
        }:
            raise RuntimeError("Malformed physical schema entry")
        converted = row["parquet_converted_type"]
        schema.append(
            (
                str(row["name"]),
                str(row["duckdb_type"]).upper(),
                bool(row["logical_required"]),
                str(row["parquet_primitive_type"]).upper(),
                str(row["parquet_repetition"]).upper(),
                None if converted is None else str(converted).upper(),
            )
        )
    if not schema or schema[0][0] != "record_id" or len({row[0] for row in schema}) != len(schema):
        raise RuntimeError("Physical schema identity drifted")
    return schema


def expected_rows(fixture: dict[str, Any]) -> list[tuple[Any, ...]]:
    source = fixture["source"]
    result: list[tuple[Any, ...]] = []
    for item in fixture["records"]:
        identity = f"{source['url']}\0{item['source_record_key']}".encode("utf-8")
        record_id = "DCGB-INTEL-" + hashlib.sha256(identity).hexdigest()[:16].upper()
        evidence = {
            "parent_commit": fixture["parent_commit"],
            "repository_evidence": fixture["repository_evidence"],
            "source": source,
            "record": item,
        }
        evidence_sha = hashlib.sha256(canonical_json(evidence).encode("utf-8")).hexdigest()
        result.append(
            (
                record_id,
                GENERATION,
                SECTION,
                item["record_kind"],
                item["source_record_key"],
                item["title"],
                item["summary"],
                item["geography"],
                item["metric_name"],
                float(item["value_min"]),
                float(item["value_max"]),
                item["unit"],
                source["source_id"],
                source["url"],
                source["source_date"],
                fixture["parent_commit"],
                source["source_licence"],
                source["source_rights_status"],
                source["source_attribution"],
                USAGE_CONTEXT,
                False,
                int(item["display_rank"]),
                evidence_sha,
            )
        )
    return sorted(result, key=lambda row: (int(row[21]), str(row[0])))


def verify_receipt(root: Path, receipt: dict[str, Any], expected_path: Path) -> None:
    if receipt.get("path") != expected_path.as_posix():
        raise RuntimeError(f"Receipt path drifted for {expected_path}")
    path = root / expected_path
    if (
        not path.is_file()
        or path.stat().st_size != receipt.get("bytes")
        or sha256_file(path) != receipt.get("sha256")
    ):
        raise RuntimeError(f"Artifact receipt failed for {expected_path}")


def verify(root: Path, source_root: Path, expected_source_commit: str) -> dict[str, Any]:
    if not COMMIT_SHA.fullmatch(expected_source_commit):
        raise RuntimeError("Expected source commit must be an exact lowercase 40-character Git SHA")
    fixture = load_json(source_root / FIXTURE)
    contract = load_json(source_root / CONTRACT)
    manifest = load_json(source_root / SOURCE_MANIFEST)
    audit = load_json(root / AUDIT_REL)
    export = load_json(root / EXPORT_REL)
    if (
        manifest.get("generation") != GENERATION
        or manifest.get("usage_context") != USAGE_CONTEXT
        or manifest.get("deployment_state") != "not-authorised"
        or manifest.get("promotion_eligible") is not False
        or contract.get("generation") != GENERATION
        or contract.get("section") != SECTION
        or contract.get("usage_context") != USAGE_CONTEXT
        or contract.get("declared_key") != ["record_id"]
        or fixture.get("generation") != GENERATION
        or fixture.get("usage_context") != USAGE_CONTEXT
    ):
        raise RuntimeError("Source governance contract drifted")
    input_receipts = manifest.get("inputs", {})
    if (
        input_receipts.get("fixture", {}).get("path") != FIXTURE.as_posix()
        or input_receipts.get("fixture", {}).get("sha256") != sha256_file(source_root / FIXTURE)
        or input_receipts.get("contract", {}).get("path") != CONTRACT.as_posix()
        or input_receipts.get("contract", {}).get("sha256") != sha256_file(source_root / CONTRACT)
    ):
        raise RuntimeError("Input fixture or contract receipt drifted")
    boundary = manifest.get("source_boundary")
    if (
        not isinstance(boundary, dict)
        or boundary.get("file_count") != 7
        or boundary.get("paths") != list(SOURCE_BOUNDARY_PATHS)
        or boundary.get("parent_commit") != fixture.get("parent_commit")
    ):
        raise RuntimeError("Exact seven-file source boundary drifted")
    self_exclusion = manifest.get("manifest_self_exclusion")
    if (
        not isinstance(self_exclusion, dict)
        or self_exclusion.get("path") != SOURCE_MANIFEST.as_posix()
        or self_exclusion.get("authenticated_by") != "EXACT_GIT_COMMIT_AND_TREE"
        or not str(self_exclusion.get("reason", "")).strip()
    ):
        raise RuntimeError("Manifest self-exclusion rule drifted")
    hashed_source_files = manifest.get("hashed_source_files")
    if not isinstance(hashed_source_files, list) or len(hashed_source_files) != 6:
        raise RuntimeError("Expected six hashed non-self source files")
    hashed_paths = {str(receipt.get("path", "")) for receipt in hashed_source_files if isinstance(receipt, dict)}
    if hashed_paths != set(SOURCE_BOUNDARY_PATHS) - {SOURCE_MANIFEST.as_posix()}:
        raise RuntimeError("Hashed source files differ from source boundary minus manifest")
    for receipt in hashed_source_files:
        path = source_root / str(receipt.get("path", "__missing__"))
        if path.is_symlink() or not path.is_file() or sha256_file(path) != receipt.get("sha256"):
            raise RuntimeError(f"Source boundary receipt failed: {receipt!r}")
    for receipt in fixture.get("repository_evidence", []):
        path = source_root / str(receipt.get("path", "__missing__"))
        if not path.is_file() or sha256_file(path) != receipt.get("sha256"):
            raise RuntimeError(f"Repository evidence receipt failed: {receipt!r}")
    source = fixture["source"]
    if (
        fixture.get("repository_code_licence") != "MIT"
        or source.get("source_licence") != "NOT_DECLARED_IN_REPOSITORY"
        or source.get("source_rights_status")
        != "REPOSITORY_TRANSCRIBED_CONTEXT_WITH_ATTRIBUTION_AND_LINK_ONLY"
        or source.get("source_licence") == fixture.get("repository_code_licence")
    ):
        raise RuntimeError("Application context and upstream rights are not independently declared")
    if (
        audit.get("schema") != "data-centres-intelligence-audit-v1"
        or audit.get("generation") != GENERATION
        or audit.get("status") != "PASS"
        or audit.get("deployment_state") != "not-authorised"
        or audit.get("promotion_eligible") is not False
        or audit.get("usage_context") != USAGE_CONTEXT
        or audit.get("source_commit") != expected_source_commit
    ):
        raise RuntimeError("Audit governance or source commit drifted")
    verify_receipt(root, audit.get("outputs", {}).get("parquet", {}), PARQUET_REL)
    verify_receipt(root, audit.get("outputs", {}).get("browser_export", {}), EXPORT_REL)

    schema = source_schema(contract)
    duckdb = load_duckdb()
    parquet_path = root / PARQUET_REL
    escaped = sql_path(parquet_path)
    relation = f"read_parquet('{escaped}', hive_partitioning=false)"
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        actual_schema = [
            (str(row[0]), str(row[1]).upper(), str(row[2]).upper())
            for row in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
        ]
        expected_schema = [
            (name, type_name, "YES" if repetition == "OPTIONAL" else "NO")
            for name, type_name, _required, _primitive, repetition, _converted in schema
        ]
        if actual_schema != expected_schema:
            raise RuntimeError(f"Physical Parquet schema mismatch: {actual_schema!r}")
        parquet_schema_rows = connection.execute(
            f"SELECT name, type, repetition_type, converted_type FROM parquet_schema('{escaped}')"
        ).fetchall()
        actual_physical = {
            str(name): (
                None if primitive is None else str(primitive).upper(),
                None if repetition is None else str(repetition).upper(),
                None if converted is None else str(converted).upper(),
            )
            for name, primitive, repetition, converted in parquet_schema_rows
            if str(name) != "duckdb_schema"
        }
        expected_physical = {
            name: (primitive, repetition, converted)
            for name, _type_name, _required, primitive, repetition, converted in schema
        }
        if actual_physical != expected_physical:
            raise RuntimeError(
                f"Parquet primitive/repetition schema mismatch: {actual_physical!r}"
            )
        codecs = sorted(
            {str(row[0]).upper() for row in connection.execute(
                f"SELECT DISTINCT compression FROM parquet_metadata('{escaped}')"
            ).fetchall()}
        )
        if codecs != ["ZSTD"]:
            raise RuntimeError(f"Parquet compression mismatch: {codecs!r}")
        stats = connection.execute(
            f"""
            SELECT
              count(*)::BIGINT,
              count(DISTINCT record_id)::BIGINT,
              count(*) FILTER (WHERE record_id IS NULL OR record_id = '')::BIGINT,
              count(*) FILTER (WHERE eligible_for_project_signal)::BIGINT
            FROM {relation}
            """
        ).fetchone()
        duplicate_groups = int(
            connection.execute(
                f"SELECT count(*) FROM (SELECT record_id FROM {relation} GROUP BY record_id HAVING count(*) > 1)"
            ).fetchone()[0]
        )
        required_nulls = {
            name: int(connection.execute(f'SELECT count(*) FROM {relation} WHERE "{name}" IS NULL').fetchone()[0])
            for name, _type_name, logical_required, _primitive, _repetition, _converted in schema
            if logical_required
        }
        rows, distinct_keys, null_keys, signal_eligible = map(int, stats)
        if (
            rows < 1
            or rows != distinct_keys
            or null_keys != 0
            or duplicate_groups != 0
            or signal_eligible != 0
            or any(required_nulls.values())
        ):
            raise RuntimeError("Key, nullability, duplicate or project-signal gate failed")

        expected = expected_rows(fixture)
        fields = ",".join(f'"{row[0]}" {row[1]}' for row in schema)
        connection.execute(f"CREATE TABLE expected_records ({fields}, PRIMARY KEY(record_id))")
        connection.executemany(
            f"INSERT INTO expected_records VALUES ({','.join('?' for _ in schema)})", expected
        )
        differences = " OR ".join(
            f'p."{row[0]}" IS DISTINCT FROM e."{row[0]}"' for row in schema
        )
        mismatches = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {relation} p
                FULL OUTER JOIN expected_records e USING(record_id)
                WHERE p.record_id IS NULL OR e.record_id IS NULL OR {differences}
                """
            ).fetchone()[0]
        )
        if mismatches != 0:
            raise RuntimeError(f"Parquet differs from independently reconstructed fixture rows: {mismatches}")
        cursor = connection.execute(
            f"SELECT * FROM {relation} ORDER BY display_rank ASC, record_id ASC"
        )
        columns = [str(column[0]) for column in cursor.description]
        typed_rows = cursor.fetchall()
        projected = [
            {name: serialise(value) for name, value in zip(columns, row)} for row in typed_rows
        ]
    finally:
        connection.close()

    record_universe = rows_digest(typed_rows)
    readback = audit.get("landed_file_readback", {})
    expected_audit_schema = [
        {
            "name": name,
            "duckdb_type": type_name,
            "logical_required": logical_required,
            "parquet_primitive_type": primitive,
            "parquet_repetition": repetition,
            "parquet_converted_type": converted,
            "duckdb_describe_nullability": "YES" if repetition == "OPTIONAL" else "NO",
        }
        for name, type_name, logical_required, primitive, repetition, converted in schema
    ]
    if (
        readback.get("compression_codecs") != ["ZSTD"]
        or readback.get("schema") != expected_audit_schema
        or readback.get("rows") != rows
        or readback.get("distinct_keys") != distinct_keys
        or readback.get("null_keys") != null_keys
        or readback.get("duplicate_key_groups") != duplicate_groups
        or readback.get("context_records_eligible_for_project_signal") != signal_eligible
        or readback.get("required_column_null_counts") != required_nulls
        or readback.get("record_universe_sha256") != record_universe
    ):
        raise RuntimeError("Audit readback claims differ from independent DuckDB results")
    if (
        export.get("schema") != "pipelinenews-data-centres-intelligence-v1"
        or export.get("generation") != GENERATION
        or export.get("deployment_state") != "not-authorised"
        or export.get("promotion_eligible") is not False
        or export.get("usage_context") != USAGE_CONTEXT
        or export.get("section") != SECTION
        or export.get("declared_key") != ["record_id"]
        or export.get("record_count") != rows
        or export.get("records") != projected
        or export.get("source_rights", {}).get("repository_code_licence") != "MIT"
        or export.get("source_rights", {}).get("upstream_source_licence")
        != "NOT_DECLARED_IN_REPOSITORY"
    ):
        raise RuntimeError("Browser export does not equal the explicitly ordered DuckDB projection")
    return {
        "status": "PASS",
        "generation": GENERATION,
        "usage_context": USAGE_CONTEXT,
        "rows": rows,
        "distinct_record_ids": distinct_keys,
        "null_record_ids": null_keys,
        "duplicate_record_id_groups": duplicate_groups,
        "context_records_eligible_for_project_signal": signal_eligible,
        "schema_exact": True,
        "compression_codecs": codecs,
        "typed_fixture_mismatches": mismatches,
        "record_universe_sha256": record_universe,
        "source_commit": expected_source_commit,
    }


def compare(left: Path, right: Path) -> dict[str, Any]:
    differences: list[dict[str, str]] = []
    receipts: list[dict[str, str]] = []
    for path in OUTPUT_PATHS:
        left_path = left / path
        right_path = right / path
        if not left_path.is_file() or not right_path.is_file():
            raise RuntimeError(f"Comparison output missing: {path}")
        left_sha = sha256_file(left_path)
        right_sha = sha256_file(right_path)
        receipts.append({"path": path.as_posix(), "sha256": left_sha})
        if left_sha != right_sha or left_path.read_bytes() != right_path.read_bytes():
            differences.append({"path": path.as_posix(), "left_sha256": left_sha, "right_sha256": right_sha})
    if differences:
        raise RuntimeError(f"Independent builds are not byte-identical: {differences!r}")
    return {"status": "PASS", "generation": GENERATION, "byte_identical_outputs": receipts}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    verify_parser.add_argument("--source-root", type=Path, default=Path("."))
    verify_parser.add_argument("--expected-source-commit", required=True)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--left", type=Path, required=True)
    compare_parser.add_argument("--right", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "verify":
        result = verify(
            args.root.resolve(), args.source_root.resolve(), args.expected_source_commit
        )
    else:
        result = compare(args.left.resolve(), args.right.resolve())
    print(pretty_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
