import json
import os
from collections import defaultdict

import numpy as np
import requests
from pydantic import BaseModel, Field
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler


class Node(BaseModel):
    """Represents a single node point in a ramp"""

    lat: float
    lng: float
    id: int  # node id


class Path(BaseModel):
    """Represents a path with way_id and nodes"""

    id: int  # way_id
    part: int  # part number when a way is broken into multiple paths
    nodes: list[Node]

    def get_subpath_id(self) -> str:
        return f"{self.id}_{self.part}"


class Ramp(BaseModel):
    """Represents a motorway ramp with its paths"""

    name: str
    to: str
    paths: list[Path]


class Bounds(BaseModel):
    """Represents geographical bounds"""

    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float


class Interchange(BaseModel):
    """Represents an interchange with multiple ramps"""

    id: int
    name: str
    bounds: Bounds
    ramps: list[Ramp]


class Coordinate(BaseModel):
    """Represents a geographical coordinate"""

    lat: float
    lng: float = Field(alias="lon")  # Map API's "lon" to our "lng"

    class Config:
        populate_by_name = True  # Allow both "lon" and "lng" field names


class OverPassNode(BaseModel):
    """Represents a raw OverPass API node"""

    type: str
    id: int
    lat: float
    lon: float
    tags: dict[str, str] = {}


class OverPassWay(BaseModel):
    """Represents a raw OverPass API way"""

    type: str
    id: int
    tags: dict[str, str] = {}
    geometry: list[Coordinate]
    nodes: list[int]


class OverPassResponse(BaseModel):
    """Represents a complete OverPass API response"""

    version: float
    generator: str
    osm3s: dict[str, str]
    elements: list[OverPassNode | OverPassWay]


def query_overpass_api() -> dict | None:
    """Query Overpass API for motorway links in Tainan"""
    overpass_url = "http://overpass-api.de/api/interpreter"

    query = """
    [out:json][timeout:60];
    area["name:en"="Tainan"]->.taiwan;
    (
      way["highway"="motorway_link"](area.taiwan);
      node["highway"="motorway_junction"](area.taiwan);
    );
    out geom;
    """

    response = requests.post(overpass_url, data={"data": query})
    response.raise_for_status()
    return response.json()


