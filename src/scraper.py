import json
import re

from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)

BERLIN = ZoneInfo("Europe/Berlin")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FahrradtermineBerlinBot/0.3)"
}


def fetch_json(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def clean_html(value):
    if not value:
        return ""
    soup = BeautifulSoup(str(value), "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def extract_image_url(page_url):
    """Read the event's preview/poster image URL from its source page."""
    if not page_url:
        return ""

    try:
        response = requests.get(page_url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for selector in (
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
        ):
            tag = soup.select_one(selector)
            if tag and tag.get("content"):
                image_url = urljoin(page_url, tag["content"].strip())
                if image_url.startswith(("https://", "http://")):
                    return image_url

        # Fallback: some pages expose the poster as the first event image.
        for selector in (
            ".event-image img",
            ".event-detail img",
            "article img",
        ):
            tag = soup.select_one(selector)
            if tag and tag.get("src"):
                image_url = urljoin(page_url, tag["src"].strip())
                if image_url.startswith(("https://", "http://")):
                    return image_url

    except requests.RequestException as exc:
        print(f"Plakat konnte nicht abgerufen werden für {page_url}: {exc}")
    except Exception as exc:
        print(f"Fehler beim Auslesen des Plakats für {page_url}: {exc}")

    return ""


def format_display_time(start):
    weekdays = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    current_year = datetime.now(BERLIN).year
    date_part = (
        f"{start.day}.{start.month}."
        if start.year == current_year
        else f"{start.day}.{start.month}.{start.year}"
    )
    return (
        f"{weekdays[start.weekday()]}, {date_part} "
        f"{start.hour}:{start.minute:02d}h"
    )


def scan_gancio(source):
    events = fetch_json(source["url"])

    if isinstance(events, dict):
        events = events.get("events", events.get("data", []))

    if not isinstance(events, list):
        raise ValueError("Der JSON-Feed enthält keine Veranstaltungsliste")

    now = datetime.now(BERLIN)
    found = []
    past = 0
    invalid = 0

    for event in events:
        if not isinstance(event, dict):
            invalid += 1
            continue

        timestamp = event.get("start_datetime")
        if not isinstance(timestamp, (int, float)):
            invalid += 1
            continue

        start = datetime.fromtimestamp(timestamp, BERLIN)

        # Nur Veranstaltungen, deren Beginn noch bevorsteht.
        if start <= now:
            past += 1
            continue

        slug = str(event.get("slug") or "").strip("/")
        event_url = (
            urljoin("https://fahrradtermine-berlin.de/", "event/" + slug)
            if slug
            else source["url"]
        )

        # Das Bild wird von der Veranstaltungsseite ausgelesen.
        image_url = extract_image_url(event_url)

        place = event.get("place") or {}
        if not isinstance(place, dict):
            place = {"name": str(place), "address": ""}

        tags = event.get("tags") or []
        if isinstance(tags, list):
            tags = [
                str(tag.get("tag", tag.get("name", "")))
                if isinstance(tag, dict)
                else str(tag)
                for tag in tags
            ]
        else:
            tags = [str(tags)] if tags else []

        end_timestamp = event.get("end_datetime")
        end_time = (
            datetime.fromtimestamp(end_timestamp, BERLIN).isoformat()
            if isinstance(end_timestamp, (int, float))
            else None
        )

        found.append({
            "source": source.get("name", "Fahrradtermine Berlin – Gancio"),
            "page": source["url"],
            "title": clean_html(event.get("title", "")),
            "url": event_url,
            "date": start.strftime("%Y-%m-%d"),
            "start_time": start.isoformat(),
            "display_time": format_display_time(start),
            "end_time": end_time,
            "place": clean_html(place.get("name", "")),
            "address": clean_html(place.get("address", "")),
            "description": clean_html(event.get("description", "")),
            "tags": tags,
            "image": image_url,
            "status": "needs_review",
        })

    found.sort(key=lambda item: item["start_time"])

    print("Einträge im Feed:", len(events))
    print("Vergangene oder bereits begonnene Termine:", past)
    print("Einträge ohne gültige Startzeit:", invalid)
    print("Zukünftige Termine:", len(found))
    print("Termine mit Plakat:", sum(bool(item["image"]) for item in found))

    return found



MONTHS = {
    "januar": 1, "jan": 1,
    "februar": 2, "feb": 2,
    "märz": 3, "maerz": 3, "mrz": 3,
    "april": 4, "apr": 4,
    "mai": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}


def parse_velodemo_date(text):
    """Deutsches Datum aus einer Überschrift lesen."""
    match = re.search(
        r"\b(?P<day>\d{1,2})\.\s*"
        r"(?P<month>[A-Za-zÄÖÜäöüß]+)\.?\s*"
        r"(?P<year>20\d{2})?\b",
        text,
        re.IGNORECASE,
    )

    if match:
        month_name = match.group("month").lower().rstrip(".")
        month = MONTHS.get(month_name)
        if not month:
            return None
        year = int(match.group("year") or datetime.now(BERLIN).year)
        day = int(match.group("day"))
    else:
        # Zusätzlich Datumsformate wie 31.10.2026 erkennen.
        match = re.search(
            r"\b(?P<day>\d{1,2})\.(?P<month>\d{1,2})"
            r"(?:\.(?P<year>20\d{2}))?\.?\b",
            text,
        )
        if not match:
            return None
        day = int(match.group("day"))
        month = int(match.group("month"))
        year = int(match.group("year") or datetime.now(BERLIN).year)

    try:
        return datetime(year, month, day, tzinfo=BERLIN)
    except ValueError:
        return None


def scan_velodemo(source):
    """Scrape VELODEMO events; pair poster images with the date heading below them."""
    response = requests.get(source["url"], headers=HEADERS, timeout=30)
    response.raise_for_status()
    # Parse bytes so BeautifulSoup can honor the page's declared text encoding.
    soup = BeautifulSoup(response.content, "html.parser")

    dated_headings = []
    for heading in soup.find_all(["h2", "h3"]):
        event_date = parse_velodemo_date(heading.get_text(" ", strip=True))
        if event_date:
            dated_headings.append((heading, event_date))

    def image_url_from_tag(img):
        src = (
            img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
            or img.get("src")
            or ""
        ).strip()
        if (not src or src.startswith("data:")) and img.get("srcset"):
            candidates = [
                item.strip().split()[0]
                for item in img.get("srcset", "").split(",")
                if item.strip()
            ]
            if candidates:
                src = candidates[-1]
        if not src or src.startswith("data:"):
            return ""
        return urljoin(source["url"], src)

    def image_date_matches(image_url, event_date):
        # Filenames such as 26-10-31_kidicalmass.jpg can validate the association.
        filename = image_url.split("?", 1)[0].rsplit("/", 1)[-1]
        match = re.search(
            r"(?<!\d)(?P<year>20\d{2}|\d{2})[-_](?P<month>\d{1,2})[-_](?P<day>\d{1,2})(?!\d)",
            filename,
        )
        if not match:
            return True  # No date in the filename, so use the page's structure.
        year = int(match.group("year"))
        if year < 100:
            year += 2000
        try:
            filename_date = (year, int(match.group("month")), int(match.group("day")))
        except ValueError:
            return False
        return filename_date == (event_date.year, event_date.month, event_date.day)

    now = datetime.now(BERLIN)
    found = []

    for heading_index, (heading, event_date) in enumerate(dated_headings):
        # Text and links belong to the event after this heading. Stop at the next
        # heading. Images are intentionally NOT taken from this section because
        # VELODEMO places a poster before its event's date heading.
        nodes = []
        for node in heading.next_siblings:
            if getattr(node, "name", None) in ("h1", "h2", "h3", "h4"):
                break
            if getattr(node, "name", None):
                nodes.append(node)

        # Find the nearest preceding poster, without crossing the previous heading.
        image_url = ""
        for previous in heading.previous_siblings:
            if getattr(previous, "name", None) in ("h1", "h2", "h3", "h4"):
                break
            imgs = []
            if getattr(previous, "name", None) == "img":
                imgs = [previous]
            elif getattr(previous, "find_all", None):
                imgs = previous.find_all("img")
            found_nearest_image = False
            for img in reversed(imgs):
                candidate = image_url_from_tag(img)
                if not candidate:
                    continue
                found_nearest_image = True
                # If the filename contains a different date, leave the poster
                # blank rather than accidentally reusing an older event's image.
                if image_date_matches(candidate, event_date):
                    image_url = candidate
                break
            if found_nearest_image:
                break

        lines = []
        links = []
        for node in nodes:
            if node.name in ("script", "style", "noscript"):
                continue
            text = node.get_text(" ", strip=True)
            if text:
                lines.append(" ".join(text.split()))
            if node.name == "a":
                links.append(node)
            links.extend(node.find_all("a"))

        # A start time can appear at the end of the event description line.
        start_match = None
        place = ""
        for line in lines:
            match = re.search(
                r"\bStart\s*:?\s*(?:um\s*)?(\d{1,2})(?:[:.](\d{2}))?\s*(?:Uhr)?\s*[,–-]?\s*(.*)",
                line,
                re.IGNORECASE,
            )
            if match:
                start_match = match
                place = match.group(3).strip(" ,–-")
                break

        time_unknown = start_match is None
        hour = int(start_match.group(1)) if start_match else 12
        minute = int(start_match.group(2) or 0) if start_match else 0
        start = event_date.replace(hour=hour, minute=minute)
        if (not time_unknown and start <= now) or (time_unknown and event_date.date() < now.date()):
            continue

        title_candidates = []
        for line in lines:
            cleaned = re.sub(
                r"\b(?:Start|Zubringer|Ziel)\s*:?.*$",
                "",
                line,
                flags=re.IGNORECASE,
            ).strip(" ,–-\t")
            if cleaned and not re.match(
                r"^(Treffen|Start|Zubringer|Ziel)\b", cleaned, re.IGNORECASE
            ):
                title_candidates.append(cleaned)
        title = title_candidates[0] if title_candidates else f"Fahrraddemo am {event_date:%d.%m.%Y}"

        # Prefer a specific event link if present; otherwise link to the source page.
        event_url = source["url"]
        for link in links:
            href = (link.get("href") or "").strip()
            label = link.get_text(" ", strip=True)
            if not href or not label or href.startswith(("mailto:", "#", "javascript:")):
                continue
            candidate = urljoin(source["url"], href)
            if "velodemo.de" in candidate.lower() and candidate.rstrip("/") == source["url"].rstrip("/"):
                continue
            if re.search(r"\.(jpe?g|png|gif|webp|svg)(?:\?|$)", candidate, re.IGNORECASE):
                continue
            event_url = candidate
            break

        found.append({
            "source": source.get("name", "VELODEMO"),
            "page": source["url"],
            "title": clean_html(title),
            "url": event_url,
            "date": start.strftime("%Y-%m-%d"),
            "start_time": start.isoformat(),
            "display_time": (
                start.strftime("%d.%m.%Y %H:%M")
                if not time_unknown
                else start.strftime("%d.%m.%Y") + " – Uhrzeit offen"
            ),
            "end_time": None,
            "place": clean_html(place),
            "address": clean_html(place),
            "description": clean_html(" ".join(lines)),
            "tags": ["Fahrraddemo"],
            "image": image_url,
            "status": "needs_review",
            "time_unknown": time_unknown,
        })

    # Drop duplicates from the same VELODEMO page (e.g. repeated date headings).
    unique = []
    seen = set()
    for event in found:
        key = (
            event.get("date", ""),
            re.sub(r"\s+", " ", event.get("title", "")).strip().casefold(),
            re.sub(r"\s+", " ", event.get("place", "")).strip().casefold(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(event)

    unique.sort(key=lambda item: item["start_time"])
    print("VELODEMO: Datumsüberschriften gefunden:", len(dated_headings))
    print("VELODEMO: zukünftige Termine:", len(unique))
    print("VELODEMO: Termine mit passend zugeordnetem Plakat:", sum(bool(item["image"]) for item in unique))
    return unique




def main():
    config = json.loads(
        (ROOT / "sources.json").read_text(encoding="utf-8")
    )

    found = []

    
        
        
    
    for source in config["sources"]:
        try:
            if source.get("type") == "gancio_json":
                found.extend(scan_gancio(source))
            elif source.get("type") == "velodemo_html":
                found.extend(scan_velodemo(source))
            else:
                print(
                    "Noch nicht unterstützt:",
                    source.get("name", source.get("type"))
                )
        except Exception as exc:
            print(
                "FEHLER:",
                source.get("name", "Unbekannte Quelle"),
                repr(exc)
            )
            raise

    output_file = OUT / "candidates.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(found, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print("Gespeichert:", output_file)
    print("Gesamtzahl:", len(found))


if __name__ == "__main__":
    main()

