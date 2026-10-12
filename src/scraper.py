from pathlib import Path
p = Path("/mnt/data/scraper.py")
code = r'''import json
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


def main():
    config = json.loads(
        (ROOT / "sources.json").read_text(encoding="utf-8")
    )

    found = []

    for source in config["sources"]:
        try:
            if source.get("type") == "gancio_json":
                found.extend(scan_gancio(source))
            else:
                print("Noch nicht unterstützt:", source.get("name", source.get("type")))
        except Exception as exc:
            print("FEHLER:", source.get("name", "Unbekannte Quelle"), repr(exc))
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

