"""
Graph operations for interchange analysis.

This module builds connectivity between path segments (as "ramps"),
constructs a DAG projection for ordered processing, and provides helpers
to derive endpoint ways for networks. Logic is separated from data
loading/assembly for clarity.
"""

from collections import Counter, defaultdict, deque

import networkx as nx

from models import Path, Ramp
from osm import OverPassWay
from path_operations import can_paths_connect


class DisjointSet:
    """Union-Find (Disjoint Set) with path compression.

    Note: No union-by-rank heuristic is used; it's sufficient for our DAG
    construction where we only need to detect (undirected) cycles cheaply.
    """

    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.parent[ra] = rb
        return True

    def is_connect(self, a: int, b: int) -> bool:
        return self.find(a) == self.find(b)


def contract_paths_to_ramps(
    paths: list[Path],
) -> list[Ramp]:
    """
    Contract sequential paths into ramps by merging along nodes that have
    exactly one incoming and one outgoing edge.

    Returns a list of Ramp objects with contiguous Path sequences; graph
    connectivity (from_ramps/to_ramps) is not set here.
    """
    if not paths:
        return []

    # Build adjacency of paths by endpoint node ids
    outgoing_paths: defaultdict[int, list[Path]] = defaultdict(list)
    incoming_paths: defaultdict[int, list[Path]] = defaultdict(list)
    for p in paths:
        s, e = p.get_endpoint_nodes()
        outgoing_paths[s.id].append(p)
        incoming_paths[e.id].append(p)

    begin_node_ids = [
        node_id for node_id, _ in outgoing_paths.items() if node_id not in incoming_paths
    ]

    # Track included paths by subpath id to avoid duplicates / cycles
    used: set[str] = set()

    def extend_chain(start: Path) -> list[Path]:
        chain = [start]
        used.add(start.get_subpath_id())
        cur = start
        last_id = cur.get_endpoint_nodes()[1].id

        # Keep extending while the junction has exactly one in and one out
        while (
            len(outgoing_paths.get(last_id, [])) == 1 and len(incoming_paths.get(last_id, [])) == 1
        ):
            nxt = outgoing_paths[last_id][0]
            sub_id = nxt.get_subpath_id()
            if sub_id in used:
                # Prevent accidental loops
                break
            if not can_paths_connect(cur, nxt):
                break
            chain.append(nxt)
            used.add(sub_id)
            cur = nxt
            last_id = cur.get_endpoint_nodes()[1].id
        return chain

    ramps: list[Ramp] = []

    # Prefer starting from begin nodes for deterministic chains
    for node_id in begin_node_ids:
        for p in outgoing_paths.get(node_id, []):
            if p.get_subpath_id() in used:
                continue
            chain = extend_chain(p)
            ramps.append(Ramp(id=len(ramps), paths=chain))

    # Fallback: cover any remaining paths (e.g., inside small cycles)
    for p in paths:
        sid = p.get_subpath_id()
        if sid in used:
            continue
        chain = extend_chain(p)
        ramps.append(Ramp(id=len(ramps), paths=chain))

    return ramps


def connect_ramps_by_nodes(ramps: list[Ramp]) -> list[Ramp]:
    """
    Build full graph connectivity (to_ramps/from_ramps) based on shared endpoint nodes.

    Implementation detail:
    - Model each ramp as an edge from its start node to end node.
    - For each node, connect every incoming-ramp to every outgoing-ramp through
        that node, updating `to_ramps`/`from_ramps` on the Ramp objects.

    This does not enforce acyclicity; use `build_dag_edges` to compute a DAG
    projection into `dag_to`.
    """
    if not ramps:
        return []

    # Build temporary graph with NetworkX
    G = nx.MultiDiGraph()
    for r in ramps:
        s, e = r.get_endpoint_nodes()
        r.to_ramps = []
        r.from_ramps = []
        G.add_edge(s.id, e.id, ramp=r)

    for node_id in G.nodes:
        out_ramps: list[Ramp] = [data.get("ramp") for _, _, data in G.out_edges(node_id, data=True)]
        in_ramps: list[Ramp] = [data.get("ramp") for _, _, data in G.in_edges(node_id, data=True)]

        # Connect every incoming ramp to every outgoing ramp through this node
        for in_r in in_ramps:
            for out_r in out_ramps:
                in_r.to_ramps.append(out_r.id)
                out_r.from_ramps.append(in_r.id)

    # Deduplicate and sort for stability
    for r in ramps:
        r.to_ramps = sorted(set(r.to_ramps))
        r.from_ramps = sorted(set(r.from_ramps))

    return ramps


