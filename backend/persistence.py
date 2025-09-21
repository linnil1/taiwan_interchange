"""Data persistence utilities for interchange data"""

import json
import os
from collections.abc import Callable
from typing import Any, TypeVar

from models import Interchange

T = TypeVar("T")


def load_interchanges() -> list[Interchange]:
    """Load interchanges data as Pydantic objects with validation"""
    json_file_path = os.path.join(os.path.dirname(__file__), "interchanges.json")
    data = json.load(open(json_file_path, encoding="utf-8"))
    datas = [Interchange.model_validate(item) for item in data]
    return datas


def save_interchanges(interchanges: list[Interchange], save_static: bool = True) -> str:
    """Save interchanges data to JSON file in backend and optionally frontend static directories"""
    backend_json_file_path = os.path.join(os.path.dirname(__file__), "interchanges.json")
    frontend_static_path = os.path.join(
        os.path.dirname(__file__), "../frontend/static/interchanges.json"
    )

    interchanges_dict = [interchange.model_dump() for interchange in interchanges]

    # Save to backend directory (for development/reference)
    with open(backend_json_file_path, "w", encoding="utf-8") as f:
        json.dump(interchanges_dict, f, indent=2, ensure_ascii=False)

    print(f"Saved to backend: {backend_json_file_path}")

    # Optionally save to frontend static directory (for production deployment)
    if save_static:
        os.makedirs(os.path.dirname(frontend_static_path), exist_ok=True)
        with open(frontend_static_path, "w", encoding="utf-8") as f:
            json.dump(interchanges_dict, f, indent=2, ensure_ascii=False)
        print(f"Saved to frontend static: {frontend_static_path}")

    return backend_json_file_path


def load_or_fetch_data(filename: str, fetch_func: Callable[[], Any], use_cache: bool = True) -> Any:
    """
    Generic function to load data from cache or fetch from source.

    Args:
        filename: Cache file path
        fetch_func: Function to fetch data if cache doesn't exist
        use_cache: Whether to use cache

    Returns:
        The loaded or fetched data (as returned by json.load)
    """
    filename = os.path.join(os.path.dirname(__file__), filename)
    if use_cache and os.path.exists(filename):
        with open(filename, encoding="utf-8") as f:
            return json.load(f)

    # Fetch data and save to cache
    data = fetch_func()
    if use_cache:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return data
