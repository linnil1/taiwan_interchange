import re
from collections import defaultdict

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from graph_operations import (
    assign_branch_ids,
    build_dag_edges,
    calculate_distance,
    connect_ramps_by_nodes,
    contract_paths_to_ramps,
    get_reverse_topological_order,
)
from models import Bounds, Interchange, Node, Path, Ramp, Relation
from osm import (
    OverPassNode,
    OverPassResponse,
    OverPassWay,
    extract_to_destination,
    is_node_traffic_light,
    load_freeway_routes,
    load_nearby_weigh_stations,
    load_overpass,
    load_provincial_routes,
    load_unknown_end_nodes,
)
from persistence import save_interchanges


def normalize_weigh_station_name(station_name: str) -> str:
    """
    Normalize weigh station names by removing directional suffixes.

    Examples:
    - "頭城南向地磅站" -> "頭城地磅站"
    - "xxx向地磅站" -> "xxx地磅站"
    """

    # Pattern to match directional suffixes like "南向", "北向", "東向", "西向" before "地磅站"
    pattern = r"(.+?)[東西南北]向地磅站$"
    match = re.match(pattern, station_name)
    if match:
        return match.group(1) + "地磅站"
    return station_name


def load_and_filter_weigh_stations(use_cache: bool = True) -> list[OverPassWay]:
    """
    Load weigh stations from API and filter for valid entries.

    Returns:
        List of filtered OverPassWay objects with name and geometry
    """
    print("Loading weigh stations...")
    weigh_stations_response = load_nearby_weigh_stations(use_cache)
    weigh_stations = weigh_stations_response.list_ways()
    weigh_stations = [ws for ws in weigh_stations if ws.tags.get("name") and ws.geometry]
    print(f"Found {len(weigh_stations)} weigh stations")
    return weigh_stations


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


## connect_paths moved to graph_operations.py as contract_paths_to_ramps and connect_ramps_by_nodes


def annotate_ramp_by_way(ramp: Ramp, way_dict: dict[int, OverPassWay]) -> list[str]:
    """Annotate ramp with destinations from OSM way dictionary"""
    all_destinations = []

    for path in ramp.paths:
        way = way_dict.get(path.id)
        if way:
            dest_list = extract_to_destination(way)
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
    """
    Propagate destination information upstream using reverse topological order on the DAG view.
    Uses get_reverse_topological_order (built from dag_to edges).
    """
    if not ramps:
        return ramps

    ramp_dict = {ramp.id: ramp for ramp in ramps}

    # Get topological order (downstream to upstream) using refactored function
    ramps = get_reverse_topological_order(ramps)

    # Process ramps in reverse topological order (DAG-based)
    for ramp in ramps:
        # Collect destinations from all downstream ramps
        for downstream_ramp_id in ramp.dag_to:
            downstream_ramp = ramp_dict.get(downstream_ramp_id)
            if downstream_ramp:
                ramp.destination.extend(downstream_ramp.destination)

        # Remove duplicates
        ramp.destination = list(set(ramp.destination))

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
    # original destination: weight station is already set before this func
    all_destinations = ramp.destination

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


def merge_interchanges(interchanges: list[Interchange]) -> Interchange:
    """Merge interchanges"""
    ramps = []
    for interchange in interchanges:
        ramps.extend(interchange.ramps)
    merged_interchange = create_interchange_from_ramps(ramps, interchanges[0].id)
    merged_interchange.name = interchanges[0].name
    return merged_interchange


