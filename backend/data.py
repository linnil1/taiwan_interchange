import json
import os
from collections import defaultdict
from pprint import pprint

import numpy as np
from pydantic import BaseModel
from sklearn.cluster import AgglomerativeClustering

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
    destination: list[str]
    from_ramps: list[int] = []  # IDs of ramps that connect to this ramp
    to_ramps: list[int] = []  # IDs of ramps that this ramp connects to
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
        ramp = Ramp(id=ramp_id, destination=[], from_ramps=[], to_ramps=[], paths=connected_paths)
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
    annotated_ramp = Ramp(
        id=ramp.id,
        destination=list(set(all_destinations)),
        from_ramps=ramp.from_ramps,
        to_ramps=ramp.to_ramps,
        paths=ramp.paths,
    )
    return annotated_ramp


def populate_ramp_connections(ramps: list[Ramp]) -> list[Ramp]:
    """Populate from_ramps and to_ramps fields based on shared endpoint nodes"""
    if not ramps:
        return ramps

    # Build a map of endpoint nodes to ramps
    node_to_ramps_from = defaultdict(set)
    node_to_ramps_to = defaultdict(set)

    for ramp in ramps:
        # Get all endpoint nodes from the ramp's paths
        node_to_ramps_from[ramp.paths[0].nodes[0].id].add(ramp.id)
        node_to_ramps_to[ramp.paths[-1].nodes[-1].id].add(ramp.id)

    # For each ramp, find connected ramps
    for ramp in ramps:
        ramp.from_ramps = list(node_to_ramps_to[ramp.paths[0].nodes[0].id])
        ramp.to_ramps = list(node_to_ramps_from[ramp.paths[-1].nodes[-1].id])
    return ramps


def group_paths_to_ramps(paths: list[Path]) -> list[Ramp]:
    """Group paths into connected ramp objects"""
    broken_paths = break_paths_at_connections(paths)
    connected_ramps = connect_paths(broken_paths)
    # Populate connection information
    connected_ramps_with_connections = populate_ramp_connections(connected_ramps)
    return connected_ramps_with_connections


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


def get_connected_ramps(ramps: list[Ramp]) -> list[list[Ramp]]:
    """Get groups of ramps that are connected by sharing endpoint nodes"""
    if not ramps:
        return []

    # Build a map of endpoint nodes to ramps
    endpoint_to_ramps = defaultdict(list)

    for ramp in ramps:
        # Get all endpoint nodes from the ramp's paths
        endpoint_nodes = set()
        for path in ramp.paths:
            if path.nodes:
                endpoint_nodes.add(path.nodes[0].id)  # First node
                endpoint_nodes.add(path.nodes[-1].id)  # Last node

        # Add this ramp to all its endpoint nodes
        for node_id in endpoint_nodes:
            endpoint_to_ramps[node_id].append(ramp)

    # Find connected ramps using DFS
    visited = set()
    connected_groups = []

    def dfs(ramp: Ramp, current_group: list[Ramp]):
        if ramp.id in visited:
            return

        visited.add(ramp.id)
        current_group.append(ramp)

        # Find all ramps connected to this one
        ramp_endpoints = set()
        for path in ramp.paths:
            if path.nodes:
                ramp_endpoints.add(path.nodes[0].id)
                ramp_endpoints.add(path.nodes[-1].id)

        # Visit all connected ramps
        for node_id in ramp_endpoints:
            for connected_ramp in endpoint_to_ramps[node_id]:
                if connected_ramp.id != ramp.id:
                    dfs(connected_ramp, current_group)

    # Find all connected groups
    for ramp in ramps:
        if ramp.id not in visited:
            current_group = []
            dfs(ramp, current_group)
            if current_group:
                connected_groups.append(current_group)

    return connected_groups


