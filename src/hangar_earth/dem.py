"""Elevation from the Copernicus DEM GLO-30 (30 m), read straight from its public
cloud-optimised GeoTIFFs: only the part of each 1°x1° tile the area needs is
downloaded."""

from __future__ import annotations

import math
import os
from collections.abc import Callable

import numpy as np

from .geo import Area, bilinear

# Faster remote reads: no directory listings, only .tif requests.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")

import rasterio  # noqa: E402  (after the GDAL settings above)
from rasterio.windows import from_bounds  # noqa: E402

# GDAL path of a tile; tests point it at local files
TILE_PATH = "/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
SOURCE = "Copernicus DEM GLO-30"
ATTRIBUTION = ("Copernicus DEM GLO-30: © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, "
               "provided under COPERNICUS by the European Union and ESA; all rights reserved")


def tile_name(lat_floor: int, lon_floor: int) -> str:
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat_floor):02d}_00_{ew}{abs(lon_floor):03d}_00_DEM"


def tiles_for(bounds: tuple[float, float, float, float]) -> list[tuple[int, int]]:
    west, south, east, north = bounds
    return [(la, lo) for la in range(math.floor(south), math.floor(north) + 1)
            for lo in range(math.floor(west), math.floor(east) + 1)]


def elevation(area: Area, n: int, progress: Callable[[str], None] = print) -> np.ndarray:
    """Heights in metres above sea level on the area's n x n grid (row 0 = north).

    Tiles that do not exist are open sea and stay at 0 m."""
    lat, lon = area.grid(n)
    out = np.zeros((n, n))
    covered = np.zeros((n, n), dtype=bool)
    for la, lo in tiles_for(area.bounds(pad_m=60)):
        name = tile_name(la, lo)
        inside = (lat >= la) & (lat <= la + 1) & (lon >= lo) & (lon <= lo + 1)
        if not inside.any():
            continue
        try:
            ds = rasterio.open(TILE_PATH.format(name=name))
        except rasterio.errors.RasterioIOError:
            progress(f"  {name}: no tile (open sea), using 0 m")
            continue
        with ds:
            west, south, east, north = area.bounds(pad_m=90)
            win = from_bounds(max(west, lo), max(south, la), min(east, lo + 1), min(north, la + 1), ds.transform)
            win = win.round_offsets().round_lengths()
            data = ds.read(1, window=win, boundless=True, fill_value=0).astype(np.float64)
            transform = ds.window_transform(win)
        progress(f"  {name}: {data.shape[1]}x{data.shape[0]} samples")
        inv = ~transform
        x, y = lon[inside], lat[inside]
        cols, rows = inv.a * x + inv.b * y + inv.c, inv.d * x + inv.e * y + inv.f
        out[inside] = bilinear(data, rows - 0.5, cols - 0.5)  # pixel centres
        covered |= inside
    if not covered.any():
        progress("  no land elevation here: the world is flat sea level")
    return out
