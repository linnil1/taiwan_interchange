from collections import Counter, defaultdict
from collections.abc import Iterable
from itertools import chain

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from graph_operations import (
    assign_branch_ids,
    build_dag_edges,
    connect_ramps_by_nodes,
    contract_paths_to_ramps,
    extract_endpoint_ways,
    filter_endpoints_by_motorway_link,
    get_reverse_topological_order,
)
from models import Interchange, Node, Ramp
from osm import (
    OverPassWay,
    load_freeway_routes,
    load_nearby_weigh_stations,
    load_overpass,
    load_provincial_routes,
    load_unknown_end_nodes,
)
from osm_operations import (
    extract_freeway_related_ways,
    is_way_access,
    normalize_weigh_station_name,
    process_relations_mapping,
)
from path_operations import (
    break_paths_by_endpoints,
    break_paths_by_traffic_lights,
    concat_paths,
    process_single_path,
)
from persistence import save_interchanges
from relation_operations import (
    NodeRelationMap,
    WayRelationMap,
    build_weigh_way_relations,
    extract_ramp_name_by_end_node_relation,
    extract_ramp_name_by_node_relation,
    extract_ramp_name_by_way_relation,
    wrap_junction_name_relation,
    wrap_relation_to_node_relation,
    wrap_ways_as_node_relation,
    wrap_ways_as_relation,
)
from utils import (
    calculate_bounds,
    choose_modal_per_group,
    ramp_contains_way,
    renumber_interchanges,
)

# ---- Special-case configuration ----
# Branch isolation: if a branch contains any of these way IDs, make that branch a standalone interchange
SPECIAL_ISOLATE_BRANCH_WAY_IDS: set[int] = {
    135638645,  # 南深路出口匝道
    328852477,  # 環北交流道
    50893495,  # 環北交流道
    922785991,  # 大鵬灣端
    612035219,  # 大鵬灣端
    383444253,  # 左營端
    277512394,  # 左營端
    564743832,  # 左營端
    277512777,  # 左營端
}

# Explicit interchange name overrides when an interchange contains a way ID
WAY_TO_INTERCHANGE_NAME: dict[int, str] = {
    534195515: "校前路交流道",
    247148858: "西螺交流道;西螺服務區",
    136861416: "高工局",
    260755985: "田寮地磅站",
    328852477: "環北交流道",
    50893495: "環北交流道",
    922785991: "大鵬灣端",
    612035219: "大鵬灣端",
    383444253: "左營端",
    277512394: "左營端",
    564743832: "左營端",
    277512777: "左營端",
}

# Ignore specific nodes when extracting names (these should not name interchanges)
IGNORED_NODE_IDS: set[int] = {1095916940, 623059692}  # 泰安服務區, 濱江街出口


def isolate_interchanges_by_branch(
    interchanges: list[Interchange], isolate_way_ids: set[int]
) -> list[Interchange]:
    """
    If an interchange contains a branch that has any of `isolate_way_ids`, split that branch
    into its own interchange. Other branches remain with the original interchange.
    """
    result: list[Interchange] = []
    new_interchanges: list[Interchange] = []

    for ic in interchanges:
        # Group ramps by branch_id inside this interchange
        by_branch: dict[int, list[Ramp]] = defaultdict(list)
        for r in ic.ramps:
            by_branch[r.branch_id].append(r)

        # Find branches to isolate
        branches_to_isolate: list[int] = []
        for branch_id, ramps in by_branch.items():
            if any(ramp_contains_way(ramps, way_id) for way_id in isolate_way_ids):
                branches_to_isolate.append(branch_id)

        if not branches_to_isolate:
            result.append(ic)
            continue

        # Keep original interchange with non-isolated branches (if any)
        kept_ramps: list[Ramp] = [r for r in ic.ramps if r.branch_id not in branches_to_isolate]
        if kept_ramps:
            kept_ic = create_interchange_from_ramps(kept_ramps, id=ic.id)
            kept_ic.name = ic.name
            result.append(kept_ic)

        # Create standalone interchanges for each isolated branch
        for b in branches_to_isolate:
            branch_ramps = by_branch[b]
            new_ic = create_interchange_from_ramps(branch_ramps, id=0)
            new_ic.name = ic.name  # will be re-annotated later
            new_interchanges.append(new_ic)

    # Renumber and return combined list
    combined = result + new_interchanges
    return renumber_interchanges(combined)


