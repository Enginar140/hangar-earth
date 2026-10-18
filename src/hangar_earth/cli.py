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
    from . import dem, imagery
    from .geo import Area
    from .world import Terrain, write

    started = time.time()
    area = Area(args.lat, args.lon, args.size)
    out = Path(args.out or args.name).expanduser().resolve()
    n = args.resolution or resolution_for(area.size)
    print(f"{args.name}: {area.size:g} m x {area.size:g} m around {area.lat:.6f}, {area.lon:.6f} -> {out}")
    print(f"[1/3] elevation ({dem.SOURCE}), {n}x{n} grid")
    terrain = Terrain(area, dem.elevation(area, n))
    print(f"      {terrain.zmin:.0f} m to {terrain.zmin + terrain.relief:.0f} m above sea level")
    print(f"[2/3] imagery ({imagery.SOURCE}), {args.texture}x{args.texture} px")
    satellite = imagery.texture(area, args.texture)
    print("[3/3] writing the world")
    sdf = write(terrain, satellite, args.name, out, dem.SOURCE, imagery.SOURCE, [dem.ATTRIBUTION, imagery.ATTRIBUTION])
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
    c.add_argument("--texture", type=int, default=2048, choices=(1024, 2048, 4096), help="texture size in pixels")
    c.add_argument("--resolution", type=int, choices=(257, 513, 1025, 2049), help="heightmap samples per edge")
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
