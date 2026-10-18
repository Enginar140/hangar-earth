"""Building footprints and heights from OpenStreetMap, through the Overpass API.

One query per world, retried with backoff on the public servers, and cached
under ~/.cache/hangar-earth/osm."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from .imagery import cache_dir as imagery_cache
from .geo import Area

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
USER_AGENT = "hangar-earth (https://github.com/Enginar140/hangar-earth)"
SOURCE = "OpenStreetMap buildings"
ATTRIBUTION = ("Buildings © OpenStreetMap contributors, available under the Open Database License (ODbL): "
               "https://www.openstreetmap.org/copyright")

LEVEL_HEIGHT = 3.0
DEFAULT_HEIGHT = {  # metres, by building=* when no height or levels are tagged
    "house": 6, "detached": 6, "semidetached_house": 6, "terrace": 7, "residential": 9, "bungalow": 4,
    "apartments": 12, "dormitory": 12, "hotel": 15, "office": 15, "commercial": 10, "retail": 6,
    "industrial": 8, "warehouse": 8, "hangar": 10, "garage": 3, "garages": 3, "shed": 3, "hut": 3,
    "kiosk": 3, "carport": 3, "church": 14, "mosque": 12, "school": 10, "hospital": 15, "university": 15,
    "stadium": 20, "train_station": 10, "greenhouse": 4,
}
FALLBACK_HEIGHT = 7.0
SKIP = {"roof", "construction", "ruins", "no"}  # canopies with min_height, sites, non-buildings


@dataclass
class Building:
    outline: list[tuple[float, float]]  # local metres (east, north), closed ring without the repeated point
    height: float
    kind: str
    osm_id: int


def _metres(value: str) -> float | None:
    """'12', '12 m', '12.5m', "40'" -> metres."""
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(m|ft|')?\s*$", value)
    if not m:
        return None
    number = float(m.group(1))
    return number * 0.3048 if m.group(2) in ("ft", "'") else number


def height_of(tags: dict[str, str]) -> float:
    for key in ("height", "building:height"):
        if key in tags and (h := _metres(tags[key])) and h > 0:
            return min(h, 600.0)
    levels = _metres(tags.get("building:levels", "")) or 0
    roof = _metres(tags.get("roof:levels", "")) or 0
    if levels:
        return (levels + roof * 0.5) * LEVEL_HEIGHT
    return float(DEFAULT_HEIGHT.get(tags.get("building", ""), FALLBACK_HEIGHT))


def query(area: Area) -> str:
    west, south, east, north = area.bounds()
    bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    return (f'[out:json][timeout:120];(way["building"]({bbox});'
            f'relation["building"]["type"="multipolygon"]({bbox}););out geom;')


def _cache_file(q: str):
    return imagery_cache().parent / "osm" / (hashlib.sha256(q.encode()).hexdigest()[:24] + ".json")


def fetch_json(q: str, progress: Callable[[str], None] = print, attempts: int = 6) -> dict:
    cached = _cache_file(q)
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    body = urllib.parse.urlencode({"data": q}).encode()
    delay = 2.0
    last: Exception | None = None
    for attempt in range(attempts):
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode("utf-8"))
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(data), encoding="utf-8")
            return data
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            progress(f"  Overpass busy ({url.split('/')[2]}: {getattr(e, 'code', e)}), retrying in {delay:.0f} s")
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"OpenStreetMap (Overpass) did not answer: {last}")


def _ring(geometry: list[dict], area: Area) -> list[tuple[float, float]] | None:
    pts = [area.to_local(p["lat"], p["lon"]) for p in geometry if p]
    if len(pts) >= 4 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    return pts


def parse(data: dict, area: Area) -> list[Building]:
    out: list[Building] = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if tags.get("building") in SKIP or "min_height" in tags or "building:min_level" in tags:
            continue
        rings = []
        if el["type"] == "way":
            rings.append(el.get("geometry", []))
        elif el["type"] == "relation":
            rings += [m.get("geometry", []) for m in el.get("members", []) if m.get("role") == "outer"]
        for geometry in rings:
            ring = _ring(geometry, area)
            if not ring:
                continue
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
            if abs(cx) > area.half or abs(cy) > area.half:
                continue  # belongs to the next area over
            out.append(Building(ring, height_of(tags), tags.get("building", "yes"), int(el["id"])))
    return out


def buildings(area: Area, progress: Callable[[str], None] = print) -> list[Building]:
    found = parse(fetch_json(query(area), progress), area)
    progress(f"  {len(found)} buildings")
    return found
