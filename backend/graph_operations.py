"""
Graph operations for interchange analysis.
Separated from data.py for better organization.
"""

from collections import defaultdict, deque
from collections.abc import Callable

import networkx as nx

from models import Path, Ramp
from path_operations import can_paths_connect


class DisjointSet:
    """Union-Find (Disjoint Set) with path compression"""

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
    can_connect: Callable[[Path, Path], bool] | None = None,
) -> list[Ramp]:
    """
    Contract sequential paths into ramps by merging along nodes with exactly
    one incoming and one outgoing edge (and not crossing a path that is marked ended).

    Returns a list of Ramp objects with contiguous Path sequences; connectivity
    (from_ramps/to_ramps) is not set here.
    """
    if not paths:
        return []
    if can_connect is None:
        can_connect = can_paths_connect

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
            if not can_connect(cur, nxt):
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
    Build the full graph connectivity (to_ramps/from_ramps) based on shared endpoint nodes.
    Implemented with NetworkX; result is stored back into Ramp.to_ramps/from_ramps.
    Does not enforce DAG; use build_dag_edges to compute a DAG projection into dag_to.
    """
    if not ramps:
        return []

    # Build temporary graph with NetworkX
    G = nx.DiGraph()
    for r in ramps:
        G.add_node(r.id)

    for r in ramps:
        s, e = r.get_endpoint_nodes()
        G.add_edge(s.id, e.id)

    # Write back edges
    for r in ramps:
        r.to_ramps = sorted(list(G.successors(r.id)))
        r.from_ramps = sorted(list(G.predecessors(r.id)))
    return ramps


def build_dag_edges(ramps: list[Ramp]) -> list[Ramp]:
    """
    Create a DAG projection from the full graph, storing edges in dag_to.
    - Keeps to_ramps/from_ramps untouched (full graph visibility).
    - Builds dag_to by adding edges in BFS order and skipping any that would form a cycle.
    - BFS ensures pop-ready behavior naturally; no extra prioritization function is needed.
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
    Create a directed graph from dag_to edges of ramps (DAG projection).
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
    Assign a weakly-connected component id to each Ramp via ramp.branch_id based on full graph (to_ramps).
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
    Get reverse topological order of ramps for destination propagation using DAG edges.

    Returns ramps in reverse topological order (downstream to upstream) based on dag_to.
    """
    if not ramps:
        return []

    G = get_graph_from_ramps_dag(ramps)

    # Get topological order (downstream to upstream)
    topo_order = list(nx.topological_sort(G))
    # Reverse to process downstream ramps first
    topo_order.reverse()
    return [G.nodes[ramp_id]["ramp"] for ramp_id in topo_order]
