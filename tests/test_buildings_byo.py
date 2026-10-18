"""Buildings (OSM) and your own data (DEM / orthophoto), offline."""

import json

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_points

from hangar_earth import byo, dem, imagery, osm
from hangar_earth.cli import main
from hangar_earth.geo import Area
from hangar_earth.mesh import signed_area, triangulate, write_obj
from test_earth import make_tile

AREA = Area(39.92, 32.854, 1000)


def test_heights_from_tags():
    assert osm.height_of({"height": "24"}) == 24
    assert osm.height_of({"height": "24 m"}) == 24
    assert osm.height_of({"building:height": "100'"}) == pytest.approx(30.48)
    assert osm.height_of({"building:levels": "5"}) == 15
    assert osm.height_of({"building:levels": "4", "roof:levels": "1"}) == 13.5
    assert osm.height_of({"building": "garage"}) == 3
    assert osm.height_of({"building": "yes"}) == osm.FALLBACK_HEIGHT
    assert osm.height_of({"height": "tall"}) == osm.FALLBACK_HEIGHT


def ring_around(lat, lon, d=0.0001):
    return [{"lat": lat - d, "lon": lon - d}, {"lat": lat - d, "lon": lon + d},
            {"lat": lat + d, "lon": lon + d}, {"lat": lat + d, "lon": lon - d}, {"lat": lat - d, "lon": lon - d}]


def overpass_fixture():
    return {"elements": [
        {"type": "way", "id": 1, "tags": {"building": "apartments", "building:levels": "6"},
         "geometry": ring_around(39.92, 32.854)},
        {"type": "relation", "id": 2, "tags": {"building": "yes", "height": "30"},
         "members": [{"role": "outer", "geometry": ring_around(39.921, 32.855)},
                     {"role": "inner", "geometry": ring_around(39.921, 32.855, 0.00003)}]},
        {"type": "way", "id": 3, "tags": {"building": "roof"}, "geometry": ring_around(39.919, 32.853)},
        {"type": "way", "id": 4, "tags": {"building": "yes", "min_height": "5"},
         "geometry": ring_around(39.919, 32.853)},
        {"type": "way", "id": 5, "tags": {"building": "yes"}, "geometry": ring_around(39.95, 32.854)},  # outside
    ]}


def test_parse_keeps_real_buildings_in_the_area():
    found = osm.parse(overpass_fixture(), AREA)
    assert sorted(b.osm_id for b in found) == [1, 2]
    by_id = {b.osm_id: b for b in found}
    assert by_id[1].height == 18 and by_id[2].height == 30 and len(by_id[1].outline) == 4


@pytest.mark.parametrize("ring", [
    [(0, 0), (10, 0), (10, 10), (0, 10)],  # square
    [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)],  # L shape
    [(0, 0), (12, 0), (12, 10), (8, 10), (8, 3), (4, 3), (4, 10), (0, 10)],  # U shape
])
def test_triangulation_covers_concave_outlines(ring):
    tris = triangulate(ring)
    assert len(tris) == len(ring) - 2
    covered = sum(abs(signed_area([ring[a], ring[b], ring[c]])) for a, b, c in tris)
    assert covered == pytest.approx(abs(signed_area(ring)))


def test_obj_has_outward_walls_and_roofs(tmp_path):
    b = osm.Building([(0, 0), (0, 10), (10, 10), (10, 0)], 12.0, "yes", 7)  # clockwise on purpose
    tris = write_obj([b], lambda x, y: 5.0, tmp_path / "b.obj")
    text = (tmp_path / "b.obj").read_text()
    assert tris == 4 * 2 + 2
    zs = sorted({float(line.split()[3]) for line in text.splitlines() if line.startswith("v ")})
    assert zs == [4.5, 17.0]  # base sunk 0.5 m, roof at ground + height
    normals = [tuple(map(float, line.split()[1:])) for line in text.splitlines() if line.startswith("vn ")]
    assert (0.0, -1.0, 0.0) in normals and (1.0, 0.0, 0.0) in normals  # south and east walls face out
    assert "mtllib b.mtl" in text and (tmp_path / "b.mtl").exists()


def utm_dem(path, area, value_fn, res=1.0, half=300):
    """A small DEM in UTM zone 36N around the area's centre."""
    x0, y0 = warp_points("EPSG:4326", "EPSG:32636", [area.lon], [area.lat])
    n = int(2 * half / res)
    xs = x0[0] - half + (np.arange(n) + 0.5) * res
    ys = y0[0] + half - (np.arange(n) + 0.5) * res
    gx, gy = np.meshgrid(xs - x0[0], ys - y0[0])
    with rasterio.open(path, "w", driver="GTiff", width=n, height=n, count=1, dtype="float32", crs="EPSG:32636",
                       transform=from_origin(x0[0] - half, y0[0] + half, res, res), nodata=-9999) as ds:
        ds.write(value_fn(gx, gy).astype("float32"), 1)


