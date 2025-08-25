"""
Utilities for extracting names via relation-based mappings and building relation maps.

This module centralizes operations that translate OSM objects (relations/ways/nodes)
into app-level Relation mappings, and helpers to extract ramp names from those maps.
"""

from __future__ import annotations

from collections.abc import Sequence

from models import Ramp, Relation
from osm import OverPassNode, OverPassRelation, OverPassWay
from osm_operations import extract_to_destination
from utils import calculate_distance

# ---- Extract ramp names from relation mappings ----


def extract_ramp_name_by_end_node_relation(
    ramp: Ramp, node_to_relations: dict[int, Relation]
) -> list[str]:
    """Extract ramp name(s) using a node->relation mapping (by end node)."""
    all_destinations: list[str] = []

    # Use the end node to determine destination
    _, end_node = ramp.get_endpoint_nodes()
    relation = node_to_relations.get(end_node.id)
    if relation:
        all_destinations.append(relation.name)

    return all_destinations


def extract_ramp_name_by_node_relation(
    ramp: Ramp, node_to_relations: dict[int, Relation]
) -> list[str]:
    """Extract ramp name(s) by scanning all nodes in the ramp.

    Useful when end-node mapping is missing but intermediate nodes carry relation context.
    """
    names: list[str] = []
    for node in ramp.list_nodes():
        rel = node_to_relations.get(node.id)
        if rel:
            names.append(rel.name)
    return list(set(names))


def extract_ramp_name_by_way_relation(
    ramp: Ramp, way_to_relations: dict[int, Relation]
) -> list[str]:
    """Extract ramp name(s) using a way->relation mapping (by path way id)."""
    all_destinations: list[str] = []
    for path in ramp.paths:
        rel = way_to_relations.get(path.id)
        if rel:
            all_destinations.append(rel.name)
    # de-duplicate while preserving minimal overhead
    return list(set(all_destinations))


# ---- Builders: convert OSM structures to app Relation maps ----


def wrap_ways_as_node_relation(ways: list[OverPassWay], road_type: str) -> dict[int, Relation]:
    """Process ways and return a node->relation mapping for those with names."""
    node_to_relation: dict[int, Relation] = {}

    for way in ways:
        if not way.tags.get("name"):
            continue
        relation = Relation(name=way.tags["name"], road_type=road_type)
        for node_id in way.nodes:
            if node_id not in node_to_relation:
                node_to_relation[node_id] = relation
    return node_to_relation


def wrap_ways_as_relation(ways: list[OverPassWay], road_type: str) -> dict[int, Relation]:
    """Wrap ways that have a name into a way_id -> Relation mapping."""
    way_to_relation: dict[int, Relation] = {}
    for way in ways:
        name = way.tags.get("name") if way.tags else None
        if not name:
            continue
        if way.id not in way_to_relation:
            way_to_relation[way.id] = Relation(name=name, road_type=road_type)
    return way_to_relation


def wrap_way_destination_to_relation(ways: list[OverPassWay]) -> dict[int, Relation]:
    """Build way_id -> Relation using extract_to_destination for each way."""
    way_to_relation: dict[int, Relation] = {}
    for way in ways:
        tokens = extract_to_destination(way)
        name = ";".join([t.strip() for t in tokens if t and t.strip()])
        if not name:
            continue
        if way.id not in way_to_relation:
            way_to_relation[way.id] = Relation(name=name, road_type="destination")
    return way_to_relation


def wrap_relation_to_node_relation(
    rel_ways_nodes: Sequence[tuple[OverPassRelation, list[OverPassWay], list[OverPassNode]]],
    road_type: str,
) -> dict[int, Relation]:
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
            if not getattr(way, "nodes", None):
                continue
            for node_id in way.nodes:
                if node_id not in node_to_relations:
                    node_to_relations[node_id] = relation_obj
    return node_to_relations


def build_weigh_way_relations(
    ways: list[OverPassWay],
    weigh_stations: list[OverPassWay],
    threshold_km: float = 0.05,
) -> dict[int, Relation]:
    """Build a global way_id -> Relation mapping for ways near a weigh station.

    For each way (with geometry), if its sampled geometry points are within the threshold
    of the nearest weigh station, map the way_id to that station's name.
    """
    if not ways or not weigh_stations:
        return {}

    # Prepare station reference points
    station_points: list[tuple[str, float, float]] = []  # (name, lat, lng)
    for ws in weigh_stations:
        if not ws.geometry:
            continue
        name = ws.tags.get("name")
        if not name:
            continue
        p = ws.geometry[0]
        station_points.append((name, p.lat, p.lng))

    way_to_rel: dict[int, Relation] = {}
    for w in ways:
        geom = getattr(w, "geometry", None)
        if not geom:
            continue
        step = max(1, len(geom) // 10)
        samples = geom[::step]
        closest_d = float("inf")
        closest_name: str | None = None
        for sname, slat, slng in station_points:
            d = min(
                (calculate_distance(pt.lat, pt.lng, slat, slng) for pt in samples),
                default=float("inf"),
            )
            if d < closest_d:
                closest_d = d
                closest_name = sname
        if closest_name and closest_d <= threshold_km:
            way_to_rel[w.id] = Relation(name=closest_name, road_type="weigh")
    return way_to_rel


def wrap_junction_name_relation(
    node_dict: dict[int, OverPassNode], ignored_ids: set[int] | None = None
) -> dict[int, Relation]:
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
    return node_to_relation
