# Data-source law

This repository uses a fail-closed source policy. Open code does not make third-party content open data.

## Facility source: OpenStreetMap

The timestamped batch producer queries the United Kingdom administrative area once through Overpass. It accepts `data_center` and `data_centre` values on `telecom`, `building` and `industrial`, including declared lifecycle prefixes. The preferred facility tag is `telecom=data_center`; a building tag can describe only one building within a larger campus.

The source record key is the type-scoped OSM identity:

```text
osm:<node|way|relation>:<id>
DCGB-OSM-<NODE|WAY|RELATION>-<id>
```

This is not a permanent real-world facility ID. The producer does not merge buildings into campuses and does not silently infer ownership, capacity or status. It retains OSM version and timestamp, the OSM base timestamp, exact tags, a compact coordinate trace and the query hash. Contributor username, UID and changeset are deliberately excluded from published tables.

OSM-derived outputs are licensed under [ODbL 1.0](https://www.openstreetmap.org/copyright) and must display `© OpenStreetMap contributors`. The repository’s MIT licence applies to code, not OSM-derived data.

## OpenInfraMap

[OpenInfraMap](https://github.com/openinframap/openinframap) is useful for visual checking, but its documented pipeline is an OpenStreetMap replication and rendering stack. It is not counted as independent evidence and this producer sends it zero requests.

## Data Center Map

Data Center Map is excluded from ingestion. Its [Terms of Use](https://www.datacentermap.com/legal/terms/) prohibit scraping, crawling, caching, programmatic retrieval and copying records into an external database. Its licensed exports are not open redistribution rights. It may be opened by a person as a market reference, but contributes zero rows, coordinates, names, addresses, IDs or validation facts to this dataset unless explicit open redistribution permission is obtained.

## BBC and PipelineNews

The [BBC report](https://www.bbc.co.uk/news/articles/c9q90q9qnn2o) is editorial context, not facility data. The owner evidence record retains only publisher, headline, canonical URL and publication date. It retains no HTML, article body, summary, snippet, image, facility field or project binding and cannot drive a news signal.

PipelineNews already carries the article link behind three quarantined `DATA_CENTRES` context cards. A later timestamped PipelineNews generation may pin the one-row owner link as `SOURCE_METADATA`; it must not duplicate the metric rows or join the link to REPD projects.

For connection-deposit policy claims, prefer [Ofgem’s primary release](https://www.ofgem.gov.uk/press-release/ofgem-acts-free-grid-capacity-tackling-speculative-data-centre-projects) over editorial paraphrase.

## Companies relationship table

The first `data-centre-company-relationships-v1.parquet` is an abstention ledger, not an ownership table. Each OSM element gets operator and owner slots. Raw source strings may be retained as candidates, but `company_number`, `data_centre_id` and `match_score` stay null; `score_method=NOT_SCORED`, `adjudication_decision=ABSTAIN` and `eligible_for_join=false`.

A later resolver may link a row only after it verifies a stable facility identity and a Companies House company number against a pinned Companies Parquet generation. Ambiguous names must remain abstentions. That resolver must never trigger a fresh Companies fetch from this workflow.
