"""
Path-level operations: build Path objects and split Ways into path segments.
"""

from models import Node, Path
from osm import OverPassNode, OverPassWay, is_node_traffic_light


def process_single_path(overpass_way: OverPassWay) -> Path:
    """Convert a single OverPass way into a Path object."""
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
    """Default rule to allow contraction: don't connect if path1 is ended."""
    return not path1.ended


def break_paths_by_nodes(paths: list[Path], node_ids: set[int]) -> list[Path]:
    """Split paths at internal nodes whose ids are in node_ids; no ended flags set here.

    Guarantees that for each original path id, the (id, part) pairs in the returned
    list are unique by assigning parts via a per-id counter.
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
    """Split paths at internal nodes that are endpoints of other paths using the generic splitter."""
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
    """Split using traffic light nodes, then post-process to set ended and unique part indices."""
    # Precompute map of traffic lights and ids
    is_light: dict[int, bool] = {nid: is_node_traffic_light(n) for nid, n in node_dict.items()}
    light_ids: set[int] = {nid for nid, v in is_light.items() if v}

    # First split using the generic splitter
    segments = break_paths_by_nodes(paths, light_ids)

    # Ensure unique parts per original path id and set ended
    next_part: dict[int, int] = {}
    results: list[Path] = []
    for seg in segments:
        pid = seg.id
        part_idx = next_part.setdefault(pid, 0)
        ended = is_light.get(seg.nodes[-1].id, False) if seg.nodes else False
        results.append(Path(id=pid, part=part_idx, nodes=seg.nodes, ended=ended))
        next_part[pid] = part_idx + 1
    return results


def break_paths_at_connections(paths: list[Path], node_dict: dict[int, OverPassNode]) -> list[Path]:
    """Split by endpoints first, then by traffic lights."""
    paths = break_paths_by_endpoints(paths)
    return break_paths_by_traffic_lights(paths, node_dict)


def filter_way_by_access(way: OverPassWay) -> bool:
    """Return True if the way is allowed by access tag."""
    access = way.tags.get("access") if isinstance(way.tags, dict) else None
    return access not in ["private", "no", "emergency", "permissive"]
