from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

APP_NAME = "Data Centres GB API"
APP_VERSION = "0.1.0"
USER_AGENT = (
    "DataCentresGB/0.1 (+https://github.com/Ventusltd/data-centres-gb; "
    "public-infrastructure research)"
)
CACHE_TTL_SECONDS = 3600
SOURCE_URLS = {
    ("datacentermap", "london"): "https://www.datacentermap.com/united-kingdom/london/",
}

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "Open API for separately sourced and provenance-labelled public "
        "data-centre records in Great Britain."
    ),
)


class DataCentreRecord(BaseModel):
    name: str
    operator: str | None = None
    address: str | None = None
    postcode: str | None = None
    locality: str | None = None
    country: str = "United Kingdom"
    status: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    source: str
    source_url: str
    retrieved_at: str


class DataCentreResponse(BaseModel):
    source: str
    source_url: str
    region: str
    retrieved_at: str
    record_count: int = Field(ge=0)
    records: list[DataCentreRecord]
    warnings: list[str] = []


_cache: dict[tuple[str, str], tuple[float, DataCentreResponse]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def split_listing_text(text: str) -> tuple[str, str | None, str | None, str | None, str | None]:
    """Best-effort parsing of a public listing label.

    Data Center Map renders listing cards as compact text. The source does not
    expose a stable open schema, so the parser is intentionally conservative.
    The original source URL remains the authoritative reference.
    """
    text = clean_text(text) or ""
    postcode_match = re.search(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", text, re.I)
    postcode = postcode_match.group(1).upper() if postcode_match else None

    locality = None
    for candidate in (
        "London",
        "Slough",
        "Hemel Hempstead",
        "Reading",
        "Crawley",
        "Woking",
        "Watford",
        "Harlow",
        "Hayes",
        "West Drayton",
        "Enfield",
        "Redhill",
        "Bracknell",
        "Iver",
        "Chelmsford",
        "Bicester",
    ):
        if re.search(rf"\b{re.escape(candidate)}\b", text, re.I):
            locality = candidate
            break

    # The first phrase is normally the facility name. Exact operator/address
    # boundaries vary, so only populate fields when a separator is visible.
    parts = [clean_text(part) for part in re.split(r"\s{2,}|\s[|·]\s", text)]
    parts = [part for part in parts if part]
    name = parts[0] if parts else text
    operator = parts[1] if len(parts) > 1 else None
    address = parts[2] if len(parts) > 2 else None

    return name, operator, address, postcode, locality


def fetch_datacentermap_london() -> DataCentreResponse:
    source = "datacentermap"
    region = "london"
    source_url = SOURCE_URLS[(source, region)]
    retrieved_at = utc_now()

    try:
        response = requests.get(
            source_url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Source fetch failed: {exc}") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    records: list[DataCentreRecord] = []
    seen_urls: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        text = clean_text(anchor.get_text(" ", strip=True))
        if not text or len(text) < 4:
            continue

        absolute_url = urljoin(source_url, href)
        if absolute_url in seen_urls:
            continue

        # Facility pages on the directory are normally below a geographic path.
        # Exclude navigation, account, pricing and quote links.
        blocked_terms = (
            "/pricing",
            "/about",
            "/contact",
            "/login",
            "/sign-in",
            "request-quote",
            "javascript:",
            "mailto:",
        )
        if any(term in absolute_url.lower() for term in blocked_terms):
            continue
        if "datacentermap.com" not in absolute_url:
            continue
        if absolute_url.rstrip("/") == source_url.rstrip("/"):
            continue

        postcode_match = re.search(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", text, re.I)
        location_hint = re.search(
            r"\b(London|Slough|Hemel Hempstead|Reading|Crawley|Woking|Watford|"
            r"Harlow|Hayes|West Drayton|Enfield|Redhill|Bracknell|Iver|Chelmsford|Bicester)\b",
            text,
            re.I,
        )
        if not postcode_match and not location_hint:
            continue

        name, operator, address, postcode, locality = split_listing_text(text)
        if len(name) > 180:
            continue

        seen_urls.add(absolute_url)
        records.append(
            DataCentreRecord(
                name=name,
                operator=operator,
                address=address,
                postcode=postcode,
                locality=locality,
                source=source,
                source_url=absolute_url,
                retrieved_at=retrieved_at,
            )
        )

    records.sort(key=lambda item: (item.locality or "", item.name.lower()))
    warnings = [
        "Records are parsed from publicly visible HTML and are not independently verified.",
        "The source's London market may include facilities outside Greater London.",
        "Facility, campus and individual-building entries may overlap.",
    ]
    if not records:
        warnings.append("No facility records were recognised; the source HTML may have changed.")

    return DataCentreResponse(
        source=source,
        source_url=source_url,
        region=region,
        retrieved_at=retrieved_at,
        record_count=len(records),
        records=records,
        warnings=warnings,
    )


def get_data(source: str, region: str, refresh: bool) -> DataCentreResponse:
    key = (source, region)
    if key not in SOURCE_URLS:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported source or region",
                "supported": [
                    {"source": available_source, "region": available_region}
                    for available_source, available_region in SOURCE_URLS
                ],
            },
        )

    now = time.time()
    cached = _cache.get(key)
    if not refresh and cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    result = fetch_datacentermap_london()
    _cache[key] = (now, result)
    return result


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "status": "experimental",
        "documentation": "/docs",
        "endpoint": "/v1/data-centres",
        "available_sources": [
            {"source": source, "region": region, "url": url}
            for (source, region), url in SOURCE_URLS.items()
        ],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": utc_now()}


@app.get("/v1/data-centres", response_model=DataCentreResponse)
def data_centres(
    source: str = Query(default="datacentermap"),
    region: str = Query(default="london"),
    refresh: bool = Query(default=False),
) -> DataCentreResponse:
    return get_data(source.lower(), region.lower(), refresh)