def group_ramps_by_interchange(
    ramps: list[Ramp], distance_threshold: float = 0.005
) -> list[Interchange]:
    """Group ramps by interchange using minimum distance clustering with all nodes"""
    if not ramps:
        return []

    # Collect all nodes from all ramps, grouped by branch_id (precomputed components)
    all_nodes = []
    branch_to_ramps: dict[int, list[Ramp]] = defaultdict(list)
    for r in ramps:
        branch_to_ramps[r.branch_id].append(r)
    node_to_cramps = []

    for key, ramps_group in enumerate(branch_to_ramps.values()):
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
                # Map cramp_id back into the branch_to_ramps order we enumerated above
                branch_id = list(branch_to_ramps.keys())[cramp_id]
                cluster_ramps.extend(branch_to_ramps[branch_id])
        if cluster_ramps:
            interchange = create_interchange_from_ramps(cluster_ramps, len(interchanges) + 1)
            interchanges.append(interchange)
    return interchanges


def tune_interchange(
    interchanges: list[Interchange],
) -> list[Interchange]:
    """
    Manual tuning of interchanges after initial clustering.
    Workflow:
    1. Merge interchanges with identical names
    2. Split interchanges whose names contain semicolons
    """

    interchange_names = defaultdict(list)
    for interchange in interchanges:
        interchange_names[interchange.name].append(interchange)

    new_interchanges = []
    for name, interchanges_group in interchange_names.items():
        if len(interchanges_group) > 1:
            merged = merge_interchanges(interchanges_group)
            new_interchanges.append(merged)
        elif ";" in name:
            new_interchanges.extend(group_ramps_by_interchange(interchanges_group[0].ramps, 0.001))
        else:
            new_interchanges.append(interchanges_group[0])

    for i, interchange in enumerate(new_interchanges):
        interchange.id = i + 1

    return new_interchanges


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


def find_closest_weigh_station_name(
    ramp: Ramp, weigh_stations: list[OverPassWay], threshold_km: float = 2.0
) -> str | None:
    """
    Find the closest weigh station name to the ramp's end node within threshold distance

    Args:
        ramp: Ramp object to find station for
        weigh_station_ways: List of OverPassWay objects containing weigh station data
        threshold_km: Maximum distance threshold in kilometers

    Returns:
        Weigh station name if found within threshold, None otherwise
    """
    # Get 10 evenly spaced nodes from the ramp
    nodes = ramp.list_nodes()
    step = len(nodes) // 10
    step = step if step > 0 else 1  # Ensure step is at least 1
    nodes = nodes[::step]

    closest_distance = float("inf")
    closest_station_name = None

    for station in weigh_stations:
        coord = station.geometry[0]
        distances = [calculate_distance(node.lat, node.lng, coord.lat, coord.lng) for node in nodes]
        distance = min(distances) if distances else float("inf")
        if distance < closest_distance:
            closest_distance = distance
            closest_station_name = station.tags["name"]

    # Return station name only if within threshold
    if closest_distance <= threshold_km:
        return closest_station_name
    return None


def annotate_interchange_name(
    interchange: Interchange,
    node_dict: dict[int, OverPassNode],
    weigh_stations: list[OverPassWay],
    distance_threshold_km: float = 0.05,
) -> Interchange:
    """
    Annotate single interchange with proper name based on motorway_junction nodes
    If no junction name found, try to find nearby weigh stations within threshold distance
    """
    # Extract proper name from motorway_junction nodes
    junction_name = extract_name_from_interchange(interchange.ramps, node_dict)

    if junction_name:
        # Use the junction name
        interchange.name = junction_name
        return interchange

    # No junction name found, try to find nearby weigh stations
    name, ramp_to_station = get_interchange_and_ramp_name_by_weight_stations(
        interchange.ramps, interchange, weigh_stations, distance_threshold_km
    )
    if name:
        interchange.name = name
        for ramp in interchange.ramps:
            if ramp.id in ramp_to_station:
                ramp.destination.append(ramp_to_station[ramp.id])

    return interchange


