from __future__ import annotations
import argparse
import copy
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

import gpxpy
import gpxpy.gpx
from geopy.distance import geodesic

EARTH_RADIUS_M = 6371000
AUTO_METHOD_THRESHOLD = 50000

def validate_inputs(gpx, gpx_file: str, trail_prefix: str, step_size: float) -> None:
    """
    Validate command-line inputs for the GPX trail waypoint generator.

    This function performs three layers of validation:

    1. CLI Argument Validation
       - Ensures trail prefix format is correct
       - Ensures step size is within acceptable bounds

    2. File Validation
       - Confirms file existence and readability
       - Ensures file is a GPX file
       - Ensures file is not empty

    3. GPX Structural Validation
       - Ensures GPX can be parsed
       - Ensures required track structure exists
       - Ensures track contains valid points

    Parameters
    ----------
    gpx_file : str
        Path to the GPX file.

    trail_prefix : str
        Prefix used for waypoint names.

    step_size : float
        Distance interval (in kilometers) between cumulative markers.

    Raises
    ------
    FileNotFoundError
        If the GPX file does not exist.

    PermissionError
        If the file cannot be read.

    ValueError
        If any input parameter or GPX structure is invalid.
    """

    # ------------------------------------------------------------------
    # 1. CLI ARGUMENT VALIDATION
    # ------------------------------------------------------------------

    # Validate trail prefix format
    if not isinstance(trail_prefix, str):
        raise ValueError("Trail prefix must be a string.")

    if not re.fullmatch(r"[A-Z]{3,6}", trail_prefix):
        raise ValueError(
            "Trail prefix must contain 3–6 uppercase letters (example: HIK, LCST)."
        )

    # Validate step size
    if not isinstance(step_size, (int, float)):
        raise ValueError("Step size must be a numeric value.")

    if step_size <= 0:
        raise ValueError("Step size must be greater than zero.")

    if step_size > 100:
        raise ValueError("Step size is unrealistically large (>100 km).")

    # ------------------------------------------------------------------
    # 2. FILE VALIDATION
    # ------------------------------------------------------------------

    # File existence
    if not os.path.exists(gpx_file):
        raise FileNotFoundError(f"GPX file '{gpx_file}' does not exist.")

    # Ensure it is a file
    if not os.path.isfile(gpx_file):
        raise ValueError(f"'{gpx_file}' is not a valid file.")

    # Check file extension
    if not gpx_file.lower().endswith(".gpx"):
        raise ValueError("Input file must have a '.gpx' extension.")

    # Check readability
    if not os.access(gpx_file, os.R_OK):
        raise PermissionError(f"GPX file '{gpx_file}' is not readable.")

    # Check file size
    if os.path.getsize(gpx_file) == 0:
        raise ValueError("GPX file is empty.")

    # ------------------------------------------------------------------
    # 3. GPX STRUCTURAL VALIDATION
    # -----------------------------------------------------------------
    if not gpx.tracks:
        raise ValueError("GPX file contains no <trk> elements.")

    track = gpx.tracks[0]

    if not track.segments:
        raise ValueError("GPX track contains no <trkseg> elements.")

    segment = track.segments[0]

    if not segment.points:
        raise ValueError("GPX segment contains no <trkpt> elements.")

    if len(segment.points) < 2:
        raise ValueError("GPX track must contain at least two points.")

    # ------------------------------------------------------------------
    # 4. BASIC GEOSPATIAL SANITY CHECKS
    # ------------------------------------------------------------------

    for idx, point in enumerate(segment.points):

        if point.latitude is None or point.longitude is None:
            raise ValueError(f"Track point {idx} has missing coordinates.")

        if not (-90 <= point.latitude <= 90):
            raise ValueError(f"Invalid latitude at point {idx}: {point.latitude}")

        if not (-180 <= point.longitude <= 180):
            raise ValueError(f"Invalid longitude at point {idx}: {point.longitude}")

        if point.elevation is not None:
            if not (-1000 <= point.elevation <= 9000):
                raise ValueError(
                    f"Unrealistic elevation at point {idx}: {point.elevation}"
                )

