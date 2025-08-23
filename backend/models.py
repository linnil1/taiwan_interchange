"""Data models for the interchange project"""

from pydantic import BaseModel


class Node(BaseModel):
    """Represents a single node point in a ramp"""

    lat: float
    lng: float
    id: int  # node id


class Path(BaseModel):
    """Represents a path with way_id and nodes"""

    id: int  # way_id
    part: int  # part number when a way is broken into multiple paths
    nodes: list[Node]
    ended: bool = False  # True if this path ends at a traffic light or similar

    def get_subpath_id(self) -> str:
        return f"{self.id}_{self.part}"

    def get_endpoint_nodes(self) -> tuple[Node, Node]:
        """Get the first and last nodes of this path"""
        assert self.nodes
        return (self.nodes[0], self.nodes[-1])


class Ramp(BaseModel):
    """Represents a motorway ramp with its paths"""

    id: int
    destination: list[str] = []
    from_ramps: list[int] = []  # IDs of ramps that connect to this ramp
    to_ramps: list[int] = []  # IDs of ramps that this ramp connects to
    dag_to: list[int] = []  # DAG-only downstream edges (subset of to_ramps)
    paths: list[Path]
    branch_id: int = -1  # weakly connected component id assigned after graph build

    def list_nodes(self) -> list[Node]:
        """Get all nodes from all paths in this ramp"""
        nodes = []
        for path in self.paths:
            nodes.extend(path.nodes)
        return nodes

    def get_endpoint_nodes(self) -> tuple[Node, Node]:
        """Get all endpoint node IDs from this ramp's paths"""
        assert self.paths
        start_endpoint, _ = self.paths[0].get_endpoint_nodes()
        _, end_endpoint = self.paths[-1].get_endpoint_nodes()
        return (start_endpoint, end_endpoint)


class Bounds(BaseModel):
    """Represents geographical bounds"""

    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float


class Relation(BaseModel):
    """Represents a road relation with name and road type"""

    name: str
    road_type: str  # "freeway", "provincial", or "unknown"


class Interchange(BaseModel):
    """Represents an interchange with multiple ramps"""

    id: int
    name: str
    bounds: Bounds
    ramps: list[Ramp]

    def list_nodes(self) -> list[Node]:
        """Get all nodes from all ramps in this interchange"""
        nodes = []
        for ramp in self.ramps:
            nodes.extend(ramp.list_nodes())
        return nodes