def group_ramps_by_interchange(ramps: list[Ramp]) -> list[Interchange]:
    """Group ramps by interchange using minimum distance clustering with all nodes"""
    if not ramps:
        return []

    # Collect all nodes from all ramps
    all_nodes = []
    # cramps = connected_ramps
    cramps = get_connected_ramps(ramps)
    node_to_cramps = []

    for key, ramps in enumerate(cramps):
        for ramp in ramps:
            for path in ramp.paths:
                for node in path.nodes:
                    node_coord = [node.lng, node.lat]
                    all_nodes.append(node_coord)
                    node_to_cramps.append(key)

    if len(all_nodes) < 2:
        return [create_interchange_from_ramps(ramps, 1)]

    # Distance threshold (in degrees, roughly 1km = 0.01 degrees)
    distance_threshold = 0.005

    # Use agglomerative clustering with distance threshold
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        linkage="single",  # minimum distance between groups
    )
    nodes_array = np.array(all_nodes)
    node_labels = clustering.fit_predict(nodes_array)

    # Group ramps based on their nodes' cluster assignments
    cramp_to_clusters = defaultdict(list)

    for node_idx, cluster_label in enumerate(node_labels):
        id = node_to_cramps[node_idx]
        cramp_to_clusters[id].append(cluster_label)

    # Assign each ramp to the cluster that contains most of its nodes
    cramp_cluster_assignment = {}
    for cramp_id, clusters in cramp_to_clusters.items():
        if clusters:
            # Use the most frequent cluster, or first one if tied
            most_frequent_cluster = max(set(clusters), key=clusters.count)
            cramp_cluster_assignment[cramp_id] = most_frequent_cluster

    # Create interchange objects
    interchanges = []
    for cluster_label_target in set(cramp_cluster_assignment.values()):
        cluster_ramps = []
        for cramp_id, cluster_label in cramp_cluster_assignment.items():
            if cluster_label == cluster_label_target:
                cluster_ramps.extend(cramps[cramp_id])
        if cluster_ramps:
            interchange = create_interchange_from_ramps(cluster_ramps, len(interchanges) + 1)
            interchanges.append(interchange)
    return interchanges


def create_interchange_from_ramps(ramps: list[Ramp], id: int) -> Interchange:
    # Calculate bounds from all ramp nodes
    bounds = calculate_bounds(ramps)
    if not bounds:
        raise ValueError("No valid bounds could be calculated for the interchange")

    # Generate interchange name based on destinations (simplified)
    destinations = set()
    for ramp in ramps:
        if ramp.destination:
            destinations.update(ramp.destination)

    if destinations:
        # Take the first few unique destinations
        interchange_name = f"Interchange to {','.join(destinations)}"
    else:
        interchange_name = f"Interchange {id}"

    return Interchange(id=id, name=interchange_name, bounds=bounds, ramps=ramps)


def annotate_interchange_name(
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


def annotate_interchange_ramps(
    interchange: Interchange, way_dict: dict[int, OverPassWay]
) -> Interchange:
    """Annotate all ramps in an interchange with destinations"""
    annotated_ramps = [annotate_ramps(ramp, way_dict) for ramp in interchange.ramps]

    return Interchange(
        id=interchange.id,
        name=interchange.name,
        bounds=interchange.bounds,
        ramps=annotated_ramps,
    )


def annotate_interchange(
    interchange: Interchange, node_dict: dict[int, OverPassNode], way_dict: dict[int, OverPassWay]
) -> Interchange:
    """Annotate single interchange with proper name and ramp destinations"""
    # First annotate the interchange name
    interchange_with_name = annotate_interchange_name(interchange, node_dict)

    # Then annotate the ramps
    fully_annotated = annotate_interchange_ramps(interchange_with_name, way_dict)

    return fully_annotated


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

    # Group ramps into interchanges
    interchanges = group_ramps_by_interchange(ramps)
    print(f"Identified {len(interchanges)} interchanges")

    # Annotate interchanges with proper names and ramp destinations
    annotated_interchanges = [
        annotate_interchange(interchange, node_dict, way_dict) for interchange in interchanges
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
