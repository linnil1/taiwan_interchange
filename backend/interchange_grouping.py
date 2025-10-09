from collections import defaultdict
from collections.abc import Iterable
from itertools import chain

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from models import Interchange, Node, Ramp
from utils import calculate_bounds, choose_modal_per_group, ramp_contains_way, renumber_interchanges


def create_interchange_from_ramps(ramps: list[Ramp], id: int) -> Interchange:
    # Calculate bounds from all ramp nodes
    all_nodes: Iterable[Node] = chain.from_iterable(ramp.list_nodes() for ramp in ramps)
    bounds = calculate_bounds(all_nodes)
    if not bounds:
        raise ValueError("No valid bounds could be calculated for the interchange")

    interchange_name = "Unknown Interchange"
    return Interchange(id=id, name=interchange_name, bounds=bounds, ramps=ramps)


def group_ramps_to_interchange(
    ramps: list[Ramp], distance_threshold: float = 0.005
) -> list[Interchange]:
    """Group ramps into interchanges using single-linkage clustering over nodes."""
    if not ramps:
        return []

    # Collect all nodes from all ramps, grouped by branch_id
    all_nodes = []
    branch_to_ramps: dict[int, list[Ramp]] = defaultdict(list)
    for r in ramps:
        branch_to_ramps[r.branch_id].append(r)
    for ramp in ramps:
        for node in ramp.list_nodes():
            all_nodes.append((node.lat, node.lng, ramp.branch_id))

    if len(all_nodes) < 2:
        return [create_interchange_from_ramps(ramps, 1)]

    # Use agglomerative clustering with distance threshold
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        linkage="single",  # minimum distance between groups
    )
    nodes_array = np.array([node[:2] for node in all_nodes])
    node_labels = clustering.fit_predict(nodes_array)

    # rearrange cluster label by branch id
    branch_to_clusters = defaultdict(list)
    for node_idx, cluster_label in enumerate(node_labels):
        branch_id = all_nodes[node_idx][2]
        branch_to_clusters[branch_id].append(cluster_label)

    # Get the modal cluster per branch
    branch_assignment = choose_modal_per_group(branch_to_clusters)
    cluster_to_branch = defaultdict(list)
    for branch_id, cluster_label in branch_assignment.items():
        cluster_to_branch[cluster_label].append(branch_id)

    # Create interchange objects
    interchanges = []
    for cluster_label, branch_ids in cluster_to_branch.items():
        ramps = [ramp for branch_id in branch_ids for ramp in branch_to_ramps[branch_id]]
        if ramps:
            interchange = create_interchange_from_ramps(ramps, len(interchanges) + 1)
            interchanges.append(interchange)
    return interchanges


def split_interchanges_by_name_marker(
    interchanges: list[Interchange], *, distance_threshold: float = 0.001
) -> list[Interchange]:
    """
    Split interchanges whose names contain semicolons (';') by re-grouping their ramps.

    Args:
        interchanges: List of interchanges to process
        distance_threshold: Threshold passed to group_ramps_by_interchange

    Returns:
        A new list of interchanges where any semicolon-named entry may be split into multiple.
    """
    result: list[Interchange] = []
    for ic in interchanges:
        if ";" in ic.name:
            print(f"Splitting interchange: {ic.name}")
            result.extend(group_ramps_to_interchange(ic.ramps, distance_threshold))
        else:
            result.append(ic)
    return renumber_interchanges(result)


def merge_interchanges_by_name(interchanges: list[Interchange]) -> list[Interchange]:
    """
    Merge interchanges that share the exact same name.

    Returns:
        A list of interchanges with duplicates (by name) merged.
    """
    name_to_group: dict[str, list[Interchange]] = defaultdict(list)
    for ic in interchanges:
        name_to_group[ic.name].append(ic)

    merged: list[Interchange] = []
    for name, group in name_to_group.items():
        if name == "Unknown Interchange":
            merged.extend(group)
            continue
        if len(group) > 1:
            combined = merge_interchanges(group)
            print(f"Merged interchanges: {name}")
            merged.append(combined)
        else:
            merged.append(group[0])
    return renumber_interchanges(merged)


def isolate_interchanges_by_branch(
    interchanges: list[Interchange], isolate_way_ids: set[int]
) -> list[Interchange]:
    """
    If an interchange contains a branch that has any of `isolate_way_ids`, split that branch
    into its own interchange. Other branches remain with the original interchange.
    """
    result: list[Interchange] = []
    new_interchanges: list[Interchange] = []

    for ic in interchanges:
        # Group ramps by branch_id inside this interchange
        by_branch: dict[int, list[Ramp]] = defaultdict(list)
        for r in ic.ramps:
            by_branch[r.branch_id].append(r)

        # Find branches to isolate
        branches_to_isolate: list[int] = []
        for branch_id, ramps in by_branch.items():
            if any(ramp_contains_way(ramps, way_id) for way_id in isolate_way_ids):
                branches_to_isolate.append(branch_id)

        if not branches_to_isolate:
            result.append(ic)
            continue

        # Keep original interchange with non-isolated branches (if any)
        kept_ramps: list[Ramp] = [r for r in ic.ramps if r.branch_id not in branches_to_isolate]
        if kept_ramps:
            kept_ic = create_interchange_from_ramps(kept_ramps, id=ic.id)
            kept_ic.name = ic.name
            result.append(kept_ic)

        # Create standalone interchanges for each isolated branch
        for b in branches_to_isolate:
            branch_ramps = by_branch[b]
            new_ic = create_interchange_from_ramps(branch_ramps, id=0)
            new_ic.name = ic.name  # will be re-annotated later
            new_interchanges.append(new_ic)

    # Renumber and return combined list
    combined = result + new_interchanges
    return renumber_interchanges(combined)


def delete_interchanges_containing_ways(
    interchanges: list[Interchange], delete_way_ids: set[int]
) -> list[Interchange]:
    """
    Delete entire interchanges that contain any of the specified way IDs.

    Args:
        interchanges: List of interchanges to filter
        delete_way_ids: Set of way IDs that should trigger interchange deletion

    Returns:
        Filtered list of interchanges with matching interchanges removed
    """
    filtered_interchanges: list[Interchange] = []

    for ic in interchanges:
        # Check if this interchange contains any of the deletion way IDs
        should_delete = False
        for way_id in delete_way_ids:
            if ramp_contains_way(ic.ramps, way_id):
                should_delete = True
                print(f"Deleting interchange {ic.id} ({ic.name}) - contains way {way_id}")
                break

        if not should_delete:
            filtered_interchanges.append(ic)

    # Renumber the remaining interchanges to maintain sequential IDs
    return renumber_interchanges(filtered_interchanges)


def merge_interchanges(interchanges: list[Interchange]) -> Interchange:
    """Merge multiple interchanges into one, preserving the first's id/name."""
    ramps = []
    for interchange in interchanges:
        ramps.extend(interchange.ramps)
    merged_interchange = create_interchange_from_ramps(ramps, interchanges[0].id)
    merged_interchange.name = interchanges[0].name
    return merged_interchange
