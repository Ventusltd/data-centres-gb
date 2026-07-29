# Data Centres GB

Open-source tooling for collecting, normalising and serving public information about data-centre infrastructure in Great Britain.

The project was created following the BBC News report **“Data centres could pay hundreds of millions in deposits for power demands”**, published on 29 July 2026. The report states that 564 data centres were listed in the UK and describes Ofgem proposals for refundable grid-connection deposits of £237,500 to £712,500 per MW. A 1 GW project could therefore face an initial deposit of £237.5 million to £712.5 million.

The BBC article is context, not the underlying facility dataset. Facility records are fetched separately from explicitly declared sources. The first adapter targets the publicly visible London listings on Data Center Map.

## Purpose

This repository separates four things that are often mixed together:

1. source discovery;
2. raw public records;
3. normalised data-centre facts;
4. an open JSON API for downstream maps, grid studies and research.

Every API response includes source and retrieval metadata. No record should be presented as independently verified merely because it was collected successfully.

## Current source

- BBC context: `https://www.bbc.co.uk/news/articles/c9q90q9qnn2o`
- Data Center Map London listings: `https://www.datacentermap.com/united-kingdom/london/`

Data Center Map currently describes its London page as containing hundreds of facilities across London and the wider London market. Counts can change between retrievals and may include locations outside Greater London, such as Slough, Hemel Hempstead, Reading and Crawley.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the API

```bash
uvicorn app:app --reload
```

Open:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/v1/data-centres?source=datacentermap&region=london
http://127.0.0.1:8000/docs
```

## Example response

```json
{
  "source": "datacentermap",
  "source_url": "https://www.datacentermap.com/united-kingdom/london/",
  "region": "london",
  "retrieved_at": "2026-07-29T12:00:00+00:00",
  "record_count": 258,
  "records": [
    {
      "name": "Example facility",
      "operator": "Example operator",
      "address": "Example address",
      "postcode": "E14 9AA",
      "locality": "London",
      "source_url": "https://www.datacentermap.com/..."
    }
  ]
}
```

The count above is illustrative. The live endpoint returns the records visible at retrieval time.

## API contract

### `GET /`

Service metadata and available sources.

### `GET /health`

Basic process health.

### `GET /v1/data-centres`

Query parameters:

- `source`: currently `datacentermap`;
- `region`: currently `london`;
- `refresh`: set to `true` to bypass the in-process cache.

The adapter performs a normal HTTP request, uses a descriptive user agent, applies a timeout and keeps a short cache. It does not bypass authentication, paywalls, CAPTCHAs or technical access controls.

## Data model

Each normalised record may contain:

```text
name
operator
address
postcode
locality
country
status
latitude
longitude
source
source_url
retrieved_at
```

Unknown fields remain `null`. Inferred values should not be silently represented as source facts.

## Source and legal discipline

This software is open source. Third-party web content is not automatically open data.

Before operating a recurring collector, users must review the source website’s current terms, robots policy and licensing position. Collection frequency should be low and proportionate. The software must not be used to defeat access controls or reproduce protected databases unlawfully.

Where a source offers a licensed API or downloadable dataset, that route should replace HTML extraction. Contributors are encouraged to add adapters for official planning portals, operator disclosures, local authority planning data and other openly licensed sources.

## Known limitations

- A commercial directory is not the same as a complete national register.
- A “London” market page may include facilities across a much wider geographic area.
- Facility, campus and individual-building records can overlap.
- Public listings may omit electrical demand, planning status or exact coordinates.
- HTML structure can change without warning.
- A successful fetch does not establish accuracy or currency.

## Development

Run a syntax check:

```bash
python -m compileall app.py
```

The next useful additions are source-specific tests, a persistent provenance store, deduplication across campus/building records, official planning-data adapters and GeoJSON output.

## Licence

Code is released under the MIT Licence. Third-party source data remains subject to the rights and terms of its publisher.

## Disclaimer

This repository is for research, documentation and early-stage infrastructure analysis. It does not provide engineering, planning, legal, investment or grid-connection advice.
