"""Data models for the interchange project"""

from enum import Enum

from pydantic import BaseModel, ConfigDict


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


class DestinationType(str, Enum):
    EXIT = "EXIT"  # from freeway to normal road
    ENTER = "ENTER"  # to freeway
    OSM = "OSM"  # OSM proivded


class RelationType(str, Enum):
    RELATION = "RELATION"  # OSM relation
    WAY = "WAY"  # OSM way
    NODE = "NODE"  # OSM node


class RoadType(str, Enum):
    FREEWAY = "freeway"
    PROVINCIAL = "provincial"
    WEIGH = "weigh"
    NORMAL = "normal"
    DESTINATION = "destination"
    WAY = "way"
    JUNCTION = "junction"
    WIKIDATA = "wikidata"


class Relation(BaseModel):
    """Represents a road relation with name and road type"""

    id: int  # OSM relation id
    name: str
    road_type: RoadType
    relation_type: RelationType
    model_config = ConfigDict(frozen=True)


class Destination(Relation):
    """Represents a destination that inherits from Relation"""

    destination_type: DestinationType
    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_relation(cls, relation: Relation, destination_type: DestinationType) -> "Destination":
        """Create a Destination from a Relation and destination type"""
        return cls(
            id=relation.id,
            name=relation.name,
            road_type=relation.road_type,
            relation_type=relation.relation_type,
            destination_type=destination_type,
        )


class Ramp(BaseModel):
    """Represents a motorway ramp with its paths"""

    id: int
    destination: list[Destination] = []
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


class WikiData(BaseModel):
    """Wikipedia data for an interchange, similar to WikiInterchangeData but with URL"""

    name: str
    exit_text: str
    km_distance: str
    region: str
    forward_direction: list[str] = []
    reverse_direction: list[str] = []
    interchange_type: list[str] = []
    opening_date: list[str] = []
    connecting_roads: list[str] = []
    url: str = ""  # Wikipedia URL where this data came from (highway page)
    interchange_url: str = ""  # Wikipedia URL for interchange-specific page (if exists)


class GovData(BaseModel):
    """Freeway Bureau data for an interchange"""

    name: str
    km_distance: str
    service_area: list[str] = []
    southbound_exit: list[str] = []
    northbound_exit: list[str] = []
    eastbound_exit: list[str] = []
    westbound_exit: list[str] = []
    notes: list[str] = []
    facility_type: str = "interchange"  # interchange, service_area, rest_stop, other
    url: str = ""  # Highway page URL
    interchange_url: str = ""  # Specific interchange diagram URL


class Bounds(BaseModel):
    """Represents geographical bounds"""

    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float


class Interchange(BaseModel):
    """Represents an interchange with multiple ramps"""

    id: int
    name: str
    bounds: Bounds
    ramps: list[Ramp]
    refs: list[Relation] = []  # freeway route_master relations that this interchange belongs to
    wikis: list[WikiData] = []
    govs: list[GovData] = []  # Government data if available
    wikidata_ids: list[
        str
    ] = []  # Wikidata IDs from OSM motorway_junction nodes (e.g., ["Q11111966"])

    def list_nodes(self) -> list[Node]:
        """Get all nodes from all ramps in this interchange"""
        nodes = []
        for ramp in self.ramps:
            nodes.extend(ramp.list_nodes())
        return nodes
