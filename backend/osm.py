from typing import Literal

import requests
from pydantic import BaseModel, Field

from persistence import load_or_fetch_data


class Coordinate(BaseModel):
    """Represents a geographical coordinate (lat/lon).

    Overpass uses the key name "lon"; we expose it as `lng` via an alias.
    """

    lat: float
    lng: float = Field(alias="lon")  # Map API's "lon" to our "lng"

    class Config:
        populate_by_name = True  # Allow both "lon" and "lng" field names


class OverPassNode(BaseModel):
    """Represents a raw OverPass API node as returned by Overpass."""

    type: Literal["node"]
    id: int
    lat: float
    lon: float
    tags: dict[str, str] = {}


class OverPassWay(BaseModel):
    """Represents a raw OverPass API way as returned by Overpass."""

    type: Literal["way"]
    id: int
    tags: dict[str, str] = {}
    geometry: list[Coordinate] = []
    nodes: list[int] = []


class OverPassRelationMember(BaseModel):
    """Represents a member of an OverPass API relation."""

    type: Literal["node", "way", "relation"]
    ref: int
    role: str = ""


class OverPassRelation(BaseModel):
    """Represents a raw OverPass API relation."""

    type: Literal["relation"]
    id: int
    tags: dict[str, str] = {}
    members: list[OverPassRelationMember] = []


class OverPassResponse(BaseModel):
    """Represents a complete OverPass API response and helpers to filter elements."""

    version: float
    generator: str
    osm3s: dict[str, str]
    elements: list[OverPassNode | OverPassWay | OverPassRelation]

    def list_ways(self) -> list[OverPassWay]:
        return [element for element in self.elements if element.type == "way"]  # type: ignore

    def list_nodes(self) -> list[OverPassNode]:
        return [element for element in self.elements if element.type == "node"]  # type: ignore

    def list_relations(self) -> list[OverPassRelation]:
        return [element for element in self.elements if element.type == "relation"]  # type: ignore


def query_motorway_links() -> dict | None:
    """Query Overpass API for motorway links and junction nodes in Taiwan."""
    overpass_url = "http://overpass-api.de/api/interpreter"

    query = """
    [out:json][timeout:60];
    area["name:en"="Taiwan"]->.taiwan;
    (
      node["highway"="motorway_junction"](area.taiwan);
      way["highway"="motorway_link"](area.taiwan);
      >;
    );
    out geom;
    """

    response = requests.post(overpass_url, data={"data": query})
    response.raise_for_status()
    return response.json()


def query_freeway_routes() -> dict | None:
    """Query Overpass API for freeway route relations in Taiwan."""
    overpass_url = "http://overpass-api.de/api/interpreter"

    query = """
        [out:json][timeout:60];
        area["name:en"="Taiwan"]->.taiwan;
        (
            relation["type"="route"]["network"="TW:freeway"](area.taiwan) -> .freeway;
            relation(br.freeway)["type"="route_master"] -> .master;
        );
        >>;
        out body;
    """

    response = requests.post(overpass_url, data={"data": query})
    response.raise_for_status()
    return response.json()


def query_provincial_routes() -> dict | None:
    """Query Overpass API for provincial route relations in Taiwan."""
    overpass_url = "http://overpass-api.de/api/interpreter"

    query = """
    [out:json][timeout:60];
    area["name:en"="Taiwan"]->.taiwan;
    (
      relation["type"="route"]["network"="TW:provincial"](area.taiwan);
      >;
    );
    out body;
    """

    response = requests.post(overpass_url, data={"data": query})
    response.raise_for_status()
    return response.json()


def query_weigh_stations() -> dict | None:
    """Query Overpass API for weigh stations with names ending in '地磅站' in Taiwan."""
    overpass_url = "http://overpass-api.de/api/interpreter"

    query = """
    [out:json][timeout:60];
    area["name:en"="Taiwan"]->.taiwan;
    (
      way["building"="yes"]["name"~"地磅站$"](area.taiwan);
    );
    out geom;
    """

    response = requests.post(overpass_url, data={"data": query})
    response.raise_for_status()
    return response.json()


