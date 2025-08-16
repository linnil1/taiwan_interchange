import json
import os
from collections import defaultdict

import numpy as np
from pydantic import BaseModel
from sklearn.cluster import AgglomerativeClustering

from osm import (
    Coordinate,
    OverPassNode,
    OverPassResponse,
    OverPassWay,
    load_freeway_routes,
    load_overpass,
    load_provincial_routes,
    load_unknown_end_nodes,
)


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
    ended: bool = False  # True if this path ends at a traffic light or similar

    def get_subpath_id(self) -> str:
        return f"{self.id}_{self.part}"


class Ramp(BaseModel):
    """Represents a motorway ramp with its paths"""

    id: int
    destination: list[str]
    from_ramps: list[int] = []  # IDs of ramps that connect to this ramp
    to_ramps: list[int] = []  # IDs of ramps that this ramp connects to
    paths: list[Path]

    def list_nodes(self) -> list[Node]:
        """Get all nodes from all paths in this ramp"""
        nodes = []
        for path in self.paths:
            nodes.extend(path.nodes)
        return nodes

    def get_endpoint_nodes(self) -> tuple[Node, Node]:
        """Get all endpoint node IDs from this ramp's paths"""
        assert self.paths, self
        assert self.paths[0].nodes
        assert self.paths[-1].nodes
        return (self.paths[0].nodes[0], self.paths[-1].nodes[-1])


class Bounds(BaseModel):
    """Represents geographical bounds"""

    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float


class Relation(BaseModel):
    """Represents a road relation with name, ref, and road type"""

    name: str
    ref: str
    road_type: str  # "freeway", "provincial", or "unknown"


class Interchange(BaseModel):
    """Represents an interchange with multiple ramps"""

    id: int
    name: str
    bounds: Bounds
    ramps: list[Ramp]

    def list_nodes(self) -> list[Node]:
        """Get all nodes from all ramps in this interchange"""
        nodes = []
        for ramp in self.ramps:
            nodes.extend(ramp.list_nodes())
        return nodes


def calculate_bounds(ramps: list[Ramp]) -> Bounds | None:
    """Calculate min/max lat/lng from list of ramps"""
    if not ramps:
        return None

    # Extract all coordinates from all ramps using the new method
    lats = []
    lons = []
    for ramp in ramps:
        nodes = ramp.list_nodes()
        lats.extend(node.lat for node in nodes)
        lons.extend(node.lng for node in nodes)

    if not lats:
        return None

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
    if "ref" in tags and tags["ref"] and not destinations:
        destinations.append(tags["ref"])

    return destinations


def calculate_center(coordinates: list[tuple[float, float]]) -> Coordinate | None:
    """Calculate the center point of a list of coordinates"""
    if not coordinates:
        return None

    lat_sum = sum(coord[1] for coord in coordinates)
    lon_sum = sum(coord[0] for coord in coordinates)
    count = len(coordinates)

    return Coordinate(lat=lat_sum / count, lon=lon_sum / count)


def is_node_traffic_light(node: OverPassNode | None) -> bool:
    """Check if a node is a traffic light or similar control node"""
    if node and node.tags:
        # Check for traffic control tags
        return (
            node.tags.get("highway") == "traffic_signals"
            or node.tags.get("traffic_signals") is not None
            or node.tags.get("highway") == "stop"
            or node.tags.get("stop") is not None
        )
    return False


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


def break_paths_at_connections(paths: list[Path], node_dict: dict[int, OverPassNode]) -> list[Path]:
    """Break paths when internal nodes connect to endpoints of other paths, and mark paths with traffic lights"""
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
                if node.id in endpoint_nodes or is_node_traffic_light(node_dict.get(node.id)):
                    break_points.append(i)

        if not break_points:
            # No breaking needed
            broken_paths.append(path)
        else:
            # Break the path at the identified points
            part_num = 0
            start_idx = 0

            for break_idx in [*break_points, len(path.nodes)]:
                # Create a path segment from start_idx to break_idx (inclusive)
                segment_nodes = path.nodes[start_idx : break_idx + 1]
                assert len(segment_nodes) >= 2  # Only create if it has at least 2 nodes

                broken_path = Path(
                    id=path.id,
                    part=part_num,
                    nodes=segment_nodes,
                    ended=is_node_traffic_light(node_dict.get(segment_nodes[-1].id)),
                )
                broken_paths.append(broken_path)
                part_num += 1
                start_idx = break_idx  # Start next segment from the break point

    return broken_paths


