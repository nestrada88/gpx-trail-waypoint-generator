# gpx-trail-waypoint-generator

A Python CLI tool for analyzing GPX hiking trails and generating navigation waypoints such as trail heads, trail ends, halfway points, elevation extrema, and cumulative distance markers.

## What the solution does

The script reads a GPX track file, validates it, analyzes the route, and produces a new GPX file enriched with generated waypoints. It is designed for hiking and trail planning workflows where you need clear milestone markers along a route.

### Generated waypoint types

The tool can generate the following waypoint categories:

- Trail Head: `TH`
- Trail End: `TE`
- Halfway Point: `HLF`
- Highest Point: `HGH`
- Lowest Point: `LWT`
- Distance markers: `KMxx` (for example, `KM01`, `KM02`, `KM05`, `KM10` depending on the step interval)

Distance marker names are based on the actual milestone distance that triggered the marker, so a 5 km step interval produces names such as `KM05`, `KM10`, `KM15`, and so on.

## Features

- Validates input GPX structure and basic coordinate values
- Computes elevation statistics including ascent, descent, minimum elevation, maximum elevation, and elevation range
- Supports distance calculations with `auto`, `geodesic`, or `haversine`
- Generates a new GPX 1.1 file with enriched metadata and preserved route/track geometry
- Offers a Docker-based wrapper for containerized execution

## Requirements

The script requires Python 3.9 or newer and the following packages:

- `gpxpy`
- `geopy`

Install them with:

```bash
pip install -r requirements.txt
```

## Usage

### Direct Python usage

Run the script with:

```bash
python gpx_trail_wpt.py <gpx_file> <trail_prefix> <step_size> [--distance-method auto|geodesic|haversine]
```

### Arguments

- `gpx_file`: Path to the input GPX file
- `trail_prefix`: Prefix for generated waypoints, using 3 to 6 uppercase letters such as `HIK` or `LCST`
- `step_size`: Distance interval in kilometers between cumulative markers
- `--distance-method`: Optional distance strategy for horizontal calculations
  - `auto` (default)
  - `geodesic`
  - `haversine`

### Examples

Generate markers every 1 km with prefix `HIK`:

```bash
python gpx_trail_wpt.py trail.gpx HIK 1
```

Generate markers every 5 km using the haversine formula:

```bash
python gpx_trail_wpt.py trail.gpx LCST 5 --distance-method haversine
```

### Output file

The script creates a new GPX file named using this pattern:

```text
<input_stem>_<step_size>_wpt.gpx
```

For example, running the tool on `trail.gpx` with a step size of `1` produces:

```text
trail_1_wpt.gpx
```

## Docker usage

A shell wrapper is included for container execution:

```bash
./run_gpx_trail_wpt.sh --file trail.gpx --prefix HIK --step 1
```

Optional flags:

- `--distance-method auto|geodesic|haversine`
- `--rebuild` to force rebuilding the Docker image

## Input requirements

The input GPX must contain a valid track structure:

- at least one `<trk>` element
- at least one `<trkseg>` element
- at least two track points with valid latitude and longitude values

If these conditions are not met, the script will stop with a validation error.

## What the output contains

The generated GPX file includes:

- the original route geometry and track information
- newly generated waypoint markers
- metadata such as bounds and descriptive labels

## Notes

- The script is intended for trail and hiking navigation workflows.
- Distance marker naming follows the actual milestone distance, so interval-based markers align with the requested step size.
- For very large GPX files, the script may reject them if they exceed the built-in safety limit for track points.

## Troubleshooting

- If you see a validation error, confirm the GPX file is well-formed and contains a valid track.
- If the script cannot find dependencies, reinstall them with `pip install -r requirements.txt`.
- If the output file is not created, check that the input path is correct and the script has write permissions for the target directory.