def build_dag_edges(ramps: list[Ramp]) -> list[Ramp]:
    """
    Create a DAG projection from the full graph, storing edges in `dag_to`.

    - Keeps `to_ramps`/`from_ramps` untouched (full graph visibility).
    - Builds `dag_to` by traversing edges in BFS order and skipping any that would
        form an (undirected) cycle, detected via a disjoint-set structure.
    - BFS order provides a stable, pop-ready processing sequence without extra
        prioritization.
    """
    if not ramps:
        return []

    # Reset DAG edges only
    for r in ramps:
        r.dag_to = []

    # Identify begin ramps (no incoming in full graph)
    in_deg = {r.id: 0 for r in ramps}
    for r in ramps:
        for v in r.to_ramps:
            in_deg[v] = in_deg.get(v, 0) + 1
    begin_ids = [rid for rid, deg in in_deg.items() if deg == 0]

    dsu = DisjointSet()

    # BFS over full graph edges, adding to dag_to if it doesn't create a cycle
    visited: set[int] = set()
    dq: deque[int] = deque(begin_ids if begin_ids else [r.id for r in ramps])
    while dq:
        u = dq.popleft()
        if u in visited:
            continue
        visited.add(u)
        # Evaluate outgoing edges from full graph
        for v in ramps[u].to_ramps:
            # Add to queue for exploration
            dq.append(v)
            # Only add to DAG if it won't create a (undirected) cycle
            if not dsu.is_connect(u, v):
                ramps[u].dag_to.append(v)
                dsu.union(u, v)
        # Keep DAG edges stable
        ramps[u].dag_to = sorted(set(ramps[u].dag_to))

    return ramps


def get_graph_from_ramps_dag(ramps: list[Ramp]) -> nx.DiGraph:
    """
    Create a directed graph from `dag_to` edges of ramps (DAG projection).
    """
    G = nx.DiGraph()
    for ramp in ramps:
        G.add_node(ramp.id, ramp=ramp)
    for ramp in ramps:
        for to_ramp_id in ramp.dag_to:
            G.add_edge(ramp.id, to_ramp_id)
    return G


def assign_branch_ids(ramps: list[Ramp]) -> list[Ramp]:
    """
    Assign a weakly-connected component id to each Ramp via `ramp.branch_id`.

    Note: Components are computed on the DAG projection (`dag_to`), treating it
    as undirected. This groups ramps that are connected within the DAG.
    """
    if not ramps:
        return []

    G = get_graph_from_ramps_dag(ramps)

    # Find connected components (treat as undirected for grouping)
    undirected_G = G.to_undirected()
    new_ramps = []
    for comp_id, component in enumerate(nx.connected_components(undirected_G)):
        for rid in component:
            ramp_obj: Ramp = G.nodes[rid]["ramp"]
            ramp_obj.branch_id = comp_id
            new_ramps.append(ramp_obj)
    return new_ramps


def get_reverse_topological_order(ramps: list[Ramp]) -> list[Ramp]:
    """
    Get reverse topological order of ramps (for downstream-to-upstream propagation)
    using DAG edges.

    Returns ramps in reverse topological order based on `dag_to`.
    """
    if not ramps:
        return []

    G = get_graph_from_ramps_dag(ramps)

    # Get topological order (downstream to upstream)
    topo_order = list(nx.topological_sort(G))
    # Reverse to process downstream ramps first
    topo_order.reverse()
    return [G.nodes[ramp_id]["ramp"] for ramp_id in topo_order]