def connect_paths(paths: list[Path]) -> list[Ramp]:
    """Connect paths when end node of one matches start node of another to form ramps"""
    if not paths:
        return []
    paths = [i for i in paths if i.nodes]  # Filter out empty paths

    # Build connection graph: node_id -> list of (subpath_id, is_start)
    # is_start=True means the node is the start of the path, False means it's the end
    node_connections = defaultdict(list)
    path_by_subpath_id: dict[str, Path] = {}  # subpath_id -> Path object

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
        if current_path.ended:
            return [current_path]
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
        prev_path = path_by_subpath_id[prev_subpath_id]
        if prev_path.ended:
            return [current_path]
        return extend_backward(prev_path) + [current_path]

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


def annotate_ramp_by_way(ramp: Ramp, way_dict: dict[int, OverPassWay]) -> list[str]:
    """Annotate ramp with destinations from OSM way dictionary"""
    all_destinations = []

    for path in ramp.paths:
        way = way_dict.get(path.id)
        if way and way.tags:
            dest_list = extract_to_destination(way.tags)
            all_destinations.extend(dest_list)

    return list(set(all_destinations))


def annotate_ramp_by_relation(ramp: Ramp, node_to_relations: dict[int, Relation]) -> list[str]:
    """Annotate ramp with destinations from relation mapping"""
    all_destinations = []

    # Use the end node to determine destination
    _, end_node = ramp.get_endpoint_nodes()
    relation = node_to_relations.get(end_node.id)
    if relation:
        all_destinations.append(relation.name)

    return all_destinations


def annotate_ramps_by_propagating(ramps: list[Ramp]) -> list[Ramp]:
    """Propagate destination information upstream using reverse topological order"""
    # Create a mapping from ramp ID to ramp for quick lookup
    ramp_dict = {ramp.id: ramp for ramp in ramps}
    visited_ramps = set()

    def dfs(ramp: Ramp) -> None:
        if ramp.id in visited_ramps:
            return
        visited_ramps.add(ramp.id)

        # Propagate destinations to upstream ramps
        for upstream_ramp_id in ramp.to_ramps:
            downstream_ramp = ramp_dict.get(upstream_ramp_id)
            assert downstream_ramp
            dfs(downstream_ramp)

            ramp.destination.extend(downstream_ramp.destination)
        ramp.destination = list(set(ramp.destination))  # Remove duplicates

    for ramp in ramps:
        if ramp.id not in visited_ramps:
            dfs(ramp)
    return ramps


def annotate_ramps_by_query_unknown(
    ramps: list[Ramp], interchange_name: str, use_cache: bool = True
) -> list[Ramp]:
    """Annotate ramps by querying unknown end nodes for ramps with empty destinations"""
    # Find ramps with empty destinations and collect their end node IDs
    empty_destination_ramps = []
    unknown_node_ids = []

    for ramp in ramps:
        if not ramp.destination:
            empty_destination_ramps.append(ramp)
            # Get the end node of connected ramps
            if not ramp.to_ramps:
                _, end_node = ramp.get_endpoint_nodes()
                unknown_node_ids.append(end_node.id)

    if not unknown_node_ids:
        return ramps

    # Query for unknown end nodes
    response = load_unknown_end_nodes(unknown_node_ids, interchange_name, use_cache)

    node_to_relation = process_relations_by_way(response, road_type="unknown")
    for ramp in ramps:
        destinations = annotate_ramp_by_relation(ramp, node_to_relation)
        ramp.destination.extend(destinations)
    return ramps


