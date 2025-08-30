from collections import Counter, defaultdict
from collections.abc import Iterable
from itertools import chain

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from graph_operations import (
    assign_branch_ids,
    build_dag_edges,
    build_ordered_node_ids_for_relation,
    connect_ramps_by_nodes,
    contract_paths_to_ramps,
    extract_endpoint_ways,
    filter_endpoints_by_motorway_link,
    get_reverse_topological_order,
)
from models import Destination, DestinationType, Interchange, Node, Ramp
from osm import (
    OverPassRelation,
    OverPassResponse,
    load_adjacent_road_relations,
    load_elevated_freeway_relation,
    load_freeway_routes,
    load_nearby_weigh_stations,
    load_overpass,
    load_provincial_routes,
    load_unknown_end_nodes,
)
from osm_operations import (
    display_for_master,
    extract_freeway_related_ways,
    filter_weight_stations,
    list_master_relations,
    normalize_weigh_station_name,
    process_relations_mapping,
    wrap_elevated_relation_as_route_master,
)
from path_operations import (
    break_paths_by_endpoints,
    break_paths_by_traffic_lights,
    concat_paths,
    filter_accessible_ways,
    process_paths_from_ways,
)
from persistence import save_interchanges
from relation_operations import (
    NodeRelationMap,
    WayRelationMap,
    build_weigh_way_relations,
    extract_ramp_name_by_end_node_relation,
    extract_ramp_name_by_node_relation,
    extract_ramp_name_by_start_node_relation,
    extract_ramp_name_by_way_relation,
    wrap_adj_road_relation,
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
    1280474016,  # 大雅系統交流道
    1281360457,  # 大雅系統交流道
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
    1280474016: "大雅系統交流道",
    1281360457: "大雅系統交流道",
    692642782: "樹林交流道",
    763190947: "樹林交流道",
    84618525: "羅東交流道",
    1174712096: "羅東交流道",
}

# Ignore specific nodes when extracting names (these should not name interchanges)
IGNORED_NODE_IDS: set[int] = {
    1095916940,  # 泰安服務區
    623059692,  # 濱江街出口
    1489583190,  # 石碇服務區
}

# Exclude specific motorway_link ways entirely when building paths (data quirks, known bad)
EXCLUDED_WAY_IDS: set[int] = set()

# Preserve these freeway endpoint ways even if they fail the connectivity filter
PRESERVED_ENDPOINT_WAY_IDS: set[int] = {439876652, 439876651}  # 機場端


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
        collected: list[Destination] = []
        for downstream_ramp_id in ramp.to_ramps:
            downstream_ramp = ramp_dict.get(downstream_ramp_id)
            if downstream_ramp and downstream_ramp.destination:
                collected.extend(downstream_ramp.destination)

        if collected:
            # If both EXIT and ENTER exist among downstream destinations, propagate only EXIT
            has_exit = any(d.type == DestinationType.EXIT for d in collected)
            has_enter = any(d.type == DestinationType.ENTER for d in collected)
            if has_exit and has_enter:
                collected = [d for d in collected if d.type != DestinationType.ENTER]

            # Merge into ramp.destination with de-dup on (name,type)
            existing = {(d.name, d.type) for d in ramp.destination}
            for d in collected:
                key = (d.name, d.type)
                if key not in existing:
                    ramp.destination.append(d)
                    existing.add(key)

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
        names = extract_ramp_name_by_end_node_relation(ramp, node_to_relation)
        if not names:
            continue
        # Unknown end node implies exiting freeway
        for name in names:
            dest = Destination(name=name, type=DestinationType.EXIT)
            ramp.destination.append(dest)
        ramp.destination = list(set(ramp.destination))
    return ramps