def extract_endpoint_ways(ways: list[Path]) -> list[Path]:
    """From an unordered set of freeway relation ways, determine begin/end ways by
    analyzing connectivity via endpoint nodes. Works across multiple components.

    Note: Filtering (e.g., motorway_link or access restrictions) is left to the caller.
    """
    way_by_id: dict[int, Path] = {w.id: w for w in ways}
    # Count how many ways start (outbound) and end (inbound) at each endpoint node
    node_out_count: Counter[int] = Counter()
    node_in_count: Counter[int] = Counter()
    endpoints_by_way: dict[int, tuple[int, int]] = {}

    for w in ways:
        start = w.nodes[0].id
        end = w.nodes[-1].id
        endpoints_by_way[w.id] = (start, end)
        node_out_count[start] += 1
        node_in_count[end] += 1

    # Select ways whose start has 0 inbound (no way ends at start)
    # or whose end has 0 outbound (no way starts at end)
    result_ids: list[int] = []
    for wid, (start, end) in endpoints_by_way.items():
        w = way_by_id[wid]
        # if is_way_motorway_link(w):
        #   continue
        if node_in_count.get(start, 0) == 0 or node_out_count.get(end, 0) == 0:
            result_ids.append(wid)

    return [way_by_id[i] for i in result_ids if i in way_by_id]


def filter_endpoints_by_motorway_link(
    endpoints: list[Path], motorway_links: list[Path]
) -> list[Path]:
    """
    Drop endpoints that directly connect to a motorway_link's entrance/exit node.

    Heuristic: remove endpoints whose end node matches the first node of any link,
    or whose start node matches the last node of any link.
    """
    if not endpoints:
        return []
    if not motorway_links:
        return endpoints

    outgoing_nodes: set[int] = set()
    incoming_nodes: set[int] = set()
    for link in motorway_links:
        if not link.nodes:
            continue
        outgoing_nodes.add(link.nodes[0].id)
        incoming_nodes.add(link.nodes[-1].id)

    def keep(p: Path) -> bool:
        s, e = p.get_endpoint_nodes()
        if e.id in outgoing_nodes:
            return False
        if s.id in incoming_nodes:
            return False
        return True

    return [p for p in endpoints if keep(p)]


def build_ordered_node_ids_for_relation(ways: list[OverPassWay]) -> dict[int, int]:
    """Return an ordering map of node_id -> order index for a route relation's member ways.

    Uses a NetworkX directed graph built from consecutive nodes in each way to determine
    a plausible linear chain, then converts to undirected for component analysis.

    Behavior changes:
    - If the member ways produce multiple connected components, raise ValueError.
    - If the single component has no endpoint node (in_degree 0), raise ValueError.
    - Use DFS preorder only (no shortest-path fallback).
    - Start from the endpoint node with in_degree == 0; if multiple, use the smallest node ID.
    """
    if not ways:
        return {}

    G = nx.DiGraph()

    # Add edges between consecutive node ids for all member ways
    for w in ways:
        if len(w.nodes) < 2:
            continue
        for node1, node2 in zip(w.nodes[:-1], w.nodes[1:]):
            G.add_edge(int(node1), int(node2))

    # Ensure a single component; error if multiple components found
    comps = list(nx.connected_components(G.to_undirected()))
    if len(comps) > 1:
        raise ValueError(
            "Relation ways contain multiple connected components; cannot determine single ordering"
        )

    # Endpoints are nodes with degree 1 in this (single) component
    endpoints = [n for n in G.nodes if G.in_degree(n) == 0]

    # Require at least one endpoint to determine a start; otherwise error
    if not endpoints:
        raise ValueError(
            "No endpoint (degree-1) node found in relation; cannot determine start for ordering"
        )

    # Use DFS preorder from the chosen start
    path = [int(n) for n in nx.dfs_preorder_nodes(G, source=min(endpoints))]

    return {nid: idx for idx, nid in enumerate(path)}


