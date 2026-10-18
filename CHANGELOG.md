# Changelog

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