def parse_gpx_file(gpx, strict=True, max_points=200000):
    """
    Parse a GPX file and extract track points.

    Parameters
    ----------
    gpx_file : str
        Path to the GPX file.

    strict : bool
        If True, perform strict validation checks.

    max_points : int
        Maximum allowed track points to prevent memory exhaustion.

    Returns
    -------
    dict
        Dictionary containing:
            - points: list of GPXTrackPoint
            - tracks: number of tracks
            - segments: number of segments
            - total_points: number of points

    Raises
    ------
    ValueError
        If the GPX structure is invalid.
    """
    if not gpx.tracks:
        raise ValueError("GPX file contains no <trk> elements.")

    all_points = []
    track_count = len(gpx.tracks)
    segment_count = 0

    for track in gpx.tracks:
        if not track.segments:
            if strict:
                raise ValueError("Track contains no <trkseg> elements.")
            continue

        for segment in track.segments:
            segment_count += 1

            if not segment.points:
                if strict:
                    raise ValueError("Track segment contains no <trkpt> elements.")
                continue

            all_points.extend(segment.points)

    if not all_points:
        raise ValueError("No valid track points found in GPX file.")

    if len(all_points) < 2:
        raise ValueError("GPX track must contain at least two points.")

    if len(all_points) > max_points:
        raise ValueError(
            f"GPX file contains too many points ({len(all_points)}). "
            f"Maximum allowed is {max_points}."
        )

    # Optional coordinate validation
    if strict:
        for i, p in enumerate(all_points):
            if p.latitude is None or p.longitude is None:
                raise ValueError(f"Missing coordinates at point {i}")

            if not (-90 <= p.latitude <= 90):
                raise ValueError(f"Invalid latitude at point {i}: {p.latitude}")

            if not (-180 <= p.longitude <= 180):
                raise ValueError(f"Invalid longitude at point {i}: {p.longitude}")

    return {
        "points": all_points,
        "tracks": track_count,
        "segments": segment_count,
        "total_points": len(all_points),
    }

def compute_elevation_statistics(trackpoints):
    """
    Compute core elevation statistics from a sequence of GPX trackpoints.

    Metrics computed:
        - total_ascent
        - total_descent
        - max_elevation
        - min_elevation
        - elevation_range

    Parameters
    ----------
    trackpoints : Iterable
        Sequence of GPX trackpoints containing an 'elevation' attribute.

    Returns
    -------
    dict
        {
            "total_ascent": float,
            "total_descent": float,
            "max_elevation": float,
            "min_elevation": float,
            "elevation_range": float
        }
    """

    total_ascent = 0.0
    total_descent = 0.0
    max_elevation = None
    min_elevation = None
    prev_elevation = None

    for point in trackpoints:
        ele = getattr(point, "elevation", None)

        # Skip points without elevation
        if ele is None:
            continue

        if max_elevation is None or ele > max_elevation:
            max_elevation = ele

        if min_elevation is None or ele < min_elevation:
            min_elevation = ele

        if prev_elevation is not None:
            delta = ele - prev_elevation

            if delta > 0:
                total_ascent += delta
            elif delta < 0:
                total_descent += abs(delta)

        prev_elevation = ele

    if max_elevation is None or min_elevation is None:
        raise ValueError("Elevation statistics cannot be computed: no elevation data found.")

    elevation_range = max_elevation - min_elevation

    return {
        "total_ascent": round(total_ascent, 2),
        "total_descent": round(total_descent, 2),
        "max_elevation": round(max_elevation, 2),
        "min_elevation": round(min_elevation, 2),
        "elevation_range": round(elevation_range, 2),
    }
    
def print_elevation_statistics(stats):
    """
    Print elevation statistics in a structured CLI format.

    Parameters
    ----------
    stats : dict
        Output dictionary returned by compute_elevation_statistics().
    """

    print("\nElevation Statistics")
    print("--------------------")
    print(f"Total Ascent:     {stats['total_ascent']:.2f} m")
    print(f"Total Descent:    {stats['total_descent']:.2f} m")
    print(f"Max Elevation:    {stats['max_elevation']:.2f} m")
    print(f"Min Elevation:    {stats['min_elevation']:.2f} m")
    print(f"Elevation Range:  {stats['elevation_range']:.2f} m")

