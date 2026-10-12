
import json
from datetime import datetime
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

BERLIN = ZoneInfo("Europe/Berlin")
HEADERS = {
    "User-Agent": "FahrradtermineBerlinBot/0.2 (event research)"
}


def fetch_json(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def clean_html(value):
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def scan_gancio(source):
    events = fetch_json(source["url"])

    if isinstance(events, dict):
        events = events.get("events", [])

    if not isinstance(events, list):
        raise ValueError("Der JSON-Feed enthält keine Veranstaltungsliste")

    now = datetime.now(BERLIN)
    found = []
    past = 0
    invalid = 0

    for event in events:
        timestamp = event.get("start_datetime")

        if not isinstance(timestamp, (int, float)):
            invalid += 1
            continue

        start = datetime.fromtimestamp(timestamp, BERLIN)

        # Nur Veranstaltungen, deren Beginn noch bevorsteht
        if start <= now:
            past += 1
            continue

        slug = event.get("slug", "")
        event_url = (
            "https://fahrradtermine-berlin.de/event/" + slug
            if slug else source["url"]
        )

        place = event.get("place") or {}
        tags = event.get("tags") or []

        if isinstance(tags, list):
            tags = [
                tag.get("tag", "") if isinstance(tag, dict)
                else str(tag)
                for tag in tags
            ]
        else:
            tags = []

        found.append({
            "source": source["name"],
            "page": source["url"],
            "title": event.get("title", "").strip(),
            "url": event_url,
            "date": start.strftime("%Y-%m-%d"),
            "start_time": start.isoformat(),
            "display_time": start.strftime("%d.%m.%Y %H:%M"),
            "end_time": (
                datetime.fromtimestamp(
                    event["end_datetime"], BERLIN
                ).isoformat()
                if isinstance(event.get("end_datetime"), (int, float))
                else None
            ),
            "place": place.get("name", ""),
            "address": place.get("address", ""),
            "description": clean_html(event.get("description", "")),
            "tags": tags,
            "image": (
                event.get("media", [{}])[0].get("name", "")
                if event.get("media") else ""
            ),
            "status": "needs_review"
        })

    found.sort(key=lambda item: item["start_time"])

    print("Einträge im Feed:", len(events))
    print("Vergangene oder bereits begonnene Termine:", past)
    print("Einträge ohne gültige Startzeit:", invalid)
    print("Zukünftige Termine:", len(found))

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
                print("Noch nicht unterstützt:", source["name"])
        except Exception as exc:
            print("FEHLER:", source["name"], repr(exc))
            raise

    output_file = OUT / "candidates.json"
    output_file.write_text(
        json.dumps(found, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("Gespeichert:", output_file)
    print("Gesamtzahl:", len(found))


if __name__ == "__main__":
    main()
