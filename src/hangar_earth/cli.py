"""Command line: `hangar-earth create --lat 39.88 --lon 33.23 --size 3000 --name ankara_hills`."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__


def resolution_for(size_m: float) -> int:
    """Heightmap samples per edge; Gazebo wants 2^k + 1. ~6 m per sample, finer than the 30 m data."""
    for n in (257, 513, 1025, 2049):
        if size_m / (n - 1) <= 6:
            return n
    return 2049


def cmd_create(args) -> int:
    from . import byo, dem, imagery
    from .geo import Area
    from .world import Terrain, write

    started = time.time()
    area = Area(args.lat, args.lon, args.size)
    out = Path(args.out or args.name).expanduser().resolve()
    own_dem = Path(args.dem).expanduser() if args.dem else None
    own_img = Path(args.imagery).expanduser() if args.imagery else None
    for f in (own_dem, own_img):
        if f and not f.is_file():
            raise ValueError(f"{f} not found")
    if args.resolution:
        n = args.resolution
    elif own_dem:
        n = byo.resolution_for(area.size, byo.pixel_size_m(own_dem, area))
    else:
        n = resolution_for(area.size)
    if args.texture:
        pixels = args.texture
    elif own_img:
        pixels = byo.texture_for(area.size, byo.pixel_size_m(own_img, area))
    elif args.imagery_url:
        pixels = 4096
    else:
        pixels = 2048
    print(f"{args.name}: {area.size:g} m x {area.size:g} m around {area.lat:.6f}, {area.lon:.6f} -> {out}")

    print(f"[1/4] elevation ({dem.SOURCE}{' + ' + own_dem.name if own_dem else ''}), "
          f"{n}x{n} grid, {area.size / (n - 1):.2f} m per sample")
    heights = dem.elevation(area, n)
    dem_source = dem.SOURCE
    credits = [dem.ATTRIBUTION]
    if own_dem:
        s = byo.sample(own_dem, area, n, [1])
        heights[s.covered] = s.values[s.covered]
        share = s.covered.mean() * 100
        print(f"  {own_dem.name} covers {share:.0f}% of the area")
        if share == 0:
            print("  warning: your DEM does not overlap this area")
        dem_source += f" + {own_dem.name}"
        credits.append(f"Elevation partly from {own_dem.name} (provided by the user).")
    terrain = Terrain(area, heights)
    print(f"      {terrain.zmin:.0f} m to {terrain.zmin + terrain.relief:.0f} m above sea level")

    if args.imagery_url:
        img_source = "custom XYZ tiles"
        print(f"[2/4] imagery ({img_source}), {pixels}x{pixels} px, {area.size / pixels:.2f} m per pixel")
        satellite = imagery.texture(area, pixels, url=args.imagery_url, max_zoom=args.imagery_zoom)
        credits.append(args.imagery_credit or f"Imagery from {args.imagery_url.split('/')[2]} (credit not given).")
    else:
        img_source = imagery.SOURCE
        print(f"[2/4] imagery ({img_source}{' + ' + own_img.name if own_img else ''}), {pixels}x{pixels} px, "
              f"{area.size / pixels:.2f} m per pixel")
        satellite = imagery.texture(area, pixels)
        credits.append(imagery.ATTRIBUTION)
    if own_img:
        import numpy as np
        from PIL import Image

        s = byo.sample(own_img, area, pixels, [1, 2, 3])
        rgb = np.asarray(satellite).copy()
        rgb[s.covered] = np.clip(s.values[s.covered], 0, 255).astype(np.uint8)
        satellite = Image.fromarray(rgb)
        print(f"  {own_img.name} covers {s.covered.mean() * 100:.0f}% of the area")
        img_source += f" + {own_img.name}"
        credits.append(f"Imagery partly from {own_img.name} (provided by the user).")

    found = []
    if args.buildings:
        from . import osm

        print(f"[3/4] buildings ({osm.SOURCE})")
        try:
            found = osm.buildings(area)
            if found:
                credits.append(osm.ATTRIBUTION)
        except RuntimeError as e:
            print(f"  skipped: {e}")
    else:
        print("[3/4] buildings: skipped (--no-buildings)")
    print("[4/4] writing the world")
    sdf = write(terrain, satellite, args.name, out, dem_source, img_source, credits, found)
    print(f"done in {time.time() - started:.0f} s: {sdf}")
    print(f"  try it:  GZ_SIM_RESOURCE_PATH={out} gz sim {sdf}")
    return 0


def cmd_info(args) -> int:
    meta = json.loads((Path(args.world) / "hangar-earth.json").read_text(encoding="utf-8"))
    print(json.dumps(meta, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hangar-earth", description="Gazebo worlds from real places.")
    p.add_argument("--version", action="version", version=f"hangar-earth {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create", help="build a world for an area")
    c.add_argument("--lat", type=float, required=True, help="centre latitude, e.g. 39.88")
    c.add_argument("--lon", type=float, required=True, help="centre longitude, e.g. 33.23")
    c.add_argument("--size", type=float, default=3000, help="edge length in metres (default 3000)")
    c.add_argument("--name", required=True, help="world name: letters, digits, '_' and '-'")
    c.add_argument("--out", help="output folder (default: ./NAME)")
    c.add_argument("--texture", type=int, choices=(1024, 2048, 4096, 8192),
                   help="texture size in pixels (default: 2048, or matched to --imagery)")
    c.add_argument("--resolution", type=int, choices=(257, 513, 1025, 2049, 4097),
                   help="heightmap samples per edge (default: about 6 m, or matched to --dem)")
    c.add_argument("--dem", metavar="FILE.tif", help="your own elevation GeoTIFF (any CRS); fills what it covers")
    c.add_argument("--imagery", metavar="FILE.tif", help="your own orthophoto GeoTIFF, RGB (any CRS)")
    c.add_argument("--imagery-url", metavar="URL",
                   help="XYZ tiles you may use, e.g. https://example.com/{z}/{x}/{y}.jpg (replaces Sentinel-2)")
    c.add_argument("--imagery-zoom", type=int, default=19, help="highest zoom of --imagery-url (default 19)")
    c.add_argument("--imagery-credit", help="attribution text for --imagery-url, written to ATTRIBUTION.txt")
    c.add_argument("--no-buildings", dest="buildings", action="store_false",
                   help="leave out OpenStreetMap buildings")
    i = sub.add_parser("info", help="show a generated world's metadata")
    i.add_argument("world", help="the world's folder")
    args = p.parse_args(argv)
    try:
        return {"create": cmd_create, "info": cmd_info}[args.command](args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
