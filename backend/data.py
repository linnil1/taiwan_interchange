from collections import Counter

from gov import (
    copy_freeway_pdfs_to_static,
    load_or_fetch_gov_interchanges,
    load_or_fetch_gov_weigh_stations,
)
from graph_operations import (
    assign_branch_ids,
    build_dag_edges,
    connect_ramps_by_nodes,
    contract_paths_to_ramps,
    extract_branch_ways,
    extract_endpoint_ways,
    filter_endpoints_by_motorway_link,
)
from interchange_annotation import (
    annotate_interchange_name,
    annotate_interchange_ramps,
    build_master_order_index,
    generate_display_ids_for_interchanges,
    map_gov_to_interchanges,
    map_wiki_to_interchanges,
    map_wikidata_to_interchanges,
    override_interchange_names_by_way,
    reorder_and_annotate_interchanges_by_node_index,
)
from interchange_grouping import (
    delete_interchanges_containing_ways,
    group_ramps_to_interchange,
    isolate_interchanges_by_branch,
    merge_interchanges_by_name,
    split_interchanges_by_name_marker,
)
from models import (
    RoadType,
)
from osm import (
    load_or_fetch_osm_adjacent_roads,
    load_or_fetch_osm_elevated_freeway,
    load_or_fetch_osm_freeway_routes,
    load_or_fetch_osm_motorway_links,
    load_or_fetch_osm_provincial_routes,
    load_or_fetch_osm_weigh_stations,
)
from osm_operations import (
    extract_freeway_related_ways,
    filter_weight_stations,
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
    add_manual_junction_names,
    build_exit_relation,
    build_weigh_way_relations,
    extract_wikidata_ids_from_nodes,
    wrap_adj_road_relation,
    wrap_junction_name_relation,
    wrap_ways_as_relation,
)
from wiki import load_all_wiki_interchanges

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
        interchanges = map_wiki_to_interchanges(
            interchanges,
            wiki_highways,
            name_mapping=WIKI_NAME_MAPPING,
            show_match_log=SHOW_MATCH_LOG,
        )

    # gov
    if add_gov_data:
        gov_highways = load_or_fetch_gov_interchanges(use_cache=use_cache)
        gov_highways.append(load_or_fetch_gov_weigh_stations(use_cache=use_cache))
        print(f"Loaded {len(gov_highways)} Government highways with interchange data")
        # Map Government data
        gov_highways = copy_freeway_pdfs_to_static(gov_highways)
        interchanges = map_gov_to_interchanges(
            interchanges,
            gov_highways,
            name_mapping=GOV_NAME_MAPPING,
            show_match_log=SHOW_MATCH_LOG,
        )
        # Copy freeway PDFs to static folder

    # wikidata from OSM nodes
    wikidata_node_rel = extract_wikidata_ids_from_nodes(node_dict, IGNORED_NODE_IDS)
    print(f"Extracted {len(wikidata_node_rel)} Wikidata IDs from OSM motorway_junction nodes")
    interchanges = map_wikidata_to_interchanges(interchanges, wikidata_node_rel)

    # Generate display IDs for frontend
    interchanges = generate_display_ids_for_interchanges(interchanges)

    json_file_path = save_interchanges(interchanges, save_static=True)
    print(f"Successfully saved interchanges to {json_file_path}")

    return True


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
