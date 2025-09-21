"""Government highway data scraping and parsing utilities."""

import os
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from typing import Literal
from urllib.parse import urljoin

import requests

# Suppress SSL warnings
import urllib3
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

from models import GovData
from persistence import load_or_fetch_data

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Constants
EMPTY_PATTERN = ["　", "&nbsp;"]
EMPTY_TEXT_PATTERNS = ["-" * i for i in range(1, 10)] + EMPTY_PATTERN

IMG_FOLDER = "freeway_imgs"


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
    facility_type: Literal["interchange", "service_area", "weigh_station"] = (
        "interchange"  # Type based on row color/content
    )


class GovHighwayData(BaseModel):
    """Complete highway data from freeway bureau for one highway page."""

    name: str  # e.g., "國道一號" extracted from title
    title: str  # Raw title text above table
    url: str
    interchanges: list[GovInterchangeData] = Field(default_factory=list)


def download_pdf(url: str, output_path: str) -> bool:
    """Download PDF from URL to specified path."""
    response = requests.get(url, timeout=30, verify=False)
    response.raise_for_status()

    with open(output_path, "wb") as f:
        f.write(response.content)
    return True


def freeway_pdf_to_img(pdf_path: str, output_path: str) -> str:
    """
    Download PDF from URL and convert it to PNG using podman.

    Args:
        pdf_url: URL of the PDF to download and convert
        output_dir: Directory to store PDFs and PNGs

    Returns:
        Path to the generated PNG file, or None if conversion failed
    """
    # Extract filename from URL (preserve the naming from the last part of URL)
    abs_input_dir = os.path.abspath(pdf_path)
    abs_output_dir = os.path.abspath(os.path.dirname(output_path))
    name = os.path.basename(output_path)

    cmd = [
        "podman",
        "run",
        "-it",
        "--rm",
        "-v",
        f"{abs_input_dir}:/input",
        "-v",
        f"{abs_output_dir}:/output",
        "docker.io/minidocks/poppler:latest",
        "pdftoppm",
        "-jpeg",
        "/input",
        f"/output/{name}",
    ]

    # Execute conversion
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0
    for i in range(1, 10):
        img_file = os.path.join(abs_output_dir, f"{name}-{i}.jpg")
        if os.path.exists(img_file):
            return img_file
    print(" ".join(cmd))
    raise AssertionError("No image file generated")


def process_interchange_pdfs(interchange: GovInterchangeData) -> GovInterchangeData:
    """
    Process an interchange to find PDFs in URL and convert them to PNG.

    Args:
        interchange: GovInterchangeData object with potential PDF URL

    Returns:
        Updated GovInterchangeData with PNG conversion information
    """
    if not interchange.url or not interchange.url.lower().endswith(".pdf"):
        return interchange

    print(f"Found PDF URL for {interchange.name}: {interchange.url}")

    # Ensure folder exists
    pdf_dir = os.path.join(os.path.dirname(__file__), "freeway_pdfs")
    img_dir = os.path.join(os.path.dirname(__file__), IMG_FOLDER)
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(img_dir, exist_ok=True)
    pdf_name = os.path.join(pdf_dir, f"{interchange.name}.pdf")
    img_name = os.path.join(img_dir, f"{interchange.name}")

    # main
    download_pdf(interchange.url, pdf_name)
    img_name = freeway_pdf_to_img(pdf_name, img_name)
    img_rel_name = os.path.relpath(img_name, os.path.join(os.path.dirname(__file__)))
    interchange.url = img_rel_name
    print(f"Converted PDF to image for {interchange.name}: {interchange.url}")
    return interchange


