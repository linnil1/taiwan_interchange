"""
Utilities for extracting names via relation-based mappings and building relation maps.

This module centralizes operations that translate OSM objects (relations/ways/nodes)
into app-level Relation mappings, and helpers to extract ramp names from those maps.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NewType

from models import Ramp, Relation, RelationType, RoadType
from osm import OverPassNode, OverPassRelation, OverPassResponse, OverPassWay
from osm_operations import extract_to_destination, process_relations_mapping
from utils import calculate_distance

# Distinct map types to differentiate node-based and way-based relation mappings
NodeRelationMap = NewType("NodeRelationMap", dict[int, Relation])
WayRelationMap = NewType("WayRelationMap", dict[int, Relation])

# ---- Extract ramp names from relation mappings ----


def extract_ramp_name_by_end_node_relation(
    ramp: Ramp, node_to_relations: NodeRelationMap
) -> list[Relation]:
    """Extract ramp relation(s) using a node->relation mapping (by end node)."""
    relations: list[Relation] = []

    # Use the end node to determine destination
    _, end_node = ramp.get_endpoint_nodes()
    relation = node_to_relations.get(end_node.id)
    if relation:
        relations.append(relation)

    return relations


def extract_ramp_name_by_start_node_relation(
    ramp: Ramp, node_to_relations: NodeRelationMap
) -> list[Relation]:
    """Extract ramp relation(s) using a node->relation mapping (by start node).

    This is useful for generic node relations like junction names when
    end-node mapping or other sources are unavailable.
    """
    relations: list[Relation] = []
    start_node, _ = ramp.get_endpoint_nodes()
    relation = node_to_relations.get(start_node.id)
    if relation:
        relations.append(relation)
    return relations


def extract_ramp_name_by_node_relation(
    ramp: Ramp, node_to_relations: NodeRelationMap
) -> list[Relation]:
    """Extract ramp relation(s) by scanning all nodes in the ramp.

    Useful when end-node mapping is missing but intermediate nodes carry relation context.
    """
    relations: list[Relation] = []
    for node in ramp.list_nodes():
        rel = node_to_relations.get(node.id)
        if rel:
            relations.append(rel)
    return list(set(relations))


def extract_ramp_name_by_way_relation(
    ramp: Ramp, way_to_relations: WayRelationMap
) -> list[Relation]:
    """Extract ramp relation(s) using a way->relation mapping (by path way id)."""
    relations: list[Relation] = []
    for path in ramp.paths:
        rel = way_to_relations.get(path.id)
        if rel:
            relations.append(rel)
    # de-duplicate while preserving minimal overhead
    return list(set(relations))


# ---- Builders: convert OSM structures to app Relation maps ----


def wrap_ways_as_node_relation(ways: list[OverPassWay], road_type: RoadType) -> NodeRelationMap:
    """Process ways and return a node->relation mapping for those with names."""
    node_to_relation: dict[int, Relation] = {}

    for way in ways:
        if not way.tags.get("name"):
            continue
        relation = Relation(
            id=way.id, name=way.tags["name"], road_type=road_type, relation_type=RelationType.WAY
        )
        for node_id in way.nodes:
            if node_id not in node_to_relation:
                node_to_relation[node_id] = relation
    return NodeRelationMap(node_to_relation)


def wrap_ways_as_relation(ways: list[OverPassWay], road_type: RoadType) -> WayRelationMap:
    """Wrap ways that have a name into a way_id -> Relation mapping."""
    way_to_relation: dict[int, Relation] = {}
    for way in ways:
        name = way.tags.get("name") if way.tags else None
        if not name:
            continue
        if way.id not in way_to_relation:
            way_to_relation[way.id] = Relation(
                id=way.id, name=name, road_type=road_type, relation_type=RelationType.WAY
            )
    return WayRelationMap(way_to_relation)


def wrap_way_destination_to_relation(ways: list[OverPassWay]) -> WayRelationMap:
    """Build way_id -> Relation using extract_to_destination for each way."""
    way_to_relation: dict[int, Relation] = {}
    for way in ways:
        tokens = extract_to_destination(way)
        name = ";".join([t.strip() for t in tokens if t and t.strip()])
        if not name:
            continue
        if way.id not in way_to_relation:
            way_to_relation[way.id] = Relation(
                id=way.id, name=name, road_type=RoadType.DESTINATION, relation_type=RelationType.WAY
            )
    return WayRelationMap(way_to_relation)


def wrap_relation_to_node_relation(
    rel_ways_nodes: Sequence[tuple[OverPassRelation, list[OverPassWay], list[OverPassNode]]],
    road_type: RoadType,
) -> NodeRelationMap:
    """Convert relation -> (ways,nodes) tuples into a node_id -> Relation mapping.

    For each relation that has a name, all nodes referenced by its member ways
    are mapped to a Relation(name, road_type) object.
    """
    node_to_relations: dict[int, Relation] = {}
    for relation, ways, nodes in rel_ways_nodes:
        if not relation.tags or "name" not in relation.tags:
            continue
        relation_obj = Relation(
            id=relation.id,
            name=relation.tags["name"],
            road_type=road_type,
            relation_type=RelationType.RELATION,
        )
        for way in ways:
            for node_id in way.nodes:
                if node_id not in node_to_relations:
                    node_to_relations[node_id] = relation_obj
    return NodeRelationMap(node_to_relations)


def wrap_adj_road_relation(response: OverPassResponse) -> NodeRelationMap:
    """Build node->Relation mapping for adjacent roads.

    Preference:
    - If a way is part of a named route=road relation (excluding network TW:freeway/TW:provincial),
      use the relation's name.
    - Otherwise, fall back to the way's own name.

    Returns NodeRelationMap mapping node_id -> Relation(name, road_type="road").
    """
    ways = response.list_ways()
    relations = response.list_relations()

    # Filter relevant relations: route=road, has name, and NOT freeway/provincial networks
    rel_way_to_name: dict[int, str] = {}
    for rel in relations:
        tags = rel.tags or {}
        if tags.get("route") != "road":
            continue
        if not tags.get("name"):
            continue
        network = tags.get("network")
        if network in {"TW:freeway", "TW:provincial"}:
            continue
        for m in rel.members:
            if m.type == "way":
                rel_way_to_name[m.ref] = tags["name"]

    node_to_relation: dict[int, Relation] = {}
    for way in ways:
        # Prefer relation name; else way name
        name = rel_way_to_name.get(way.id) or ((way.tags or {}).get("name") or "")
        if not name:
            continue
        rel_obj = Relation(
            id=way.id, name=name, road_type=RoadType.NORMAL, relation_type=RelationType.WAY
        )
        for nid in way.nodes:
            if nid not in node_to_relation:
                node_to_relation[nid] = rel_obj

    return NodeRelationMap(node_to_relation)


def build_weigh_way_relations(
    ways: list[OverPassWay],
    weigh_stations: list[OverPassWay],
    threshold_km: float = 0.05,
) -> WayRelationMap:
    """Build way_id -> Relation mapping for weigh stations to their closest way.

    For each weigh station, find the single closest way (based on sampled geometry points).
    If the minimum distance is within ``threshold_km``, annotate that way with the station's
    name. Conflicts where multiple stations choose the same way are resolved by keeping the
    station that is closer to that way.
    """
    if not ways or not weigh_stations:
        return WayRelationMap({})

    way_to_rel: dict[int, Relation] = {}

    for ws in weigh_stations:
        sname = ws.tags.get("name")
        if not sname:
            continue
        rel = Relation(
            id=ws.id, name=sname, road_type=RoadType.WEIGH, relation_type=RelationType.WAY
        )
        if not ws.geometry:
            continue
        slat, slng = ws.geometry[0].lat, ws.geometry[0].lng

        closest_way_id: int | None = None
        closest_dist: float = float("inf")
        for way in ways:
            step_size = max(1, len(way.nodes) // 10)
            points = way.geometry[::step_size] if step_size else []
            d = min(
                (calculate_distance(n.lat, n.lng, slat, slng) for n in points), default=float("inf")
            )
            if d < closest_dist:
                closest_dist = d
                closest_way_id = way.id

        if closest_way_id is None or closest_dist > threshold_km:
            continue
        way_to_rel[closest_way_id] = rel

    return WayRelationMap(way_to_rel)


def wrap_junction_name_relation(
    node_dict: dict[int, OverPassNode], ignored_ids: set[int] | None = None
) -> NodeRelationMap:
    """Build node_id -> Relation for motorway_junction nodes with name tags.

    Optionally ignores node IDs provided in ignored_ids.
    """
    ignored_ids = ignored_ids or set()
    node_to_relation: dict[int, Relation] = {}
    for node_id, osm_node in node_dict.items():
        if (
            osm_node
            and osm_node.tags
            and osm_node.tags.get("highway") == "motorway_junction"
            and "name" in osm_node.tags
            and (osm_node.id not in ignored_ids)
        ):
            node_to_relation[node_id] = Relation(
                id=osm_node.id,
                name=osm_node.tags["name"],
                road_type=RoadType.JUNCTION,
                relation_type=RelationType.NODE,
            )
    return NodeRelationMap(node_to_relation)


def extract_wikidata_ids_from_nodes(
    node_dict: dict[int, OverPassNode], ignored_ids: set[int] | None = None
) -> NodeRelationMap:
    """Extract Wikidata IDs from motorway_junction nodes as a NodeRelationMap.

    Returns a NodeRelationMap where each relation contains the Wikidata ID as the name.
    This allows reusing extract_ramp_name_by_node_relation for mapping to interchanges.
    Optionally ignores node IDs provided in ignored_ids.
    """
    ignored_ids = ignored_ids or set()
    node_to_relation: dict[int, Relation] = {}
    for node_id, osm_node in node_dict.items():
        if (
            osm_node
            and osm_node.tags
            and osm_node.tags.get("highway") == "motorway_junction"
            and "wikidata" in osm_node.tags
            and (osm_node.id not in ignored_ids)
        ):
            node_to_relation[node_id] = Relation(
                id=osm_node.id,
                name=osm_node.tags["wikidata"],  # Use wikidata ID as the name
                road_type=RoadType.WIKIDATA,
                relation_type=RelationType.NODE,
            )
    return NodeRelationMap(node_to_relation)


def build_exit_relation(response: OverPassResponse, road_type: RoadType) -> NodeRelationMap:
    """Build node->relation mapping for exits/roads from a single Overpass response.

    Takes an OverPassResponse and returns a NodeRelationMap of node_id -> Relation(name, road_type)
    based on relation membership.
    """
    rel_tuples = process_relations_mapping(response)
    return wrap_relation_to_node_relation(rel_tuples, road_type)


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
