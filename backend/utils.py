"""
Utility functions shared across backend modules.
"""

import math
import re
from collections import Counter
from collections.abc import Hashable, Iterable
from typing import TypeVar

from models import Bounds, Node


def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate the distance between two coordinates using the Haversine formula.
    Returns distance in kilometers.
    """
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


def normalize_weigh_station_name(station_name: str) -> str:
    """
    Normalize weigh station names by removing directional suffixes.

    Examples:
    - "頭城南向地磅站" -> "頭城地磅站"
    - "xxx向地磅站" -> "xxx地磅站"
    """

    # Pattern to match directional suffixes like "南向", "北向", "東向", "西向" before "地磅站"
    pattern = r"(.+?)[東西南北]向地磅站$"
    match = re.match(pattern, station_name)
    if match:
        return match.group(1) + "地磅站"
    return station_name


def calculate_bounds(nodes: Iterable[Node]) -> Bounds | None:
    """Calculate min/max lat/lng from a list of nodes.

    Args:
        nodes: Iterable of Node objects.
    Returns:
        Bounds or None if no nodes provided.
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
        - group_to_values: mapping from an integer group key to a list of hashable values.

    Returns:
        - dict[int, T]: mapping from group key to its modal value. If a group has
            multiple values tied for max frequency, the earliest occurrence in the
            group's input list is chosen.
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