def override_interchange_names_by_way(
    interchanges: list[Interchange], mapping: dict[int, str] = WAY_TO_INTERCHANGE_NAME
) -> list[Interchange]:
    """
    Override interchange names if they contain any specific way IDs defined in `mapping`.
    Mutates interchanges in place and also returns the list for convenience.
    """
    for ic in interchanges:
        for way_id, name in mapping.items():
            if ramp_contains_way(ic.ramps, way_id):
                ic.name = name
                break
    return interchanges


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


def annotate_ramps_by_propagating(ramps: list[Ramp]) -> list[Ramp]:
    """
    Propagate destination information upstream using reverse topological order of the DAG.
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
    """Annotate ramps by querying unknown end nodes for ramps with empty destinations."""
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

    node_to_relation = wrap_ways_as_node_relation(response.list_ways(), road_type="unknown")
    for ramp in ramps:
        destinations = extract_ramp_name_by_end_node_relation(ramp, node_to_relation)
        ramp.destination.extend(destinations)
    return ramps


def annotate_ramp(
    ramp: Ramp,
    way_to_relations: WayRelationMap | None = None,
    node_to_relations: NodeRelationMap | None = None,
    weigh_way_to_relations: WayRelationMap | None = None,
) -> Ramp:
    """Annotate a single ramp with destinations using priority:
    1) end-node relation; 2) weigh-station way relation; 3) generic way relation.
    """
    # original destination: weight station is already set before this func
    all_destinations = list(ramp.destination)

    # 1) end-node relation
    if not all_destinations and node_to_relations:
        end_node_dests = extract_ramp_name_by_end_node_relation(ramp, node_to_relations)
        all_destinations.extend(end_node_dests)

    # 2) weigh-station way relation
    if not all_destinations and weigh_way_to_relations:
        weigh_dests = extract_ramp_name_by_way_relation(ramp, weigh_way_to_relations)
        all_destinations.extend(weigh_dests)

    # 3) generic way relation
    if not all_destinations and way_to_relations:
        way_dests = extract_ramp_name_by_way_relation(ramp, way_to_relations)
        all_destinations.extend(way_dests)

    # Assign de-duplicated
    ramp.destination = list(set(all_destinations))
    return ramp


def merge_interchanges(interchanges: list[Interchange]) -> Interchange:
    """Merge multiple interchanges into one, preserving the first's id/name."""
    ramps = []
    for interchange in interchanges:
        ramps.extend(interchange.ramps)
    merged_interchange = create_interchange_from_ramps(ramps, interchanges[0].id)
    merged_interchange.name = interchanges[0].name
    return merged_interchange


def group_ramps_to_interchange(
    ramps: list[Ramp], distance_threshold: float = 0.005
) -> list[Interchange]:
    """Group ramps into interchanges using single-linkage clustering over nodes."""
    if not ramps:
        return []

    # Collect all nodes from all ramps, grouped by branch_id
    all_nodes = []
    branch_to_ramps: dict[int, list[Ramp]] = defaultdict(list)
    for r in ramps:
        branch_to_ramps[r.branch_id].append(r)
    for ramp in ramps:
        for node in ramp.list_nodes():
            all_nodes.append((node.lat, node.lng, ramp.branch_id))

    if len(all_nodes) < 2:
        return [create_interchange_from_ramps(ramps, 1)]

    # Use agglomerative clustering with distance threshold
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        linkage="single",  # minimum distance between groups
    )
    nodes_array = np.array([node[:2] for node in all_nodes])
    node_labels = clustering.fit_predict(nodes_array)

    # rearrange cluster label by branch id
    branch_to_clusters = defaultdict(list)
    for node_idx, cluster_label in enumerate(node_labels):
        branch_id = all_nodes[node_idx][2]
        branch_to_clusters[branch_id].append(cluster_label)

    # Get the modal cluster per branch
    branch_assignment = choose_modal_per_group(branch_to_clusters)
    cluster_to_branch = defaultdict(list)
    for branch_id, cluster_label in branch_assignment.items():
        cluster_to_branch[cluster_label].append(branch_id)

    # Create interchange objects
    interchanges = []
    for cluster_label, branch_ids in cluster_to_branch.items():
        ramps = [ramp for branch_id in branch_ids for ramp in branch_to_ramps[branch_id]]
        if ramps:
            interchange = create_interchange_from_ramps(ramps, len(interchanges) + 1)
            interchanges.append(interchange)
    return interchanges