def copy_freeway_pdfs_to_static(gov_highways: list[GovHighwayData]) -> list[GovHighwayData]:
    """Copy freeway_pdfs folder to frontend static directory."""
    frontend_freeway_folder = os.path.join(
        os.path.dirname(__file__), "..", "frontend", "static", IMG_FOLDER
    )
    if os.path.exists(frontend_freeway_folder):
        shutil.rmtree(frontend_freeway_folder)
    os.makedirs(frontend_freeway_folder, exist_ok=True)

    for highway in gov_highways:
        for interchange in highway.interchanges:
            if interchange.url and not interchange.url.startswith("http"):
                filename = os.path.join(os.path.dirname(__file__), interchange.url)
                # interchange.url = os.path.join("/static", interchange.url)
                # copy file
                print(f"Copied {filename} to {frontend_freeway_folder}, url: {interchange.url}")
                shutil.copy2(filename, frontend_freeway_folder)
    return gov_highways


def fetch_website(url: str) -> BeautifulSoup:
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
            # Special case: if the table has a <caption>, use it as the title first
            title = ""
            caption = elem.find("caption")
            if caption and isinstance(caption, Tag):
                cap_text = caption.get_text(strip=True)
                if cap_text:
                    title = cap_text

            # Look backward to find the title (text right before the table)
            for j in range(i - 1, -1, -1):
                if title:
                    break
                prev_elem = all_elements[j]
                if isinstance(prev_elem, Tag):
                    if prev_elem.name == "table":
                        # Stop if we hit another table
                        break
                    text = prev_elem.get_text(strip=True)
                    if text.strip().startswith("國道"):
                        title = text.strip()
                        break

            if not title:
                print(f"Warning: Could not find title for table at index {elem}")
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


def parse_table_to_highway_data(table: Tag, title: str, url: str) -> GovHighwayData:
    """Parse a single table and return GovHighwayData."""
    # Extract highway name from title (e.g., "國道2甲" from "國道2甲 - (圳頭－大園)")
    highway_match = re.search(r"國道\d+(?:號[甲乙]?|[甲乙])*", title)
    highway_name = highway_match.group(0) if highway_match else title.strip()

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


def query_gov_highways(url: str) -> list[GovHighwayData]:
    """
    Read and parse a freeway bureau highway page content into List of GovHighwayData structures.

    Args:
        url: URL of the highway page from freeway.gov.tw

    Returns:
        List of GovHighwayData objects with parsed interchange information
    """
    soup = fetch_website(url)
    tables_with_titles = find_tables(soup)

    if not tables_with_titles:
        raise ValueError(f"Could not find data tables in {url}")

    highway_data_list = []
    for table, title in tables_with_titles:
        highway_data = parse_table_to_highway_data(table, title, url)
        highway_data_list.append(highway_data)

    return highway_data_list


def query_links_from_index_page() -> list[str]:
    """
    Read the index page and return list of highway page URLs.

    Returns:
        List of URLs for individual highway pages
    """
    index_url = "https://www.freeway.gov.tw/Publish.aspx?cnid=1906"

    soup = fetch_website(index_url)

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


def query_all_gov_highways() -> list[GovHighwayData]:
    """Fetch and parse all highway pages from freeway bureau."""
    urls = query_links_from_index_page()
    all_data = []
    for url in urls:
        highway_data_list = query_gov_highways(url)

        # Process each highway data to find and convert PDFs
        for highway_data in highway_data_list:
            highway_data.interchanges = [
                process_interchange_pdfs(interchange) for interchange in highway_data.interchanges
            ]

        all_data.extend(highway_data_list)
        time.sleep(1)  # Be polite and avoid overwhelming the server
    return all_data


def load_or_fetch_gov_interchanges(use_cache: bool = True) -> list[GovHighwayData]:
    """Load all government interchange data from freeway bureau."""
    data = load_or_fetch_data(
        "gov_cache_interchanges.json",
        lambda: [highway.model_dump() for highway in query_all_gov_highways()],
        use_cache,
    )
    return [GovHighwayData.model_validate(item) for item in data]