def annotate_ramp(
    ramp: Ramp,
    way_to_relations: WayRelationMap | None = None,
    freeway_node_rel: NodeRelationMap | None = None,
    provincial_node_rel: NodeRelationMap | None = None,
    junction_node_rel: NodeRelationMap | None = None,
    weigh_way_to_relations: WayRelationMap | None = None,
    endnode_adjacent_relations: NodeRelationMap | None = None,
) -> Ramp:
    """Annotate a single ramp with destinations using priority:
    1) weigh-station way relation (EXIT);
    2) freeway end-node relation (ENTER);
    3) provincial end-node relation (ENTER);
    4) end-node adjacent route relation (EXIT);
    5) generic OSM way relation (lowest, OSM).
    """
    all_destinations: list[Destination] = []

    # 1) weigh-station way relation (top priority)
    if not all_destinations and weigh_way_to_relations:
        weigh_names = extract_ramp_name_by_way_relation(ramp, weigh_way_to_relations)
        # weigh station implies EXIT direction
        all_destinations.extend(Destination(name=n, type=DestinationType.EXIT) for n in weigh_names)

    # 2) freeway end-node relation
    if not all_destinations and freeway_node_rel:
        freeway_names = extract_ramp_name_by_end_node_relation(ramp, freeway_node_rel)
        all_destinations.extend(
            Destination(name=n, type=DestinationType.ENTER) for n in freeway_names
        )

    # 3) provincial end-node relation
    if not all_destinations and provincial_node_rel:
        provincial_names = extract_ramp_name_by_end_node_relation(ramp, provincial_node_rel)
        all_destinations.extend(
            Destination(name=n, type=DestinationType.ENTER) for n in provincial_names
        )

    # 4) end-node adjacent route relation (EXIT)
    if not all_destinations and endnode_adjacent_relations:
        adj_names = extract_ramp_name_by_end_node_relation(ramp, endnode_adjacent_relations)
        all_destinations.extend(Destination(name=n, type=DestinationType.EXIT) for n in adj_names)

    # 5) generic node relation by start node (junction names) just above generic way
    if not all_destinations and junction_node_rel:
        start_node_names = extract_ramp_name_by_start_node_relation(ramp, junction_node_rel)
        all_destinations.extend(
            Destination(name=n, type=DestinationType.OSM) for n in start_node_names
        )

    # 6) generic way relation (lowest priority)
    if not all_destinations and way_to_relations:
        way_names = extract_ramp_name_by_way_relation(ramp, way_to_relations)
        all_destinations.extend(Destination(name=n, type=DestinationType.OSM) for n in way_names)

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
    # Collect junction names (motorway_junction nodes)
    names: set[str] = set()
    for ramp in interchange.ramps:
        names.update(extract_ramp_name_by_node_relation(ramp, junction_node_rel))

    # Also include weigh-station names
    weigh_names: set[str] = set()
    for ramp in interchange.ramps:
        weigh_names.update(extract_ramp_name_by_way_relation(ramp, weigh_way_rel))
    if weigh_names:
        weigh_names = set(normalize_weigh_station_name(name) for name in weigh_names if name)

    combined = sorted(set(n for n in list(names) + list(weigh_names) if n))
    if combined:
        interchange.name = ";".join(combined)
    return interchange