def save_overpass_cache(data: dict) -> bool:
    """Save Overpass API response to cache file"""
    cache_file_path = os.path.join(os.path.dirname(__file__), "overpass_cache.json")
    with open(cache_file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved Overpass data to cache: {cache_file_path}")
    return True


def load_overpass_cache() -> dict | None:
    """Load Overpass API response from cache file"""
    cache_file_path = os.path.join(os.path.dirname(__file__), "overpass_cache.json")
    if not os.path.exists(cache_file_path):
        print("No cache file found, will query Overpass API")
        return None

    with open(cache_file_path, encoding="utf-8") as f:
        data = json.load(f)
    print(f"Loaded Overpass data from cache: {cache_file_path}")
    return data


def get_overpass_data(use_cache: bool = True) -> OverPassResponse:
    """Get Overpass data from cache or API"""
    if use_cache:
        data = load_overpass_cache()
    else:
        print("Querying Overpass API...")
        data = query_overpass_api()
        save_overpass_cache(data)
    return OverPassResponse.model_validate(data)


def calculate_bounds(ramps: list[Ramp]) -> Bounds | None:
    """Calculate min/max lat/lng from list of ramps"""
    if not ramps:
        return None

    # Extract all coordinates from all ramps' paths
    all_coordinates = []
    for ramp in ramps:
        for path in ramp.paths:
            for node in path.nodes:
                all_coordinates.append((node.lng, node.lat))

    if not all_coordinates:
        return None

    lats = [coord[1] for coord in all_coordinates]
    lons = [coord[0] for coord in all_coordinates]

    return Bounds(min_lat=min(lats), max_lat=max(lats), min_lng=min(lons), max_lng=max(lons))


def calculate_center(coordinates: list[tuple[float, float]]) -> Coordinate | None:
    """Calculate the center point of a list of coordinates"""
    if not coordinates:
        return None

    lat_sum = sum(coord[1] for coord in coordinates)
    lon_sum = sum(coord[0] for coord in coordinates)
    count = len(coordinates)

    return Coordinate(lat=lat_sum / count, lng=lon_sum / count)


def extract_to_destination(tags: dict[str, str]) -> str:
    """Extract destination from way tags"""
    # Try different tag patterns for destination
    destinations = []

    # Check for 'destination' tag
    if "destination" in tags:
        destinations.append(tags["destination"])

    # Check for 'destination:ref' tag
    if "destination:ref" in tags:
        destinations.append(tags["destination:ref"])

    # Check for 'ref' tag
    if "ref" in tags:
        destinations.append(tags["ref"])

    # Check for 'name' tag
    if "name" in tags:
        destinations.append(tags["name"])

    return "; ".join(destinations) if destinations else "Unknown"


def process_single_path(overpass_way: OverPassWay) -> Path:
    """Process a single OSM way into a Path object"""
    assert overpass_way.geometry, "Way geometry is empty"
    assert overpass_way.nodes, "Way nodes are empty"
    assert len(overpass_way.geometry) == len(overpass_way.nodes), (
        "Geometry and nodes length mismatch"
    )

    # Convert geometry to node format
    nodes = []
    for coord, node_id in zip(overpass_way.geometry, overpass_way.nodes):
        nodes.append(Node(lat=coord.lat, lng=coord.lng, id=node_id))

    way_id = overpass_way.id

    return Path(id=way_id, part=0, nodes=nodes)


def break_paths_at_connections(paths: list[Path]) -> list[Path]:
    """Break paths when internal nodes connect to endpoints of other paths"""
    if not paths:
        return []

    # Collect all endpoint nodes (first and last nodes of each path)
    endpoint_nodes = set()
    for path in paths:
        if path.nodes:
            endpoint_nodes.add(path.nodes[0].id)  # First node
            endpoint_nodes.add(path.nodes[-1].id)  # Last node

    broken_paths = []

    for path in paths:
        if not path.nodes or len(path.nodes) <= 2:
            # Don't break paths with 2 or fewer nodes
            broken_paths.append(path)
            continue

        # Find internal nodes that are endpoints of other paths
        break_points = []
        for i, node in enumerate(path.nodes):
            if i > 0 and i < len(path.nodes) - 1:  # Internal node (not first or last)
                if node.id in endpoint_nodes:
                    break_points.append(i)

        if not break_points:
            # No breaking needed
            broken_paths.append(path)
        else:
            # Break the path at the identified points
            part_num = 0
            start_idx = 0

            for break_idx in break_points:
                # Create a path segment from start_idx to break_idx (inclusive)
                segment_nodes = path.nodes[start_idx : break_idx + 1]
                if len(segment_nodes) >= 2:  # Only create if it has at least 2 nodes
                    broken_path = Path(id=path.id, part=part_num, nodes=segment_nodes)
                    broken_paths.append(broken_path)
                    part_num += 1

                start_idx = break_idx  # Start next segment from the break point

            # Create the final segment
            final_nodes = path.nodes[start_idx:]
            if len(final_nodes) >= 2:
                broken_path = Path(id=path.id, part=part_num, nodes=final_nodes)
                broken_paths.append(broken_path)

    return broken_paths


def connect_paths(paths: list[Path]) -> list[Ramp]:
    """Connect paths when end node of one matches start node of another to form ramps"""
    if not paths:
        return []
    paths = [i for i in paths if i.nodes]  # Filter out empty paths

    # Build connection graph: node_id -> list of (subpath_id, is_start)
    # is_start=True means the node is the start of the path, False means it's the end
    node_connections = defaultdict(list)
    path_by_subpath_id = {}  # subpath_id -> Path object

    for path in paths:
        subpath_id = path.get_subpath_id()
        path_by_subpath_id[subpath_id] = path
        start_node_id = path.nodes[0].id
        end_node_id = path.nodes[-1].id
        node_connections[start_node_id].append((subpath_id, True))  # This path starts at this node
        node_connections[end_node_id].append((subpath_id, False))  # This path ends at this node

    def can_node_extend(node_id: int) -> bool:
        """
        Check if a node can be extended into a ramp
        Only if it did not have any other incoming or outgoing connections
        """
        return (
            node_id in node_connections
            and len(node_connections[node_id]) == 2
            and node_connections[node_id][0][1] != node_connections[node_id][1][1]
        )

    def get_next_path(node_id: int, find_start: bool) -> str:
        """
        Get the next path subpath_id that starts at the given node ID
        """
        if node_id in node_connections:
            for subpath_id, is_start in node_connections[node_id]:
                if is_start == find_start:
                    return subpath_id
        assert False

    used_subpath_ids = set()

    def extend_forward(current_path: Path) -> list[Path]:
        used_subpath_ids.add(current_path.get_subpath_id())

        end_node_id = current_path.nodes[-1].id
        if not can_node_extend(end_node_id):
            return [current_path]
        next_subpath_id = get_next_path(end_node_id, find_start=True)
        if next_subpath_id in used_subpath_ids:
            return [current_path]
        return [current_path] + extend_forward(path_by_subpath_id[next_subpath_id])

    def extend_backward(current_path: Path) -> list[Path]:
        used_subpath_ids.add(current_path.get_subpath_id())
        start_node_id = current_path.nodes[0].id
        if not can_node_extend(start_node_id):
            return [current_path]
        prev_subpath_id = get_next_path(start_node_id, find_start=False)
        if prev_subpath_id in used_subpath_ids:
            return [current_path]
        return extend_backward(path_by_subpath_id[prev_subpath_id]) + [current_path]

    connected_ramps = []
    for start_path in paths:
        if start_path.get_subpath_id() in used_subpath_ids:
            continue

        connected_paths = extend_backward(start_path)[:-1] + extend_forward(start_path)
        ramp = Ramp(
            name=f"Ramp {connected_paths[0].get_subpath_id()}", to="Unknown", paths=connected_paths
        )
        connected_ramps.append(ramp)
    return connected_ramps


def annotate_ramps(
    ramps: list[Ramp], overpass_nodes: list[OverPassNode], overpass_ways: list[OverPassWay]
) -> list[Ramp]:
    """Annotate ramps with proper names and destinations from OSM data"""
    # Create mappings for quick lookup
    way_tags = {}
    for way in overpass_ways:
        way_tags[way.id] = way.tags or {}

    node_tags = {}
    for node in overpass_nodes:
        node_tags[node.id] = node.tags or {}

    annotated_ramps = []

    for ramp in ramps:
        # Extract info from all paths in the ramp to determine name and destination
        all_names = []
        all_destinations = []

        for path in ramp.paths:
            tags = way_tags.get(path.id, {})
            if "name" in tags and tags["name"]:
                all_names.append(tags["name"])
            dest = extract_to_destination(tags)
            if dest != "Unknown":
                all_destinations.append(dest)

        # Determine best name and destination
        if all_destinations:
            ramp_to = "; ".join(set(all_destinations))
        else:
            ramp_to = "Unknown"

        if all_names:
            ramp_name = "; ".join(set(all_names))
        else:
            ramp_name = f"Ramp {ramp.paths[0].id}" if ramp.paths else "Unnamed Ramp"

        # Create annotated ramp
        annotated_ramp = Ramp(name=ramp_name, to=ramp_to, paths=ramp.paths)
        annotated_ramps.append(annotated_ramp)

    return annotated_ramps


def process_ramps_from_ways(ways: list[OverPassWay], nodes: list[OverPassNode]) -> list[Ramp]:
    """Process OSM ways into connected ramp objects"""
    paths = [process_single_path(way) for way in ways]
    broken_paths = break_paths_at_connections(paths)
    connected_ramps = connect_paths(broken_paths)
    annotated_ramps = annotate_ramps(connected_ramps, nodes, ways)
    return annotated_ramps


def group_ramps_by_interchange(ramps: list[Ramp]) -> list[Interchange]:
    """Group ramps by interchange using DBSCAN clustering algorithm"""
    if not ramps:
        return []

    # Calculate center points for each ramp
    ramp_centers = []
    valid_ramps = []

    for ramp in ramps:
        # Get coordinates from all paths in the ramp
        ramp_coords = []
        for path in ramp.paths:
            for node in path.nodes:
                ramp_coords.append((node.lng, node.lat))

        if not ramp_coords:
            continue

        center = calculate_center(ramp_coords)
        if center:
            ramp_centers.append([center.lng, center.lat])
            valid_ramps.append(ramp)

    if len(valid_ramps) < 2:
        return []

    # Convert to numpy array for sklearn
    centers_array = np.array(ramp_centers)

    # Scale the coordinates for better clustering
    # Note: We use a small scaling factor since coordinates are already in degrees
    scaler = StandardScaler()
    centers_scaled = scaler.fit_transform(centers_array)

    # Use DBSCAN clustering
    # eps=0.5 corresponds to about 1km when properly scaled
    # min_samples=2 means we need at least 2 ramps to form an interchange
    dbscan = DBSCAN(eps=0.1, min_samples=2)
    cluster_labels = dbscan.fit_predict(centers_scaled)

    # Group ramps by cluster
    clusters = defaultdict(list)
    for i, label in enumerate(cluster_labels):
        if label != -1:  # -1 means noise/outlier
            clusters[label].append(valid_ramps[i])

    # Create interchange objects
    interchanges = []
    for cluster_id, cluster_ramps in clusters.items():
        if len(cluster_ramps) < 1:
            continue

        # Calculate bounds from all ramp nodes
        bounds = calculate_bounds(cluster_ramps)
        if not bounds:
            continue

        # Generate interchange name based on destinations
        destinations = set()
        for ramp in cluster_ramps:
            if ramp.to and ramp.to != "Unknown":
                destinations.update(ramp.to.split("; "))

        if destinations:
            # Take the first few unique destinations
            dest_list = list(destinations)[:2]
            interchange_name = f"Interchange to {', '.join(dest_list)}"
        else:
            interchange_name = f"Interchange {cluster_id + 1}"

        interchange = Interchange(
            id=cluster_id + 1,
            name=interchange_name,
            bounds=bounds,
            ramps=cluster_ramps,
        )

        interchanges.append(interchange)

    return interchanges


def generate_interchanges_json(use_cache: bool = True) -> bool:
    """Generate interchanges.json file from Overpass API data"""
    print("Getting Overpass data...")

    response = get_overpass_data(use_cache)

    ways = [
        element
        for element in response.elements
        if element.type == "way" and hasattr(element, "geometry")
    ]
    nodes = [element for element in response.elements if element.type == "node"]

    print(f"Found {len(ways)} motorway links and {len(nodes)} motorway junctions")

    if not ways:
        print("No motorway links found in Tainan")
        return False

    print("Processing ramps...")
    ramps = process_ramps_from_ways(ways, nodes)
    print(f"Processed {len(ramps)} ramps")

    interchanges = group_ramps_by_interchange(ramps)

    print(f"Identified {len(interchanges)} interchanges")

    # Save to JSON file
    json_file_path = os.path.join(os.path.dirname(__file__), "interchanges.json")

    # Convert dataclasses to dictionaries for JSON serialization
    interchanges_dict = [interchange.model_dump() for interchange in interchanges]

    with open(json_file_path, "w", encoding="utf-8") as f:
        json.dump(interchanges_dict, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {json_file_path}")
    print(f"Generated {len(interchanges)} interchanges")

    # Print first few interchanges as sample
    for i, interchange in enumerate(interchanges[:3]):
        print(f"\nSample interchange {i + 1}:")
        print(f"  Name: {interchange.name}")
        print(
            f"  Bounds: ({interchange.bounds.min_lat:.6f}, {interchange.bounds.min_lng:.6f}) to ({interchange.bounds.max_lat:.6f}, {interchange.bounds.max_lng:.6f})"
        )
        print(f"  Ramps: {len(interchange.ramps)}")

        for j, ramp in enumerate(interchange.ramps[:2]):  # Show first 2 ramps
            print(f"    Ramp {j + 1}: {ramp.name} → {ramp.to}")
            print(f"      Paths: {len(ramp.paths)}")
            for k, path in enumerate(ramp.paths):
                print(f"        Path {k + 1} (way {path.id}): {len(path.nodes)} nodes")

    return True


def load_interchanges() -> list[Interchange]:
    """Load interchanges data as Pydantic objects with validation"""
    json_file_path = os.path.join(os.path.dirname(__file__), "interchanges.json")
    data = json.load(open(json_file_path, encoding="utf-8"))
    datas = [Interchange.model_validate(item) for item in data]
    return datas


if __name__ == "__main__":
    print("Generating interchanges data from Overpass API...")
    success = generate_interchanges_json(use_cache=True)
    if success:
        print("\n✅ Successfully generated interchanges.json")
        print("You can now run the Flask app with: python app.py")
    else:
        print("\n❌ Failed to generate interchanges.json")