def split_interchanges_by_name_marker(
    interchanges: list[Interchange], *, distance_threshold: float = 0.001
) -> list[Interchange]:
    """
    Split interchanges whose names contain semicolons (';') by re-grouping their ramps.

    Args:
        interchanges: List of interchanges to process
        distance_threshold: Threshold passed to group_ramps_by_interchange

    Returns:
        A new list of interchanges where any semicolon-named entry may be split into multiple.
    """
    result: list[Interchange] = []
    for ic in interchanges:
        if ";" in ic.name:
            print(f"Splitting interchange: {ic.name}")
            result.extend(group_ramps_to_interchange(ic.ramps, distance_threshold))
        else:
            result.append(ic)
    return renumber_interchanges(result)


def merge_interchanges_by_name(interchanges: list[Interchange]) -> list[Interchange]:
    """
    Merge interchanges that share the exact same name.

    Returns:
        A list of interchanges with duplicates (by name) merged.
    """
    name_to_group: dict[str, list[Interchange]] = defaultdict(list)
    for ic in interchanges:
        name_to_group[ic.name].append(ic)

    merged: list[Interchange] = []
    for name, group in name_to_group.items():
        if name == "Unknown Interchange":
            merged.extend(group)
            continue
        if len(group) > 1:
            combined = merge_interchanges(group)
            print(f"Merged interchanges: {name}")
            merged.append(combined)
        else:
            merged.append(group[0])
    return renumber_interchanges(merged)


def create_interchange_from_ramps(ramps: list[Ramp], id: int) -> Interchange:
    # Calculate bounds from all ramp nodes
    all_nodes: Iterable[Node] = chain.from_iterable(ramp.list_nodes() for ramp in ramps)
    bounds = calculate_bounds(all_nodes)
    if not bounds:
        raise ValueError("No valid bounds could be calculated for the interchange")

    # Generate interchange name based on destinations (simplified)
    destinations = set()
    for ramp in ramps:
        if ramp.destination:
            destinations.update(ramp.destination)

    interchange_name = "Unknown Interchange"
    return Interchange(id=id, name=interchange_name, bounds=bounds, ramps=ramps)


def annotate_interchange_name(
    interchange: Interchange,
    junction_node_rel: NodeRelationMap,
    weigh_way_rel: WayRelationMap,
) -> Interchange:
    """
    Annotate single interchange with proper name based on motorway_junction nodes
    If no junction name found, try to find nearby weigh stations within threshold distance
    """
    # Derive junction name(s) via provided node relations
    names: set[str] = set()
    for ramp in interchange.ramps:
        names.update(extract_ramp_name_by_node_relation(ramp, junction_node_rel))
    if names:
        interchange.name = ";".join(sorted(names))
        return interchange

    # Fallback: if no junction name, try weigh-station way relations
    weigh_names: set[str] = set()
    for ramp in interchange.ramps:
        weigh_names.update(extract_ramp_name_by_way_relation(ramp, weigh_way_rel))
    if weigh_names:
        weigh_names = set(normalize_weigh_station_name(name) for name in weigh_names if name)
        interchange.name = ";".join(sorted(weigh_names))
    return interchange


def annotate_interchange_ramps(
    interchange: Interchange,
    way_to_relations: WayRelationMap | None = None,
    node_to_relations: NodeRelationMap | None = None,
    weigh_way_to_relations: WayRelationMap | None = None,
    use_cache: bool = True,
) -> Interchange:
    """Annotate all ramps in an interchange with destinations."""
    # First annotate individual ramps
    ramps = [
        annotate_ramp(
            ramp,
            way_to_relations=way_to_relations,
            node_to_relations=node_to_relations,
            weigh_way_to_relations=weigh_way_to_relations,
        )
        for ramp in interchange.ramps
    ]

    # Then use query unknown for ramps with empty destinations
    # ramps = annotate_ramps_by_query_unknown(ramps, interchange.name, use_cache)

    # Finally, propagate destinations upstream from exit ramps to entry ramps
    ramps = annotate_ramps_by_propagating(ramps)

    return Interchange(
        id=interchange.id,
        name=interchange.name,
        bounds=interchange.bounds,
        ramps=ramps,
    )


def build_highway_relation(use_cache: bool = True) -> NodeRelationMap:
    """Build mapping from node id to road relation objects (freeway, provincial)."""
    # Process each type and combine results with priority: freeway > provincial
    node_to_relations = {}

    # Process provincial (low priority)
    response_provincial = load_provincial_routes(use_cache)
    provincial_rel = process_relations_mapping(response_provincial)
    provincial_mapping = wrap_relation_to_node_relation(provincial_rel, "provincial")
    node_to_relations.update(provincial_mapping)

    # Process freeway
    response_freeway = load_freeway_routes(use_cache)
    freeway_rel = process_relations_mapping(response_freeway)
    freeway_mapping = wrap_relation_to_node_relation(freeway_rel, "freeway")
    node_to_relations.update(freeway_mapping)

    return NodeRelationMap(node_to_relations)