def load_or_fetch_osm_freeway_routes(use_cache: bool = True) -> OverPassResponse:
    """Load freeway route relations from cache or Overpass API."""
    data = load_or_fetch_data(
        "osm_cache_freeway.json", lambda: query_freeway_routes() or {}, use_cache
    )
    return OverPassResponse.model_validate(data)


def load_or_fetch_osm_provincial_routes(use_cache: bool = True) -> OverPassResponse:
    """Load provincial route relations from cache or Overpass API."""
    data = load_or_fetch_data(
        "osm_cache_provincial.json", lambda: query_provincial_routes() or {}, use_cache
    )
    return OverPassResponse.model_validate(data)


def load_or_fetch_osm_weigh_stations(use_cache: bool = True) -> OverPassResponse:
    """Load weigh stations in Taiwan from cache or Overpass API."""
    data = load_or_fetch_data(
        "osm_cache_weigh_stations.json", lambda: query_weigh_stations() or {}, use_cache
    )
    return OverPassResponse.model_validate(data)


def load_or_fetch_osm_motorway_links(use_cache: bool = True) -> OverPassResponse:
    """Load motorway_link/junction Overpass response from cache or Overpass API."""
    data = load_or_fetch_data(
        "osm_cache_motorway_links.json", lambda: query_motorway_links() or {}, use_cache
    )
    return OverPassResponse.model_validate(data)


def query_adjacent_roads() -> dict | None:
    """Query Overpass API for route=road relations adjacent to motorway_link nodes in Taiwan.

    This focuses on ways connected to motorway_link nodes (excluding the links themselves),
    then finds named route=road relations for those ways. Used to annotate end-node relations
    as a fallback after generic way relations.
    """
    overpass_url = "http://overpass-api.de/api/interpreter"

    query = """
    [out:json][timeout:60];
    area["name:en"="Taiwan"]->.taiwan;
    way["highway"="motorway_link"](area.taiwan)->.motorway_links;
    node(w.motorway_links)->.motorway_links_nodes;
    way(bn.motorway_links_nodes)["highway"!="motorway_link"]->.nodes_way;
    rel(bw.nodes_way)["name"]["route"="road"]->.nodes_way_rel;
    .ways_rel out body;
    .nodes_way out body;
    .nodes_way_rel out body;
    """
    response = requests.post(overpass_url, data={"data": query})
    response.raise_for_status()
    return response.json()


def load_or_fetch_osm_adjacent_roads(use_cache: bool = True) -> OverPassResponse:
    """Load adjacent route=road relations from cache or Overpass API."""
    data = load_or_fetch_data(
        "osm_cache_adjacent_roads.json", lambda: query_adjacent_roads() or {}, use_cache
    )
    return OverPassResponse.model_validate(data)


# --- Special elevated freeway relation: 汐止-楊梅高架 (relation id: 9282022) ---
def query_elevated_freeway() -> dict | None:
    """Query Overpass API for the special elevated freeway relation (id: 9282022)."""
    overpass_url = "http://overpass-api.de/api/interpreter"

    query = """
    [out:json][timeout:60];
    area["name:en"="Taiwan"]->.taiwan;
    (
      relation(id: 9282022);
    );
    >>;
    out body;
    """

    response = requests.post(overpass_url, data={"data": query})
    response.raise_for_status()
    return response.json()


def load_or_fetch_osm_elevated_freeway(use_cache: bool = True) -> OverPassResponse:
    """Load the special elevated freeway relation (id: 9282022) from cache or Overpass API."""
    data = load_or_fetch_data(
        "osm_cache_elevated_freeway.json", lambda: query_elevated_freeway() or {}, use_cache
    )
    return OverPassResponse.model_validate(data)
