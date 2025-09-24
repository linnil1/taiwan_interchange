from collections import Counter, defaultdict
from collections.abc import Iterable
from itertools import chain
from typing import TypeVar

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from gov import (
    GovHighwayData,
    copy_freeway_pdfs_to_static,
    create_gov_data_from_interchange,
    load_or_fetch_gov_interchanges,
    load_or_fetch_gov_weigh_stations,
)
from graph_operations import (
    assign_branch_ids,
    build_dag_edges,
    build_ordered_node_ids_for_relation,
    connect_ramps_by_nodes,
    contract_paths_to_ramps,
    extract_branch_ways,
    extract_endpoint_ways,
    filter_endpoints_by_motorway_link,
    get_reverse_topological_order,
)
from models import (
    Destination,
    DestinationType,
    GovData,
    Interchange,
    Node,
    Ramp,
    Relation,
    RelationType,
    RoadType,
    WikiData,
)
from osm import (
    OverPassRelation,
    OverPassResponse,
    load_or_fetch_osm_adjacent_roads,
    load_or_fetch_osm_elevated_freeway,
    load_or_fetch_osm_freeway_routes,
    load_or_fetch_osm_motorway_links,
    load_or_fetch_osm_provincial_routes,
    load_or_fetch_osm_weigh_stations,
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
from persistence import load_interchanges, save_interchanges
from relation_operations import (
    NodeRelationMap,
    WayRelationMap,
    build_weigh_way_relations,
    extract_ramp_name_by_end_node_relation,
    extract_ramp_name_by_node_relation,
    extract_ramp_name_by_way_relation,
    wrap_adj_road_relation,
    wrap_junction_name_relation,
    wrap_relation_to_node_relation,
    wrap_ways_as_relation,
)
from utils import (
    calculate_bounds,
    choose_modal_per_group,
    ramp_contains_way,
    renumber_interchanges,
)
from wiki import WikiHighway, create_wiki_data_from_interchange, load_all_wiki_interchanges

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

# Delete entire interchanges that contain these specific way IDs
DELETE_INTERCHANGE_WAY_IDS: set[int] = {
    391862272,  # 第二貨櫃中心
    642611481,  # 過港隧道
}

# Explicit interchange name overrides when an interchange contains a way ID
WAY_TO_INTERCHANGE_NAME: dict[int, str] = {
    247148858: "西螺交流道;西螺服務區",
    # 136861416: "高工局",
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
    552542934: "高架道路汐止端",
    202808793: "校前路交流道;楊梅休息站;楊梅端",
    1149403167: "五股交流道;泰山轉接道",
    136861414: "五股交流道;泰山轉接道",
}

# TODO: maybe change most above to use this instead
NODE_TO_INTERCHANGE_NAME: dict[int, str] = {
    1501451270: "高速公路局",
}

# Ignore specific nodes when extracting names (these should not name interchanges)
IGNORED_NODE_IDS: set[int] = {
    1095916940,  # 泰安服務區
    623059692,  # 濱江街出口
    1489583190,  # 石碇服務區
    32615877,  # 五股轉接道
    260240394,  # 五股轉接道
    59840990,  # 楊梅端
}

# Exclude specific motorway_link ways entirely when building paths (data quirks, known bad)
EXCLUDED_WAY_IDS: set[int] = set()

# Preserve these freeway endpoint ways even if they fail the connectivity filter
PRESERVED_ENDPOINT_WAY_IDS: set[int] = {439876652, 439876651}  # 機場端

WIKI_NAME_MAPPING = {
    "汐止端": "高架道路汐止端",
    "瑞隆路": "瑞隆路出口匝道",
    "南深路": "南深路出口匝道",
}

GOV_NAME_MAPPING = {
    "楊梅端": "高架道路楊梅端",
    "汐止端": "高架道路汐止端",
}

SHOW_MATCH_LOG = False


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


def delete_interchanges_containing_ways(
    interchanges: list[Interchange], delete_way_ids: set[int]
) -> list[Interchange]:
    """
    Delete entire interchanges that contain any of the specified way IDs.

    Args:
        interchanges: List of interchanges to filter
        delete_way_ids: Set of way IDs that should trigger interchange deletion

    Returns:
        Filtered list of interchanges with matching interchanges removed
    """
    filtered_interchanges: list[Interchange] = []

    for ic in interchanges:
        # Check if this interchange contains any of the deletion way IDs
        should_delete = False
        for way_id in delete_way_ids:
            if ramp_contains_way(ic.ramps, way_id):
                should_delete = True
                print(f"Deleting interchange {ic.id} ({ic.name}) - contains way {way_id}")
                break

        if not should_delete:
            filtered_interchanges.append(ic)

    # Renumber the remaining interchanges to maintain sequential IDs
    return renumber_interchanges(filtered_interchanges)


def override_interchange_names_by_way(
    interchanges: list[Interchange], mapping: dict[int, str]
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
            has_exit = any(d.destination_type == DestinationType.EXIT for d in collected)
            has_enter = any(d.destination_type == DestinationType.ENTER for d in collected)
            if has_exit and has_enter:
                collected = [d for d in collected if d.destination_type != DestinationType.ENTER]

            # Merge into ramp.destination with de-dup on (name,type)
            existing = {(d.name, d.destination_type) for d in ramp.destination}
            for d in collected:
                key = (d.name, d.destination_type)
                if key not in existing:
                    ramp.destination.append(d)
                    existing.add(key)

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
        weigh_relations = extract_ramp_name_by_way_relation(ramp, weigh_way_to_relations)
        # weigh station implies EXIT direction
        all_destinations.extend(
            Destination.from_relation(rel, DestinationType.EXIT) for rel in weigh_relations
        )

    # 2) freeway end-node relation
    if not all_destinations and freeway_node_rel:
        freeway_relations = extract_ramp_name_by_end_node_relation(ramp, freeway_node_rel)
        all_destinations.extend(
            Destination.from_relation(rel, DestinationType.ENTER) for rel in freeway_relations
        )

    # 3) provincial end-node relation
    if not all_destinations and provincial_node_rel:
        provincial_relations = extract_ramp_name_by_end_node_relation(ramp, provincial_node_rel)
        all_destinations.extend(
            Destination.from_relation(rel, DestinationType.ENTER) for rel in provincial_relations
        )

    # 4) end-node adjacent route relation (EXIT)
    if not all_destinations and endnode_adjacent_relations:
        adj_relations = extract_ramp_name_by_end_node_relation(ramp, endnode_adjacent_relations)
        all_destinations.extend(
            Destination.from_relation(rel, DestinationType.EXIT) for rel in adj_relations
        )

    # 5) generic node relation by start node (junction names) just above generic way
    """
    # currently disabled
    if not all_destinations and junction_node_rel:
        start_node_relations = extract_ramp_name_by_start_node_relation(ramp, junction_node_rel)
        all_destinations.extend(
            Destination.from_relation(rel, DestinationType.OSM) for rel in start_node_relations
        )

    # 6) generic way relation (lowest priority)
    if not all_destinations and way_to_relations:
        way_relations = extract_ramp_name_by_way_relation(ramp, way_to_relations)
        all_destinations.extend(
            Destination.from_relation(rel, DestinationType.OSM) for rel in way_relations
        )
    """

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
        relations = extract_ramp_name_by_node_relation(ramp, junction_node_rel)
        names.update(rel.name for rel in relations)

    # Also include weigh-station names
    weigh_names: set[str] = set()
    for ramp in interchange.ramps:
        weigh_relations = extract_ramp_name_by_way_relation(ramp, weigh_way_rel)
        weigh_names.update(rel.name for rel in weigh_relations)
    if weigh_names:
        weigh_names = set(normalize_weigh_station_name(name) for name in weigh_names if name)

    combined = sorted(set(n for n in list(names) + list(weigh_names) if n))
    if combined:
        # print(f"Rename {interchange.name} to " + ";".join(combined))
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

    # Finally, propagate destinations upstream from exit ramps to entry ramps
    ramps = annotate_ramps_by_propagating(ramps)

    return Interchange(
        id=interchange.id,
        name=interchange.name,
        bounds=interchange.bounds,
        ramps=ramps,
    )


def build_exit_relation(response: OverPassResponse, road_type: RoadType) -> NodeRelationMap:
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
) -> tuple[OverPassRelation, OverPassRelation]:
    """Extract the two preferred route relations for a master based on name preferences.

    Returns:
        Tuple of (primary_route, secondary_route) where primary has higher priority
    """
    member_route_ids = [m.ref for m in master.members if m.type == "relation"]
    candidates: list[OverPassRelation] = [
        rel_by_id[rid]
        for rid in member_route_ids
        if rid in rel_by_id and (rel_by_id[rid].tags or {}).get("type") == "route"
    ]

    # Assert that there are always exactly two candidates
    assert len(candidates) == 2, (
        f"Expected exactly 2 route candidates for master {master.id}, got {len(candidates)}"
    )

    # Choose preferred route by name tokens
    candidates.sort(key=preferred_route_score)

    primary = candidates[0]
    secondary = candidates[1]

    if preferred_route_score(primary)[0] == 1 or preferred_route_score(secondary)[0] == 0:
        raise ValueError(f"No preferred route found for master {master.id}")

    print(f"Choose primary: {primary.tags['name']}, secondary: {secondary.tags['name']}")
    return primary, secondary


def build_master_order_index(
    response: OverPassResponse,
) -> dict[int, tuple[str, int, Relation]]:
    """Build a global node index for freeway masters using both primary and secondary routes.

    Returns dict[node_id, (ref, order, relation)] where:
    - ref: master tags.ref if present, else master tags.name, else f"master:{id}"
    - order: index along the selected member route's ordered nodes
    - relation: Relation object with master information

    Processing order:
    1. Primary routes are processed first and take precedence
    2. Secondary routes are processed second and only add nodes not already present

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

    node_index: dict[int, tuple[str, int, Relation]] = {}

    masters = list_master_relations(response)
    # Process masters in ref order for stability
    for master in masters:
        primary, secondary = get_preferred_route_for_master(master, rel_by_id)

        # Process primary route (higher priority)
        ways = route_rel_ways.get(primary.id, [])
        if not ways:
            raise ValueError(f"No ways found for primary route {primary.id}")
        # Process secondary route (lower priority)
        ways_secondary = route_rel_ways.get(secondary.id, [])
        if not ways_secondary:
            raise ValueError(f"No ways found for secondary route {secondary.id}")

        mref, mname = display_for_master(master)

        # Create Relation object for this master
        master_relation = Relation(
            id=master.id,
            name=mname,
            road_type=RoadType.FREEWAY,
            relation_type=RelationType.RELATION,
        )

        ordered = build_ordered_node_ids_for_relation(ways)
        if not ordered:
            raise ValueError(f"No ordered nodes found for primary route {primary.id}")

        ordered_secondary = build_ordered_node_ids_for_relation(ways_secondary)
        if not ordered_secondary:
            raise ValueError(f"No ordered nodes found for secondary route {secondary.id}")

        last_order = max(ordered.values(), default=0)

        # Merge into global index only if not already present (primary takes precedence)
        for i, order in ordered_secondary.items():
            node_index[i] = mref, int(order) + last_order + 1, master_relation
        for i, order in ordered.items():
            node_index[i] = (mref, int(order), master_relation)

    return node_index


def reorder_and_annotate_interchanges_by_node_index(
    interchanges: list[Interchange],
    node_index: dict[int, tuple[str, int, Relation]],
) -> list[Interchange]:
    """Reorder and annotate interchanges based on node_index, sorting by master reference and node order.

    This function processes a list of Interchange objects by:
    - Annotating each interchange's `refs` list with unique master relations from nodes in the interchange.
    - Determining the minimum order for each interchange based on the node_index.
    - Sorting the interchanges by their minimum order (master ref, order, master relation).
    - Renumbering the sorted interchanges using renumber_interchanges.
    """
    if not interchanges or not node_index:
        return interchanges

    # Create a dictionary for quick interchange lookup by id
    interchanges = renumber_interchanges(interchanges)

    # Annotate refs and track min order for each interchange, keyed by interchange id
    ic_min_index: dict[int, tuple[str, int, Relation]] = {}
    for ic in interchanges:
        # Track existing relation names to avoid duplicates
        existing_ref_names = {rel.name for rel in ic.refs}
        for n in ic.list_nodes():
            if n.id not in node_index:
                continue
            mref, morder, master_relation = node_index[n.id]
            if master_relation.name not in existing_ref_names:
                ic.refs.append(master_relation)
                existing_ref_names.add(master_relation.name)
            # Update min order for sorting
            current = ic_min_index.get(ic.id)
            index = (mref, morder, master_relation)
            if current is None or current > index:
                ic_min_index[ic.id] = index

    interchanges = sorted(
        interchanges, key=lambda ic: ic_min_index.get(ic.id, ("ZZZZZZZZZ", 0, ""))
    )
    return renumber_interchanges(interchanges)


def add_manual_junction_names(node_dict: dict[int, str]) -> NodeRelationMap:
    """Add manual motorway_junction names for specific nodes not present in OSM data."""

    junction_node_rel: dict[int, Relation] = {}
    for id, name in node_dict.items():
        junction_node_rel[id] = Relation(
            id=id,
            name=name,
            road_type=RoadType.JUNCTION,
            relation_type=RelationType.RELATION,
        )
    return NodeRelationMap(junction_node_rel)


def generate_interchanges_json(
    use_cache: bool = True, add_wiki_data: bool = True, add_gov_data: bool = True
) -> bool:
    """
    The main function:
    Generate interchanges.json from Overpass API data group them by interchange
    """
    # Basic
    print("Getting Overpass data...")
    response = load_or_fetch_osm_motorway_links(use_cache)
    ways = response.list_ways()
    ways = filter_accessible_ways(ways, EXCLUDED_WAY_IDS)
    nodes = response.list_nodes()
    print(f"Loaded {len(ways)} motorway_link ways and {len(nodes)} motorway junction nodes")
    if not ways or not nodes:
        print("No motorway links/nodes found in Taiwan")
        return False

    # Process paths from motorway_link ways
    node_dict = {node.id: node for node in nodes}
    paths = process_paths_from_ways(ways, excluded_ids=None, duplicate_two_way=True)
    print(f"Processed {len(paths)} paths")

    # Add elevated freeway's branch (not part of long connected components), and endpoints
    elev_resp = load_or_fetch_osm_elevated_freeway(use_cache)
    elevated_wrapped = wrap_elevated_relation_as_route_master(elev_resp)
    elevated_ways = extract_freeway_related_ways(elevated_wrapped)
    print(f"Extracted {len(elevated_ways)} elevated freeway-related ways")
    elevated_paths = process_paths_from_ways(
        elevated_ways, excluded_ids=None, duplicate_two_way=False
    )
    elevated_branches = extract_branch_ways(elevated_paths)
    elevated_endpoints = extract_endpoint_ways(elevated_paths)
    elevated_all_paths = concat_paths(elevated_branches, elevated_endpoints)
    print(f"Found {len(elevated_all_paths)} elevated branch and endpoint ways")

    # Add freeway endpoints
    freeway_resp = load_or_fetch_osm_freeway_routes(use_cache)
    freeway_ways = extract_freeway_related_ways(freeway_resp)
    print(f"Extracted {len(freeway_ways)} freeway-related ways")
    freeway_paths = process_paths_from_ways(
        freeway_ways, excluded_ids=None, duplicate_two_way=False
    )
    freeway_endpoints = extract_endpoint_ways(freeway_paths)
    freeway_endpoints = filter_endpoints_by_motorway_link(freeway_endpoints, paths)
    print(f"Added {len(freeway_endpoints)} freeway endpoint ways")
    paths = concat_paths(paths, freeway_endpoints)

    # Add elevated paths
    if elevated_all_paths:
        paths = concat_paths(paths, elevated_all_paths)
        print(f"Added {len(elevated_all_paths)} elevated paths")

    # Manually add preserved endpoint ways after the first concat
    preserved_paths = [p for p in freeway_paths if p.id in PRESERVED_ENDPOINT_WAY_IDS]
    if preserved_paths:
        paths = concat_paths(paths, preserved_paths)
    print(f"Total paths after adding endpoints: {len(paths)}")

    # Group paths into ramps
    paths = break_paths_by_endpoints(paths)
    paths = break_paths_by_traffic_lights(paths, node_dict)
    ramps = contract_paths_to_ramps(paths)
    ramps = connect_ramps_by_nodes(ramps)
    ramps = build_dag_edges(ramps)
    ramps = assign_branch_ids(ramps)
    print(f"Grouped into {len(ramps)} ramps")

    # 1. Group ramps into interchanges
    interchanges = group_ramps_to_interchange(ramps, 0.005)
    print(f"Identified {len(interchanges)} interchanges")

    # 2. Force Split interchange
    interchanges = isolate_interchanges_by_branch(interchanges, SPECIAL_ISOLATE_BRANCH_WAY_IDS)

    # 3. Annotate interchange names
    ws_response = load_or_fetch_osm_weigh_stations(use_cache)
    weigh_stations = filter_weight_stations(ws_response)
    print(f"Loaded {len(weigh_stations)} weigh stations")
    weigh_way_rel = build_weigh_way_relations(ways, weigh_stations)
    junction_node_rel = wrap_junction_name_relation(node_dict, IGNORED_NODE_IDS)
    junction_node_rel.update(add_manual_junction_names(NODE_TO_INTERCHANGE_NAME))
    interchanges = [
        annotate_interchange_name(interchange, junction_node_rel, weigh_way_rel)
        for interchange in interchanges
    ]
    # 4. Split interchanges by (;)
    interchanges = split_interchanges_by_name_marker(interchanges, distance_threshold=0.001)

    # 5. Force rename
    interchanges = override_interchange_names_by_way(interchanges, WAY_TO_INTERCHANGE_NAME)

    # 6. Merge interchanges by name
    interchanges = merge_interchanges_by_name(interchanges)
    print(f"After merge: {len(interchanges)} interchanges")

    # 7. Annotate interchange again
    interchanges = [
        annotate_interchange_name(interchange, junction_node_rel, weigh_way_rel)
        for interchange in interchanges
    ]
    interchanges = merge_interchanges_by_name(interchanges)

    # 8. Force Remove interchanges
    interchanges = delete_interchanges_containing_ways(interchanges, DELETE_INTERCHANGE_WAY_IDS)
    print(f"Final: {len(interchanges)} interchanges")

    # 9. Annotate ramp
    # by freeway/provincial, adjacent road, junction name relation, weigh-station way relation
    provincial_resp = load_or_fetch_osm_provincial_routes(use_cache)
    provincial_node_rel = build_exit_relation(provincial_resp, RoadType.PROVINCIAL)
    print(f"Prepared {len(provincial_node_rel)} provincial node relations")
    freeway_node_rel = build_exit_relation(freeway_resp, RoadType.FREEWAY)
    print(
        f"Prepared {len(freeway_node_rel)} freeway and {len(provincial_node_rel)} provincial node relations"
    )
    print(f"Prepared {len(weigh_way_rel)} weigh-station relations (way-based)")
    adj_resp = load_or_fetch_osm_adjacent_roads(use_cache)
    endnode_adjacent_relations = wrap_adj_road_relation(adj_resp)
    print(f"Prepared {len(endnode_adjacent_relations)} adjacent route=road relations (node-based)")
    way_to_relations = wrap_ways_as_relation(ways, road_type=RoadType.WAY)
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

    # Debug: print duplicate names
    names = [ic.name for ic in interchanges]
    counter = Counter(names)
    for name, count in counter.items():
        if count > 1 or ";" in name:
            print(f"Special Interchange '{name}' count: {count}")

    # 10. Reorder and annotate by freeway master index (freeway takes precedence over elevated)
    node_index = build_master_order_index(freeway_resp)
    elevated_index = build_master_order_index(elevated_wrapped)
    elevated_index.update(node_index)  # freeway index takes precedence
    node_index = elevated_index
    interchanges = reorder_and_annotate_interchanges_by_node_index(interchanges, node_index)

    # wiki
    if add_wiki_data:
        wiki_highways = load_all_wiki_interchanges(use_cache=use_cache)
        print(f"Loaded {len(wiki_highways)} Wikipedia highways with interchange data")
        # Map Wikipedia data
        interchanges = map_wiki_to_interchanges(interchanges, wiki_highways)

    # gov
    if add_gov_data:
        gov_highways = load_or_fetch_gov_interchanges(use_cache=use_cache)
        gov_highways.append(load_or_fetch_gov_weigh_stations(use_cache=use_cache))
        print(f"Loaded {len(gov_highways)} Government highways with interchange data")
        # Map Government data
        gov_highways = copy_freeway_pdfs_to_static(gov_highways)
        interchanges = map_gov_to_interchanges(interchanges, gov_highways)
        # Copy freeway PDFs to static folder

    json_file_path = save_interchanges(interchanges, save_static=True)
    print(f"Successfully saved interchanges to {json_file_path}")

    return True


T = TypeVar("T")


def map_external_to_interchanges(
    interchanges: list[Interchange], external_data_map: dict[str, T]
) -> list[list[T]]:
    """
    Generic function to map external data to interchanges based on name matching.

    Args:
        interchanges: List of interchanges to map external data to
        external_data_map: Dictionary mapping interchange names to external data objects

    Returns:
        List of lists where each inner list contains matched external data for the corresponding interchange
    """
    # Match interchanges to external data
    result: list[list[T]] = []
    matched_count = 0

    for interchange in interchanges:
        # Handle multiple names separated by semicolon
        names_to_try = [name.strip() for name in interchange.name.split(";")]
        names_matched = {name for name in names_to_try if name in external_data_map}
        if not names_matched:
            result.append([])
            continue

        if SHOW_MATCH_LOG:
            print(f"✅ Matched '{interchange.name}' to external data: {names_matched}")

        # Add all matched external data
        matched_data = [external_data_map[name] for name in names_matched]
        result.append(matched_data)
        matched_count += 1

    print(f"Successfully matched {matched_count}/{len(interchanges)} interchanges to external data")

    # Show not match summary
    if SHOW_MATCH_LOG:
        unmatched_interchanges = [ic for i, ic in enumerate(interchanges) if not result[i]]
        print(f"Unmatched interchanges: {len(unmatched_interchanges)}")
        for interchange in unmatched_interchanges:
            print(f"  Interchange '{interchange.name}' not matched to any external entry")

        all_matched_data = {
            getattr(data, "name", str(data)) for data_list in result for data in data_list
        }
        unmatched_external = []
        for data in external_data_map.values():
            name = getattr(data, "name", str(data))
            if name not in all_matched_data:
                unmatched_external.append(name)

        print(f"Unmatched external entries: {len(unmatched_external)}")
        for name in sorted(set(unmatched_external)):
            print(f"  External entry '{name}' not matched to any interchange")

    return result


def map_wiki_to_interchanges(
    interchanges: list[Interchange], wiki_highways: list[WikiHighway]
) -> list[Interchange]:
    """
    Map Wikipedia interchange data to existing interchanges.

    Args:
        interchanges: List of interchanges to map to Wikipedia data
        wiki_highways: List of WikiHighway objects with interchange data

    Returns:
        List of interchanges with wikis populated where matches are found
    """
    # Create a mapping of interchange names to wiki data
    wiki_name_map: dict[str, WikiData] = {}

    for highway in wiki_highways:
        for wiki_interchange in highway.interchanges:
            # Create WikiData object with URL using transform function
            wiki_data = create_wiki_data_from_interchange(wiki_interchange, highway.url)

            # Apply name mapping if needed
            if wiki_interchange.name in WIKI_NAME_MAPPING:
                mapped_name = WIKI_NAME_MAPPING[wiki_interchange.name]
                wiki_name_map[mapped_name] = wiki_data
            else:
                # Handle "交流道" suffix: add both with and without suffix as keys
                clean_name = wiki_interchange.name.strip()
                wiki_name_map[clean_name] = wiki_data
                if not clean_name.endswith("交流道"):
                    wiki_name_map[clean_name + "交流道"] = wiki_data

    # Get matched data using the generic function
    matched_wikis = map_external_to_interchanges(interchanges, wiki_name_map)

    # Set the wikis attribute for each interchange
    for interchange, wikis in zip(interchanges, matched_wikis):
        interchange.wikis = wikis

    return interchanges


def map_gov_to_interchanges(
    interchanges: list[Interchange], gov_highways: list[GovHighwayData]
) -> list[Interchange]:
    """
    Map Government interchange data to existing interchanges.

    Args:
        interchanges: List of interchanges to map to Government data
        gov_highways: List of GovHighwayData objects with interchange data

    Returns:
        List of interchanges with govs populated where matches are found
    """
    # Create a mapping of interchange names to gov data
    gov_name_map: dict[str, GovData] = {}

    for highway in gov_highways:
        for gov_interchange_data in highway.interchanges:
            gov_data = create_gov_data_from_interchange(gov_interchange_data, highway.url)

            # Apply name mapping if needed
            if gov_interchange_data.name in GOV_NAME_MAPPING:
                mapped_name = GOV_NAME_MAPPING[gov_interchange_data.name]
                gov_name_map[mapped_name] = gov_data
            else:
                clean_name = gov_interchange_data.name.strip()
                gov_name_map[clean_name] = gov_data
                if not clean_name.endswith("交流道"):
                    gov_name_map[clean_name + "交流道"] = gov_data

    # Get matched data using the generic function
    matched_govs = map_external_to_interchanges(interchanges, gov_name_map)

    # Set the govs attribute for each interchange
    for interchange, govs in zip(interchanges, matched_govs):
        interchange.govs = govs

    return interchanges


def extract_mock_data() -> None:
    """Extract mock data for testing purposes."""
    data = load_interchanges()
    mock_data = []
    for ic in data:
        if ic.name == "石碇交流道" or "汐止系統" in ic.name:
            mock_data.append(ic.model_dump())
    import json

    with open("interchanges_mock.json", "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print("Generating interchanges data from Overpass API...")
    success = generate_interchanges_json(use_cache=True, add_wiki_data=True)
    if success:
        print("\n✅ Successfully generated interchanges.json")
        print("You can now run the Flask app with: python app.py")
    else:
        print("\n❌ Failed to generate interchanges.json")
