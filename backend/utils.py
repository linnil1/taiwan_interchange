"""
Utility functions shared across backend modules.

Includes:
- Haversine distance calculation
- Bounds calculation for collections of nodes
- Modal value selection per group with deterministic tie-breaks
"""

import math
from collections import Counter
from collections.abc import Hashable, Iterable
from typing import TypeVar

from models import Bounds, Interchange, Node, Ramp


def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance (km) between two coordinates using the Haversine formula."""
    # Convert latitude and longitude from degrees to radians
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])

    # Haversine formula
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    # Radius of Earth in kilometers
    r = 6371

    return c * r


def calculate_bounds(nodes: Iterable[Node]) -> Bounds | None:
    """Calculate min/max lat/lng from a list of nodes.

    Args:
        nodes: Iterable of Node objects
    Returns:
        Bounds or None if no nodes provided
    """
    lats: list[float] = []
    lngs: list[float] = []
    for n in nodes:
        lats.append(n.lat)
        lngs.append(n.lng)

    if not lats:
        return None

    return Bounds(min_lat=min(lats), max_lat=max(lats), min_lng=min(lngs), max_lng=max(lngs))


# Generic type for modal aggregation per group; must be hashable for counting
T = TypeVar("T", bound=Hashable)


def choose_modal_per_group(group_to_values: dict[int, list[T]]) -> dict[int, T]:
    """Return the modal value for each group with deterministic tie-breaking.

    Inputs:
        group_to_values: mapping from int group key to list of hashable values

    Returns:
        mapping from group key to its modal value. If multiple values tie for max
        frequency, the earliest occurrence in that group's input list is chosen.
    """
    result: dict[int, T] = {}
    for gid, values in group_to_values.items():
        if not values:
            continue
        counts = Counter(values)
        max_count = max(counts.values())
        # Deterministic tie-break: earliest in the original list with max frequency
        for v in values:
            if counts[v] == max_count:
                result[gid] = v
                break
    return result


def ramp_contains_way(ramps: list[Ramp], way_id: int) -> bool:
    """Return True if any path in the given ramps matches the OSM way id."""
    return any(p.id == way_id for r in ramps for p in r.paths)


def renumber_interchanges(interchanges: list[Interchange]) -> list[Interchange]:
    """Renumber interchanges sequentially starting from 1."""
    for i, ic in enumerate(interchanges):
        ic.id = i + 1
    return interchanges
