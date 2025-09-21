"""
Wikipedia scraper for Taiwan freeway interchange data.

This module extracts interchange information from Wikipedia pages about Taiwan freeway interchanges.
Uses OpenAI to parse the complex table structure and caches results in JSON files.
"""

import json
import os

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from pydantic import BaseModel

from models import WikiData
from persistence import load_or_fetch_data

# Constants
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4.1-mini"

# List of Wikipedia URLs to scrape
# https://zh.wikipedia.org/wiki/中華民國國道
WIKI_URLS = [
    # 1
    "https://zh.wikipedia.org/wiki/中山高速公路交流道列表",
    # 2
    "https://zh.wikipedia.org/wiki/國道二號_(中華民國)",
    "https://zh.wikipedia.org/wiki/國道二號甲線",
    # 3
    "https://zh.wikipedia.org/wiki/福爾摩沙高速公路交流道列表",
    "https://zh.wikipedia.org/wiki/國道三號甲線",
    # 4
    "https://zh.wikipedia.org/wiki/國道四號_(中華民國)",
    # 5
    "https://zh.wikipedia.org/wiki/蔣渭水高速公路交流道列表",
    # 6
    "https://zh.wikipedia.org/wiki/水沙連高速公路",
    # 8
    "https://zh.wikipedia.org/wiki/國道八號_(中華民國)",
    # 10
    "https://zh.wikipedia.org/wiki/國道十號_(中華民國)",
]


class WikiInterchangeData(BaseModel):
    """Data structure for interchange information."""

    name: str
    exit_text: str
    km_distance: str
    region: str
    forward_direction: list[str] = []
    reverse_direction: list[str] = []
    interchange_type: list[str] = []
    opening_date: list[str] = []
    connecting_roads: list[str] = []
    url: str = ""  # Optional Wikipedia page URL for the specific interchange


class WikiHighway(BaseModel):
    """Data structure for highway with list of interchanges."""

    freeway_name: str
    url: str
    start_point: str
    end_point: str
    length_km: str
    alt_names: list[str] = []
    interchanges: list[WikiInterchangeData] = []


def fetch_website(url: str) -> str | None:
    """Fetch raw HTML content from a website URL."""
    response = requests.get(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    )
    response.raise_for_status()
    return response.text


def filter_body(html_content: str) -> str:
    """Extract only the bodyContent section using BeautifulSoup."""
    soup = BeautifulSoup(html_content, "html.parser")
    body_content = soup.find(id="bodyContent")

    if body_content:
        return str(body_content)
    else:
        print("Warning: Could not find bodyContent, using full content")
        return html_content


def parse_by_ai(body_content: str, url: str) -> dict:
    """Use OpenAI to parse the HTML content and extract interchange data."""
    if not OPENAI_API_KEY:
        print("Cannot use OpenAI without API key")
        return {}

    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""
You are given the HTML content of a Wikipedia page about Taiwan freeway interchanges. Parse the content and return a single JSON object that exactly matches the schema below. Return only valid JSON — no explanation, no markdown, no extra keys, no comments.

Schema (keys must appear):
{{
  "freeway_name": string,          // e.g. "國道一號"
  "url": string,                   // the page URL (use the provided URL)
  "alt_names": [string],           // array, [] if none
  "start_point": string,           // "" if unknown
  "end_point": string,             // "" if unknown
  "length_km": string,             // total length in km, numbers only as string e.g. "123.4" or "" if unknown
  "interchanges": [
    {{
      "name": string,
      "exit_text": string,         // exit number/text or "" if unknown
      "km_distance": string,       // e.g. "12.3" or "" if unknown
      "region": string,            // area/region or "" if unknown
      "forward_direction": [string],
      "reverse_direction": [string],
      "interchange_type": [string],
      "opening_date": [string],
      "connecting_roads": [string],
      "url": string                // Wikipedia URL for this specific interchange if linked, "" if none
    }}
  ]
}}

Instructions:
- Extract interchange rows from tables and any inline lists that represent interchanges. Treat entries like "里港地磅站設置於里港交流道西行入口匝道" or "335.1仁德服務區" as interchanges: fill at least the name and any other available fields.
- Use table cells and nearby labels to populate fields. Infer values only when clear; otherwise use empty string "" or empty array [] as specified.
- For each interchange, if the name is a hyperlink, extract the full Wikipedia URL and put it in the "url" field. If not linked, use "".
- Remove HTML tags, decode entities, trim and normalize whitespace.
- Preserve the page order of interchanges.
- All array fields must be arrays of strings (use [] if missing). Fields that are single text should be strings.
- Do not output any keys other than those in the schema.
- Set "url" to: {url}

HTML_CONTENT_BEGIN
{body_content}
HTML_CONTENT_END
"""

    print("Sending prompt to OpenAI...", prompt)
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=prompt,
    )
    content = response.output_text.strip()
    print("Received response from OpenAI:", content)

    # Clean up the response (remove markdown if present)
    if content.startswith("```json"):
        content = content[7:]
    if content.endswith("```"):
        content = content[:-3]

    # Parse JSON
    parsed_data = json.loads(content)
    return parsed_data if isinstance(parsed_data, dict) else {}


def query_wikipedia_interchanges(url: str) -> WikiHighway:
    """Query Wikipedia for interchange data from a specific URL."""
    html_content = fetch_website(url)
    if not html_content:
        raise ValueError("Failed to retrieve HTML content")

    body_content = filter_body(html_content)
    parsed_data = parse_by_ai(body_content, url)
    data = WikiHighway.model_validate(parsed_data)
    return data


def load_or_fetch_wiki_data(cache_filename: str, url: str, use_cache: bool = True) -> WikiHighway:
    """
    Load cached Wikipedia interchange data or fetch and cache it.

    Args:
        cache_filename: Name of the cache file (without path)
        url: Wikipedia URL to fetch
        use_cache: Whether to use cache
    """
    data = load_or_fetch_data(
        cache_filename, lambda: query_wikipedia_interchanges(url).model_dump(), use_cache
    )
    return WikiHighway.model_validate(data)


def load_all_wiki_interchanges(use_cache: bool = True) -> list[WikiHighway]:
    """Load all Wikipedia interchange data."""
    all_data = []

    for url in WIKI_URLS:
        name = url.split("/")[-1]
        cache_filename = f"wiki_cache_interchanges_{name}.json"
        data = load_or_fetch_wiki_data(cache_filename, url, use_cache)
        all_data.append(data)

    return all_data


def create_wiki_data_from_interchange(
    wiki_interchange: WikiInterchangeData, highway_url: str
) -> WikiData:
    """Transform WikiInterchangeData to WikiData with URLs."""
    return WikiData(
        name=wiki_interchange.name,
        exit_text=wiki_interchange.exit_text,
        km_distance=wiki_interchange.km_distance,
        region=wiki_interchange.region,
        forward_direction=wiki_interchange.forward_direction,
        reverse_direction=wiki_interchange.reverse_direction,
        interchange_type=wiki_interchange.interchange_type,
        opening_date=wiki_interchange.opening_date,
        connecting_roads=wiki_interchange.connecting_roads,
        url=highway_url,  # Highway page URL (always present)
        interchange_url=wiki_interchange.url,  # Specific interchange page URL (optional)
    )


if __name__ == "__main__":
    from pprint import pprint

    all_data = load_all_wiki_interchanges(use_cache=False)
    for data in all_data:
        pprint(data.model_dump())