def calculate_3d_distance(point1, point2, distance_method="auto", dataset_size=None):
    """
    Compute the 3D distance between two GPX track points.

    Parameters
    ----------
    point1 : GPXTrackPoint
    point2 : GPXTrackPoint
    distance_method : str
        Horizontal distance method:
            - 'geodesic'
            - 'haversine'
            - 'auto'
    dataset_size : int, optional
        Total number of track points used to determine algorithm
        automatically when distance_method='auto'.

    Returns
    -------
    float
        Distance in meters.
    """

    # ------------------------------------------------------------------
    # Coordinate validation
    # ------------------------------------------------------------------

    if point1.latitude is None or point1.longitude is None:
        raise ValueError("Point1 has invalid coordinates")

    if point2.latitude is None or point2.longitude is None:
        raise ValueError("Point2 has invalid coordinates")

    lat1, lon1 = point1.latitude, point1.longitude
    lat2, lon2 = point2.latitude, point2.longitude

    # ------------------------------------------------------------------
    # Determine distance method
    # ------------------------------------------------------------------

    method = distance_method

    if distance_method == "auto":

        if dataset_size and dataset_size > AUTO_METHOD_THRESHOLD:
            method = "haversine"
        else:
            method = "geodesic"

    # ------------------------------------------------------------------
    # Horizontal distance calculation
    # ------------------------------------------------------------------

    if method == "geodesic":

        horizontal_distance = geodesic((lat1, lon1), (lat2, lon2)).meters

    elif method == "haversine":

        lat1_r, lon1_r, lat2_r, lon2_r = map(
            math.radians, (lat1, lon1, lat2, lon2)
        )

        dlat = lat2_r - lat1_r
        dlon = lon2_r - lon1_r

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
        )

        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        horizontal_distance = EARTH_RADIUS_M * c

    else:

        raise ValueError(
            "Invalid distance method. Allowed values: "
            "'auto', 'geodesic', 'haversine'."
        )

    # ------------------------------------------------------------------
    # Elevation difference
    # ------------------------------------------------------------------

    if point1.elevation is not None and point2.elevation is not None:

        elevation_diff = point2.elevation - point1.elevation

    else:

        elevation_diff = 0.0

    # ------------------------------------------------------------------
    # 3D distance computation
    # ------------------------------------------------------------------

    return math.sqrt(horizontal_distance**2 + elevation_diff**2)

