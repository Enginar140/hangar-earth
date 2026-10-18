"""Ground texture from EOX's Sentinel-2 cloudless mosaic (2016, CC BY 4.0).

Tiles are fetched in parallel, cached under ~/.cache/hangar-earth, stitched and
resampled onto the world's local grid."""

from __future__ import annotations

import math
import os
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from .geo import EARTH_RADIUS, Area, bilinear, mercator_tile

URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg"
SOURCE = "Sentinel-2 cloudless 2016 by EOX"
ATTRIBUTION = ("Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH "
               "(Contains modified Copernicus Sentinel data 2016), licensed CC BY 4.0")
MAX_ZOOM = 15  # the data is 10 m; deeper tiles are only upscaled
TILE = 256


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "hangar-earth" / "eox-s2cloudless-2016"


def zoom_for(area: Area, pixels: int) -> int:
    """Smallest zoom whose tiles are at least as sharp as the texture needs."""
    want = area.size / pixels  # metres per texture pixel
    for z in range(8, MAX_ZOOM + 1):
        tile_res = 2 * math.pi * EARTH_RADIUS * area.coslat / (TILE * 2 ** z)
        if tile_res <= want * 1.5:
            return z
    return MAX_ZOOM


def _fetch(z: int, x: int, y: int) -> Image.Image:
    path = cache_dir() / str(z) / str(x) / f"{y}.jpg"
    if not path.exists():
        req = urllib.request.Request(URL.format(z=z, x=x, y=y), headers={"User-Agent": "hangar-earth"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return Image.open(path).convert("RGB")


def texture(area: Area, pixels: int, progress: Callable[[str], None] = print) -> Image.Image:
    """A pixels x pixels RGB image covering the area, north up."""
    z = zoom_for(area, pixels)
    west, south, east, north = area.bounds(pad_m=50)
    x0, y0 = (int(v) for v in mercator_tile(north, west, z))
    x1, y1 = (int(v) for v in mercator_tile(south, east, z))
    jobs = [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    progress(f"  {len(jobs)} imagery tiles at zoom {z}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        tiles = list(pool.map(lambda j: _fetch(*j), jobs))
    mosaic = Image.new("RGB", ((x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE))
    for (_, x, y), tile in zip(jobs, tiles):
        mosaic.paste(tile, ((x - x0) * TILE, (y - y0) * TILE))
    lat, lon = area.grid(pixels)
    tx, ty = mercator_tile(lat, lon, z)
    img = bilinear(np.asarray(mosaic, dtype=np.float32), (ty - y0) * TILE - 0.5, (tx - x0) * TILE - 0.5)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
