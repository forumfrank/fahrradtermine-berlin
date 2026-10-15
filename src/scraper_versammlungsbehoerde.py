#!/usr/bin/env python3
"""Scrape matching Berlin assembly notifications and render a HedgeDoc-ready weekly list.

Source rows are read from Berlin.de. Matching single-event URLs are looked up on
Demonstrations.org by title and date. If no single page can be matched, the entry
links to a prefilled search on Demonstrations.org and is marked in the output.

Writes:
  output/candidates_versammlungsbehoerde.json
  output/versammlungsbehoerde.html
"""
from __future__ import annotations

import html
import json
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
JSON_OUTPUT = OUT / "candidates_versammlungsbehoerde.json"
HTML_OUTPUT = OUT / "versammlungsbehoerde.html"
BERLIN_URL = "https://www.berlin.de/polizei/service/versammlungsbehoerde/versammlungen-aufzuege/"
DEMO_URL = "https://demonstrations.org/de/events"
BERLIN = ZoneInfo("Europe/Berlin")

# Feste Korrekturen für bekannte Einzelansichten, die trotz korrektem Titel
# gelegentlich nicht aus der Ergebnisliste zugeordnet werden.
KNOWN_DEMO_URL_OVERRIDES = [
    {
        "date": "2026-10-16",
        "title_contains": "sichere schulwege machen unsere kinder stark neumannstrasse fur alle sicher machen",
        "url": "https://demonstrations.org/de/events/63038--sichere-schulwege-machen-unsere-kinder-stark--neumannstra-e-f-r-alle-sicher-machen--gefordert-wird-d",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FahrradtermineBerlinBot/1.0; GitHub project forumfrank/fahrradtermine-berlin)",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
}

