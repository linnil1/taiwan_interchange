"""
Utilities for extracting names via relation-based mappings and building relation maps.

This module centralizes operations that translate OSM objects (relations/ways/nodes)
into app-level Relation mappings, and helpers to extract ramp names from those maps.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NewType

from models import Ramp, Relation
from osm import OverPassNode, OverPassRelation, OverPassWay
from osm_operations import extract_to_destination
from utils import calculate_distance

# Distinct map types to differentiate node-based and way-based relation mappings
NodeRelationMap = NewType("NodeRelationMap", dict[int, Relation])
WayRelationMap = NewType("WayRelationMap", dict[int, Relation])

# ---- Extract ramp names from relation mappings ----


def extract_ramp_name_by_end_node_relation(
    ramp: Ramp, node_to_relations: NodeRelationMap
) -> list[str]:
    """Extract ramp name(s) using a node->relation mapping (by end node)."""
    all_destinations: list[str] = []

    # Use the end node to determine destination
    _, end_node = ramp.get_endpoint_nodes()
    relation = node_to_relations.get(end_node.id)
    if relation:
        all_destinations.append(relation.name)

    return all_destinations


def extract_ramp_name_by_node_relation(ramp: Ramp, node_to_relations: NodeRelationMap) -> list[str]:
    """Extract ramp name(s) by scanning all nodes in the ramp.

    Useful when end-node mapping is missing but intermediate nodes carry relation context.
    """
    names: list[str] = []
    for node in ramp.list_nodes():
        rel = node_to_relations.get(node.id)
        if rel:
            names.append(rel.name)
    return list(set(names))


def extract_ramp_name_by_way_relation(ramp: Ramp, way_to_relations: WayRelationMap) -> list[str]:
    """Extract ramp name(s) using a way->relation mapping (by path way id)."""
    all_destinations: list[str] = []
    for path in ramp.paths:
        rel = way_to_relations.get(path.id)
        if rel:
            all_destinations.append(rel.name)
    # de-duplicate while preserving minimal overhead
    return list(set(all_destinations))


# ---- Builders: convert OSM structures to app Relation maps ----


def wrap_ways_as_node_relation(ways: list[OverPassWay], road_type: str) -> NodeRelationMap:
    """Process ways and return a node->relation mapping for those with names."""
    node_to_relation: dict[int, Relation] = {}

    for way in ways:
        if not way.tags.get("name"):
            continue
        relation = Relation(name=way.tags["name"], road_type=road_type)
        for node_id in way.nodes:
            if node_id not in node_to_relation:
                node_to_relation[node_id] = relation
    return NodeRelationMap(node_to_relation)


def wrap_ways_as_relation(ways: list[OverPassWay], road_type: str) -> WayRelationMap:
    """Wrap ways that have a name into a way_id -> Relation mapping."""
    way_to_relation: dict[int, Relation] = {}
    for way in ways:
        name = way.tags.get("name") if way.tags else None
        if not name:
            continue
        if way.id not in way_to_relation:
            way_to_relation[way.id] = Relation(name=name, road_type=road_type)
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
            way_to_relation[way.id] = Relation(name=name, road_type="destination")
    return WayRelationMap(way_to_relation)


def wrap_relation_to_node_relation(
    rel_ways_nodes: Sequence[tuple[OverPassRelation, list[OverPassWay], list[OverPassNode]]],
    road_type: str,
) -> NodeRelationMap:
    """Convert relation -> (ways,nodes) tuples into a node_id -> Relation mapping.

    For each relation that has a name, all nodes referenced by its member ways
    are mapped to a Relation(name, road_type) object.
    """
    node_to_relations: dict[int, Relation] = {}
    for relation, ways, nodes in rel_ways_nodes:
        if not relation.tags or "name" not in relation.tags:
            continue
        relation_obj = Relation(name=relation.tags["name"], road_type=road_type)
        for way in ways:
            for node_id in way.nodes:
                if node_id not in node_to_relations:
                    node_to_relations[node_id] = relation_obj
    return NodeRelationMap(node_to_relations)


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
        rel = Relation(name=sname, road_type="weigh")
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
            node_to_relation[node_id] = Relation(name=osm_node.tags["name"], road_type="junction")
    return NodeRelationMap(node_to_relation)
