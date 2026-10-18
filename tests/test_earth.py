"""Offline tests: synthetic DEM tiles and imagery stand in for the network."""

import json
import math

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin

from hangar_earth import dem, imagery
from hangar_earth.cli import main, resolution_for
from hangar_earth.geo import EARTH_RADIUS, Area, mercator_tile
from hangar_earth.world import Terrain, heightmap_png, write


def test_area_bounds_and_local_frame():
    a = Area(39.88, 33.23, 3000)
    west, south, east, north = a.bounds()
    assert north - south == pytest.approx(math.degrees(3000 / EARTH_RADIUS))
    assert a.to_local(north, a.lon)[1] == pytest.approx(1500, abs=0.01)
    assert a.to_local(a.lat, east)[0] == pytest.approx(1500, abs=0.01)
    lat, lon = a.grid(5)
    assert lat[0, 0] > lat[-1, 0] and lon[0, -1] > lon[0, 0]  # row 0 north, column 0 west
    with pytest.raises(ValueError):
        Area(39, 33, 50)


def test_resolution_is_gazebo_friendly():
    for size in (500, 3000, 6000, 20000):
        n = resolution_for(size)
        assert (n - 1) & (n - 2) == 0  # 2^k + 1


def make_tile(path, lat_floor, lon_floor, fn):
    """A 1x1 degree GeoTIFF at 0.01 deg (coarse but enough) with heights fn(lat, lon)."""
    n = 101
    lats = lat_floor + 1 - (np.arange(n) + 0.5) / (n - 1)
    lons = lon_floor + (np.arange(n) + 0.5) / (n - 1)
    lo, la = np.meshgrid(lons, lats)
    with rasterio.open(path, "w", driver="GTiff", width=n, height=n, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(lon_floor, lat_floor + 1, 1 / (n - 1), 1 / (n - 1))) as ds:
        ds.write(fn(la, lo).astype("float32"), 1)


def test_elevation_samples_tiles_and_treats_missing_as_sea(tmp_path, monkeypatch):
    # heights grow to the north and the east: 1000 + 1000*(lat-39) + 500*(lon-33)
    make_tile(tmp_path / f"{dem.tile_name(39, 33)}.tif", 39, 33,
              lambda la, lo: 1000 + 1000 * (la - 39) + 500 * (lo - 33))
    monkeypatch.setattr(dem, "TILE_PATH", str(tmp_path / "{name}.tif"))
    h = dem.elevation(Area(39.5, 33.5, 5000), 65, progress=lambda *_: None)
    centre = h[32, 32]
    assert centre == pytest.approx(1000 + 500 + 250, abs=8)
    assert h[0, 32] > centre > h[-1, 32]  # north is higher
    assert h[32, -1] > centre > h[32, 0]  # east is higher

    # an area straddling into a tile that does not exist (sea) keeps 0 there
    h2 = dem.elevation(Area(39.995, 33.5, 3000), 33, progress=lambda *_: None)
    assert (h2[0] == 0).all() and (h2[-1] > 0).all()


def test_imagery_is_north_up(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def fake_fetch(z, x, y):  # red grows southwards across tiles, green eastwards
        tile = np.zeros((256, 256, 3), np.uint8)
        tile[..., 0] = (y * 37) % 256
        tile[..., 1] = (x * 37) % 256
        return Image.fromarray(tile)

    monkeypatch.setattr(imagery, "_fetch", fake_fetch)
    area = Area(39.88, 33.23, 3000)
    img = np.asarray(imagery.texture(area, 256, progress=lambda *_: None)).astype(int)
    z = imagery.zoom_for(area, 256)
    _, ytop = mercator_tile(area.bounds()[3], area.lon, z)
    assert img[0, 128, 0] == (int(ytop) * 37) % 256  # top row comes from the northern tiles


def test_write_world(tmp_path):
    a = Area(39.88, 33.23, 1000)
    n = 33
    heights = np.fromfunction(lambda r, c: 900 + c * 2.0, (n, n))  # rises to the east, 64 m of relief
    t = Terrain(a, heights)
    sdf = write(t, Image.new("RGB", (256, 256), (90, 120, 60)), "test_world", tmp_path / "w", "DEM", "IMG", ["A", "B"])
    text = sdf.read_text()
    assert '<world name="test_world">' in text and "<latitude_deg>39.88000000</latitude_deg>" in text
    assert "<elevation>900.00</elevation>" in text and "<size>1000 1000 64.00</size>" in text
    assert "gz-sim-imu-system" in text  # ArduPilot vehicles need it
    png = np.asarray(Image.open(tmp_path / "w" / "terrain.png"))
    assert png.dtype == np.uint16 and png[0, 0] == 0 and png[0, -1] == 65535
    meta = json.loads((tmp_path / "w" / "hangar-earth.json").read_text())
    raw = np.frombuffer((tmp_path / "w" / "heights.u16").read_bytes(), "<u2").reshape(n, n)
    assert raw[5, -1] == 640 and meta["heights"]["n"] == n  # decimetres
    assert t.height_at(500, 0) == pytest.approx(64) and t.height_at(-500, 0) == pytest.approx(0)
    assert "A" in (tmp_path / "w" / "ATTRIBUTION.txt").read_text()
    assert heightmap_png(t).size == (n, n)
    with pytest.raises(ValueError):
        write(t, Image.new("RGB", (8, 8)), "bad name!", tmp_path / "x", "", "", [])


def test_cli_rejects_bad_input(capsys):
    assert main(["create", "--lat", "95", "--lon", "33", "--name", "x"]) == 2
    assert "latitude" in capsys.readouterr().err
