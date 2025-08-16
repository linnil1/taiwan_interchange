import json
import os

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

    type: str
    id: int
    lat: float
    lon: float
    tags: dict[str, str] = {}


class OverPassWay(BaseModel):
    """Represents a raw OverPass API way"""

    type: str
    id: int
    tags: dict[str, str] = {}
    geometry: list[Coordinate]
    nodes: list[int]


class OverPassResponse(BaseModel):
    """Represents a complete OverPass API response"""

    version: float
    generator: str
    osm3s: dict[str, str]
    elements: list[OverPassNode | OverPassWay]

    def list_ways(self) -> list[OverPassWay]:
        return [element for element in self.elements if element.type == "way"]  # type: ignore

    def list_nodes(self) -> list[OverPassNode]:
        return [element for element in self.elements if element.type == "node"]  # type: ignore


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


def save_overpass_cache(data: dict) -> bool:
    """Save Overpass API response to cache file"""
    cache_file_path = os.path.join(os.path.dirname(__file__), "overpass_cache.json")
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
    save_overpass_cache(data)
    return OverPassResponse.model_validate(data)
