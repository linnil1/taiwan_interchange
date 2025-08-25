import json
import os
from collections.abc import Callable
from functools import partial
from typing import Literal

import requests
from pydantic import BaseModel, Field


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


def query_overpass_api() -> dict | None:
    """Query Overpass API for motorway links and junction nodes in Taiwan."""
    overpass_url = "http://overpass-api.de/api/interpreter"

    query = """
    [out:json][timeout:60];
    area["name:en"="Taiwan"]->.taiwan;
    (
      way["highway"="motorway_link"](area.taiwan);
      node["highway"="motorway_junction"](area.taiwan);
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
      relation["type"="route"]["network"="TW:freeway"](area.taiwan);
      >;
    );
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


def query_unknown_end_nodes(node_ids: list[int]) -> dict | None:
    """Query Overpass API for the given nodes and their connected ways (bn)."""
    overpass_url = "http://overpass-api.de/api/interpreter"

    # Convert node IDs to comma-separated string
    node_ids_str = ",".join(str(node_id) for node_id in node_ids)

    query = f"""
    [out:json][timeout:60];
    area["name:en"="Taiwan"]->.taiwan;
    (
      node(id:{node_ids_str})(area.taiwan);
      way(bn)(area.taiwan);
    );
    out body;
    """

    response = requests.post(overpass_url, data={"data": query})
    response.raise_for_status()
    return response.json()


def query_nearby_weigh_stations() -> dict | None:
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


def save_overpass_cache(data: dict, cache_file_path: str) -> bool:
    """Save Overpass API response to a cache file (JSON)."""
    with open(cache_file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved Overpass data to cache: {cache_file_path}")
    return True


def load_or_fetch_overpass(
    cache_filename: str,
    fetch_func: Callable[[], dict | None],
    use_cache: bool = True,
) -> OverPassResponse:
    """
    Load a cached Overpass response or fetch and cache it using `fetch_func`.

    Args:
        cache_filename: Name of the cache file (without path)
        fetch_func: Function to call if cache miss or use_cache=False (should take no arguments)
        use_cache: Whether to use cache
    """
    cache_file_path = os.path.join(os.path.dirname(__file__), cache_filename)

    if os.path.exists(cache_file_path) and use_cache:
        with open(cache_file_path, encoding="utf-8") as f:
            data = json.load(f)
            return OverPassResponse.model_validate(data)

    data = fetch_func()
    assert data, "No data returned from Overpass API"
    save_overpass_cache(data, cache_file_path)
    return OverPassResponse.model_validate(data)


def load_freeway_routes(use_cache: bool = True) -> OverPassResponse:
    """Load freeway route relations from cache or Overpass API."""
    return load_or_fetch_overpass("freeway_cache.json", query_freeway_routes, use_cache=use_cache)


def load_provincial_routes(use_cache: bool = True) -> OverPassResponse:
    """Load provincial route relations from cache or Overpass API."""
    return load_or_fetch_overpass(
        "provincial_cache.json", query_provincial_routes, use_cache=use_cache
    )


def load_unknown_end_nodes(
    node_ids: list[int], interchange_name: str, use_cache: bool = True
) -> OverPassResponse:
    """Load selected nodes and their connected ways from cache or Overpass API."""
    cache_filename = f"unknown_cache_{interchange_name.replace(' ', '_')}.json"
    fetch_func = partial(query_unknown_end_nodes, node_ids)
    return load_or_fetch_overpass(cache_filename, fetch_func, use_cache=use_cache)


def load_nearby_weigh_stations(use_cache: bool = True) -> OverPassResponse:
    """Load weigh stations in Taiwan from cache or Overpass API."""
    return load_or_fetch_overpass(
        "weigh_stations_cache.json", query_nearby_weigh_stations, use_cache=use_cache
    )


def load_overpass(use_cache: bool = True) -> OverPassResponse:
    """Load motorway_link/junction Overpass response from cache or Overpass API."""
    return load_or_fetch_overpass("overpass_cache.json", query_overpass_api, use_cache=use_cache)