def generate_waypoints(points, prefix, step_size, distance_method="auto"):
    """
    Generate trail waypoints including:

    - Trail Head
    - Trail End
    - Halfway Point
    - Exact interpolated KM markers
    - Highest Point
    - Lowest Point

    Performance improvements added:

    1. Segment distance caching
    2. Cumulative distance array

    These optimizations eliminate redundant distance calculations while
    preserving all original behavior and waypoint placement logic.
    """

    waypoints = []

    if not points or len(points) < 2:
        return waypoints

    # -----------------------------------------------------
    # Helper: interpolate position along a segment
    # -----------------------------------------------------

    def interpolate_point(p1, p2, fraction):
        lat = p1.latitude + fraction * (p2.latitude - p1.latitude)
        lon = p1.longitude + fraction * (p2.longitude - p1.longitude)

        ele1 = p1.elevation or 0
        ele2 = p2.elevation or 0
        ele = ele1 + fraction * (ele2 - ele1)

        return lat, lon, ele

    # -----------------------------------------------------
    # Initialize start waypoint
    # -----------------------------------------------------

    start = points[0]

    waypoints.append(
        create_waypoint(
            start.latitude,
            start.longitude,
            start.elevation,
            f"{prefix}_TH",
            "Trail Head"
        )
    )

    # -----------------------------------------------------
    # Track highest and lowest points
    # -----------------------------------------------------

    highest_point = start
    lowest_point = start

    # -----------------------------------------------------
    # PRECOMPUTE SEGMENT DISTANCES (distance caching)
    # -----------------------------------------------------

    segment_distances = []
    dataset_size = len(points)

    for i in range(1, dataset_size):
        d = calculate_3d_distance(
            points[i - 1],
            points[i],
            distance_method,
            dataset_size=dataset_size
        )
        segment_distances.append(d)

    # -----------------------------------------------------
    # BUILD CUMULATIVE DISTANCE ARRAY
    # -----------------------------------------------------

    cumulative_distances = [0.0]

    for d in segment_distances:
        cumulative_distances.append(cumulative_distances[-1] + d)

    total_distance = cumulative_distances[-1]
    halfway_distance = total_distance / 2

    # -----------------------------------------------------
    # Distance tracking
    # -----------------------------------------------------

    cumulative_distance = 0.0
    step_meters = step_size * 1000

    next_marker_distance = step_meters
    km_index = 1

    halfway_added = False

    # -----------------------------------------------------
    # Main segment loop
    # -----------------------------------------------------

    for i in range(1, dataset_size):

        p1 = points[i - 1]
        p2 = points[i]

        segment_distance = segment_distances[i - 1]

        # Update highest and lowest elevation
        if (p2.elevation or 0) > (highest_point.elevation or 0):
            highest_point = p2

        if (p2.elevation or 0) < (lowest_point.elevation or 0):
            lowest_point = p2

        # -------------------------------------------------
        # KM marker interpolation
        # -------------------------------------------------

        while cumulative_distance + segment_distance >= next_marker_distance:

            distance_into_segment = next_marker_distance - cumulative_distance

            if segment_distance == 0:
                break

            fraction = distance_into_segment / segment_distance

            lat, lon, ele = interpolate_point(p1, p2, fraction)

            waypoints.append(
                create_waypoint(
                    lat,
                    lon,
                    ele,
                    f"{prefix}_KM{km_index:02d}",
                    f"{km_index} km Marker"
                )
            )

            km_index += 1
            next_marker_distance = km_index * step_meters

        # -------------------------------------------------
        # Halfway marker interpolation
        # -------------------------------------------------

        if (
            not halfway_added
            and cumulative_distance + segment_distance >= halfway_distance
        ):

            distance_into_segment = halfway_distance - cumulative_distance

            if segment_distance > 0:
                fraction = distance_into_segment / segment_distance

                lat, lon, ele = interpolate_point(p1, p2, fraction)

                waypoints.append(
                    create_waypoint(
                        lat,
                        lon,
                        ele,
                        f"{prefix}_HLF",
                        "Halfway Point"
                    )
                )

                halfway_added = True

        cumulative_distance += segment_distance

    # -----------------------------------------------------
    # Trail End waypoint
    # -----------------------------------------------------

    end = points[-1]

    waypoints.append(
        create_waypoint(
            end.latitude,
            end.longitude,
            end.elevation,
            f"{prefix}_TE",
            "Trail End"
        )
    )

    # -----------------------------------------------------
    # Highest elevation waypoint
    # -----------------------------------------------------

    waypoints.append(
        create_waypoint(
            highest_point.latitude,
            highest_point.longitude,
            highest_point.elevation,
            f"{prefix}_HGH",
            "Highest Point"
        )
    )

    # -----------------------------------------------------
    # Lowest elevation waypoint
    # -----------------------------------------------------

    waypoints.append(
        create_waypoint(
            lowest_point.latitude,
            lowest_point.longitude,
            lowest_point.elevation,
            f"{prefix}_LWT",
            "Lowest Point"
        )
    )

    return waypoints

def create_waypoint(*args):
    """
    Create a GPX waypoint.

    Supported call patterns:

    1. create_waypoint(point, name, description)
       where `point` is a GPXTrackPoint

    2. create_waypoint(lat, lon, ele, name, description)

    This preserves backward compatibility while supporting
    interpolated coordinate creation.
    """

    # --------------------------------------------------
    # Pattern 1: existing implementation
    # --------------------------------------------------

    if len(args) == 3:

        point, name, description = args

        waypoint = gpxpy.gpx.GPXWaypoint(
            latitude=point.latitude,
            longitude=point.longitude,
            elevation=point.elevation,
            name=name,
            description=description,
            time=point.time
        )

        return waypoint

    # --------------------------------------------------
    # Pattern 2: interpolated coordinates
    # --------------------------------------------------

    elif len(args) == 5:

        lat, lon, ele, name, description = args

        waypoint = gpxpy.gpx.GPXWaypoint(
            latitude=lat,
            longitude=lon,
            elevation=ele,
            name=name,
            description=description
        )

        return waypoint

    else:
        raise TypeError(
            "create_waypoint() expected either "
            "(point, name, description) or "
            "(lat, lon, ele, name, description)"
        )

