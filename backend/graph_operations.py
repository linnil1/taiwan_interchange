"""
Graph operations for interchange analysis.
Separated from data.py for better organization.
"""

from collections import defaultdict

import networkx as nx

from models import Path, Ramp


def get_begin_nodes(paths: list[Path]) -> list[int]:
    """
    Find all begin nodes for path traversal.
    """
    if not paths:
        return []

    out_count = defaultdict(int)

    for path in paths:
        start_node, end_node = path.get_endpoint_nodes()
        out_count[end_node.id] += 1
        out_count[start_node.id] += 0
    return [node_id for node_id, count in out_count.items() if count == 0]


def get_graph_from_ramps(ramps: list[Ramp]) -> nx.DiGraph:
    """
    Create a directed graph from a list of ramps.
    """
    G = nx.DiGraph()
    for ramp in ramps:
        G.add_node(ramp.id, ramp=ramp)

    for ramp in ramps:
        for to_ramp_id in ramp.to_ramps:
            G.add_edge(ramp.id, to_ramp_id)
    return G


def get_connected_ramps(ramps: list[Ramp]) -> list[list[Ramp]]:
    """
    Get groups of ramps that are connected using to_ramps/from_ramps with NetworkX.

    Returns a list of connected ramp groups.
    """
    if not ramps:
        return []

    G = get_graph_from_ramps(ramps)

    # Find connected components (treat as undirected for grouping)
    undirected_G = G.to_undirected()

    # Convert component IDs back to ramp objects
    connected_groups = []
    for component in nx.connected_components(undirected_G):
        group_ramps = [G.nodes[ramp_id]["ramp"] for ramp_id in component]
        connected_groups.append(group_ramps)

    return connected_groups


def get_reverse_topological_order(ramps: list[Ramp]) -> list[Ramp]:
    """
    Get reverse topological order of ramps for destination propagation.

    Returns ramp IDs in reverse topological order (downstream to upstream).
    Since connect_paths ensures no cycles, this will always succeed.
    """
    if not ramps:
        return []

    G = get_graph_from_ramps(ramps)

    # Get topological order (downstream to upstream)
    topo_order = list(nx.topological_sort(G))
    # Reverse to process downstream ramps first
    topo_order.reverse()
    return [G.nodes[ramp_id]["ramp"] for ramp_id in topo_order]
