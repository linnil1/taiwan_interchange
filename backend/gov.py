"""Government highway data scraping and parsing utilities."""

import re
from collections.abc import Sequence
from typing import Literal
from urllib.parse import urljoin

import requests

# Suppress SSL warnings
import urllib3
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Constants
EMPTY_PATTERN = ["　", "&nbsp;"]
EMPTY_TEXT_PATTERNS = ["-" * i for i in range(1, 10)] + EMPTY_PATTERN


class GovInterchangeData(BaseModel):
    """Data structure for a single interchange/facility from freeway bureau table."""

    name: str  # Facility name (設施名稱)
    km_distance: str  # Mileage (里程)
    service_area: list[str] = Field(
        default_factory=list
    )  # Main service area/connecting roads (主要服務區域 / 連接道路)
    southbound_exit: list[str] = Field(
        default_factory=list
    )  # Southbound exit preview location (南向出口預告地名)
    northbound_exit: list[str] = Field(
        default_factory=list
    )  # Northbound exit preview location (北向出口預告地名)
    eastbound_exit: list[str] = Field(
        default_factory=list
    )  # Eastbound exit preview location (東向出口預告地名)
    westbound_exit: list[str] = Field(
        default_factory=list
    )  # Westbound exit preview location (西向出口預告地名)
    notes: list[str] = Field(default_factory=list)  # Other notes/information (其他)
    url: str = ""  # Link to detailed interchange diagram if available
    facility_type: Literal["interchange", "service_area"] = (
        "interchange"  # Type based on row color/content
    )


class GovHighwayData(BaseModel):
    """Complete highway data from freeway bureau for one highway page."""

    name: str  # e.g., "國道一號" extracted from title
    title: str  # Raw title text above table
    url: str
    interchanges: list[GovInterchangeData] = Field(default_factory=list)


def get_webpage_content(url: str) -> BeautifulSoup:
    """Fetch webpage content and return BeautifulSoup object."""
    response = requests.get(url, timeout=30, verify=False)
    response.raise_for_status()
    response.encoding = "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def find_tables(soup: BeautifulSoup) -> list[tuple[Tag, str]]:
    """Find all data tables with their preceding titles."""
    content_div = soup.find("div", {"id": "ctl00_CPHolder1_Publisher1_Show3"})
    if not content_div or not isinstance(content_div, Tag):
        return []

    # Get all elements in order
    all_elements = content_div.find_all(["p", "table", "strong", "span"])

    tables_with_titles = []
    for i, elem in enumerate(all_elements):
        if isinstance(elem, Tag) and elem.name == "table":
            # Look backward to find the title (text right before the table)
            title = ""
            for j in range(i - 1, max(i - 3, -1), -1):
                prev_elem = all_elements[j]
                if isinstance(prev_elem, Tag):
                    text = prev_elem.get_text(strip=True)
                    if text.strip().startswith("國道"):
                        title = text.strip()
                        break

            if not title:
                print(f"Warning: Could not find title for table at index {i}")
                continue

            tables_with_titles.append((elem, title))
            title = ""

    return tables_with_titles


def has_background_color(row: Tag) -> bool:
    """Check if a style string contains background color."""
    bgcolor = row.get("bgcolor", "")
    if bgcolor and isinstance(bgcolor, str):
        return True

    style = row.get("style", "")
    if style and isinstance(style, str):
        if "background-color" in style.lower():
            return True

    return False


def determine_facility_type(row: Tag) -> Literal["service_area", "interchange"]:
    """Determine facility type based on row styling."""
    # Check background color on the row itself
    if has_background_color(row):
        return "service_area"

    # Check cells for background color as well
    cells = row.find_all(["th", "td"])
    for cell in cells:
        if isinstance(cell, Tag):
            if has_background_color(cell):
                return "service_area"

    return "interchange"


def split_text_by_br(cell: Tag) -> str:
    """Split text content by <br> tags and convert to newlines."""
    # Get text content and handle <br> tags by replacing them with newlines
    cell_html = str(cell)
    cell_html = cell_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    # Parse back to get clean text
    temp_soup = BeautifulSoup(cell_html, "html.parser")
    return temp_soup.get_text(strip=True)


def cleanup_text(text: str) -> str:
    """Clean up text by stripping and removing unwanted patterns."""
    text = text.strip()
    if text in EMPTY_TEXT_PATTERNS:
        return ""
    for pattern in EMPTY_PATTERN:
        text = text.replace(pattern, "")
    return text