def test_own_dem_in_utm_lands_in_the_right_place(tmp_path):
    utm_dem(tmp_path / "dem.tif", AREA, lambda e, n: 900 + e * 0.1)  # rises 0.1 m per metre east
    s = byo.sample(tmp_path / "dem.tif", AREA, 101, [1])
    assert 0.25 < s.covered.mean() < 0.45  # 600 m of the 1000 m area, squared
    c = 50
    assert s.covered[c, c] and s.values[c, c] == pytest.approx(900, abs=0.5)
    east = c + 20  # 200 m east
    assert s.values[c, east] == pytest.approx(920, abs=1.0)
    assert not s.covered[0, 0]  # the corner is outside the file
    assert byo.pixel_size_m(tmp_path / "dem.tif", AREA) == pytest.approx(1.0)
    assert byo.resolution_for(1000, 1.0) == 1025 and byo.resolution_for(1000, 30) == 257
    assert byo.texture_for(1000, 0.25) == 4096 and byo.texture_for(1000, 0.05) == 8192


def test_own_orthophoto_in_web_mercator(tmp_path):
    x0, y0 = warp_points("EPSG:4326", "EPSG:3857", [AREA.lon], [AREA.lat])
    n = 200
    rgb = np.zeros((3, n, n), np.uint8)
    rgb[0] = 200  # red everywhere, green on the east half
    rgb[1, :, n // 2:] = 150
    with rasterio.open(tmp_path / "ortho.tif", "w", driver="GTiff", width=n, height=n, count=3, dtype="uint8",
                       crs="EPSG:3857", transform=from_origin(x0[0] - 400, y0[0] + 400, 4, 4)) as ds:
        ds.write(rgb)
    s = byo.sample(tmp_path / "ortho.tif", AREA, 64, [1, 2, 3])
    mid = 32
    assert s.covered[mid, mid] and s.values[mid, mid - 10][0] == pytest.approx(200, abs=2)
    assert s.values[mid, mid - 10][1] < 20 and s.values[mid, mid + 10][1] == pytest.approx(150, abs=2)


def test_create_with_buildings_and_own_dem(tmp_path, monkeypatch):
    make_tile(tmp_path / f"{dem.tile_name(39, 32)}.tif", 39, 32, lambda la, lo: 850 + 0 * la)
    monkeypatch.setattr(dem, "TILE_PATH", str(tmp_path / "{name}.tif"))
    monkeypatch.setattr(imagery, "_fetch", lambda z, x, y, url=imagery.URL: Image.new("RGB", (256, 256), (90, 110, 60)))
    monkeypatch.setattr(osm, "fetch_json", lambda q, progress=print: overpass_fixture())
    utm_dem(tmp_path / "dem.tif", AREA, lambda e, n: 880 + 0 * e, res=5)
    out = tmp_path / "w"
    assert main(["create", "--lat", "39.92", "--lon", "32.854", "--size", "1000", "--name", "kizilay_test",
                 "--out", str(out), "--dem", str(tmp_path / "dem.tif"), "--texture", "1024"]) == 0
    meta = json.loads((out / "hangar-earth.json").read_text())
    assert meta["buildings"]["count"] == 2 and (out / "buildings.obj").exists()
    assert meta["heights"]["n"] == 257  # 5 m DEM over 1 km
    assert meta["relief_m"] == pytest.approx(30, abs=1)  # 850 m global, 880 m where the own DEM is
    credits = (out / "ATTRIBUTION.txt").read_text()
    assert "OpenStreetMap" in credits and "dem.tif" in credits
    assert "<uri>buildings.obj</uri>" in (out / "kizilay_test.sdf").read_text()


def test_buildings_without_collision(tmp_path):
    from hangar_earth.world import Terrain, write

    t = Terrain(Area(39.92, 32.85, 500), np.full((17, 17), 900.0))
    b = osm.Building([(0, 0), (10, 0), (10, 10), (0, 10)], 12.0, "yes", 7)
    for mode, collides in (("mesh", True), ("none", False)):
        out = tmp_path / mode
        sdf = write(t, Image.new("RGB", (64, 64)), "w", out, "", "", [], [b], building_collision=mode).read_text()
        model = sdf[sdf.index('<model name="buildings">'):]
        assert ("<collision" in model) is collides and "<visual" in model
        assert json.loads((out / "hangar-earth.json").read_text())["buildings"]["collision"] is collides