def generate_interchanges_json(use_cache: bool = True) -> bool:
    """
    The main function:
    Generate interchanges.json from Overpass API data group them by interchange
    """
    print("Getting Overpass data...")
    response = load_overpass(use_cache)
    ways = response.list_ways()
    ways = [i for i in ways if is_way_access(i)]
    nodes = response.list_nodes()
    print(f"Loaded {len(ways)} motorway_link ways and {len(nodes)} motorway junction nodes")

    if not ways or not nodes:
        print("No motorway links/nodes found in Taiwan")
        return False

    # Also include the very first/last non-motorway_link ways at freeway endpoints
    freeway_resp = load_freeway_routes(use_cache)
    freeway_ways = extract_freeway_related_ways(freeway_resp)
    freeway_paths = [process_single_path(way) for way in freeway_ways]
    freeway_endpoints = extract_endpoint_ways(freeway_paths)
    print(f"Found {len(freeway_endpoints)} freeway endpoint ways (pre-filter)")
    # We'll filter right before concatenation when motorway_link paths are available

    print("Processing paths and ramps...")
    # Create dictionaries / mappings for efficient lookup
    node_dict = {node.id: node for node in nodes}
    way_to_relations = wrap_ways_as_relation(ways, road_type="way")
    junction_node_rel = wrap_junction_name_relation(node_dict, IGNORED_NODE_IDS)
    paths = [process_single_path(way) for way in ways]
    print(f"Processed {len(paths)} paths")

    # Filter freeway endpoints by motorway_link connectivity and then concatenate
    freeway_endpoints = filter_endpoints_by_motorway_link(freeway_endpoints, paths)
    paths = concat_paths(paths, freeway_endpoints)
    print(
        f"Found {len(paths)} total paths (motorway_link + freeway endpoints) and {len(nodes)} motorway junctions"
    )

    # Group paths into ramps
    paths = break_paths_by_endpoints(paths)
    paths = break_paths_by_traffic_lights(paths, node_dict)
    ramps = contract_paths_to_ramps(paths)
    ramps = connect_ramps_by_nodes(ramps)
    ramps = build_dag_edges(ramps)
    ramps = assign_branch_ids(ramps)
    print(f"Grouped into {len(ramps)} ramps")

    # Group ramps into interchanges
    interchanges = group_ramps_to_interchange(ramps, 0.005)
    print(f"Identified {len(interchanges)} interchanges")
    interchanges = isolate_interchanges_by_branch(interchanges, SPECIAL_ISOLATE_BRANCH_WAY_IDS)

    # Load weigh stations for naming fallback
    # Build a global mapping: way_id -> weigh-station relation
    weigh_stations = load_and_filter_weigh_stations(use_cache)
    print(f"Loaded {len(weigh_stations)} weigh stations")
    weigh_way_rel = build_weigh_way_relations(ways, weigh_stations)

    # Build junction relation mapping once and use for naming
    # Apply manual tuning for specific interchanges (require annotate name first)
    interchanges = [
        annotate_interchange_name(interchange, junction_node_rel, weigh_way_rel)
        for interchange in interchanges
    ]
    # Split first, then merge
    interchanges = split_interchanges_by_name_marker(interchanges, distance_threshold=0.001)
    interchanges = override_interchange_names_by_way(interchanges, WAY_TO_INTERCHANGE_NAME)
    interchanges = merge_interchanges_by_name(interchanges)

    # Annotate interchange again, and annotate ramp
    interchanges = [
        annotate_interchange_name(interchange, junction_node_rel, weigh_way_rel)
        for interchange in interchanges
    ]
    interchanges = merge_interchanges_by_name(interchanges)
    print(f"After merge: {len(interchanges)} interchanges")

    print("Building node to relation mapping...")
    node_to_relations = build_highway_relation(use_cache)
    print(f"Mapped {len(node_to_relations)} nodes to road relations")

    # We already have weigh_way_rel for all ways
    print(f"Prepared {len(weigh_way_rel)} weigh-station relations (way-based)")
    interchanges = [
        annotate_interchange_ramps(
            interchange,
            way_to_relations=way_to_relations,
            node_to_relations=node_to_relations,
            weigh_way_to_relations=weigh_way_rel,
            use_cache=use_cache,
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
