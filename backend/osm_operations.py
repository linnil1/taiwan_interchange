"""
OSM processing helpers separate from API/data models.

This module provides:
- Tag-based helpers (access, traffic lights, destination parsing)
- Freeway relation extraction with geometry preparation
- Simple name normalization utilities
"""

import re

from models import Relation
from osm import Coordinate, OverPassNode, OverPassResponse, OverPassWay


def extract_to_destination(way: OverPassWay) -> list[str]:
    """Extract destinations from way tags: exit_to, destination, or ref.

    Returns all values split by ';' for exit_to/destination, or single ref if
    destination fields are absent.
    """
    destinations: list[str] = []
    tags = way.tags or {}

    if tags.get("exit_to"):
        destinations.extend(tags["exit_to"].split(";"))

    if tags.get("destination"):
        destinations.extend(tags["destination"].split(";"))

    if tags.get("ref") and not destinations:
        destinations.append(tags["ref"])

    return destinations


def is_node_traffic_light(node: OverPassNode | None) -> bool:
    """Check if a node is a traffic signal/stop control point based on tags."""
    if node and node.tags:
        return (
            node.tags.get("highway") == "traffic_signals"
            or node.tags.get("traffic_signals") is not None
            or node.tags.get("highway") == "stop"
            or node.tags.get("stop") is not None
        )
    return False


def is_way_access(way: OverPassWay) -> bool:
    """Return True if the way is generally accessible (not private/no/emergency/permissive)."""
    access = way.tags.get("access") if isinstance(way.tags, dict) else None
    return access not in ["private", "no", "emergency", "permissive"]


def is_way_motorway_link(way: OverPassWay) -> bool:
    """Return True if the way has highway=motorway_link."""
    return (way.tags or {}).get("highway") == "motorway_link"


def extract_freeway_related_ways(response: OverPassResponse) -> list[OverPassWay]:
    """Extract ways that are members of freeway relations from a freeway response.

    Ensures each returned way has nodes/geometry populated.

    Note:
    - Ways tagged with highway=proposed are skipped (e.g., planned spur lines).
    - We do not special-case relation names (e.g., 國道一號甲線) anymore; proposed
      ways are filtered by tag instead.
    """
    if not response.elements:
        return []

    ways = response.list_ways()
    nodes = response.list_nodes()
    way_by_id = {w.id: w for w in ways}
    node_by_id = {n.id: n for n in nodes}
    related_ids: list[int] = []
    for rel in response.list_relations():
        if rel.tags.get("type") != "route":
            continue
        related_ids.extend([m.ref for m in rel.members if m.type == "way"])

    # Preserve order, de-dup, and only return usable ways
    seen: set[int] = set()
    result: list[OverPassWay] = []
    for wid in related_ids:
        if wid in seen:
            continue
        seen.add(wid)
        w = way_by_id.get(wid)
        if not w or not getattr(w, "nodes", None):
            continue
        # Ignore proposed highways
        if (w.tags or {}).get("highway") == "proposed":
            continue
        node_objs = [node_by_id.get(n) for n in w.nodes]
        if any(no is None for no in node_objs):
            continue
        if len(node_objs) < 2:
            continue
        w.geometry = [Coordinate(lat=n.lat, lon=n.lon) for n in node_objs if n is not None]
        result.append(w)
    return result


def normalize_weigh_station_name(station_name: str) -> str:
    """
    Normalize weigh station names by removing directional suffixes.

    Examples:
    - "頭城南向地磅站" -> "頭城地磅站"
    - "xxx向地磅站" -> "xxx地磅站"
    """
    pattern = r"(.+?)[東西南北]向地磅站$"
    match = re.match(pattern, station_name)
    if match:
        return match.group(1) + "地磅站"
    return station_name


def process_relations_by_way(response: OverPassResponse, road_type: str) -> dict[int, Relation]:
    """Process ways and return a node->relation mapping for those with names."""
    ways = response.list_ways()
    node_to_relation: dict[int, Relation] = {}

    for way in ways:
        if not way.tags.get("name"):
            continue
        relation = Relation(name=way.tags["name"], road_type=road_type)
        for node_id in way.nodes:
            if node_id not in node_to_relation:
                node_to_relation[node_id] = relation
    return node_to_relation


def process_relations_mapping(response: OverPassResponse, road_type: str) -> dict[int, Relation]:
    """Process relation membership to build node->relation mapping by name."""
    node_to_relations: dict[int, Relation] = {}
    relations = response.list_relations()
    ways = response.list_ways()

    # Create way_id to way mapping for efficiency
    way_dict = {way.id: way for way in ways}

    for relation in relations:
        if not relation.tags or "name" not in relation.tags:
            continue

        relation_obj = Relation(name=relation.tags["name"], road_type=road_type)

        # Gather way members
        way_ids_in_relation = {member.ref for member in relation.members if member.type == "way"}

        # Map all nodes from these ways to this relation object
        for way_id in way_ids_in_relation:
            way = way_dict.get(way_id)
            if way and way.nodes:
                for node_id in way.nodes:
                    if node_id not in node_to_relations:
                        node_to_relations[node_id] = relation_obj

    return node_to_relations
