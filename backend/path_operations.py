"""
Path-level operations: convert Overpass Ways to Path objects and split Paths
at logical breakpoints (endpoints, traffic lights, specified nodes).

Also includes small helpers for concatenation and connectivity checks.
"""

from models import Node, Path
from osm import OverPassNode, OverPassWay
from osm_operations import is_node_traffic_light, is_one_way, is_way_access


def process_single_path(overpass_way: OverPassWay, reverse: bool = False) -> Path:
    """Convert a single OverPass way into a Path object.

    Requires geometry and node lists to be present and of equal length.

    Args:
        overpass_way: Source way from Overpass.
        reverse: When True, build the path with nodes reversed (for two-way duplication).
    """
    assert overpass_way.geometry, "Way geometry is empty"
    assert overpass_way.nodes, "Way nodes are empty"
    assert len(overpass_way.geometry) == len(overpass_way.nodes), (
        "Geometry and nodes length mismatch"
    )

    nodes = [
        Node(lat=c.lat, lng=c.lng, id=nid)
        for c, nid in zip(overpass_way.geometry, overpass_way.nodes)
    ]
    # Use part=1 for reversed copy to differentiate; downstream splitters will renumber parts anyway
    part = 1 if reverse else 0
    nodes = list(reversed(nodes)) if reverse else nodes
    return Path(id=overpass_way.id, part=part, nodes=nodes)


def filter_accessible_ways(
    ways: list[OverPassWay], excluded_ids: set[int] | None = None
) -> list[OverPassWay]:
    """Filter ways to those that are accessible and not excluded by id.

    Args:
        ways: Input OverPass ways.
        excluded_ids: Optional set of way IDs to exclude.
    """
    excluded_ids = excluded_ids or set()
    return [w for w in ways if is_way_access(w) and w.id not in excluded_ids]


def process_paths_from_ways(
    ways: list[OverPassWay], *, excluded_ids: set[int] | None = None, duplicate_two_way: bool = True
) -> list[Path]:
    """Convert a list of OverPass ways into a list of Path objects.

    - Filters ways by accessibility and excluded IDs.
    - Converts each way into a Path.
    - If duplicate_two_way is True and way is not explicitly oneway=yes,
      also adds a reversed Path for the same way id.
    """
    filtered = filter_accessible_ways(ways, excluded_ids)
    paths: list[Path] = []
    for way in filtered:
        paths.append(process_single_path(way))
        if duplicate_two_way and not is_one_way(way):
            paths.append(process_single_path(way, reverse=True))
    return paths


def can_paths_connect(path1: Path, path2: Path) -> bool:
    """Default rule for contraction: allow only if the first path isn't ended.

    The second parameter is unused here but kept for signature compatibility with
    pluggable predicates.
    """
    return not path1.ended


def break_paths_by_nodes(paths: list[Path], node_ids: set[int]) -> list[Path]:
    """
    Split paths at internal nodes whose ids are in `node_ids`.

    - Does not modify `ended` flags.
    - Guarantees that for each original path id, the (id, part) pairs in the
      returned list are unique by assigning parts via a per-id counter.
    """
    if not paths:
        return []

    next_part: dict[int, int] = {}

    def alloc_part(pid: int) -> int:
        p = next_part.get(pid, 0)
        next_part[pid] = p + 1
        return p

    results: list[Path] = []
    for path in paths:
        pid = path.id
        if not path.nodes or len(path.nodes) <= 2:
            results.append(Path(id=pid, part=alloc_part(pid), nodes=path.nodes))
            continue

        break_points: list[int] = [
            i for i in range(1, len(path.nodes) - 1) if path.nodes[i].id in node_ids
        ]

        if not break_points:
            results.append(Path(id=pid, part=alloc_part(pid), nodes=path.nodes))
            continue

        start_idx = 0
        for break_idx in [*break_points, len(path.nodes)]:
            segment_nodes = path.nodes[start_idx : break_idx + 1]
            assert len(segment_nodes) >= 2
            results.append(Path(id=pid, part=alloc_part(pid), nodes=segment_nodes))
            start_idx = break_idx
    return results


def break_paths_by_endpoints(paths: list[Path]) -> list[Path]:
    """Split paths at internal nodes that are endpoints of any path in the set."""
    if not paths:
        return []

    endpoint_nodes: set[int] = set()
    for path in paths:
        if path.nodes:
            endpoint_nodes.add(path.nodes[0].id)
            endpoint_nodes.add(path.nodes[-1].id)
    return break_paths_by_nodes(paths, endpoint_nodes)


def break_paths_by_traffic_lights(
    paths: list[Path], node_dict: dict[int, OverPassNode]
) -> list[Path]:
    """Split at traffic light nodes, then mark segments ending at a light as `ended`."""
    # Precompute map of traffic lights and ids
    is_light: dict[int, bool] = {nid: is_node_traffic_light(n) for nid, n in node_dict.items()}
    light_ids: set[int] = {nid for nid, v in is_light.items() if v}

    # First split using the generic splitter
    paths = break_paths_by_nodes(paths, light_ids)

    for path in paths:
        path.ended = is_light.get(path.nodes[-1].id, False) if path.nodes else False
    return paths


def concat_paths(path1: list[Path], path2: list[Path]) -> list[Path]:
    """Concatenate two lists of paths, ensuring each path id appears once."""
    # Allow path1, path2 has duplicated path id
    # If they share ids, prefer path1
    path1_ids = set(i.id for i in path1)
    path2_ids = set(i.id for i in path2)
    new_ids = path2_ids - path1_ids
    return path1 + [p for p in path2 if p.id in new_ids]
