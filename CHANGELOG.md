# Changelog

## 0.3.0 (2026-10-18)

- `--building-collision {mesh,none}`: `none` keeps buildings visual only, so big cities do not slow
  the physics down. `hangar-earth.json` records it as `buildings.collision`.

## 0.2.0 (2026-10-18)

- **Buildings from OpenStreetMap** (on by default, `--no-buildings`): heights from `height`,
  `building:levels` or the building type; all buildings extruded into one OBJ mesh (walls and
  flat roofs, ear-clipped, outward normals) that renders fast and collides. Overpass queries
  retry with backoff on two servers and are cached.
- **Your own data**: `--dem FILE.tif` and `--imagery FILE.tif` in any coordinate system replace the
  global data where they cover the area; big files are read at the needed resolution; heightmap
  and texture sizes follow their pixel size (up to 4097 samples, 8192 px).
- **Any XYZ tile source you may use**: `--imagery-url`, `--imagery-zoom`, `--imagery-credit`.
  Example in the README with the Netherlands' open 8 cm aerial imagery.
- Verified in Gazebo Harmonic: Kızılay (1646 buildings) renders and a box lands on a 76 m roof;
  Delft with 15 cm open imagery.

## 0.1.0 (2026-10-18)

First release.

- `hangar-earth create --lat --lon --size --name`: a Gazebo world for any place, with
  Copernicus DEM GLO-30 terrain (only the needed window is read from the public COGs, open sea
  becomes 0 m, areas across tile borders work) and a Sentinel-2 cloudless 2016 texture
  (parallel, cached downloads), plus a terrain normal map.
- The world sits at its real coordinates (`<spherical_coordinates>`), with the origin at the
  area's lowest point, and loads the physics, IMU, NavSat and sensors systems ArduPilot needs.
- `hangar-earth.json` and `heights.u16` describe the terrain for tools; Hangar uses them to put
  vehicles on the ground. `ATTRIBUTION.txt` carries the data credits.
- `hangar-earth info FOLDER`.
- Verified in Gazebo Harmonic 8.15: terrain orientation matches the DEM, vehicles stand on the
  hills, ArduPilot SITL reports the real positions.
