# Data Centres GB

Open-source, provenance-first tooling for compiling United Kingdom data-centre source records into compact Parquet, DuckDB-readable relationship tables and a small map export.

The facility source is **OpenStreetMap via one bounded Overpass request**. Data Center Map is excluded from ingestion because its current terms prohibit programmatic retrieval and external-database copying. OpenInfraMap is an OSM visualisation layer, not a second source. See [the data-source law](docs/data-sources.md).

## What this generation builds

The `202608281053` candidate producer:

1. posts one declared UK query to Overpass;
2. immediately ignores contributor username, UID and changeset;
3. fails closed on empty, partial, remarked, duplicated or untagged results;
4. compiles the same retained response twice with DuckDB 1.3.2;
5. proves byte-identical ZSTD Parquet and exact DuckDB readback;
6. writes only an immutable candidate branch—never `main` or Pages.

Outputs:

```text
data/facilities/generation=202608281053/source=OPENSTREETMAP/osm-data-centre-elements-v1.parquet
data/relationships/generation=202608281053/data-centre-company-relationships-v1.parquet
exports/202608281053-osm-data-centres.geojson
reports/202608281053-osm-data-centres-audit.json
```

The facility Parquet grain is one OSM element. `DCGB-OSM-<TYPE>-<ID>` is a stable source-record ID, not a claim that one element equals one real facility. Buildings and campuses are not silently merged.

The company relationship Parquet is deliberately conservative. It retains raw OSM operator/owner strings, but asserts no company number, computes no score and marks every row `ABSTAIN` / `eligible_for_join=false`. A later resolver must use a pinned Companies Parquet generation and verified Companies House numbers; this producer makes zero Companies requests.

## Run offline verification

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest -v tests/test_202608281053_osm_data_centres.py
```

The unit suite uses only the hostile fixture. It never accesses the network.

## Local API

The FastAPI service reads an already landed GeoJSON export. It performs no source fetch from a request handler.

```bash
uvicorn app:app --reload
```

Endpoints:

```text
GET /
GET /health
GET /v1/data-centres/sources
GET /v1/data-centres
GET /v1/data-centres?generation=202608281053
```

If no candidate output has been deliberately installed, `/v1/data-centres` returns `404` rather than fetching a website.

## BBC / PipelineNews boundary

The BBC report [“Data centres could pay hundreds of millions in deposits for power demands”](https://www.bbc.co.uk/news/articles/c9q90q9qnn2o) is news context, not facility data. PipelineNews already carries its link behind three quarantined `DATA_CENTRES` context cards. This repository also defines a one-row link-only owner evidence record for a future pinned `SOURCE_METADATA` projection; it stores no article body, HTML, snippet, summary, image or project binding.

Use Ofgem’s primary release for connection-deposit policy claims. Do not bind editorial context to facilities, companies or REPD projects.

## Licensing

- Code: MIT.
- OSM-derived Parquet, relationships and GeoJSON: ODbL 1.0.
- Required attribution: `© OpenStreetMap contributors`.
- Third-party news links remain subject to their publishers’ rights.

This repository provides research data, not engineering, planning, legal, investment or grid-connection advice.