def query_gov_weigh_stations() -> GovHighwayData:
    """
    Read weigh station data from freeway bureau weigh station page.

    Returns:
        A single GovHighwayData object with parsed weigh station information
    """
    url = "https://www.freeway.gov.tw/Publish.aspx?cnid=2057"
    soup = fetch_website(url)

    # Find the main content area
    content_div = soup.find("div", {"id": "ctl00_CPHolder1_Publisher1_Show3"})
    if not content_div or not isinstance(content_div, Tag):
        raise ValueError(f"Could not find content area in weigh station page {url}")

    # Find all tables in the content - assert there's only one
    tables = content_div.find_all("table")
    assert len(tables) == 1, f"Expected exactly 1 table, found {len(tables)}"

    table = tables[0]
    if not isinstance(table, Tag):
        raise ValueError(f"Table is not a valid Tag in weigh station page {url}")

    # Parse table handling rowspan properly
    rows = table.find_all("tr")
    if not rows:
        raise ValueError(f"Could not find rows in weigh station page {url}")

    # Convert table to matrix handling rowspan
    tables = []

    for i, row in enumerate(rows):
        if not isinstance(row, Tag):
            continue

        cells = row.find_all(["th", "td"])
        if not cells:
            continue

        if len(tables) == i:
            tables.append([])

        for cell in cells:
            cell_str = cell.get_text(strip=True) if isinstance(cell, Tag) else ""
            tables[i].append(cell_str)
            if not isinstance(cell, Tag):
                continue
            if cell.has_attr("rowspan"):
                rowspan_str = cell.attrs["rowspan"]
                if not rowspan_str or not isinstance(rowspan_str, str):
                    continue
                rowspan = int(rowspan_str)
                for r in range(1, rowspan):
                    if len(tables) == i + r:
                        tables.append([])
                    tables[i + r].append(cell_str)

    # Process the matrix to extract weigh station data
    tables = [t for t in tables if len(t) == 5]  # Remove empty rows

    header, *rows = tables
    weigh_stations = {}

    for row_data in rows:
        highway = row_data[0].strip()
        station_name = row_data[1].strip() + "地磅站"
        direction = row_data[2].strip()
        km_distance = row_data[3].strip()
        special_weight = row_data[4].strip()

        station = GovInterchangeData(
            name=station_name,
            km_distance="",
            service_area=[],
            notes=[],
            facility_type="weigh_station",
        )
        if station_name in weigh_stations:
            station = weigh_stations[station_name]

        station.km_distance += f"{',' if station.km_distance else ''}{km_distance}"
        station.service_area.append(f"{highway}{direction}{km_distance}")

        if special_weight:
            station.km_distance += (
                f"{',' if station.km_distance else ''}{special_weight.split('(')[0]}"
            )
            station.service_area.append(f"{highway}{direction}動態地磅{special_weight}")
        weigh_stations[station_name] = station

    # Create single highway data containing all weigh stations
    return GovHighwayData(
        name="地磅站",
        title="地磅站",
        url=url,
        interchanges=list(weigh_stations.values()),
    )


def load_or_fetch_gov_weigh_stations(use_cache: bool = True) -> GovHighwayData:
    """Load all government weigh station data from freeway bureau."""
    data = load_or_fetch_data(
        "gov_cache_weigh_stations.json", lambda: query_gov_weigh_stations().model_dump(), use_cache
    )
    return GovHighwayData.model_validate(data)


def create_gov_data_from_interchange(
    gov_interchange: GovInterchangeData, highway_url: str
) -> GovData:
    """Transform GovInterchangeData to GovData format."""
    return GovData(
        name=gov_interchange.name,
        km_distance=gov_interchange.km_distance,
        service_area=gov_interchange.service_area,
        southbound_exit=gov_interchange.southbound_exit,
        northbound_exit=gov_interchange.northbound_exit,
        eastbound_exit=gov_interchange.eastbound_exit,
        westbound_exit=gov_interchange.westbound_exit,
        notes=gov_interchange.notes,
        facility_type=gov_interchange.facility_type,
        url=highway_url,  # Highway page URL (always present)
        interchange_url=gov_interchange.url,  # Specific interchange diagram URL (optional)
    )


if __name__ == "__main__":
    regular_data = load_or_fetch_gov_interchanges(use_cache=True)
    weigh_station_data = load_or_fetch_gov_weigh_stations(use_cache=False)