def annotate_ramp(
    ramp: Ramp,
    way_dict: dict[int, OverPassWay],
    node_to_relations: dict[int, Relation] | None = None,
) -> Ramp:
    """Annotate single ramp with destinations using multiple methods"""
    all_destinations = []

    # Try relation mapping first (highest priority)
    if node_to_relations:
        relation_destinations = annotate_ramp_by_relation(ramp, node_to_relations)
        all_destinations.extend(relation_destinations)

    # If no relation destinations, try way tags
    # TODO: temporary disabled it
    if not all_destinations:
        way_destinations = annotate_ramp_by_way(ramp, way_dict)
        all_destinations.extend(way_destinations)

    # Create annotated ramp with id and destination list
    ramp.destination = list(set(all_destinations))
    return ramp


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
    ramps = connect_paths(paths)
    # Populate connection information
    ramps = populate_ramp_connections(ramps)
    return ramps


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
        # Get all endpoint nodes from the ramp using the new method
        start_node, end_node = ramp.get_endpoint_nodes()
        endpoint_to_ramps[start_node.id].append(ramp)
        endpoint_to_ramps[end_node.id].append(ramp)

    # Find connected ramps using DFS
    visited = set()
    connected_groups = []

    def dfs(ramp: Ramp, current_group: list[Ramp]):
        if ramp.id in visited:
            return

        visited.add(ramp.id)
        current_group.append(ramp)

        # Find all ramps connected to this one using the new method
        ramp_endpoints = ramp.get_endpoint_nodes()

        # Visit all connected ramps
        for node in ramp_endpoints:
            for connected_ramp in endpoint_to_ramps[node.id]:
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


def group_ramps_by_interchange(
    ramps: list[Ramp], distance_threshold: float = 0.005
) -> list[Interchange]:
    """Group ramps by interchange using minimum distance clustering with all nodes"""
    if not ramps:
        return []

    # Collect all nodes from all ramps
    all_nodes = []
    # cramps = connected_ramps
    cramps = get_connected_ramps(ramps)
    node_to_cramps = []

    for key, ramps_group in enumerate(cramps):
        for ramp in ramps_group:
            for node in ramp.list_nodes():
                node_coord = [node.lng, node.lat]
                all_nodes.append(node_coord)
                node_to_cramps.append(key)

    if len(all_nodes) < 2:
        return [create_interchange_from_ramps(ramps, 1)]

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


def tune_interchange(interchanges: list[Interchange]) -> list[Interchange]:
    """
    Manual tuning of interchanges after initial clustering.
    Apply specific rules for known interchange groupings.
    """
    # Find interchanges that should be regrouped
    special_nodes = set(
        [
            1549192482,  # 新化端
        ]
    )

    # Separate interchanges that match special criteria
    special_interchanges = []
    regular_interchanges = []

    for interchange in interchanges:
        # Check if the interchange name contains any of the special names
        is_special = (
            len(special_nodes.intersection([node.id for node in interchange.list_nodes()])) > 0
        )

        if is_special:
            special_interchanges.append(interchange)
        else:
            regular_interchanges.append(interchange)

    # If we found special interchanges, regroup them with stricter parameters
    if len(special_interchanges) >= 1:
        print(f"Found {len(special_interchanges)} special interchanges to regroup")

        # Extract all ramps from special interchanges
        all_special_ramps = []
        for interchange in special_interchanges:
            all_special_ramps.extend(interchange.ramps)

        # Regroup with stricter parameters
        regrouped_interchanges = group_ramps_by_interchange(all_special_ramps, 0.001)

        # Add regrouped interchanges to regular ones
        regular_interchanges.extend(regrouped_interchanges)

        # Reassign IDs to maintain uniqueness
        for i, interchange in enumerate(regular_interchanges):
            interchange.id = i + 1
    else:
        # No special interchanges found, return original list
        regular_interchanges = interchanges

    return regular_interchanges


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
    interchange: Interchange,
    way_dict: dict[int, OverPassWay],
    node_to_relations: dict[int, Relation] | None = None,
    use_cache: bool = True,
) -> Interchange:
    """Annotate all ramps in an interchange with destinations"""
    # First annotate individual ramps
    ramps = [annotate_ramp(ramp, way_dict, node_to_relations) for ramp in interchange.ramps]

    # Then use query unknown for ramps with empty destinations
    ramps = annotate_ramps_by_query_unknown(ramps, interchange.name, use_cache)

    # Finally, propagate destinations upstream from exit ramps to entry ramps
    ramps = annotate_ramps_by_propagating(ramps)

    return Interchange(
        id=interchange.id,
        name=interchange.name,
        bounds=interchange.bounds,
        ramps=ramps,
    )


def annotate_interchange(
    interchange: Interchange,
    node_dict: dict[int, OverPassNode],
    way_dict: dict[int, OverPassWay],
    node_to_relations: dict[int, Relation],
    use_cache: bool = True,
) -> Interchange:
    """Annotate single interchange with proper name and ramp destinations"""
    # First annotate the interchange name
    interchange = annotate_interchange_name(interchange, node_dict)

    # Then annotate the ramps
    interchange = annotate_interchange_ramps(interchange, way_dict, node_to_relations, use_cache)

    return interchange