def split_text_content(text: str) -> list[str]:
    """Split text content by common separators and clean up."""
    text = cleanup_text(text)
    if not text:
        return []

    # Split by common separators including Chinese comma, regular comma, line breaks, and 、
    parts = re.split(r"[,，、\n\r]", text)
    cleaned_parts = [cleanup_text(p) for p in parts]
    return [p for p in cleaned_parts if p]


def extract_url_from_cell(cell: Tag) -> str:
    """Extract URL from a table cell if it contains a link."""
    link_elem = cell.find("a")
    if link_elem and isinstance(link_elem, Tag):
        href = link_elem.get("href")
        if href and isinstance(href, str):
            if href.startswith("/"):
                return urljoin("https://www.freeway.gov.tw", href)
            elif href.startswith("http"):
                return href
    return ""


def parse_table_row(
    main_row: Tag, sub_rows: list[Tag], headers: list[str]
) -> GovInterchangeData | None:
    """Parse a main facility row and its sub-rows into GovInterchangeData."""
    if not isinstance(main_row, Tag):
        return None

    cells = main_row.find_all(["th", "td"])
    if len(cells) < 3:
        return None

    first_cell = cells[0]
    if not isinstance(first_cell, Tag):
        return None

    # Extract facility name
    facility_name_elem = first_cell.find("a")
    if facility_name_elem and isinstance(facility_name_elem, Tag):
        facility_name = facility_name_elem.get_text(strip=True)
    else:
        facility_name = first_cell.get_text(strip=True)

    # Skip summary rows
    if "交流道數量合計" in facility_name or "服務區數量合計" in facility_name:
        return None

    # Extract URL
    url = extract_url_from_cell(first_cell)

    # Determine facility type
    facility_type = determine_facility_type(main_row)

    # Extract data based on headers and cells
    km_distance = ""
    service_area = []
    southbound_exit = []
    northbound_exit = []
    eastbound_exit = []
    westbound_exit = []
    notes = []

    # Map cells to headers
    for i, header in enumerate(headers):
        if i >= len(cells):
            break
        cell = cells[i]
        if not isinstance(cell, Tag):
            continue

        # Get text content and handle <br> tags
        cell_text = split_text_by_br(cell)

        if i == 0:  # First column is facility name, already processed
            continue
        elif i == 1:  # Second column is usually km distance
            km_distance = cell_text
        elif i == 2:  # Third column is usually service area
            service_area = split_text_content(cell_text)
        elif "南向" in header or "南下" in header:
            southbound_exit = split_text_content(cell_text)
        elif "北向" in header or "北上" in header:
            northbound_exit = split_text_content(cell_text)
        elif "東向" in header or "東行" in header:
            eastbound_exit = split_text_content(cell_text)
        elif "西向" in header or "西行" in header:
            westbound_exit = split_text_content(cell_text)
        elif "其他" in header or "備註" in header:
            notes.extend(split_text_content(cell_text))

    # Process sub-rows for additional exit information
    for sub_row in sub_rows:
        sub_cells = sub_row.find_all(["th", "td"])
        additional_note = ":".join(
            [cell.get_text(strip=True) for cell in sub_cells if isinstance(cell, Tag)]
        )
        notes.append(additional_note)

    return GovInterchangeData(
        name=facility_name,
        km_distance=km_distance,
        service_area=service_area,
        southbound_exit=southbound_exit,
        northbound_exit=northbound_exit,
        eastbound_exit=eastbound_exit,
        westbound_exit=westbound_exit,
        notes=notes,
        url=url,
        facility_type=facility_type,
    )