# Match words/compounds at the beginning of a word so e.g. "Radweg" matches,
# but an unrelated word such as "gerade" does not.
KEYWORD_PATTERNS = {
    "Fahrrad": re.compile(r"fahrrad\w*", re.IGNORECASE),
    "Rad": re.compile(r"\brad\w*", re.IGNORECASE),
    "Radfahren": re.compile(r"radfahren\w*", re.IGNORECASE),
    "Klima": re.compile(r"klima\w*", re.IGNORECASE),
    "Baum": re.compile(r"\bbaum\w*", re.IGNORECASE),
    "Bäume": re.compile(r"\bbäume\w*", re.IGNORECASE),
    "A100": re.compile(r"\ba100\b", re.IGNORECASE),
    "THF": re.compile(r"\bthf\b", re.IGNORECASE),
}
KEYWORD_RE = re.compile("|".join(f"(?:{p.pattern})" for p in KEYWORD_PATTERNS.values()), re.IGNORECASE)
KEYWORDS = tuple(KEYWORD_PATTERNS)
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
MONTHS_DE = {
    "jan": 1, "januar": 1, "feb": 2, "februar": 2, "mär": 3, "mrz": 3, "märz": 3,
    "apr": 4, "april": 4, "mai": 5, "jun": 6, "juni": 6, "jul": 7, "juli": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "okt": 10,
    "oktober": 10, "nov": 11, "november": 11, "dez": 12, "dezember": 12,
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def clean(value: object) -> str:
    if value is None:
        return ""
    text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", clean(value)).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def get_page(url: str, *, timeout: int = 30) -> str:
    response = SESSION.get(url, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def get_table_column_map(table) -> dict[str, int]:
    """Find the main table header row and map its column titles."""
    desired = {
        "datum": ("datum", "date"),
        "von": ("von", "beginn", "start"),
        "bis": ("bis", "ende", "end"),
        "thema": ("thema", "titel", "title"),
        "plz": ("plz", "postleitzahl"),
        "ort": ("versammlungsort", "ort", "location"),
        "strecke": ("aufzugsstrecke", "strecke", "route"),
    }
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        names = [normalized(cell.get_text(" ", strip=True)) for cell in cells]
        if not any(name in ("datum", "date") for name in names):
            continue
        result = {}
        for field, variants in desired.items():
            for idx, name in enumerate(names):
                if name in variants:
                    result[field] = idx
                    break
        if all(k in result for k in ("datum", "von", "bis", "thema")):
            return result
    return {}


def parse_source_date(value: str) -> date | None:
    value = clean(value)
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None
    return None


def parse_clock(value: str) -> str | None:
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", clean(value))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def berlin_datetime(day: date, clock: str | None) -> datetime:
    hour, minute = (0, 0) if not clock else tuple(int(v) for v in clock.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BERLIN)


def matched_keywords(title: str) -> list[str]:
    return [keyword for keyword, pattern in KEYWORD_PATTERNS.items() if pattern.search(title)]


def scrape_berlin_source(today: date) -> list[dict]:
    print(f"Lese Versammlungsbehörde: {BERLIN_URL}")
    page = get_page(BERLIN_URL)
    soup = BeautifulSoup(page, "html.parser")
    found = []
    suitable_table_found = False

    for table in soup.find_all("table"):
        column_map = get_table_column_map(table)
        if not column_map:
            continue
        suitable_table_found = True
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells or cells[0].name == "th":
                continue

            def col(name: str) -> str:
                idx = column_map.get(name)
                return clean(cells[idx].get_text(" ", strip=True)) if idx is not None and idx < len(cells) else ""

            day = parse_source_date(col("datum"))
            title = col("thema")
            if not day or not title or day < today:
                continue
            keywords = matched_keywords(title)
            if not keywords:
                continue

            start_clock = parse_clock(col("von"))
            end_clock = parse_clock(col("bis"))
            postcode = col("plz")
            location = col("ort")
            route = col("strecke")
            place_parts = []
            if postcode:
                place_parts.append(postcode)
            if location:
                place_parts.append(location)
            place = " · ".join(place_parts) or (route.split(" - ", 1)[0].strip() if route else "")

            start_dt = berlin_datetime(day, start_clock)
            end_dt = berlin_datetime(day, end_clock) if end_clock else None
            found.append({
                "source": "Versammlungsbehörde Berlin",
                "page": BERLIN_URL,
                "url": "",
                "title": title,
                "date": day.isoformat(),
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat() if end_dt else None,
                "start_clock": start_clock,
                "end_clock": end_clock,
                "display_time": "",
                "place": place,
                "address": location,
                "postcode": postcode,
                "route": route,
                "description": "",
                "tags": keywords,
                "matched_keywords": keywords,
                "map_url": "",
                "url_status": "unmatched",
            })

    if not suitable_table_found:
        raise RuntimeError("Die Versammlungstabelle auf Berlin.de wurde nicht gefunden; Seitenstruktur hat sich möglicherweise geändert.")

    # Remove exact duplicates only; recurring event occurrences on different dates remain.
    deduped, seen = [], set()
    for item in found:
        key = (item["date"], normalized(item["title"]), normalized(item["place"]), item["start_clock"], item["end_clock"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    print(f"Berlin.de: {len(deduped)} zukünftige Termine mit Suchwörtern gefunden.")
    return deduped


def parse_demo_datetime(text: str) -> datetime | None:
    """Parse a date/time from a German demonstrations.org event-list card."""
    text = clean(text)
    # Example: Fr., 16 Okt. 2026 07:20 Berlin
    regex = re.compile(
        r"(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?[,]?\s*(\d{1,2})\s+([A-Za-zÄÖÜäöü]{3,8})\.?\s+(\d{4})\s+(\d{1,2}):(\d{2})",
        re.IGNORECASE,
    )
    match = regex.search(text)
    if not match:
        return None
    month_token = match.group(2).casefold().rstrip(".")
    month = MONTHS_DE.get(month_token)
    if not month:
        month = MONTHS_DE.get(month_token[:3])
    if not month:
        return None
    try:
        return datetime(int(match.group(3)), month, int(match.group(1)), int(match.group(4)), int(match.group(5)), tzinfo=BERLIN)
    except ValueError:
        return None


def extract_link_datetime(anchor) -> datetime | None:
    node = anchor
    best = None
    # Keep the tightest ancestor that contains a date/time, not the whole page.
    for _ in range(5):
        if node is None:
            break
        dt = parse_demo_datetime(node.get_text(" ", strip=True))
        if dt:
            best = dt
            break
        node = node.parent
    return best


def parse_demo_index(page: str) -> list[dict]:
    soup = BeautifulSoup(page, "html.parser")
    items, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(DEMO_URL, html.unescape(anchor.get("href", "").strip()))
        path = urlparse(href).path
        if not re.search(r"/de/events/\d+", path):
            continue
        visible_title = clean(anchor.get_text(" ", strip=True))
        title = visible_title if len(visible_title) > 4 else clean(anchor.get("title") or anchor.get("aria-label"))
        if not title or title.casefold() in {"arrow_forward_ios", "mehr", "details"}:
            continue
        key = (href.split("?", 1)[0], normalized(title))
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": title, "url": href, "datetime": extract_link_datetime(anchor)})
    return items


def demo_search_url_groups(base_html: str) -> tuple[list[list[str]], bool]:
    """Return keyword-search URL groups, trying fallback parameter names only if needed."""
    soup = BeautifulSoup(base_html, "html.parser")
    candidate = None
    action = DEMO_URL
    for form in soup.find_all("form"):
        for field in form.find_all(["input", "textarea"]):
            placeholder = (field.get("placeholder") or "").casefold()
            aria = (field.get("aria-label") or "").casefold()
            if "event namen" in placeholder or "event name" in placeholder or "event namen" in aria:
                candidate = field.get("name") or field.get("id")
                action = urljoin(DEMO_URL, form.get("action") or DEMO_URL)
                if form.get("method", "get").casefold() != "get":
                    candidate = None
                if candidate:
                    break
        if candidate:
            break

    # If the search box exposes its GET parameter, use it. Otherwise try common
    # names in groups and stop after the first group that actually adds links.
    parameter_groups = [[candidate]] if candidate else [["search"], ["q"], ["query"]]
    return [
        [action + ("&" if "?" in action else "?") + urlencode({group[0]: term}) for term in KEYWORDS]
        for group in parameter_groups
    ], bool(candidate)


def collect_demo_links() -> list[dict]:
    print(f"Suche Einzel-URLs auf demonstrations.org: {DEMO_URL}")
    try:
        base_html = get_page(DEMO_URL)
    except Exception as exc:
        print(f"WARNUNG: demonstrations.org konnte nicht gelesen werden: {exc}")
        return []

    items = parse_demo_index(base_html)
    print(f"demonstrations.org Startseite: {len(items)} Einzel-URLs erkannt.")
    # Search by each desired keyword so the index's default date window/page size
    # does not hide all matches. Probe common parameter names only until one works.
    search_groups, has_named_form_field = demo_search_url_groups(base_html)
    for group in search_groups:
        before = {item["url"].split("?", 1)[0] for item in items}
        for search_url in group:
            try:
                page = get_page(search_url, timeout=20)
                items.extend(parse_demo_index(page))
            except Exception as exc:
                print(f"Hinweis: Suchabruf übersprungen ({search_url}): {exc}")
        after = {item["url"].split("?", 1)[0] for item in items}
        if has_named_form_field or len(after - before) > 0:
            break

    deduped, seen = [], set()
    for item in items:
        key = item["url"].split("?", 1)[0]
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    print(f"demonstrations.org gesamt: {len(deduped)} unterschiedliche Einzel-URLs.")
    return deduped


def title_match_score(source_title: str, demo_title: str) -> float:
    a = normalized(source_title)
    b = normalized(demo_title)
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    at, bt = set(a.split()), set(b.split())
    overlap = len(at & bt) / max(1, min(len(at), len(bt)))
    # Link text may be truncated by the event list, so reward complete coverage
    # of the shorter title as well as conventional text similarity.
    return max(seq, overlap * 0.92)


def known_demo_url_override(event: dict) -> str:
    title = normalized(event.get("title", ""))
    for override in KNOWN_DEMO_URL_OVERRIDES:
        if event.get("date") == override["date"] and override["title_contains"] in title:
            return override["url"]
    return ""


def match_demo_url(event: dict, candidates: list[dict]) -> str:
    best_item, best_score = None, 0.0
    source_dt = datetime.fromisoformat(event["start_time"])
    for item in candidates:
        score = title_match_score(event["title"], item["title"])
        if score < 0.66:
            continue
        dt = item.get("datetime")
        # A strong title match should win, but an exact date/time breaks ties
        # between repeating series or similarly titled events.
        if dt:
            delta_days = abs((dt.date() - source_dt.date()).days)
            score -= min(delta_days, 3650) / 3650 * 0.12
            if dt.date() == source_dt.date():
                score += 0.06
            if dt.hour == source_dt.hour and dt.minute == source_dt.minute:
                score += 0.04
        if score > best_score:
            best_item, best_score = item, score
    return best_item["url"] if best_item else ""


def search_fallback_url(title: str) -> str:
    # Marked as a fallback in JSON and HTML; not presented as a matched single page.
    return DEMO_URL + "?" + urlencode({"search": title})


def inspect_demo_map(detail_url: str) -> tuple[str, str]:
    """Return (dedicated map iframe URL, page anchor for map fallback).

    Some Demos pages use a map iframe. Others draw their route directly in the
    event page with JavaScript, so they have no standalone map URL. In that case
    detect a likely map container id and return its fragment for a page-iframe
    fallback (e.g. detail_url + "#map").
    """
    if not detail_url.startswith("https://demonstrations.org/de/events/"):
        return "", "#map"
    try:
        soup = BeautifulSoup(get_page(detail_url, timeout=18), "html.parser")
    except Exception as exc:
        print(f"Hinweis: Einzelansicht für Kartenprüfung nicht abrufbar: {exc}")
        return "", "#map"

    map_terms = ("map", "maps", "route", "geo", "leaflet", "openstreetmap", "google.com/maps",
                 "mapbox", "arcgis", "carto", "geodata", "karte", "aufzug")
    for iframe in soup.find_all("iframe", src=True):
        src = urljoin(detail_url, html.unescape(iframe.get("src", "").strip()))
        descriptor = " ".join([
            src,
            iframe.get("title", ""),
            " ".join(iframe.get("class", [])),
            iframe.get("id", ""),
        ]).casefold()
        if any(term in descriptor for term in map_terms):
            return src, "#map"

    # Map implementations such as Leaflet commonly use a dedicated container id.
    candidates = []
    for node in soup.find_all(["div", "section", "article", "main"]):
        node_id = str(node.get("id", "")).strip()
        descriptor = " ".join([node_id, " ".join(node.get("class", []))]).casefold()
        if node_id and any(term in descriptor for term in ("map", "karte", "geo", "route", "aufzug", "leaflet")):
            priority = 0 if node_id.casefold() in {"map", "mapid", "route-map", "map-container", "geo-map"} else 1
            candidates.append((priority, node_id))
    if candidates:
        candidates.sort()
        return "", "#" + quote(candidates[0][1], safe="-_.:")
    return "", "#map"

def map_query_for_event(event: dict) -> str:
    """Use the stationary location or first route stop for a map marker."""
    location = clean(event.get("address"))
    route = clean(event.get("route"))
    if route:
        # On moving demonstrations, show the route's first named stop as a fallback.
        first = re.split(r"\s+-\s+|\s+–\s+|;", route, maxsplit=1)[0]
        first = re.sub(r"\s*\([^)]*\)\s*", " ", first).strip(" ,;·")
        if first:
            location = first
    location = re.sub(r"\s+", " ", location).strip()
    if not location:
        return ""
    postcode = clean(event.get("postcode"))
    query = f"{location}, {postcode}, Berlin, Germany" if postcode and postcode not in location else f"{location}, Berlin, Germany"
    return query


def geocode_embed_url(query: str, cache: dict[str, str]) -> str:
    """Build an OSM iframe for a geocoded point; throttle Nominatim to <=1 req/s."""
    key = normalized(query)
    if not key:
        return ""
    if key in cache:
        return cache[key]
    # Nominatim is a best-effort fallback; do not break the scrape if unavailable.
    if cache:
        time.sleep(1.1)
    try:
        response = SESSION.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "jsonv2", "limit": 1},
            timeout=12,
        )
        response.raise_for_status()
        result = response.json()
        if not result:
            cache[key] = ""
            return ""
        lat, lon = float(result[0]["lat"]), float(result[0]["lon"])
        # A compact window around the location; marker coordinates remain exact.
        west, south, east, north = lon - 0.004, lat - 0.0025, lon + 0.004, lat + 0.0025
        bbox = f"{west:.6f}%2C{south:.6f}%2C{east:.6f}%2C{north:.6f}"
        src = f"https://www.openstreetmap.org/export/embed.html?bbox={bbox}&layer=mapnik&marker={lat:.6f}%2C{lon:.6f}"
        cache[key] = src
        return src
    except Exception as exc:
        print(f"Hinweis: Geo-Fenster nicht verfügbar für {query!r}: {exc}")
        cache[key] = ""
        return ""


def week_heading(dt: datetime) -> tuple[tuple[int, int], str]:
    iso = dt.isocalendar()
    monday = dt.date() - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    if monday.year == sunday.year:
        dates = f"{monday.day}.{monday.month:02d}. - {sunday.day}.{sunday.month:02d}."
    else:
        dates = f"{monday.day}.{monday.month:02d}.{monday.year} - {sunday.day}.{sunday.month:02d}.{sunday.year}"
    # Keep the same KW heading format as the other lists.
    return (iso.year, iso.week), f"# KW {iso.week} / {dates}"


def display_time(event: dict) -> str:
    start = datetime.fromisoformat(event["start_time"]).astimezone(BERLIN)
    end_raw = event.get("end_time")
    end = datetime.fromisoformat(end_raw).astimezone(BERLIN) if end_raw else None
    date_part = f"{start.day}.{start.month:02d}." if start.year == datetime.now(BERLIN).year else f"{start.day}.{start.month:02d}.{start.year}"
    base = f"{WEEKDAYS[start.weekday()]}, {date_part},  {start.hour:02d}:{start.minute:02d}"
    if end:
        base += f" - {end.hour:02d}:{end.minute:02d}"
    return base


def esc(value: object) -> str:
    return html.escape(str(value or "").strip(), quote=True)


def build_outputs(events: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

    prepared = []
    for event in events:
        try:
            dt = datetime.fromisoformat(event["start_time"]).astimezone(BERLIN)
        except (KeyError, ValueError, TypeError):
            continue
        prepared.append((dt, event))
    prepared.sort(key=lambda pair: (pair[0], normalized(pair[1].get("title")), normalized(pair[1].get("place"))))

    blocks = [
        "<!-- Automatisch aus der Berliner Versammlungsbehörde erzeugt; vor Veröffentlichung prüfen. -->",
        "",
        "# Versammlungsbehörde Berlin – Fahrrad, Klima, Bäume, A100 und THF",
        "",
        "<!-- Einzel-URLs werden von demonstrations.org übernommen. Bei fehlender Einzelansicht zeigt der Link eine Suche. -->",
        "",
    ]
    current_week = None
    current_year = datetime.now(BERLIN).year
    iframe_count = 0
    fallback_count = 0

    for dt, event in prepared:
        week_key, heading = week_heading(dt)
        if week_key != current_week:
            current_week = week_key
            blocks.extend([heading, ""])

        title = esc(event.get("title"))
        url = esc(event.get("url") or event.get("page") or BERLIN_URL)
        display = esc(display_time(event))
        place = esc(event.get("place") or "Ort nicht angegeben")
        route = clean(event.get("route"))
        notes = []
        if route and normalized(route) != normalized(event.get("place")):
            notes.append("Aufzugsstrecke: " + route)
        if event.get("url_status") != "matched":
            fallback_count += 1
            notes.append("Einzelansicht bei demonstrations.org nicht automatisch zugeordnet; Suchlink verwenden.")
        note_html = f'<div class="Bemerkung">{esc(" · ".join(notes))}</div>' if notes else '<div class="Bemerkung"></div>'

        map_url = event.get("map_url") or ""
        geo_html = ""
        if map_url:
            iframe_count += 1
            if event.get("map_embed_type") == "detail_page":
                iframe_title = f"Kartenansicht in der Einzelveranstaltung zu {title}"
                iframe_height = 460
            else:
                iframe_title = f"Karte zu {title}"
                iframe_height = 240
            geo_html = (
                f'<div class="GeoFenster"><iframe src="{esc(map_url)}" title="{esc(iframe_title)}" '
                'loading="lazy" referrerpolicy="no-referrer-when-downgrade" '
                f'style="width:100%;max-width:500px;height:{iframe_height}px;border:0" allowfullscreen></iframe></div>'
            )

        tag_html = esc(" · ".join(event.get("matched_keywords") or []))
        blocks.extend([
            f'<!-- Versammlungsbehörde: {esc(event.get("date"))} / {title} -->',
            '<div class="Rahmen" style="border:0;margin:0;padding:0">',
            f'<div class="Zeit" style="color:red">{display}</div>',
            f'<div class="Rubrik">{tag_html}</div>',
            f'<div class="Titel">{title}</div>',
            f'<div class="Ort">{place}</div>',
            note_html,
            geo_html,
            f'<div class="Quelle"><a href="{url}">{"Einzeltermin auf demonstrations.org" if event.get("url_status") == "matched" else "Terminsuche auf demonstrations.org"}</a></div>',
            '</div>',
            '<hr>',
            '',
        ])

    HTML_OUTPUT.write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")
    print(f"JSON gespeichert: {JSON_OUTPUT}")
    print(f"HTML gespeichert: {HTML_OUTPUT} ({len(prepared)} Termine)")
    print(f"Einzel-URLs von demonstrations.org zugeordnet: {sum(e.get('url_status') == 'matched' for e in events)}")
    print(f"Suchlink-Fallbacks (bitte prüfen): {fallback_count}")
    print(f"Geo-Fenster im iframe: {iframe_count}")


def main() -> None:
    today = datetime.now(BERLIN).date()
    events = scrape_berlin_source(today)
    if not events:
        # A successful zero-match result should not be confused with a failed scrape.
        print("Keine passenden zukünftigen Termine auf Berlin.de gefunden.")
        build_outputs([])
        return

    demo_links = collect_demo_links()
    matched = 0
    for event in events:
        direct = known_demo_url_override(event) or match_demo_url(event, demo_links)
        if direct:
            event["url"] = direct
            event["url_status"] = "matched"
            matched += 1
        else:
            event["url"] = search_fallback_url(event["title"])
            event["url_status"] = "search_fallback"

    # Prefer a map/route iframe already present on the single event page.
    # Repeated events in a series share the same URL and are only fetched once.
    map_cache_by_url: dict[str, tuple[str, str]] = {}
    unique_urls = list(dict.fromkeys(e["url"] for e in events if e.get("url_status") == "matched"))
    for idx, direct_url in enumerate(unique_urls[:50], start=1):
        map_cache_by_url[direct_url] = inspect_demo_map(direct_url)
        if idx % 10 == 0:
            print(f"Kartenquelle geprüft: {idx}/{min(50, len(unique_urls))}")

    geocode_cache: dict[str, str] = {}
    for event in events:
        direct_url = event.get("url", "")
        map_url, map_anchor = map_cache_by_url.get(direct_url, ("", "#map")) if event.get("url_status") == "matched" else ("", "#map")
        if map_url:
            event["map_embed_type"] = "map_iframe"
        elif event.get("url_status") == "matched":
            # On some Demos event pages the route is rendered in the page itself,
            # not as a separate map iframe. Try anchoring the page to its map.
            # If the site disallows framing or has no suitable anchor, the normal
            # direct link below the iframe remains available.
            map_url = direct_url + map_anchor
            event["map_embed_type"] = "detail_page"
        else:
            query = map_query_for_event(event)
            if query:
                map_url = geocode_embed_url(query, geocode_cache)
                event["map_embed_type"] = "osm_point" if map_url else ""
        event["map_url"] = map_url
        event["display_time"] = display_time(event)

    print(f"Einzel-URLs zugeordnet: {matched} von {len(events)} Terminen.")
    build_outputs(events)


if __name__ == "__main__":
    main()