def save_gpx_file(
    original_gpx,
    waypoints,
    output_file: str | Path,
    *,
    creator: str = "Trail One GPX Trail Waypoint Generator",
    metadata_name: str = "Trail One - Waypoint-Enriched GPX",
    metadata_desc: str = (
        "GPX trail export generated by Trail One. "
        "Includes computed waypoint markers, preserved route/track geometry, "
        "metadata, bounds, and optional extensions."
    ),
    author_name: str = "Trail One",
    author_link_href: str = "https://es.wikiloc.com/wikiloc/user.do?id=18125352",
    author_link_text: str = "Trail One on Wikiloc",
    author_link_type: str = "text/html",
    copyright_author: str = "Trail One | Solo Hiking",
    copyright_year: Optional[int] = None,
    copyright_license: Optional[str] = None,
    metadata_time: Optional[datetime] = None,
    metadata_keywords: Optional[Sequence[str]] = None,
    metadata_extensions: Optional[Iterable[ET.Element]] = None,
    root_extensions: Optional[Iterable[ET.Element]] = None,
    preserve_existing_waypoints: bool = True,
    preserve_existing_routes: bool = True,
    preserve_existing_tracks: bool = True,
    preserve_existing_metadata_extensions: bool = True,
) -> Path:
    """
    Serialize a waypoint-enriched GPX 1.1 document to disk using a safe,
    atomic write strategy.

    This function is intentionally "trail-grade" rather than minimal:
    it reconstructs the final GPX document in schema-compliant order,
    computes bounds, injects rich default metadata, preserves original
    navigation geometry, supports metadata/root extensions, validates
    the generated XML before and after writing, and replaces the target
    file atomically.

    Parameters
    ----------
    original_gpx : gpxpy.gpx.GPX
        Parsed GPX object representing the source file.

    waypoints : Sequence[gpxpy.gpx.GPXWaypoint]
        Generated waypoint markers to be injected into the output GPX.

    output_file : str | pathlib.Path
        Destination GPX file path.

    creator : str, optional
        GPX root `creator` attribute. GPX 1.1 requires this attribute.

    metadata_name : str, optional
        Metadata `<name>` value.

    metadata_desc : str, optional
        Metadata `<desc>` value.

    author_name : str, optional
        Metadata `<author><name>` value.

    author_link_href : str, optional
        Metadata author/profile URL and metadata-level link URL.

    author_link_text : str, optional
        Human-readable text for the author/profile link.

    author_link_type : str, optional
        MIME-like type for the profile link.

    copyright_author : str, optional
        Metadata copyright author attribute.

    copyright_year : int | None, optional
        Copyright year. Defaults to current UTC year when omitted.

    copyright_license : str | None, optional
        Optional license URI for `<copyright><license>`.

    metadata_time : datetime | None, optional
        Metadata timestamp. Defaults to current UTC timestamp when omitted.

    metadata_keywords : Sequence[str] | None, optional
        Comma-separated keyword payload for GPX metadata. If omitted,
        a project-specific Trail One keyword set is generated.

    metadata_extensions : Iterable[xml.etree.ElementTree.Element] | None, optional
        Additional XML elements to append under `<metadata><extensions>`.

    root_extensions : Iterable[xml.etree.ElementTree.Element] | None, optional
        Additional XML elements to append under root `<extensions>`.

    preserve_existing_waypoints : bool, optional
        Preserve original GPX `<wpt>` elements.

    preserve_existing_routes : bool, optional
        Preserve original GPX `<rte>` elements.

    preserve_existing_tracks : bool, optional
        Preserve original GPX `<trk>` elements.

    preserve_existing_metadata_extensions : bool, optional
        Preserve original `<metadata><extensions>` payload when present.

    Returns
    -------
    pathlib.Path
        The final resolved output path.

    Raises
    ------
    TypeError
        If inputs are of the wrong type.

    ValueError
        If the output path is invalid, XML generation fails, or the final
        document cannot be validated.

    OSError
        If the file cannot be written or atomically replaced.

    Notes
    -----
    Design goals:
    1. Full GPX 1.1 metadata population by default.
    2. Computed bounds across original geometry and generated waypoints.
    3. Preservation of routes/tracks/waypoints and arbitrary XML extensions.
    4. UTF-8 XML output with declaration.
    5. Atomic write via temporary file + fsync + os.replace().
    """

    # ------------------------------------------------------------------
    # Local helpers
    # ------------------------------------------------------------------

    def _require_datetime_utc(value: datetime) -> datetime:
        """Normalize datetimes to timezone-aware UTC."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _isoformat_z(value: datetime) -> str:
        """Return a GPX-friendly ISO 8601 UTC string."""
        return _require_datetime_utc(value).isoformat().replace("+00:00", "Z")

    def _local_name(tag: str) -> str:
        """Return the local XML tag name without namespace."""
        return tag.split("}", 1)[1] if tag.startswith("{") else tag

    def _qname(ns: str, local: str) -> str:
        """Build a namespaced XML tag."""
        return f"{{{ns}}}{local}"

    def _append_text(parent: ET.Element, ns: str, tag: str, text: Optional[str]) -> Optional[ET.Element]:
        """Append a child tag when text is not blank."""
        if text is None:
            return None
        text = str(text).strip()
        if not text:
            return None
        child = ET.SubElement(parent, _qname(ns, tag))
        child.text = text
        return child

    def _append_link(
        parent: ET.Element,
        ns: str,
        href: str,
        text: Optional[str] = None,
        link_type: Optional[str] = None,
    ) -> ET.Element:
        """Append a GPX 1.1 linkType element."""
        link_el = ET.SubElement(parent, _qname(ns, "link"), {"href": href})
        _append_text(link_el, ns, "text", text)
        _append_text(link_el, ns, "type", link_type)
        return link_el

    def _iter_point_coords_from_xml(root: ET.Element, ns: str):
        """
        Yield (lat, lon) pairs from all GPX point-bearing elements that may
        affect the spatial extent of the document.
        """
        point_tags = ("wpt", "rtept", "trkpt")
        for elem in root.iter():
            if _local_name(elem.tag) in point_tags:
                lat = elem.attrib.get("lat")
                lon = elem.attrib.get("lon")
                if lat is None or lon is None:
                    continue
                try:
                    yield float(lat), float(lon)
                except (TypeError, ValueError):
                    continue

    def _iter_point_coords_from_waypoints(items) -> Iterable[tuple[float, float]]:
        """Yield valid waypoint coordinates from generated waypoint objects."""
        for point in items:
            lat = getattr(point, "latitude", None)
            lon = getattr(point, "longitude", None)
            if lat is None or lon is None:
                continue
            if not (-90.0 <= float(lat) <= 90.0):
                continue
            if not (-180.0 <= float(lon) <= 180.0):
                continue
            yield float(lat), float(lon)

    def _compute_bounds(
        source_root: ET.Element,
        generated_waypoints,
        ns: str,
    ) -> Optional[tuple[float, float, float, float]]:
        """
        Compute GPX bounds across original geometry plus generated waypoints.

        Returns
        -------
        tuple[min_lat, min_lon, max_lat, max_lon] | None
        """
        coords = list(_iter_point_coords_from_xml(source_root, ns))
        coords.extend(_iter_point_coords_from_waypoints(generated_waypoints))

        if not coords:
            return None

        lats = [lat for lat, _ in coords]
        lons = [lon for _, lon in coords]
        return min(lats), min(lons), max(lats), max(lons)

    def _deepcopy_children(parent: Optional[ET.Element]) -> list[ET.Element]:
        """Deep-copy child elements for safe XML reattachment."""
        if parent is None:
            return []
        return [copy.deepcopy(child) for child in list(parent)]

    def _serialize_waypoints_to_xml_elements(generated_waypoints, ns: str) -> list[ET.Element]:
        """
        Serialize GPXWaypoint objects through gpxpy so waypoint XML, including
        fields and extensions known to gpxpy, is preserved faithfully.
        """
        tmp_gpx = gpxpy.gpx.GPX()
        tmp_gpx.waypoints.extend(generated_waypoints)
        tmp_xml = tmp_gpx.to_xml()
        tmp_root = ET.fromstring(tmp_xml.encode("utf-8"))
        return [copy.deepcopy(elem) for elem in tmp_root.findall(_qname(ns, "wpt"))]

    def _validate_output_path(path_obj: Path) -> Path:
        """Validate and normalize destination path semantics."""
        if path_obj.exists() and path_obj.is_dir():
            raise ValueError(f"Output path points to a directory, not a file: {path_obj}")
        if path_obj.suffix.lower() != ".gpx":
            raise ValueError("Output file must use the '.gpx' extension.")
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        return path_obj.resolve()

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    if original_gpx is None:
        raise TypeError("original_gpx must be a parsed GPX object, not None.")

    if not hasattr(original_gpx, "to_xml"):
        raise TypeError("original_gpx must expose a to_xml() method compatible with gpxpy.GPX.")

    if waypoints is None:
        raise TypeError("waypoints must not be None.")

    output_path = _validate_output_path(Path(output_file))

    for idx, waypoint in enumerate(waypoints):
        if not hasattr(waypoint, "latitude") or not hasattr(waypoint, "longitude"):
            raise TypeError(f"Waypoint at index {idx} is not GPX waypoint-compatible.")

    # ------------------------------------------------------------------
    # Parse original GPX XML for schema-aware reconstruction
    # ------------------------------------------------------------------

    try:
        original_xml = original_gpx.to_xml()
        original_root = ET.fromstring(original_xml.encode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Unable to serialize/parse original GPX object: {exc}") from exc

    # Discover namespace from the original document when present.
    if original_root.tag.startswith("{"):
        gpx_ns = original_root.tag.split("}", 1)[0][1:]
    else:
        gpx_ns = "http://www.topografix.com/GPX/1/1"

    ET.register_namespace("", gpx_ns)

    now_utc = _require_datetime_utc(metadata_time or datetime.now(timezone.utc))
    year_utc = int(copyright_year or now_utc.year)

    default_keywords = [
        "Trail One",
        "Solo Hiking",
        "GPX",
        "GPX 1.1",
        "hiking trail",
        "waypoint generation",
        "trailhead",
        "trail end",
        "halfway point",
        "cumulative distance markers",
        "3D distance",
        "geodesic",
        "haversine",
        "elevation",
        "route analysis",
        "trail navigation",
        "outdoor navigation",
        "mountain trail",
        "volcanic hiking",
        "LCST",
        "Nicaragua",
        "TrailOne Hiking Series",
    ]
    keywords = list(metadata_keywords) if metadata_keywords else default_keywords
    keywords_text = ", ".join(dict.fromkeys(k.strip() for k in keywords if str(k).strip()))

    bounds = _compute_bounds(original_root, waypoints, gpx_ns)

    # ------------------------------------------------------------------
    # Rebuild final GPX document in GPX 1.1 schema order
    # ------------------------------------------------------------------

    final_root = ET.Element(
        _qname(gpx_ns, "gpx"),
        {
            "version": "1.1",
            "creator": creator,
        },
    )

    # ------------------------------
    # metadata
    # ------------------------------
    metadata_el = ET.SubElement(final_root, _qname(gpx_ns, "metadata"))

    _append_text(metadata_el, gpx_ns, "name", metadata_name)
    _append_text(metadata_el, gpx_ns, "desc", metadata_desc)

    # author: personType -> name, email, link
    author_el = ET.SubElement(metadata_el, _qname(gpx_ns, "author"))
    _append_text(author_el, gpx_ns, "name", author_name)
    _append_link(author_el, gpx_ns, author_link_href, author_link_text, author_link_type)

    # copyright: copyrightType -> author attr, optional year/license
    copyright_el = ET.SubElement(
        metadata_el,
        _qname(gpx_ns, "copyright"),
        {"author": copyright_author},
    )
    _append_text(copyright_el, gpx_ns, "year", str(year_utc))
    _append_text(copyright_el, gpx_ns, "license", copyright_license)

    # metadata-level link
    _append_link(metadata_el, gpx_ns, author_link_href, author_link_text, author_link_type)

    _append_text(metadata_el, gpx_ns, "time", _isoformat_z(now_utc))
    _append_text(metadata_el, gpx_ns, "keywords", keywords_text)

    if bounds is not None:
        min_lat, min_lon, max_lat, max_lon = bounds
        ET.SubElement(
            metadata_el,
            _qname(gpx_ns, "bounds"),
            {
                "minlat": f"{min_lat:.8f}",
                "minlon": f"{min_lon:.8f}",
                "maxlat": f"{max_lat:.8f}",
                "maxlon": f"{max_lon:.8f}",
            },
        )

    # metadata extensions: preserve existing + append caller-provided
    existing_metadata = original_root.find(_qname(gpx_ns, "metadata"))
    existing_metadata_extensions = None
    if existing_metadata is not None:
        existing_metadata_extensions = existing_metadata.find(_qname(gpx_ns, "extensions"))

    metadata_extension_children = []
    if preserve_existing_metadata_extensions:
        metadata_extension_children.extend(_deepcopy_children(existing_metadata_extensions))
    if metadata_extensions:
        metadata_extension_children.extend(copy.deepcopy(ext) for ext in metadata_extensions)

    if metadata_extension_children:
        metadata_ext_el = ET.SubElement(metadata_el, _qname(gpx_ns, "extensions"))
        for child in metadata_extension_children:
            metadata_ext_el.append(child)

    # ------------------------------
    # wpt (original first, then generated)
    # ------------------------------
    if preserve_existing_waypoints:
        for wpt in original_root.findall(_qname(gpx_ns, "wpt")):
            final_root.append(copy.deepcopy(wpt))

    for generated_wpt in _serialize_waypoints_to_xml_elements(waypoints, gpx_ns):
        final_root.append(generated_wpt)

    # ------------------------------
    # rte
    # ------------------------------
    if preserve_existing_routes:
        for rte in original_root.findall(_qname(gpx_ns, "rte")):
            final_root.append(copy.deepcopy(rte))

    # ------------------------------
    # trk
    # ------------------------------
    if preserve_existing_tracks:
        for trk in original_root.findall(_qname(gpx_ns, "trk")):
            final_root.append(copy.deepcopy(trk))

    # ------------------------------
    # root extensions
    # ------------------------------
    existing_root_extensions = original_root.find(_qname(gpx_ns, "extensions"))
    root_extension_children = _deepcopy_children(existing_root_extensions)
    if root_extensions:
        root_extension_children.extend(copy.deepcopy(ext) for ext in root_extensions)

    if root_extension_children:
        root_ext_el = ET.SubElement(final_root, _qname(gpx_ns, "extensions"))
        for child in root_extension_children:
            root_ext_el.append(child)

    # ------------------------------------------------------------------
    # Pre-write XML validation
    # ------------------------------------------------------------------

    try:
        xml_bytes = ET.tostring(final_root, encoding="utf-8", xml_declaration=True)
        ET.fromstring(xml_bytes)
    except Exception as exc:
        raise ValueError(f"Generated GPX XML is not well-formed: {exc}") from exc

    # ------------------------------------------------------------------
    # Atomic write: temp file -> fsync -> replace
    # ------------------------------------------------------------------

    temp_path: Optional[Path] = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".gpx",
            prefix=f"{output_path.stem}.",
            dir=str(output_path.parent),
            delete=False,
        ) as tmp_file:
            temp_path = Path(tmp_file.name)
            tmp_file.write(xml_bytes)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        # Post-write validation from disk to catch truncation/corruption issues.
        with open(temp_path, "rb") as f:
            ET.parse(f)

        os.replace(temp_path, output_path)

    except Exception:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise

    return output_path

def main():
    parser = argparse.ArgumentParser(description="Analyze GPX hiking trails and generate waypoint markers.")
    parser.add_argument("gpx_file", type=str, help="Path to the GPX file.")
    parser.add_argument("trail_prefix", type=str, help="Three-letter uppercase prefix for waypoint markers.")
    parser.add_argument("step_size", type=float, help="Distance interval (in km) for cumulative markers.")
    parser.add_argument("--distance-method", choices=["auto", "geodesic", "haversine"],default="auto",help="Horizontal distance calculation method.")
    args = parser.parse_args()

    try:
        with open(args.gpx_file, "r", encoding="utf-8") as fh:
            gpx = gpxpy.parse(fh)

        validate_inputs(gpx, args.gpx_file, args.trail_prefix, args.step_size)

        result = parse_gpx_file(gpx)
        points = result["points"]
        
        elevation_stats = compute_elevation_statistics(points)
        print_elevation_statistics(elevation_stats)
        
        waypoints = generate_waypoints(
            points,
            args.trail_prefix,
            args.step_size,
            distance_method=args.distance_method
        )
        
        output_file = f"{os.path.splitext(args.gpx_file)[0]}_{args.step_size}_wpt.gpx"
        
        original_gpx = gpx

        save_gpx_file(
            original_gpx=original_gpx,
            waypoints=waypoints,
            output_file=output_file,
        )
        
        print("\n✅ GPX Waypoint Generation Complete!")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
