import json
import os
from collections import defaultdict
from pprint import pprint

import numpy as np
from pydantic import BaseModel
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler

from osm import Coordinate, OverPassNode, OverPassWay, load_overpass


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

    id: int
    to: list[str]
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


def extract_to_destination(tags: dict[str, str]) -> list[str]:
    """Extract destination from way tags - retrieve all three tags"""
    destinations = []

    # Check for 'exit_to' tag
    if "exit_to" in tags and tags["exit_to"]:
        destinations.extend(tags["exit_to"].split(";"))

    # Check for 'destination' tag
    if "destination" in tags and tags["destination"]:
        destinations.extend(tags["destination"].split(";"))

    # Check for 'ref' tag
    if "ref" in tags and tags["ref"]:
        destinations.append(tags["ref"])

    return destinations


def calculate_center(coordinates: list[tuple[float, float]]) -> Coordinate | None:
    """Calculate the center point of a list of coordinates"""
    if not coordinates:
        return None

    lat_sum = sum(coord[1] for coord in coordinates)
    lon_sum = sum(coord[0] for coord in coordinates)
    count = len(coordinates)

    return Coordinate(lat=lat_sum / count, lng=lon_sum / count)


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
    ramp_id = 0
    for start_path in paths:
        if start_path.get_subpath_id() in used_subpath_ids:
            continue

        connected_paths = extend_backward(start_path)[:-1] + extend_forward(start_path)
        ramp = Ramp(id=ramp_id, to=[], paths=connected_paths)
        connected_ramps.append(ramp)
        ramp_id += 1
    return connected_ramps


def annotate_ramps(ramp: Ramp, way_dict: dict[int, OverPassWay]) -> Ramp:
    """Annotate single ramp with destinations from OSM way dictionary"""
    # Extract destinations from all paths in the ramp
    all_destinations = []

    for path in ramp.paths:
        way = way_dict.get(path.id)
        if way and way.tags:
            dest_list = extract_to_destination(way.tags)
            all_destinations.extend(dest_list)

    # Create annotated ramp with id and destination list
    annotated_ramp = Ramp(id=ramp.id, to=list(set(all_destinations)), paths=ramp.paths)
    return annotated_ramp


def group_paths_to_ramps(paths: list[Path]) -> list[Ramp]:
    """Group paths into connected ramp objects"""
    broken_paths = break_paths_at_connections(paths)
    connected_ramps = connect_paths(broken_paths)
    return connected_ramps


def extract_name_from_interchange(ramps: list[Ramp], node_dict: dict[int, OverPassNode]) -> str:
    """Extract interchange name from motorway_junction nodes with names in tags"""
    junction_names = []

    for ramp in ramps:
        for path in ramp.paths:
            for node in path.nodes:
                osm_node = node_dict.get(node.id)
                if osm_node and osm_node.tags:
                    if (
                        osm_node.tags.get("highway") == "motorway_junction"
                        and "name" in osm_node.tags
                    ):
                        junction_names.append(osm_node.tags["name"])

    return ";".join(set(junction_names)) if junction_names else ""


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
        interchange = create_interchange_from_ramps(cluster_ramps, cluster_id)
        interchanges.append(interchange)

    return interchanges


def create_interchange_from_ramps(ramps: list[Ramp], cluster_id: int) -> Interchange:
    # Calculate bounds from all ramp nodes
    bounds = calculate_bounds(ramps)
    if not bounds:
        raise ValueError("No valid bounds could be calculated for the interchange")

    # Generate interchange name based on destinations (simplified)
    destinations = set()
    for ramp in ramps:
        if ramp.to:
            destinations.update(ramp.to)

    if destinations:
        # Take the first few unique destinations
        interchange_name = f"Interchange to {','.join(destinations)}"
    else:
        interchange_name = f"Interchange {cluster_id + 1}"

    return Interchange(id=cluster_id + 1, name=interchange_name, bounds=bounds, ramps=ramps)


def annotate_interchange(
    interchange: Interchange, node_dict: dict[int, OverPassNode]
) -> Interchange:
    """Annotate single interchange with proper name based on motorway_junction nodes"""
    # Extract proper name from motorway_junction nodes
    junction_name = extract_name_from_interchange(interchange.ramps, node_dict)

    if junction_name:
        # Use the junction name
        annotated_interchange = Interchange(
            id=interchange.id,
            name=junction_name,
            bounds=interchange.bounds,
            ramps=interchange.ramps,
        )
    else:
        # Keep the original name if no junction name found
        annotated_interchange = interchange

    return annotated_interchange


def generate_interchanges_json(use_cache: bool = True) -> bool:
    """Generate interchanges.json file from Overpass API data"""
    print("Getting Overpass data...")
    response = load_overpass(use_cache)

    ways = [element for element in response.elements if element.type == "way"]
    nodes = [element for element in response.elements if element.type == "node"]
    print(f"Found {len(ways)} motorway links and {len(nodes)} motorway junctions")

    if not ways:
        print("No motorway links found in Tainan")
        return False

    print("Processing paths and ramps...")

    # Create dictionaries for efficient lookup
    way_dict = {way.id: way for way in ways}
    node_dict = {node.id: node for node in nodes}

    # Process individual paths from ways
    paths = [process_single_path(way) for way in ways]
    print(f"Processed {len(paths)} paths")

    # Group paths into ramps
    ramps = group_paths_to_ramps(paths)
    print(f"Grouped into {len(ramps)} ramps")

    # Annotate ramps with destinations
    annotated_ramps = [annotate_ramps(ramp, way_dict) for ramp in ramps]
    print(f"Annotated {len(annotated_ramps)} ramps")

    interchanges = group_ramps_by_interchange(annotated_ramps)
    print(f"Identified {len(interchanges)} interchanges")

    # Annotate interchanges with proper names
    annotated_interchanges = [
        annotate_interchange(interchange, node_dict) for interchange in interchanges
    ]
    print(f"Annotated {len(annotated_interchanges)} interchanges")

    json_file_path = save_interchanges(annotated_interchanges)
    print(f"Successfully saved interchanges to {json_file_path}")

    # Print first few interchanges as sample
    pprint(annotated_interchanges[:3])

    return True


def load_interchanges() -> list[Interchange]:
    """Load interchanges data as Pydantic objects with validation"""
    json_file_path = os.path.join(os.path.dirname(__file__), "interchanges.json")
    data = json.load(open(json_file_path, encoding="utf-8"))
    datas = [Interchange.model_validate(item) for item in data]
    return datas


def save_interchanges(interchanges: list[Interchange]) -> str:
    """Save interchanges data to JSON file"""
    json_file_path = os.path.join(os.path.dirname(__file__), "interchanges.json")
    interchanges_dict = [interchange.model_dump() for interchange in interchanges]
    with open(json_file_path, "w", encoding="utf-8") as f:
        json.dump(interchanges_dict, f, indent=2, ensure_ascii=False)
    return json_file_path


if __name__ == "__main__":
    print("Generating interchanges data from Overpass API...")
    success = generate_interchanges_json(use_cache=True)
    if success:
        print("\n✅ Successfully generated interchanges.json")
        print("You can now run the Flask app with: python app.py")
    else:
        print("\n❌ Failed to generate interchanges.json")
