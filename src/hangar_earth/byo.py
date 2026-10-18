"""Your own data: a DEM or an orthophoto as a GeoTIFF, in any coordinate system.

Where your file covers the area it replaces the global data (Copernicus DEM,
Sentinel-2); elsewhere the global data stays. Large files are read at the
resolution the world needs, not in full."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform as warp_points
from rasterio.windows import Window

from .geo import EARTH_RADIUS, Area, bilinear


@dataclass
class Sampled:
    values: np.ndarray  # (n, n) or (n, n, bands)
    covered: np.ndarray  # (n, n) bool: the file has data here


def pixel_size_m(path: Path, area: Area) -> float:
    """The file's pixel size in metres at the area (geographic files are converted)."""
    with rasterio.open(path) as ds:
        dx, dy = abs(ds.transform.a), abs(ds.transform.e)
        if ds.crs and ds.crs.is_geographic:
            dx = math.radians(dx) * EARTH_RADIUS * area.coslat
            dy = math.radians(dy) * EARTH_RADIUS
        return float(min(dx, dy))


def sample(path: Path, area: Area, n: int, bands: list[int]) -> Sampled:
    """Values of the given bands on the area's n x n grid (row 0 = north)."""
    lat, lon = area.grid(n)
    with rasterio.open(path) as ds:
        if ds.crs is None:
            raise ValueError(f"{path} has no coordinate system; a GeoTIFF needs one")
        xs, ys = warp_points("EPSG:4326", ds.crs, lon.ravel().tolist(), lat.ravel().tolist())
        xs = np.asarray(xs).reshape(n, n)
        ys = np.asarray(ys).reshape(n, n)
        inv = ~ds.transform
        cols = inv.a * xs + inv.b * ys + inv.c
        rows = inv.d * xs + inv.e * ys + inv.f
        r0 = max(int(math.floor(rows.min())) - 1, 0)
        c0 = max(int(math.floor(cols.min())) - 1, 0)
        r1 = min(int(math.ceil(rows.max())) + 2, ds.height)
        c1 = min(int(math.ceil(cols.max())) + 2, ds.width)
        empty = Sampled(np.zeros((n, n, len(bands)) if len(bands) > 1 else (n, n)), np.zeros((n, n), bool))
        if r1 <= r0 or c1 <= c0:
            return empty  # the file does not reach this area
        h, w = r1 - r0, c1 - c0
        # never read more than about twice the grid's resolution: big orthophotos stay cheap
        scale = max(h / (2 * n), w / (2 * n), 1.0)
        out_h, out_w = max(int(h / scale), 2), max(int(w / scale), 2)
        data = ds.read(bands, window=Window(c0, r0, w, h), out_shape=(len(bands), out_h, out_w),
                       resampling=Resampling.bilinear, masked=True)
        fr = (rows - r0) * (out_h / h) - 0.5
        fc = (cols - c0) * (out_w / w) - 0.5
        inside = (rows >= 0) & (rows < ds.height) & (cols >= 0) & (cols < ds.width)
    mask = np.ma.getmaskarray(data).any(axis=0)
    valid = ~mask[np.clip(np.round(fr).astype(int), 0, out_h - 1), np.clip(np.round(fc).astype(int), 0, out_w - 1)]
    filled = np.ma.filled(data.astype(np.float64), 0.0)
    img = np.moveaxis(filled, 0, -1) if len(bands) > 1 else filled[0]
    values = bilinear(img, fr, fc)
    return Sampled(values, inside & valid)


def resolution_for(size_m: float, cell_m: float, cap: int = 2049) -> int:
    """Heightmap samples per edge (2^k + 1) for a target cell size."""
    for n in (257, 513, 1025, 2049, 4097):
        if size_m / (n - 1) <= max(cell_m, 0.25) or n >= cap:
            return n
    return cap


def texture_for(size_m: float, pixel_m: float, cap: int = 8192) -> int:
    for px in (1024, 2048, 4096, 8192):
        if size_m / px <= max(pixel_m, 0.05) or px >= cap:
            return px
    return cap
