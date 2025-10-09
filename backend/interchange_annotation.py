from typing import TypeVar

from gov import GovHighwayData, create_gov_data_from_interchange
from graph_operations import (
    build_ordered_node_ids_for_relation,
    generate_ramp_display_ids,
    get_reverse_topological_order,
)
from models import (
    Destination,
    DestinationType,
    GovData,
    Interchange,
    Ramp,
    Relation,
    RelationType,
    RoadType,
    WikiData,
)
from osm import OverPassRelation, OverPassResponse
from osm_operations import (
    display_for_master,
    list_master_relations,
    normalize_weigh_station_name,
    process_relations_mapping,
)
from relation_operations import (
    NodeRelationMap,
    WayRelationMap,
    extract_ramp_name_by_end_node_relation,
    extract_ramp_name_by_node_relation,
    extract_ramp_name_by_way_relation,
)
from utils import ramp_contains_way, renumber_interchanges
from wiki import WikiHighway, create_wiki_data_from_interchange


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


T = TypeVar("T")


def map_external_to_interchanges(
    interchanges: list[Interchange],
    external_data_map: dict[str, T],
    *,
    show_match_log: bool = False,
) -> list[list[T]]:
    """
    Generic function to map external data to interchanges based on name matching.

    Args:
        interchanges: List of interchanges to map external data to
        external_data_map: Dictionary mapping interchange names to external data objects
        show_match_log: Whether to show detailed matching log

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

        if show_match_log:
            print(f"✅ Matched '{interchange.name}' to external data: {names_matched}")

        # Add all matched external data
        matched_data = [external_data_map[name] for name in names_matched]
        result.append(matched_data)
        matched_count += 1

    print(f"Successfully matched {matched_count}/{len(interchanges)} interchanges to external data")

    # Show not match summary
    if show_match_log:
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
    interchanges: list[Interchange],
    wiki_highways: list[WikiHighway],
    *,
    name_mapping: dict[str, str] | None = None,
    show_match_log: bool = False,
) -> list[Interchange]:
    """
    Map Wikipedia interchange data to existing interchanges.

    Args:
        interchanges: List of interchanges to map to Wikipedia data
        wiki_highways: List of WikiHighway objects with interchange data
        name_mapping: Optional mapping from wiki names to interchange names
        show_match_log: Whether to show detailed matching log

    Returns:
        List of interchanges with wikis populated where matches are found
    """
    # Create a mapping of interchange names to wiki data
    wiki_name_map: dict[str, WikiData] = {}
    name_mapping = name_mapping or {}

    for highway in wiki_highways:
        for wiki_interchange in highway.interchanges:
            # Create WikiData object with URL using transform function
            wiki_data = create_wiki_data_from_interchange(wiki_interchange, highway.url)

            # Apply name mapping if needed
            if wiki_interchange.name in name_mapping:
                mapped_name = name_mapping[wiki_interchange.name]
                wiki_name_map[mapped_name] = wiki_data
            else:
                # Handle "交流道" suffix: add both with and without suffix as keys
                clean_name = wiki_interchange.name.strip()
                wiki_name_map[clean_name] = wiki_data
                if not clean_name.endswith("交流道"):
                    wiki_name_map[clean_name + "交流道"] = wiki_data

    # Get matched data using the generic function
    matched_wikis = map_external_to_interchanges(
        interchanges, wiki_name_map, show_match_log=show_match_log
    )

    # Set the wikis attribute for each interchange
    for interchange, wikis in zip(interchanges, matched_wikis):
        interchange.wikis = wikis

    return interchanges


def generate_display_ids_for_interchanges(interchanges: list[Interchange]) -> list[Interchange]:
    """Generate display IDs for all interchanges and sort ramps based on display IDs."""
    for interchange in interchanges:
        # Generate display ID mapping
        interchange.ramp_display_ids = generate_ramp_display_ids(interchange.ramps)

        if not interchange.ramp_display_ids:
            continue

        # Sort ramps based on display IDs
        interchange.ramps = sorted(
            interchange.ramps,
            key=lambda ramp: interchange.ramp_display_ids[ramp.id],
        )

        # Sort from_ramps and to_ramps for each ramp based on display IDs
        for ramp in interchange.ramps:
            ramp.from_ramps = sorted(
                ramp.from_ramps, key=lambda ramp_id: interchange.ramp_display_ids[ramp_id]
            )
            ramp.to_ramps = sorted(
                ramp.to_ramps, key=lambda ramp_id: interchange.ramp_display_ids[ramp_id]
            )
    return interchanges


def map_wikidata_to_interchanges(
    interchanges: list[Interchange], wikidata_node_rel: NodeRelationMap
) -> list[Interchange]:
    """
    Map Wikidata IDs from OSM motorway_junction nodes to interchanges.

    Args:
        interchanges: List of interchanges to map Wikidata IDs to
        wikidata_node_rel: NodeRelationMap containing wikidata IDs as relation names

    Returns:
        List of interchanges with wikidata_ids populated where node matches are found
    """
    for interchange in interchanges:
        wikidata_ids: set[str] = set()

        for ramp in interchange.ramps:
            wikidata_relations = extract_ramp_name_by_node_relation(ramp, wikidata_node_rel)
            for relation in wikidata_relations:
                wikidata_ids.add(relation.name)  # relation.name contains the wikidata ID

        # Set the wikidata_ids as a sorted list for consistency
        interchange.wikidata_ids = sorted(list(wikidata_ids))

    return interchanges


def map_gov_to_interchanges(
    interchanges: list[Interchange],
    gov_highways: list[GovHighwayData],
    *,
    name_mapping: dict[str, str] | None = None,
    show_match_log: bool = False,
) -> list[Interchange]:
    """
    Map Government interchange data to existing interchanges.

    Args:
        interchanges: List of interchanges to map to Government data
        gov_highways: List of GovHighwayData objects with interchange data
        name_mapping: Optional mapping from government names to interchange names
        show_match_log: Whether to show detailed matching log

    Returns:
        List of interchanges with govs populated where matches are found
    """
    # Create a mapping of interchange names to gov data
    gov_name_map: dict[str, GovData] = {}
    name_mapping = name_mapping or {}

    for highway in gov_highways:
        for gov_interchange_data in highway.interchanges:
            gov_data = create_gov_data_from_interchange(gov_interchange_data, highway.url)

            # Apply name mapping if needed
            if gov_interchange_data.name in name_mapping:
                mapped_name = name_mapping[gov_interchange_data.name]
                gov_name_map[mapped_name] = gov_data
            else:
                clean_name = gov_interchange_data.name.strip()
                gov_name_map[clean_name] = gov_data
                if not clean_name.endswith("交流道"):
                    gov_name_map[clean_name + "交流道"] = gov_data

    # Get matched data using the generic function
    matched_govs = map_external_to_interchanges(
        interchanges, gov_name_map, show_match_log=show_match_log
    )

    # Set the govs attribute for each interchange
    for interchange, govs in zip(interchanges, matched_govs):
        interchange.govs = govs

    return interchanges
