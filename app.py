from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

APP_NAME = "Data Centres GB API"
APP_VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
GENERATION = re.compile(r"^[0-9]{12}$")
EXPORT_SUFFIX = "-osm-data-centres.geojson"

SOURCE_POLICY = {
    "openstreetmap": {
        "status": "enabled-batch-only",
        "role": "sole facility source",
        "licence": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors",
        "request_handler_fetches": 0,
    },
    "openinframap": {
        "status": "visual-validation-only",
        "role": "OpenStreetMap renderer, not independent evidence",
        "request_handler_fetches": 0,
    },
    "datacentermap": {
        "status": "prohibited-from-ingestion",
        "role": "human-only market reference",
        "reason": "Current terms prohibit programmatic retrieval and external-database copying",
        "request_handler_fetches": 0,
    },
}

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Read-only API over deliberately landed OSM-derived candidate exports.",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def available_exports() -> list[tuple[str, Path]]:
    exports: list[tuple[str, Path]] = []
    for path in (ROOT / "exports").glob(f"*{EXPORT_SUFFIX}"):
        generation = path.name.removesuffix(EXPORT_SUFFIX)
        if GENERATION.fullmatch(generation) and path.is_file() and not path.is_symlink():
            exports.append((generation, path))
    return sorted(exports)


def load_export(generation: str | None) -> dict[str, Any]:
    if generation is not None and not GENERATION.fullmatch(generation):
        raise HTTPException(status_code=400, detail="generation must be a 12-digit timestamp")
    exports = available_exports()
    if generation is None:
        if not exports:
            raise HTTPException(
                status_code=404,
                detail="No OSM data-centre export is installed; this API never fetches a source on demand",
            )
        selected_generation, path = exports[-1]
    else:
        selected_generation = generation
        path = ROOT / "exports" / f"{generation}{EXPORT_SUFFIX}"
        if not path.is_file() or path.is_symlink():
            raise HTTPException(status_code=404, detail="Requested generation is not installed")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Installed export is unreadable") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "FeatureCollection"
        or payload.get("generation") != selected_generation
        or payload.get("licence") != "ODbL-1.0"
        or payload.get("attribution") != "© OpenStreetMap contributors"
        or not isinstance(payload.get("features"), list)
    ):
        raise HTTPException(status_code=500, detail="Installed export failed its data-law envelope")
    return payload


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "status": "candidate-read-only",
        "endpoint": "/v1/data-centres",
        "source_policy": "/v1/data-centres/sources",
        "installed_generations": [generation for generation, _path in available_exports()],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": utc_now()}


@app.get("/v1/data-centres/sources")
def sources() -> dict[str, Any]:
    return {"sources": SOURCE_POLICY, "network_requests_from_api": 0}


@app.get("/v1/data-centres")
def data_centres(
    generation: str | None = Query(default=None, description="12-digit immutable generation")
) -> dict[str, Any]:
    return load_export(generation)