def process_relations_by_way(response: OverPassResponse, road_type: str) -> dict[int, Relation]:
    ways = response.list_ways()
    node_to_relation = {}

    # Process ways
    for way in ways:
        if not way.tags.get("name"):
            continue
        relation = Relation(name=way.tags["name"], road_type=road_type, ref="")
        for node_id in way.nodes:
            if node_id in node_to_relation:
                continue
            node_to_relation[node_id] = relation
    return node_to_relation


def process_relations_mapping(response: OverPassResponse, road_type: str) -> dict[int, Relation]:
    """Process relations and return node to relation mapping"""
    node_to_relations = {}
    relations = response.list_relations()
    ways = response.list_ways()

    print(f"Processing {road_type}: {len(relations)} relations, {len(ways)} ways")

    # Create way_id to way mapping for efficiency
    way_dict = {way.id: way for way in ways}

    for relation in relations:
        # Skip if no name in tags for relations
        if not relation.tags or "name" not in relation.tags:
            continue

        relation_obj = Relation(
            name=relation.tags["name"],
            ref=relation.tags.get("ref", ""),
            road_type=road_type,
        )

        # Get all way members from this relation
        way_ids_in_relation = set()
        for member in relation.members:
            if member.get("type") == "way":
                way_ids_in_relation.add(member.get("ref"))

        # Map all nodes from these ways to this relation object
        for way_id in way_ids_in_relation:
            way = way_dict.get(way_id)
            if way and hasattr(way, "nodes") and way.nodes:
                for node_id in way.nodes:
                    if node_id not in node_to_relations:
                        node_to_relations[node_id] = relation_obj

    return node_to_relations


def build_node_to_relation_mapping(use_cache: bool = True) -> dict[int, Relation]:
    """Build mapping from node ID to road relation objects (freeway, provincial)"""
    # Load the responses
    response_freeway = load_freeway_routes(use_cache)
    response_provincial = load_provincial_routes(use_cache)

    # Process each type and combine results with priority: freeway > provincial
    node_to_relations = {}

    # Process provincial first (lower priority)
    provincial_mapping = process_relations_mapping(response_provincial, "provincial")
    node_to_relations.update(provincial_mapping)

    # Process freeway second (higher priority, will overwrite provincial)
    freeway_mapping = process_relations_mapping(response_freeway, "freeway")
    node_to_relations.update(freeway_mapping)

    return node_to_relations


def generate_interchanges_json(use_cache: bool = True) -> bool:
    """Generate interchanges.json file from Overpass API data"""
    print("Getting Overpass data...")
    response = load_overpass(use_cache)
    ways = response.list_ways()
    nodes = response.list_nodes()
    print(f"Found {len(ways)} motorway links and {len(nodes)} motorway junctions")

    if not ways:
        print("No motorway links found in Tainan")
        return False

    print("Building node to relation mapping...")
    node_to_relations = build_node_to_relation_mapping(use_cache)
    print(f"Mapped {len(node_to_relations)} nodes to road relations")

    print("Processing paths and ramps...")

    # Create dictionaries for efficient lookup
    way_dict = {way.id: way for way in ways}
    node_dict = {node.id: node for node in nodes}

    # Process individual paths from ways
    paths = [process_single_path(way) for way in ways]
    print(f"Processed {len(paths)} paths")

    # Group paths into ramps
    paths = break_paths_at_connections(paths, node_dict)
    ramps = group_paths_to_ramps(paths)
    print(f"Grouped into {len(ramps)} ramps")

    # Group ramps into interchanges
    interchanges = group_ramps_by_interchange(ramps, 0.005)
    print(f"Identified {len(interchanges)} interchanges")

    # Apply manual tuning for specific interchanges
    interchanges = tune_interchange(interchanges)
    print(f"After tuning: {len(interchanges)} interchanges")

    # Annotate interchanges with proper names and ramp destinations
    interchanges = [
        annotate_interchange(interchange, node_dict, way_dict, node_to_relations, use_cache)
        for interchange in interchanges
    ]
    print(f"Annotated {len(interchanges)} interchanges")

    json_file_path = save_interchanges(interchanges)
    print(f"Successfully saved interchanges to {json_file_path}")

    # Print first few interchanges as sample
    # pprint(interchanges[:3])

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
