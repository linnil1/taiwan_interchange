"""
Path-level operations: convert Overpass Ways to Path objects and split Paths
at logical breakpoints (endpoints, traffic lights, specified nodes).

Also includes small helpers for concatenation and connectivity checks.
"""

from models import Node, Path
from osm import OverPassNode, OverPassWay
from osm_operations import is_node_traffic_light


def process_single_path(overpass_way: OverPassWay) -> Path:
    """Convert a single OverPass way into a Path object.

    Requires geometry and node lists to be present and of equal length.
    """
    assert overpass_way.geometry, "Way geometry is empty"
    assert overpass_way.nodes, "Way nodes are empty"
    assert len(overpass_way.geometry) == len(overpass_way.nodes), (
        "Geometry and nodes length mismatch"
    )

    nodes = [
        Node(lat=coord.lat, lng=coord.lng, id=node_id)
        for coord, node_id in zip(overpass_way.geometry, overpass_way.nodes)
    ]
    return Path(id=overpass_way.id, part=0, nodes=nodes)


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
    seen: set[int] = set()
    result: list[Path] = []
    for p in path1 + path2:
        if p.id not in seen:
            seen.add(p.id)
            result.append(p)
    return result
