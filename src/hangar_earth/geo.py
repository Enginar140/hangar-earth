"""The local frame of a world: a square area around a point, in metres east/north.

Gazebo worlds are flat ENU frames; over a few kilometres an equirectangular
mapping around the centre is accurate to well under a metre, which is far
finer than the 30 m elevation data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

EARTH_RADIUS = 6378137.0


@dataclass(frozen=True)
class Area:
    lat: float
    lon: float
    size: float  # edge length in metres

    def __post_init__(self) -> None:
        if not -85 < self.lat < 85:
            raise ValueError("latitude must be between -85 and 85")
        if not -180 <= self.lon <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if not 100 <= self.size <= 20000:
            raise ValueError("size must be between 100 m and 20 km")

    @property
    def half(self) -> float:
        return self.size / 2

    @property
    def coslat(self) -> float:
        return math.cos(math.radians(self.lat))

    def bounds(self, pad_m: float = 0.0) -> tuple[float, float, float, float]:
        """(west, south, east, north) in degrees."""
        h = self.half + pad_m
        dlat = math.degrees(h / EARTH_RADIUS)
        dlon = math.degrees(h / (EARTH_RADIUS * self.coslat))
        return self.lon - dlon, self.lat - dlat, self.lon + dlon, self.lat + dlat

    def grid(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Latitudes and longitudes of an n x n grid; row 0 is the north edge."""
        xs = np.linspace(-self.half, self.half, n)
        ys = np.linspace(self.half, -self.half, n)
        x, y = np.meshgrid(xs, ys)
        lat = self.lat + np.degrees(y / EARTH_RADIUS)
        lon = self.lon + np.degrees(x / (EARTH_RADIUS * self.coslat))
        return lat, lon

    def to_local(self, lat: float, lon: float) -> tuple[float, float]:
        """Metres east and north of the centre."""
        east = math.radians(lon - self.lon) * EARTH_RADIUS * self.coslat
        north = math.radians(lat - self.lat) * EARTH_RADIUS
        return east, north


def bilinear(img: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Sample img at fractional (row, col) positions, clamped to its edges."""
    r0 = np.clip(np.floor(rows).astype(int), 0, img.shape[0] - 2)
    c0 = np.clip(np.floor(cols).astype(int), 0, img.shape[1] - 2)
    dr = np.clip(rows - r0, 0, 1)
    dc = np.clip(cols - c0, 0, 1)
    if img.ndim == 3:
        dr, dc = dr[..., None], dc[..., None]
    return (img[r0, c0] * (1 - dr) * (1 - dc) + img[r0 + 1, c0] * dr * (1 - dc)
            + img[r0, c0 + 1] * (1 - dr) * dc + img[r0 + 1, c0 + 1] * dr * dc)


def mercator_tile(lat, lon, zoom: int):
    """Fractional Web Mercator tile coordinates (x, y) for lat/lon (scalars or arrays)."""
    n = 2 ** zoom
    x = (np.asarray(lon, dtype=float) + 180.0) / 360.0 * n
    y = (1.0 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2.0 * n
    return x, y
