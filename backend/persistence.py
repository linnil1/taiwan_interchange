"""Data persistence utilities for interchange data"""

import json
import os

from models import Interchange


def load_interchanges() -> list[Interchange]:
    """Load interchanges data as Pydantic objects with validation"""
    json_file_path = os.path.join(os.path.dirname(__file__), "interchanges.json")
    data = json.load(open(json_file_path, encoding="utf-8"))
    datas = [Interchange.model_validate(item) for item in data]
    return datas


def save_interchanges(interchanges: list[Interchange]) -> str:
    """Save interchanges data to JSON file"""
    json_file_path = os.path.join(os.path.dirname(__file__), "interchanges.json")
    interchanges_dict = [interchange.model_dump() for interchange in interchanges]
    with open(json_file_path, "w", encoding="utf-8") as f:
        json.dump(interchanges_dict, f, indent=2, ensure_ascii=False)
    return json_file_path