def get_interchange_and_ramp_name_by_weight_stations(
    interchange_ramps: list[Ramp],
    interchange: Interchange,
    weigh_stations: list[OverPassWay],
    distance_threshold_km: float = 0.05,
) -> tuple[str, dict[int, str]]:
    # First, find all weigh stations for all ramps (store original names)
    ramp_to_station = {}
    for ramp in interchange_ramps:
        weigh_station_name = find_closest_weigh_station_name(
            ramp, weigh_stations, distance_threshold_km
        )
        if weigh_station_name:
            ramp_to_station[ramp.id] = weigh_station_name

    # Check if we found any weigh stations
    if not ramp_to_station:
        return "", {}

    # Fix max occur and assign it using branch_id groupings
    branch_to_ramps: dict[int, list[Ramp]] = defaultdict(list)
    for r in interchange.ramps:
        branch_to_ramps[r.branch_id].append(r)
    for ramps in branch_to_ramps.values():
        station_name_count = defaultdict(int)
        for ramp in ramps:
            if ramp.id in ramp_to_station:
                station_name_count[ramp_to_station[ramp.id]] += 1
        if not station_name_count:
            continue
        most_frequent_name = max(station_name_count.keys(), key=lambda x: station_name_count[x])
        for ramp in ramps:
            if ramp.id in ramp_to_station:
                ramp_to_station[ramp.id] = most_frequent_name
    return normalize_weigh_station_name(list(ramp_to_station.values())[0]), ramp_to_station


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
    weigh_stations: list[OverPassWay],
    use_cache: bool = True,
) -> Interchange:
    """Annotate single interchange with proper name and ramp destinations"""
    # First annotate the interchange name
    interchange = annotate_interchange_name(interchange, node_dict, weigh_stations)

    # Then annotate the ramps
    interchange = annotate_interchange_ramps(interchange, way_dict, node_to_relations, use_cache)

    return interchange


def process_relations_by_way(response: OverPassResponse, road_type: str) -> dict[int, Relation]:
    """Process relations by way and return node to relation mapping"""
    ways = response.list_ways()
    node_to_relation = {}

    # Process ways
    for way in ways:
        if not way.tags.get("name"):
            continue
        relation = Relation(name=way.tags["name"], road_type=road_type)
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
            road_type=road_type,
        )

        # Get all way members from this relation
        way_ids_in_relation = set()
        for member in relation.members:
            if member.type == "way":
                way_ids_in_relation.add(member.ref)

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
    ways = [i for i in ways if i.tags.get("access") not in ["private", "no", "emergency"]]
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
    ramps = contract_paths_to_ramps(paths)
    ramps = connect_ramps_by_nodes(ramps)
    # Build DAG view without altering full graph
    ramps = build_dag_edges(ramps)
    print(f"Grouped into {len(ramps)} ramps")

    # Annotate branch/component ids on paths for downstream grouping
    ramps = assign_branch_ids(ramps)

    # Group ramps into interchanges
    interchanges = group_ramps_by_interchange(ramps, 0.005)
    print(f"Identified {len(interchanges)} interchanges")

    # Load weigh stations for naming fallback
    weigh_stations = load_and_filter_weigh_stations(use_cache)

    # Apply manual tuning for specific interchanges (require annotate name first)
    interchanges = [
        annotate_interchange_name(interchange, node_dict, weigh_stations)
        for interchange in interchanges
    ]
    interchanges = tune_interchange(interchanges)
    print(f"After tuning: {len(interchanges)} interchanges")

    # Annotate interchanges with proper ramp destinations
    # (the interchange is annotated again)
    interchanges = [
        annotate_interchange(
            interchange, node_dict, way_dict, node_to_relations, weigh_stations, use_cache
        )
        for interchange in interchanges
    ]
    print(f"Annotated {len(interchanges)} interchanges")

    json_file_path = save_interchanges(interchanges)
    print(f"Successfully saved interchanges to {json_file_path}")

    # Print first few interchanges as sample
    # pprint(interchanges[:3])

    return True


if __name__ == "__main__":
    print("Generating interchanges data from Overpass API...")
    success = generate_interchanges_json(use_cache=True)
    if success:
        print("\n✅ Successfully generated interchanges.json")
        print("You can now run the Flask app with: python app.py")
    else:
        print("\n❌ Failed to generate interchanges.json")