def annotate_interchange_ramps(
    interchange: Interchange,
    way_to_relations: WayRelationMap | None = None,
    freeway_node_rel: NodeRelationMap | None = None,
    provincial_node_rel: NodeRelationMap | None = None,
    junction_node_rel: NodeRelationMap | None = None,
    weigh_way_to_relations: WayRelationMap | None = None,
    endnode_adjacent_relations: NodeRelationMap | None = None,
    use_cache: bool = True,
) -> Interchange:
    """Annotate all ramps in an interchange with destinations."""
    # First annotate individual ramps
    ramps = [
        annotate_ramp(
            ramp,
            way_to_relations=way_to_relations,
            freeway_node_rel=freeway_node_rel,
            provincial_node_rel=provincial_node_rel,
            junction_node_rel=junction_node_rel,
            weigh_way_to_relations=weigh_way_to_relations,
            endnode_adjacent_relations=endnode_adjacent_relations,
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


def build_exit_relation(response: OverPassResponse, road_type: str) -> NodeRelationMap:
    """Build node->relation mapping for exits/roads from a single Overpass response.

    Takes an OverPassResponse and returns a NodeRelationMap of node_id -> Relation(name, road_type)
    based on relation membership.
    """
    rel_tuples = process_relations_mapping(response)
    return wrap_relation_to_node_relation(rel_tuples, road_type)


def preferred_route_score(rel: OverPassRelation) -> tuple[int, str]:
    """Score a route relation for selection under a master by name preference."""
    name = (rel.tags or {}).get("name", "")
    for idx, token in enumerate(["南向", "南下", "順向", "東向"]):
        if token in name:
            return (0, f"{idx}_{name}")
    return (1, name)


def get_preferred_route_for_master(
    master: OverPassRelation, rel_by_id: dict[int, OverPassRelation]
) -> OverPassRelation | None:
    """Extract the preferred route relation for a master based on name preferences."""
    member_route_ids = [m.ref for m in master.members if m.type == "relation"]
    candidates: list[OverPassRelation] = [
        rel_by_id[rid]
        for rid in member_route_ids
        if rid in rel_by_id and (rel_by_id[rid].tags or {}).get("type") == "route"
    ]
    if not candidates:
        return None
    # Choose preferred route by name tokens
    candidates.sort(key=preferred_route_score)
    if preferred_route_score(candidates[0])[0] == 1 or preferred_route_score(candidates[1])[0] == 0:
        for cd in candidates:
            print(cd.tags)
        raise ValueError(f"No preferred route found for master {master.id}")
    print(f"Choose {candidates[0].tags['name']}")
    return candidates[0]


def build_master_order_index(
    response: OverPassResponse,
) -> dict[int, tuple[str, int, str]]:
    """Build a global node index for freeway masters.

    Returns dict[node_id, (ref, order, name)] where:
    - ref: master tags.ref if present, else master tags.name, else f"master:{id}"
    - order: index along the selected member route's ordered nodes
    - name: master tags.name if present, else ref string

    Constraints: Only uses list_master_relations, process_relations_mapping, and
    build_ordered_node_ids_for_relation.
    """
    # Map relation id -> its member ways (for route relations)
    rel_tuples = process_relations_mapping(response)
    route_rel_ways: dict[int, list] = {}
    rel_by_id: dict[int, OverPassRelation] = {}
    for rel, ways, _ in rel_tuples:  # _nodes not used, so ignore it
        rel_by_id[rel.id] = rel
        if (rel.tags or {}).get("type") == "route":
            route_rel_ways[rel.id] = ways

    node_index: dict[int, tuple[str, int, str]] = {}

    masters = list_master_relations(response)
    # Process masters in ref order for stability
    for master in masters:
        chosen = get_preferred_route_for_master(master, rel_by_id)
        if not chosen:
            raise ValueError(f"No route found for master {master.id}")
        ways = route_rel_ways.get(chosen.id, [])
        if not ways:
            raise ValueError(f"No ways found for route {chosen.id}")
        ordered = build_ordered_node_ids_for_relation(ways)
        if not ordered:
            continue
        mref, mname = display_for_master(master)

        # Merge into global index
        for nid, order in ordered.items():
            new_val = (mref, int(order), mname)
            node_index[nid] = new_val
    return node_index


def reorder_and_annotate_interchanges_by_node_index(
    interchanges: list[Interchange],
    node_index: dict[int, tuple[str, int, str]],
) -> list[Interchange]:
    """Reorder and annotate interchanges based on node_index, sorting by master reference and node order.

    This function processes a list of Interchange objects by:
    - Annotating each interchange's `refs` list with unique master names from nodes in the interchange.
    - Determining the minimum order for each interchange based on the node_index.
    - Sorting the interchanges by their minimum order (master ref, order, master name).
    - Renumbering the sorted interchanges using renumber_interchanges.
    """
    if not interchanges or not node_index:
        return interchanges

    # Create a dictionary for quick interchange lookup by id
    interchanges = renumber_interchanges(interchanges)
    ic_dict = {ic.id: ic for ic in interchanges}

    # Annotate refs and track min order for each interchange, keyed by interchange id
    ic_min_index: dict[int, tuple[str, int, str]] = {}
    for ic in interchanges:
        for n in ic.list_nodes():
            if n.id not in node_index:
                continue
            mref, morder, mname = node_index[n.id]
            if mname not in ic.refs:
                ic.refs.append(mname)
            # Update min order for sorting
            current = ic_min_index.get(ic.id)
            index = (mref, morder, mname)
            if current is None or current > index:
                ic_min_index[ic.id] = index

    interchanges = sorted(
        interchanges, key=lambda ic: ic_min_index.get(ic.id, ("ZZZZZZZZZ", 0, ""))
    )
    return renumber_interchanges(interchanges)


def generate_interchanges_json(use_cache: bool = True) -> bool:
    """
    The main function:
    Generate interchanges.json from Overpass API data group them by interchange
    """
    print("Getting Overpass data...")
    response = load_overpass(use_cache)
    ways = response.list_ways()
    ways = filter_accessible_ways(ways, EXCLUDED_WAY_IDS)
    nodes = response.list_nodes()
    print(f"Loaded {len(ways)} motorway_link ways and {len(nodes)} motorway junction nodes")

    if not ways or not nodes:
        print("No motorway links/nodes found in Taiwan")
        return False

    # Also include the very first/last non-motorway_link ways at freeway endpoints
    freeway_resp = load_freeway_routes(use_cache)
    freeway_ways = extract_freeway_related_ways(freeway_resp)
    freeway_paths = process_paths_from_ways(
        freeway_ways, excluded_ids=None, duplicate_two_way=False
    )
    freeway_endpoints = extract_endpoint_ways(freeway_paths)
    print(f"Found {len(freeway_endpoints)} freeway endpoint ways (pre-filter)")
    # We'll filter right before concatenation when motorway_link paths are available

    print("Processing paths and ramps...")
    # Create dictionaries / mappings for efficient lookup
    node_dict = {node.id: node for node in nodes}
    way_to_relations = wrap_ways_as_relation(ways, road_type="way")
    junction_node_rel = wrap_junction_name_relation(node_dict, IGNORED_NODE_IDS)
    paths = process_paths_from_ways(ways, excluded_ids=None, duplicate_two_way=True)
    print(f"Processed {len(paths)} paths")

    # Filter freeway endpoints by motorway_link connectivity and then concatenate
    freeway_endpoints = filter_endpoints_by_motorway_link(freeway_endpoints, paths)
    paths = concat_paths(paths, freeway_endpoints)

    # Manually add preserved endpoint ways after the first concat
    preserved_paths = [p for p in freeway_paths if p.id in PRESERVED_ENDPOINT_WAY_IDS]
    if preserved_paths:
        paths = concat_paths(paths, preserved_paths)

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
    ws_response = load_nearby_weigh_stations(use_cache)
    weigh_stations = filter_weight_stations(ws_response)
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

    provincial_resp = load_provincial_routes(use_cache)
    provincial_node_rel = build_exit_relation(provincial_resp, "provincial")
    print(f"Prepared {len(provincial_node_rel)} provincial node relations")

    # freeway_resp already loaded above
    freeway_node_rel = build_exit_relation(freeway_resp, "freeway")
    print(
        f"Prepared {len(freeway_node_rel)} freeway and {len(provincial_node_rel)} provincial node relations"
    )

    # We already have weigh_way_rel for all ways
    print(f"Prepared {len(weigh_way_rel)} weigh-station relations (way-based)")

    # Build adjacent road relations for end-node annotation (used before generic way relation)
    adj_resp = load_adjacent_road_relations(use_cache)
    endnode_adjacent_relations = wrap_adj_road_relation(adj_resp)
    print(f"Prepared {len(endnode_adjacent_relations)} adjacent route=road relations (node-based)")
    interchanges = [
        annotate_interchange_ramps(
            interchange,
            way_to_relations=way_to_relations,
            freeway_node_rel=freeway_node_rel,
            provincial_node_rel=provincial_node_rel,
            junction_node_rel=junction_node_rel,
            weigh_way_to_relations=weigh_way_rel,
            endnode_adjacent_relations=endnode_adjacent_relations,
            use_cache=use_cache,
        )
        for interchange in interchanges
    ]
    print(f"Annotated {len(interchanges)} interchanges")

    names = [ic.name for ic in interchanges]
    counter = Counter(names)
    for name, count in counter.items():
        if count > 1 or ";" in name:
            print(f"Special Interchange '{name}' count: {count}")

    # Build master indices separately for freeway and elevated, then merge (freeway takes precedence)
    node_index = build_master_order_index(freeway_resp)
    elev_resp = load_elevated_freeway_relation(use_cache)
    elevated_wrapped = wrap_elevated_relation_as_route_master(elev_resp)
    elevated_index = build_master_order_index(elevated_wrapped)
    elevated_index.update(node_index)  # freeway index takes precedence
    node_index = elevated_index

    interchanges = reorder_and_annotate_interchanges_by_node_index(interchanges, node_index)

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