def connected_components_of_ways(ways: list[OverPassWay]) -> list[list[OverPassWay]]:
    """Return connected components of ways based on shared node ids.

    Builds an undirected graph whose vertices are way ids and adds an edge
    between two ways if they share at least one node id. Returns a list
    of components as lists of OverPassWay objects.

    Args:
        ways: List of OverPassWay objects with populated `id` and `nodes`.

    Returns:
        A list of components, each component is a list of OverPassWay objects.
    """
    if not ways:
        return []

    # Map from node id -> list of way ids containing that node
    node_to_way_ids: defaultdict[int, list[int]] = defaultdict(list)
    way_ids: list[int] = []
    id_to_way: dict[int, OverPassWay] = {}
    for w in ways:
        wid = int(w.id)
        way_ids.append(wid)
        id_to_way[wid] = w
        for nid in getattr(w, "nodes", []) or []:
            node_to_way_ids[int(nid)].append(wid)

    G = nx.Graph()
    for wid in way_ids:
        G.add_node(wid)

    for way_list in node_to_way_ids.values():
        if len(way_list) < 2:
            continue
        # Fully connect all ways that share this node (clique on this subset)
        for i in range(len(way_list)):
            for j in range(i + 1, len(way_list)):
                G.add_edge(way_list[i], way_list[j])

    return [[id_to_way[i] for i in comp] for comp in nx.connected_components(G)]


def find_longest_connected_path(ways: list[Path]) -> list[Path]:
    """Find the longest connected path from each connected component.

    This creates a graph from the ways, finds all connected components,
    and returns the longest simple path from each component efficiently.

    Args:
        ways: List of Path objects to analyze

    Returns:
        List of Path objects representing the longest paths from all components
    """
    if not ways:
        return []

    if len(ways) == 1:
        return ways

    # Build a graph where nodes are way IDs and edges connect ways that share endpoints
    G = nx.Graph()
    way_by_id: dict[int, Path] = {w.id: w for w in ways}

    # Add all ways as nodes
    for way in ways:
        G.add_node(way.id)

    # Add edges between ways that share endpoint nodes
    endpoint_to_ways: dict[int, list[int]] = {}
    for way in ways:
        start_node = way.nodes[0].id
        end_node = way.nodes[-1].id

        for node_id in [start_node, end_node]:
            if node_id not in endpoint_to_ways:
                endpoint_to_ways[node_id] = []
            endpoint_to_ways[node_id].append(way.id)

    # Connect ways that share endpoint nodes
    for node_id, way_ids in endpoint_to_ways.items():
        for i in range(len(way_ids)):
            for j in range(i + 1, len(way_ids)):
                G.add_edge(way_ids[i], way_ids[j])

    # Find all connected components
    components = list(nx.connected_components(G))

    all_longest_paths = []

    # For each component, find the longest simple path efficiently
    for component in components:
        if len(component) == 1:
            # Single way component
            way_id = next(iter(component))
            all_longest_paths.append(way_by_id[way_id])
            continue

        # Create subgraph for this component
        subgraph = G.subgraph(component)

        # Find nodes with degree 1 (endpoints) - these are natural start/end points
        degree_1_nodes = [node for node in component if subgraph.degree(node) == 1]

        longest_path = []
        max_distance = 0

        if len(degree_1_nodes) < 2:
            raise ValueError("Not enough degree-1 nodes to find a path")

        # Use degree-1 nodes to find the longest path
        for i, start_node in enumerate(degree_1_nodes):
            for j, end_node in enumerate(degree_1_nodes):
                if i < j:  # Avoid duplicate pairs
                    path = nx.shortest_path(subgraph, start_node, end_node)
                    distance = len(path)
                    if distance > max_distance:
                        max_distance = distance
                        longest_path = path

        # Add the longest path ways from this component
        component_longest_ways = [
            way_by_id[way_id] for way_id in longest_path if way_id in way_by_id
        ]
        all_longest_paths.extend(component_longest_ways)

    return all_longest_paths


def extract_branch_ways(ways: list[Path]) -> list[Path]:
    """Extract all ways that are NOT part of the longest connected paths.

    This is the complement of finding the longest paths - it returns all
    the "branch" ways that connect to but are not part of the main routes
    in each connected component.

    Args:
        ways: List of Path objects to analyze

    Returns:
        List of Path objects that are branches (not in longest paths)
    """
    if not ways:
        return []

    longest_path_ways = find_longest_connected_path(ways)
    longest_path_ids = {w.id for w in longest_path_ways}

    # Return all ways that are not in the longest path
    branch_ways = [w for w in ways if w.id not in longest_path_ids]

    return branch_ways