def extract_facility_groups(rows: Sequence[Tag], headers: list[str]) -> list[tuple[Tag, list[Tag]]]:
    """Extract list of tuples (main_row, sub_rows) from table rows."""
    facility_groups = []
    i = 1  # Start from first data row (skip header)

    while i < len(rows):
        row = rows[i]
        if not isinstance(row, Tag):
            i += 1
            continue

        cells = row.find_all(["th", "td"])
        if len(cells) < 3:
            i += 1
            continue

        first_cell = cells[0]
        if not isinstance(first_cell, Tag):
            i += 1
            continue

        # Check if this is a main facility row
        has_rowspan = bool(first_cell.get("rowspan"))
        has_full_columns = len(cells) >= len(headers)
        is_sub_exit_row = len(cells) <= 2 and first_cell.get_text(strip=True) in [
            "A",
            "B",
            "C",
            "D",
        ]

        is_main_facility = (has_rowspan or has_full_columns) and not is_sub_exit_row

        if is_main_facility:
            # Collect sub-rows that belong to this facility
            sub_rows = []
            j = i + 1

            # If main row has rowspan, collect the sub-rows
            if has_rowspan:
                try:
                    rowspan_value = first_cell.get("rowspan")
                    if rowspan_value and isinstance(rowspan_value, str):
                        rowspan_count = int(rowspan_value)
                        for k in range(1, rowspan_count):
                            if j < len(rows) and isinstance(rows[j], Tag):
                                sub_rows.append(rows[j])
                                j += 1
                except (ValueError, TypeError):
                    pass

            facility_groups.append((row, sub_rows))
            i = j  # Move to next unprocessed row
        else:
            i += 1  # Skip this row (might be a sub-row that was already processed)

    return facility_groups


def parse_table_interchanges(table: Tag, headers: list[str]) -> list[GovInterchangeData]:
    """Parse a single table and return list of interchanges."""
    # Extract facility groups (main_row, sub_rows)
    rows = table.find_all("tr")
    row_list = [row for row in rows if isinstance(row, Tag)]
    facility_groups = extract_facility_groups(row_list, headers)

    interchanges = []
    for main_row, sub_rows in facility_groups:
        facility = parse_table_row(main_row, sub_rows, headers)
        if facility:
            interchanges.append(facility)

    return interchanges


def parse_table(table: Tag, title: str, url: str) -> GovHighwayData:
    """Parse a single table and return GovHighwayData."""
    # Extract highway name from title (e.g., "國道2甲" from "國道2甲 - (圳頭－大園)")
    highway_match = re.search(r"國道\d+(?:號[甲乙]?|[甲乙])*", title)
    highway_name = highway_match.group(0) if highway_match else title.split("-")[0].strip()

    # Get all rows from the table (including thead and tbody)
    rows = table.find_all("tr")
    if not rows:
        return GovHighwayData(name=highway_name, title=title, url=url, interchanges=[])

    # Extract headers from first row
    header_row = rows[0]
    headers = []
    if isinstance(header_row, Tag):
        header_cells = header_row.find_all(["th", "td"])
        headers = [cell.get_text(strip=True) for cell in header_cells if isinstance(cell, Tag)]

    if not headers:
        return GovHighwayData(name=highway_name, title=title, url=url, interchanges=[])

    # Parse interchanges from table
    interchanges = parse_table_interchanges(table, headers)

    return GovHighwayData(name=highway_name, title=title, url=url, interchanges=interchanges)


def read_gov_highway_content(url: str) -> list[GovHighwayData]:
    """
    Read and parse a freeway bureau highway page content into List of GovHighwayData structures.

    Args:
        url: URL of the highway page from freeway.gov.tw

    Returns:
        List of GovHighwayData objects with parsed interchange information
    """
    soup = get_webpage_content(url)
    tables_with_titles = find_tables(soup)

    if not tables_with_titles:
        raise ValueError(f"Could not find data tables in {url}")

    highway_data_list = []
    for table, title in tables_with_titles:
        highway_data = parse_table(table, title, url)
        highway_data_list.append(highway_data)

    return highway_data_list


def read_gov_index_page() -> list[str]:
    """
    Read the index page and return list of highway page URLs.

    Returns:
        List of URLs for individual highway pages
    """
    index_url = "https://www.freeway.gov.tw/Publish.aspx?cnid=1906"

    soup = get_webpage_content(index_url)
    highway_urls = []

    # Look for highway links in the content
    content_area = soup.find("div", {"class": "FCK"}) or soup.find("div", {"class": "FCKdetail"})

    if not content_area or not isinstance(content_area, Tag):
        raise ValueError("Could not find content area in index page")

    # Find all links that contain highway numbers
    links = content_area.find_all("a", href=True)

    urls = []
    for link in links:
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not href or not isinstance(href, str):
            continue
        urls.append(href)
    return urls


if __name__ == "__main__":
    # Example usage
    print("Fetching highway page URLs...")
    # urls = read_gov_index_page()
    urls = ["https://www.freeway.gov.tw/Publish.aspx?cnid=1906&p=4622"]
    print(f"Found {len(urls)} highway page URLs")

    from pprint import pprint

    for url in urls:
        highway_data_list = read_gov_highway_content(url)
        for highway_data in highway_data_list:
            pprint(highway_data.model_dump())
