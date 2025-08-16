import json
import os
from typing import Literal

import requests
from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    """Represents a geographical coordinate"""

    lat: float
    lng: float = Field(alias="lon")  # Map API's "lon" to our "lng"

    class Config:
        populate_by_name = True  # Allow both "lon" and "lng" field names


class OverPassNode(BaseModel):
    """Represents a raw OverPass API node"""

    type: Literal["node"]
    id: int
    lat: float
    lon: float
    tags: dict[str, str] = {}


class OverPassWay(BaseModel):
    """Represents a raw OverPass API way"""

    type: Literal["way"]
    id: int
    tags: dict[str, str] = {}
    geometry: list[Coordinate] = []
    nodes: list[int] = []


class OverPassRelation(BaseModel):
    """Represents a raw OverPass API relation"""

    type: Literal["relation"]
    id: int
    tags: dict[str, str] = {}
    members: list[dict] = []


class OverPassResponse(BaseModel):
    """Represents a complete OverPass API response"""

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
    """Query Overpass API for motorway links in Tainan"""
    overpass_url = "http://overpass-api.de/api/interpreter"

    query = """
    [out:json][timeout:60];
    area["name:en"="Tainan"]->.taiwan;
    (
      way["highway"="motorway_link"](area.taiwan);
      node["highway"="motorway_junction"](area.taiwan);
    );
    out geom;
    """

    response = requests.post(overpass_url, data={"data": query})
    response.raise_for_status()
    return response.json()


def query_freeway_routes() -> dict | None:
    """Query Overpass API for freeway routes in Taiwan"""
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
    """Query Overpass API for provincial routes in Taiwan"""
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
    """Query Overpass API for unknown end nodes and their connected ways"""
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


def load_freeway_routes(use_cache: bool = True) -> OverPassResponse:
    """Load freeway routes Overpass API response from cache file"""
    cache_file_path = os.path.join(os.path.dirname(__file__), "freeway_cache.json")
    if os.path.exists(cache_file_path) and use_cache:
        with open(cache_file_path, encoding="utf-8") as f:
            data = json.load(f)
            return OverPassResponse.model_validate(data)

    data = query_freeway_routes()
    assert data, "No data returned from Overpass API"
    save_overpass_cache(data, cache_file_path)
    return OverPassResponse.model_validate(data)


def load_provincial_routes(use_cache: bool = True) -> OverPassResponse:
    """Load provincial routes Overpass API response from cache file"""
    cache_file_path = os.path.join(os.path.dirname(__file__), "provincial_cache.json")
    if os.path.exists(cache_file_path) and use_cache:
        with open(cache_file_path, encoding="utf-8") as f:
            data = json.load(f)
            return OverPassResponse.model_validate(data)

    data = query_provincial_routes()
    assert data, "No data returned from Overpass API"
    save_overpass_cache(data, cache_file_path)
    return OverPassResponse.model_validate(data)


def load_unknown_end_nodes(
    node_ids: list[int], interchange_name: str, use_cache: bool = True
) -> OverPassResponse:
    """Load unknown end nodes Overpass API response from cache file"""
    # Use interchange name for cache filename to cache by interchange
    cache_file_path = os.path.join(
        os.path.dirname(__file__), f"unknown_cache_{interchange_name.replace(' ', '_')}.json"
    )
    if os.path.exists(cache_file_path) and use_cache:
        with open(cache_file_path, encoding="utf-8") as f:
            data = json.load(f)
            return OverPassResponse.model_validate(data)

    data = query_unknown_end_nodes(node_ids)
    assert data, "No data returned from Overpass API"
    save_overpass_cache(data, cache_file_path)
    return OverPassResponse.model_validate(data)


def save_overpass_cache(data: dict, cache_file_path: str) -> bool:
    """Save Overpass API response to cache file"""
    with open(cache_file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved Overpass data to cache: {cache_file_path}")
    return True


def load_overpass(use_cache: bool = True) -> OverPassResponse:
    """Load Overpass API response from cache file"""
    cache_file_path = os.path.join(os.path.dirname(__file__), "overpass_cache.json")
    if os.path.exists(cache_file_path) and use_cache:
        with open(cache_file_path, encoding="utf-8") as f:
            data = json.load(f)
            return OverPassResponse.model_validate(data)

    data = query_overpass_api()
    assert data, "No data returned from Overpass API"
    save_overpass_cache(data, cache_file_path)
    return OverPassResponse.model_validate(data)
