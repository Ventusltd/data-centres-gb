#!/usr/bin/env python3
"""Fetch, compile and verify the 202608281053 OSM data-centre candidate."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterable

GENERATION = "202608281053"
DUCKDB_VERSION = "1.3.2"
ENDPOINT = "https://overpass-api.de/api/interpreter"
QUERY_REL = Path("queries/202608281053-gb-data-centres.overpassql")
CONTRACT_REL = Path("contracts/202608281053-osm-data-centres.json")
MANIFEST_REL = Path("manifests/202608281053-osm-data-centres-source.json")
EVIDENCE_REL = Path("evidence/202608281053-bbc-data-centres-news-link.json")
FIXTURE_REL = Path("data/source-fixtures/202608281053-overpass-fixture.json")
ELEMENTS_REL = Path(
    "data/facilities/generation=202608281053/source=OPENSTREETMAP/"
    "osm-data-centre-elements-v1.parquet"
)
RELATIONSHIPS_REL = Path(
    "data/relationships/generation=202608281053/"
    "data-centre-company-relationships-v1.parquet"
)
GEOJSON_REL = Path("exports/202608281053-osm-data-centres.geojson")
AUDIT_REL = Path("reports/202608281053-osm-data-centres-audit.json")
OUTPUTS = (ELEMENTS_REL, RELATIONSHIPS_REL, GEOJSON_REL, AUDIT_REL)
SOURCE_BOUNDARY = (
    ".github/workflows/202608281053-osm-data-centres-candidate.yml",
    ".github/workflows/ci.yml",
    "README.md",
    "app.py",
    "build/python/202608281053-osm-data-centres.py",
    "contracts/202608281053-osm-data-centres.json",
    "data/source-fixtures/202608281053-overpass-fixture.json",
    "docs/data-sources.md",
    "evidence/202608281053-bbc-data-centres-news-link.json",
    "manifests/202608281053-osm-data-centres-source.json",
    "queries/202608281053-gb-data-centres.overpassql",
    "requirements.txt",
    "tests/test_202608281053_osm_data_centres.py",
)
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
DATA_CENTRE_VALUE = re.compile(r"^data_cent(?:er|re)$")
LIFECYCLES = ("proposed", "planned", "construction", "disused", "abandoned", "demolished")
FEATURE_KEYS = ("telecom", "building", "industrial")
ATTRIBUTION = "© OpenStreetMap contributors"
LICENCE = "ODbL-1.0"

ELEMENT_SCHEMA: tuple[tuple[str, str, bool], ...] = (
    ("source_record_id", "VARCHAR", True),
    ("source_element_key", "VARCHAR", True),
    ("generation", "VARCHAR", True),
    ("source_name", "VARCHAR", True),
    ("osm_type", "VARCHAR", True),
    ("osm_id", "BIGINT", True),
    ("osm_version", "BIGINT", True),
    ("osm_timestamp", "TIMESTAMP", True),
    ("osm_base_timestamp", "TIMESTAMP", True),
    ("fetched_at", "TIMESTAMP", True),
    ("inclusion_rule", "VARCHAR", True),
    ("matched_rules_json", "VARCHAR", True),
    ("lifecycle", "VARCHAR", True),
    ("name_raw", "VARCHAR", False),
    ("operator_raw", "VARCHAR", False),
    ("owner_raw", "VARCHAR", False),
    ("ref_raw", "VARCHAR", False),
    ("wikidata_raw", "VARCHAR", False),
    ("operator_wikidata_raw", "VARCHAR", False),
    ("uprn_raw", "VARCHAR", False),
    ("tags_json", "VARCHAR", True),
    ("coordinate_trace_json", "VARCHAR", True),
    ("centroid_latitude", "DOUBLE", True),
    ("centroid_longitude", "DOUBLE", True),
    ("bbox_min_latitude", "DOUBLE", True),
    ("bbox_min_longitude", "DOUBLE", True),
    ("bbox_max_latitude", "DOUBLE", True),
    ("bbox_max_longitude", "DOUBLE", True),
    ("geometry_sha256", "VARCHAR", True),
    ("query_sha256", "VARCHAR", True),
    ("source_url", "VARCHAR", True),
    ("source_attribution", "VARCHAR", True),
    ("source_licence", "VARCHAR", True),
    ("facility_identity_status", "VARCHAR", True),
    ("eligible_for_company_binding", "BOOLEAN", True),
)

RELATIONSHIP_SCHEMA: tuple[tuple[str, str, bool], ...] = (
    ("relationship_record_id", "VARCHAR", True),
    ("generation", "VARCHAR", True),
    ("data_centre_source_record_id", "VARCHAR", True),
    ("data_centre_id", "VARCHAR", False),
    ("company_number", "VARCHAR", False),
    ("company_name_raw", "VARCHAR", False),
    ("relationship_type", "VARCHAR", True),
    ("company_ref_status", "VARCHAR", True),
    ("match_score", "DOUBLE", False),
    ("score_method", "VARCHAR", True),
    ("adjudication_decision", "VARCHAR", True),
    ("evidence_status", "VARCHAR", True),
    ("abstention_reason", "VARCHAR", True),
    ("source_url", "VARCHAR", True),
    ("source_attribution", "VARCHAR", True),
    ("source_licence", "VARCHAR", True),
    ("eligible_for_join", "BOOLEAN", True),
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def load_duckdb():
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"duckdb=={DUCKDB_VERSION} is required") from exc
    if duckdb.__version__ != DUCKDB_VERSION:
        raise RuntimeError(
            f"DuckDB version drift: expected {DUCKDB_VERSION}, got {duckdb.__version__}"
        )
    return duckdb


def parse_utc(value: Any, label: str) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RuntimeError(f"{label} must be an ISO-8601 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RuntimeError(f"Invalid {label}: {value!r}") from exc
    return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)


def iso_z(value: dt.datetime) -> str:
    return value.replace(tzinfo=dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean_tag(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def query_sha(root: Path) -> str:
    return sha256_bytes((root / QUERY_REL).read_bytes())


def doctor(root: Path) -> dict[str, Any]:
    missing = [path for path in SOURCE_BOUNDARY if not (root / path).is_file()]
    if missing:
        raise RuntimeError(f"Source boundary files missing: {missing!r}")
    contract = load_json(root / CONTRACT_REL)
    manifest = load_json(root / MANIFEST_REL)
    evidence = load_json(root / EVIDENCE_REL)
    expected_outputs = {
        "elements_parquet": ELEMENTS_REL.as_posix(),
        "relationships_parquet": RELATIONSHIPS_REL.as_posix(),
        "browser_geojson": GEOJSON_REL.as_posix(),
        "audit_report": AUDIT_REL.as_posix(),
    }
    if (
        contract.get("schema") != "data-centres-osm-contract-v1"
        or contract.get("generation") != GENERATION
        or contract.get("declared_keys")
        != {
            "elements": ["source_record_id"],
            "relationships": ["relationship_record_id"],
        }
        or contract.get("outputs") != expected_outputs
        or contract.get("duckdb_version") != DUCKDB_VERSION
        or contract.get("parquet_compression") != "ZSTD"
    ):
        raise RuntimeError("Contract governance drifted")
    if contract.get("element_schema") != [
        {"name": name, "duckdb_type": type_name, "logical_required": required}
        for name, type_name, required in ELEMENT_SCHEMA
    ]:
        raise RuntimeError("Element schema contract drifted")
    if contract.get("relationship_schema") != [
        {"name": name, "duckdb_type": type_name, "logical_required": required}
        for name, type_name, required in RELATIONSHIP_SCHEMA
    ]:
        raise RuntimeError("Relationship schema contract drifted")
    if (
        manifest.get("schema") != "data-centres-osm-source-manifest-v1"
        or manifest.get("generation") != GENERATION
        or manifest.get("source_boundary") != list(SOURCE_BOUNDARY)
        or manifest.get("overpass", {}).get("endpoint") != ENDPOINT
        or manifest.get("overpass", {}).get("query_sha256") != query_sha(root)
        or manifest.get("excluded_sources", {}).get("datacentermap", {}).get("network_requests") != 0
        or manifest.get("visual_validation", {}).get("openinframap", {}).get("network_requests") != 0
    ):
        raise RuntimeError("Source manifest drifted")
    if (
        evidence.get("schema") != "data-centres-news-link-v1"
        or evidence.get("record_kind") != "NEWS_LINK"
        or evidence.get("canonical_url")
        != "https://www.bbc.co.uk/news/articles/c9q90q9qnn2o"
        or evidence.get("summary") is not None
        or evidence.get("eligible_for_news_signal") is not False
        or evidence.get("project_binding_count") != 0
    ):
        raise RuntimeError("BBC link-only evidence boundary drifted")
    return {"status": "PASS", "generation": GENERATION, "source_files": len(SOURCE_BOUNDARY)}


def fetch(root: Path, output: Path) -> dict[str, Any]:
    doctor(root)
    import requests

    query = (root / QUERY_REL).read_text(encoding="utf-8")
    headers = {
        "User-Agent": "Ventusltd-data-centres-gb/1.0 (+https://github.com/Ventusltd/data-centres-gb)",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    attempts = 0
    last_error = "unknown failure"
    response = None
    for delay in (0, 30, 60):
        if delay:
            time.sleep(delay)
        attempts += 1
        try:
            candidate = requests.post(
                ENDPOINT,
                data={"data": query},
                headers=headers,
                timeout=(20, 150),
            )
            if candidate.status_code in {406, 429} or 500 <= candidate.status_code < 600:
                last_error = f"HTTP {candidate.status_code}"
                continue
            candidate.raise_for_status()
            response = candidate
            break
        except requests.RequestException as exc:
            last_error = str(exc)
    if response is None:
        raise RuntimeError(f"Bounded Overpass fetch failed after {attempts} attempts: {last_error}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Overpass did not return JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Overpass response must be a JSON object")
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    envelope = {
        "schema": "overpass-data-centres-fetch-v1",
        "endpoint": ENDPOINT,
        "query_sha256": query_sha(root),
        "fetched_at": fetched_at,
        "network_request_attempts": attempts,
        "network_successful_requests": 1,
        "payload": payload,
    }
    validate_envelope(envelope, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(pretty_json(envelope), encoding="utf-8")
    return {
        "status": "PASS",
        "fetched_at": fetched_at,
        "elements": len(payload["elements"]),
        "network_request_attempts": attempts,
        "query_sha256": envelope["query_sha256"],
        "output_sha256": sha256_file(output),
    }


def validate_envelope(envelope: dict[str, Any], root: Path) -> tuple[dict[str, Any], dt.datetime, dt.datetime]:
    if (
        envelope.get("schema") != "overpass-data-centres-fetch-v1"
        or envelope.get("endpoint") != ENDPOINT
        or envelope.get("query_sha256") != query_sha(root)
        or not isinstance(envelope.get("network_request_attempts"), int)
        or not 0 <= int(envelope["network_request_attempts"]) <= 3
        or envelope.get("network_successful_requests") not in {0, 1}
    ):
        raise RuntimeError("Fetch envelope provenance drifted")
    fetched_at = parse_utc(envelope.get("fetched_at"), "fetched_at")
    payload = envelope.get("payload")
    if not isinstance(payload, dict) or payload.get("remark"):
        raise RuntimeError("Overpass payload is partial, invalid or contains a remark")
    elements = payload.get("elements")
    if not isinstance(elements, list) or not elements or len(elements) > 100000:
        raise RuntimeError("Overpass element set must be non-empty and bounded")
    osm3s = payload.get("osm3s")
    if not isinstance(osm3s, dict):
        raise RuntimeError("Overpass osm3s provenance is missing")
    osm_base = parse_utc(osm3s.get("timestamp_osm_base"), "timestamp_osm_base")
    return payload, fetched_at, osm_base


def matching_rules(tags: dict[str, Any]) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for key in FEATURE_KEYS:
        value = tags.get(key)
        if isinstance(value, str) and DATA_CENTRE_VALUE.fullmatch(value):
            matches.append((key, "OPERATIONAL_OR_UNSPECIFIED"))
    for lifecycle in LIFECYCLES:
        for key in FEATURE_KEYS:
            value = tags.get(f"{lifecycle}:{key}")
            if isinstance(value, str) and DATA_CENTRE_VALUE.fullmatch(value):
                matches.append((f"{lifecycle}:{key}", lifecycle.upper()))
    return matches


def coordinate_trace(element: dict[str, Any]) -> list[list[float]]:
    coordinates: list[list[float]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            lat, lon = value.get("lat"), value.get("lon")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                coordinates.append([float(lon), float(lat)])
            for key in ("center", "geometry", "members"):
                if key in value:
                    walk(value[key])
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(element)
    unique: list[list[float]] = []
    seen: set[tuple[float, float]] = set()
    for lon, lat in coordinates:
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise RuntimeError("OSM coordinate is outside EPSG:4326 bounds")
        pair = (lon, lat)
        if pair not in seen:
            seen.add(pair)
            unique.append([lon, lat])
    if not unique:
        raise RuntimeError("OSM element has no usable coordinate evidence")
    return unique


def normalise(envelope: dict[str, Any], root: Path) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    payload, fetched_at, osm_base = validate_envelope(envelope, root)
    element_rows: list[tuple[Any, ...]] = []
    relationship_rows: list[tuple[Any, ...]] = []
    seen: set[tuple[str, int]] = set()
    q_sha = str(envelope["query_sha256"])
    for raw in payload["elements"]:
        if not isinstance(raw, dict):
            raise RuntimeError("Every Overpass element must be an object")
        osm_type = raw.get("type")
        osm_id = raw.get("id")
        osm_version = raw.get("version")
        if osm_type not in {"node", "way", "relation"} or not isinstance(osm_id, int):
            raise RuntimeError("OSM element identity is invalid")
        if not isinstance(osm_version, int) or osm_version < 1:
            raise RuntimeError("OSM element version is missing or invalid")
        key = (osm_type, osm_id)
        if key in seen:
            raise RuntimeError(f"Duplicate OSM element in response: {key!r}")
        seen.add(key)
        tags = raw.get("tags")
        if not isinstance(tags, dict) or not tags:
            raise RuntimeError("Matched OSM element has no tags")
        matches = matching_rules(tags)
        if not matches:
            raise RuntimeError(f"Element {key!r} does not satisfy the declared query law")
        trace = coordinate_trace(raw)
        lons = [pair[0] for pair in trace]
        lats = [pair[1] for pair in trace]
        if osm_type == "node":
            centroid_lon, centroid_lat = trace[0]
        elif isinstance(raw.get("center"), dict):
            centroid_lon = float(raw["center"]["lon"])
            centroid_lat = float(raw["center"]["lat"])
        else:
            centroid_lon = (min(lons) + max(lons)) / 2
            centroid_lat = (min(lats) + max(lats)) / 2
        trace_json = canonical_json(trace)
        record_id = f"DCGB-OSM-{osm_type.upper()}-{osm_id}"
        element_key = f"osm:{osm_type}:{osm_id}"
        source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
        primary_rule, lifecycle = matches[0]
        name = clean_tag(tags.get("name"))
        operator = clean_tag(tags.get("operator"))
        owner = clean_tag(tags.get("owner"))
        row = (
            record_id,
            element_key,
            GENERATION,
            "OPENSTREETMAP",
            osm_type,
            osm_id,
            osm_version,
            parse_utc(raw.get("timestamp"), f"{element_key}.timestamp"),
            osm_base,
            fetched_at,
            primary_rule,
            canonical_json([rule for rule, _status in matches]),
            lifecycle,
            name,
            operator,
            owner,
            clean_tag(tags.get("ref")),
            clean_tag(tags.get("wikidata")),
            clean_tag(tags.get("operator:wikidata")),
            clean_tag(tags.get("ref:GB:uprn")),
            canonical_json(tags),
            trace_json,
            centroid_lat,
            centroid_lon,
            min(lats),
            min(lons),
            max(lats),
            max(lons),
            sha256_bytes(trace_json.encode("utf-8")),
            q_sha,
            source_url,
            ATTRIBUTION,
            LICENCE,
            "SOURCE_ELEMENT_ONLY",
            False,
        )
        element_rows.append(row)
        for role, raw_name in (("OPERATOR", operator), ("OWNER", owner)):
            relationship_rows.append(
                (
                    f"DCCO-{record_id}-{role}",
                    GENERATION,
                    record_id,
                    None,
                    None,
                    raw_name,
                    role,
                    "UNRESOLVED",
                    None,
                    "NOT_SCORED",
                    "ABSTAIN",
                    "OSM_SOURCE_STRING_ONLY" if raw_name else "NO_SOURCE_PARTY",
                    "COMPANY_NUMBER_NOT_VERIFIED" if raw_name else "SOURCE_PARTY_MISSING",
                    source_url,
                    ATTRIBUTION,
                    LICENCE,
                    False,
                )
            )
    element_rows.sort(key=lambda row: (row[4], row[5]))
    relationship_rows.sort(key=lambda row: row[0])
    return element_rows, relationship_rows


def create_table(connection: Any, name: str, schema: Iterable[tuple[str, str, bool]], key: str) -> None:
    fields = []
    for column, type_name, required in schema:
        fields.append(f'"{column}" {type_name}{" NOT NULL" if required else ""}')
    fields.append(f'PRIMARY KEY ("{key}")')
    connection.execute(f'CREATE TABLE "{name}" ({", ".join(fields)})')


def insert_rows(connection: Any, table: str, schema: tuple[tuple[str, str, bool], ...], rows: list[tuple[Any, ...]]) -> None:
    if rows:
        connection.executemany(
            f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in schema)})', rows
        )


def copy_parquet(connection: Any, table: str, path: Path, order_by: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"COPY (SELECT * FROM \"{table}\" ORDER BY {order_by}) "
        f"TO '{sql_path(path)}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)"
    )


def read_rows(connection: Any, path: Path) -> tuple[list[str], list[tuple[Any, ...]]]:
    cursor = connection.execute(
        f"SELECT * FROM read_parquet('{sql_path(path)}', hive_partitioning=false)"
    )
    return [str(column[0]) for column in cursor.description], cursor.fetchall()


def geojson_from_rows(columns: list[str], rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    index = {name: position for position, name in enumerate(columns)}
    features = []
    for row in rows:
        properties = {
            name: row[index[name]]
            for name in (
                "source_record_id",
                "name_raw",
                "operator_raw",
                "owner_raw",
                "lifecycle",
                "source_url",
                "source_attribution",
                "source_licence",
                "facility_identity_status",
                "eligible_for_company_binding",
            )
        }
        features.append(
            {
                "type": "Feature",
                "id": row[index["source_record_id"]],
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        row[index["centroid_longitude"]],
                        row[index["centroid_latitude"]],
                    ],
                },
                "properties": properties,
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "OSM data-centre source elements — not deduplicated facilities",
        "generation": GENERATION,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "features": features,
    }


def schema_receipt(connection: Any, path: Path) -> list[dict[str, str]]:
    escaped = sql_path(path)
    return [
        {"name": str(name), "duckdb_type": str(type_name).upper()}
        for name, type_name, _null, _key, _default, _extra in connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{escaped}', hive_partitioning=false)"
        ).fetchall()
    ]


def build(root: Path, input_path: Path, output_root: Path, source_commit: str) -> dict[str, Any]:
    doctor(root)
    if not COMMIT_SHA.fullmatch(source_commit):
        raise RuntimeError("source_commit must be a lowercase 40-character SHA")
    envelope = load_json(input_path)
    payload, fetched_at, osm_base = validate_envelope(envelope, root)
    element_rows, relationship_rows = normalise(envelope, root)
    duckdb = load_duckdb()
    elements_path = output_root / ELEMENTS_REL
    relationships_path = output_root / RELATIONSHIPS_REL
    geojson_path = output_root / GEOJSON_REL
    audit_path = output_root / AUDIT_REL
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        connection.execute("SET preserve_insertion_order = false")
        create_table(connection, "elements", ELEMENT_SCHEMA, "source_record_id")
        create_table(connection, "relationships", RELATIONSHIP_SCHEMA, "relationship_record_id")
        insert_rows(connection, "elements", ELEMENT_SCHEMA, element_rows)
        insert_rows(connection, "relationships", RELATIONSHIP_SCHEMA, relationship_rows)
        copy_parquet(connection, "elements", elements_path, '"osm_type", "osm_id"')
        copy_parquet(connection, "relationships", relationships_path, '"relationship_record_id"')
        columns, landed_rows = read_rows(connection, elements_path)
        geojson = geojson_from_rows(columns, landed_rows)
        geojson_path.parent.mkdir(parents=True, exist_ok=True)
        geojson_path.write_text(pretty_json(geojson), encoding="utf-8")
        element_schema_receipt = schema_receipt(connection, elements_path)
        relationship_schema_receipt = schema_receipt(connection, relationships_path)
    finally:
        connection.close()
    raw_sha = sha256_file(input_path)
    audit = {
        "schema": "data-centres-osm-audit-v1",
        "status": "PASS",
        "generation": GENERATION,
        "source_commit": source_commit,
        "fetched_at": iso_z(fetched_at),
        "osm_base_timestamp": iso_z(osm_base),
        "query_sha256": envelope["query_sha256"],
        "raw_fetch_sha256": raw_sha,
        "raw_fetch_landed": False,
        "source_payload_element_count": len(payload["elements"]),
        "element_rows": len(element_rows),
        "relationship_rows": len(relationship_rows),
        "network": {
            "overpass_request_attempts": envelope["network_request_attempts"],
            "overpass_successful_requests": envelope["network_successful_requests"],
            "datacentermap_requests": 0,
            "openinframap_requests": 0,
            "companies_fetch_requests": 0,
        },
        "identity": {
            "source_record_key": "osm_type + osm_id",
            "canonical_facility_ids_created": 0,
            "company_numbers_asserted": 0,
            "relationship_decisions": ["ABSTAIN"],
        },
        "rights": {
            "data_licence": LICENCE,
            "attribution": ATTRIBUTION,
            "code_licence": "MIT",
            "datacentermap_ingestion": "PROHIBITED",
            "openinframap_role": "VISUAL_VALIDATION_ONLY",
        },
        "schemas": {
            "elements": element_schema_receipt,
            "relationships": relationship_schema_receipt,
        },
        "outputs": {
            "elements_parquet": {
                "path": ELEMENTS_REL.as_posix(),
                "sha256": sha256_file(elements_path),
                "bytes": elements_path.stat().st_size,
                "compression": "ZSTD",
            },
            "relationships_parquet": {
                "path": RELATIONSHIPS_REL.as_posix(),
                "sha256": sha256_file(relationships_path),
                "bytes": relationships_path.stat().st_size,
                "compression": "ZSTD",
            },
            "browser_geojson": {
                "path": GEOJSON_REL.as_posix(),
                "sha256": sha256_file(geojson_path),
                "bytes": geojson_path.stat().st_size,
                "derived_from": "elements_parquet_duckdb_readback",
            },
        },
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(pretty_json(audit), encoding="utf-8")
    return audit


def verify_table(connection: Any, path: Path, schema: tuple[tuple[str, str, bool], ...], key: str) -> list[tuple[Any, ...]]:
    escaped = sql_path(path)
    expected_schema = [(name, type_name) for name, type_name, _required in schema]
    actual_schema = [
        (str(name), str(type_name).upper())
        for name, type_name, _null, _key, _default, _extra in connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{escaped}', hive_partitioning=false)"
        ).fetchall()
    ]
    if actual_schema != expected_schema:
        raise RuntimeError(f"Parquet schema mismatch for {path}: {actual_schema!r}")
    relation = f"read_parquet('{escaped}', hive_partitioning=false)"
    rows, distinct_keys, null_keys = map(
        int,
        connection.execute(
            f'SELECT count(*), count(DISTINCT "{key}"), count(*) FILTER (WHERE "{key}" IS NULL OR "{key}" = \'\') FROM {relation}'
        ).fetchone(),
    )
    if rows != distinct_keys or null_keys:
        raise RuntimeError(f"Key gate failed for {path}")
    for name, _type_name, required in schema:
        if required and int(
            connection.execute(f'SELECT count(*) FROM {relation} WHERE "{name}" IS NULL').fetchone()[0]
        ):
            raise RuntimeError(f"Required-column null gate failed: {path}:{name}")
    codecs = {
        str(value).upper()
        for (value,) in connection.execute(
            f"SELECT DISTINCT compression FROM parquet_metadata('{escaped}')"
        ).fetchall()
    }
    if codecs != {"ZSTD"}:
        raise RuntimeError(f"Parquet compression drift for {path}: {codecs!r}")
    return connection.execute(f'SELECT * FROM {relation} ORDER BY "{key}"').fetchall()


def verify(root: Path, source_root: Path, input_path: Path, expected_source_commit: str) -> dict[str, Any]:
    doctor(source_root)
    if not COMMIT_SHA.fullmatch(expected_source_commit):
        raise RuntimeError("Invalid expected source commit")
    audit = load_json(root / AUDIT_REL)
    if (
        audit.get("schema") != "data-centres-osm-audit-v1"
        or audit.get("status") != "PASS"
        or audit.get("generation") != GENERATION
        or audit.get("source_commit") != expected_source_commit
        or audit.get("raw_fetch_landed") is not False
        or audit.get("network", {}).get("datacentermap_requests") != 0
        or audit.get("network", {}).get("openinframap_requests") != 0
        or audit.get("network", {}).get("companies_fetch_requests") != 0
        or audit.get("identity", {}).get("canonical_facility_ids_created") != 0
        or audit.get("identity", {}).get("company_numbers_asserted") != 0
    ):
        raise RuntimeError("Audit governance gate failed")
    envelope = load_json(input_path)
    expected_elements, expected_relationships = normalise(envelope, source_root)
    duckdb = load_duckdb()
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        actual_elements = verify_table(
            connection, root / ELEMENTS_REL, ELEMENT_SCHEMA, "source_record_id"
        )
        actual_relationships = verify_table(
            connection,
            root / RELATIONSHIPS_REL,
            RELATIONSHIP_SCHEMA,
            "relationship_record_id",
        )
        expected_elements_by_key = sorted(expected_elements, key=lambda row: row[0])
        expected_relationships_by_key = sorted(expected_relationships, key=lambda row: row[0])
        if actual_elements != expected_elements_by_key:
            raise RuntimeError("Elements Parquet differs from independently normalised input")
        if actual_relationships != expected_relationships_by_key:
            raise RuntimeError("Relationships Parquet differs from independently normalised input")
        columns, rows = read_rows(connection, root / ELEMENTS_REL)
        expected_geojson = geojson_from_rows(columns, rows)
    finally:
        connection.close()
    if load_json(root / GEOJSON_REL) != expected_geojson:
        raise RuntimeError("GeoJSON is not the exact DuckDB readback projection")
    for label, rel in (
        ("elements_parquet", ELEMENTS_REL),
        ("relationships_parquet", RELATIONSHIPS_REL),
        ("browser_geojson", GEOJSON_REL),
    ):
        receipt = audit.get("outputs", {}).get(label, {})
        if receipt.get("path") != rel.as_posix() or receipt.get("sha256") != sha256_file(root / rel):
            raise RuntimeError(f"Output receipt failed: {label}")
    banned = {"user", "uid", "changeset"}
    element_names = {name for name, _type_name, _required in ELEMENT_SCHEMA}
    if banned & element_names:
        raise RuntimeError("Contributor identifiers leaked into element schema")
    return {
        "status": "PASS",
        "generation": GENERATION,
        "element_rows": len(actual_elements),
        "relationship_rows": len(actual_relationships),
        "company_numbers_asserted": 0,
        "source_commit": expected_source_commit,
    }


def compare(left: Path, right: Path) -> dict[str, Any]:
    receipts = []
    for rel in OUTPUTS:
        left_path, right_path = left / rel, right / rel
        if not left_path.is_file() or not right_path.is_file():
            raise RuntimeError(f"Comparison output missing: {rel}")
        if left_path.read_bytes() != right_path.read_bytes():
            raise RuntimeError(f"Independent builds differ: {rel}")
        receipts.append({"path": rel.as_posix(), "sha256": sha256_file(left_path)})
    return {"status": "PASS", "generation": GENERATION, "byte_identical": receipts}


def land(candidate_root: Path, destination_root: Path, source_commit: str) -> dict[str, Any]:
    audit = load_json(candidate_root / AUDIT_REL)
    if audit.get("source_commit") != source_commit:
        raise RuntimeError("Candidate source commit does not match land request")
    for rel in OUTPUTS:
        source = candidate_root / rel
        destination = destination_root / rel
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"Candidate output is missing or unsafe: {rel}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return {"status": "PASS", "generation": GENERATION, "landed": [p.as_posix() for p in OUTPUTS]}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    doctor_parser = commands.add_parser("doctor")
    doctor_parser.add_argument("--root", type=Path, required=True)
    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("--root", type=Path, required=True)
    fetch_parser.add_argument("--output", type=Path, required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--root", type=Path, required=True)
    build_parser.add_argument("--input", type=Path, required=True)
    build_parser.add_argument("--output-root", type=Path, required=True)
    build_parser.add_argument("--source-commit", required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    verify_parser.add_argument("--source-root", type=Path, required=True)
    verify_parser.add_argument("--input", type=Path, required=True)
    verify_parser.add_argument("--expected-source-commit", required=True)
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("--left", type=Path, required=True)
    compare_parser.add_argument("--right", type=Path, required=True)
    land_parser = commands.add_parser("land")
    land_parser.add_argument("--candidate-root", type=Path, required=True)
    land_parser.add_argument("--destination-root", type=Path, required=True)
    land_parser.add_argument("--source-commit", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "doctor":
        result = doctor(args.root.resolve())
    elif args.command == "fetch":
        result = fetch(args.root.resolve(), args.output.resolve())
    elif args.command == "build":
        result = build(
            args.root.resolve(), args.input.resolve(), args.output_root.resolve(), args.source_commit
        )
    elif args.command == "verify":
        result = verify(
            args.root.resolve(),
            args.source_root.resolve(),
            args.input.resolve(),
            args.expected_source_commit,
        )
    elif args.command == "compare":
        result = compare(args.left.resolve(), args.right.resolve())
    else:
        result = land(
            args.candidate_root.resolve(), args.destination_root.resolve(), args.source_commit
        )
    print(pretty_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
