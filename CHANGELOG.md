# Changelog

## [Unreleased]

- The scan engine takes the optional SLM, Zernike, and power-meter panels and locks them itself. SteeringWidget takes only the engine.
- Map axes and the radius and step boxes say um, without a second SI prefix.

## [1.0.0] - 2026-09-28

- Tilt scan of coupled power on H, V, or both, with the maps stacked under the scan controls.
- Save the Zernike coefficient state, both SLM centers, the power array, and a PNG.
- Pin the engines used by the scan: slm v0.3.0, zernikes v1.1.0, powermeters v0.2.0, cameras v0.2.1.
