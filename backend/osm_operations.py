"""
OSM processing helpers separate from API/data models.

This module provides:
- Tag-based helpers (access, traffic lights, destination parsing)
- Freeway relation extraction with geometry preparation
- Simple name normalization utilities
"""

import re

from osm import Coordinate, OverPassNode, OverPassRelation, OverPassResponse, OverPassWay


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
        if not w or not w.nodes:
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


def filter_weight_stations(response: OverPassResponse) -> list[OverPassWay]:
    """Return weigh station ways that have a name and geometry.

    The input is the OverPassResponse from load_nearby_weigh_stations.
    """
    ways = response.list_ways()
    return [w for w in ways if (w.tags or {}).get("name") and getattr(w, "geometry", None)]


def is_one_way(way: OverPassWay) -> bool:
    """Determine if a way is one-way.

    Considers common OSM encodings:
    - oneway=yes/true/1/-1 treated as one-way ("-1" means opposite direction)
    - oneway=no/false/0 treated as two-way
    Missing tag treated as two-way.
    """
    val = (way.tags or {}).get("oneway", "no").strip().lower()
    return val in {"yes", "true", "1", "-1"}


def process_relations_mapping(
    response: OverPassResponse,
) -> list[tuple[OverPassRelation, list[OverPassWay], list[OverPassNode]]]:
    """Process relation membership and return list of (relation, ways, nodes).

    The road_type is retained for downstream mapping but not used here directly.
    """
    if not response.elements:
        return []

    relations = response.list_relations()
    ways = response.list_ways()
    nodes = response.list_nodes()

    way_by_id = {w.id: w for w in ways}
    node_by_id = {n.id: n for n in nodes}
    result: list[tuple[OverPassRelation, list[OverPassWay], list[OverPassNode]]] = []

    for relation in relations:
        # Collect way members for this relation
        way_ids = [m.ref for m in relation.members if m.type == "way"]
        rel_ways = [way_by_id[w] for w in way_ids if w in way_by_id]
        # Collect unique node objects from those ways
        node_ids = []
        for w in rel_ways:
            node_ids.extend(w.nodes)
        seen: set[int] = set()
        rel_nodes = [
            node_by_id[nid]
            for nid in node_ids
            if nid in node_by_id and not (nid in seen or seen.add(nid))
        ]
        result.append((relation, rel_ways, rel_nodes))

    return result


def list_master_relations(response: OverPassResponse) -> list[OverPassRelation]:
    """Return all route_master relations from response."""
    return [
        rel for rel in response.list_relations() if (rel.tags or {}).get("type") == "route_master"
    ]


def display_for_master(master: OverPassRelation) -> tuple[str, str]:
    """Return (ref, name) for a master relation with fallbacks."""
    tags = master.tags or {}
    ref = tags.get("ref") or tags.get("name") or f"master:{master.id}"
    name = tags.get("name") or ref
    return ref, name
