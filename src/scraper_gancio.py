#!/usr/bin/env python3
"""Scrape Gancio's JSON feed and write output/candidates_gancio.json."""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
BERLIN = ZoneInfo("Europe/Berlin")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FahrradtermineBerlinBot/0.4)"}


def clean_html(value):
    if not value:
        return ""
    return " ".join(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True).split())


def source_config():
    data = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    for source in data.get("sources", []):
        if source.get("type") == "gancio_json":
            return source
    raise SystemExit("Keine Quelle mit type='gancio_json' in sources.json gefunden.")


def fetch_json(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def image_from_page(page_url):
    """Try standard preview metadata; keep scraping faults non-fatal."""
    try:
        response = requests.get(page_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        for selector in ('meta[property="og:image"]', 'meta[name="twitter:image"]'):
            tag = soup.select_one(selector)
            value = tag.get("content", "").strip() if tag else ""
            if value:
                candidate = urljoin(page_url, value)
                if candidate.startswith(("https://", "http://")):
                    return candidate
    except requests.RequestException as exc:
        print(f"Gancio: Bild-Metadaten nicht abrufbar ({page_url}): {exc}")
    return ""


def normalize_tags(value):
    if not isinstance(value, list):
        value = [value] if value else []
    result = []
    for tag in value:
        if isinstance(tag, dict):
            tag = tag.get("tag") or tag.get("name") or ""
        tag = str(tag).strip()
        if tag and tag not in result:
            result.append(tag)
    return result


def event_start(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, BERLIN)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=BERLIN) if parsed.tzinfo is None else parsed.astimezone(BERLIN)
        except ValueError:
            return None
    return None


def scrape(source):
    payload = fetch_json(source["url"])
    if isinstance(payload, dict):
        payload = payload.get("events", payload.get("data", []))
    if not isinstance(payload, list):
        raise ValueError("Der Gancio-JSON-Feed enthält keine Veranstaltungsliste.")

    now = datetime.now(BERLIN)
    found = []
    skipped_past = 0
    skipped_invalid = 0
    for item in payload:
        if not isinstance(item, dict):
            skipped_invalid += 1
            continue
        start = event_start(item.get("start_datetime"))
        if start is None:
            skipped_invalid += 1
            continue
        if start <= now:
            skipped_past += 1
            continue

        slug = str(item.get("slug") or "").strip("/")
        event_url = urljoin(source["url"], "/event/" + slug) if slug else source["url"]
        place = item.get("place") or {}
        if not isinstance(place, dict):
            place = {"name": str(place), "address": ""}

        # Use a feed-provided image when it is a direct URL; otherwise read the event page.
        image = ""
        for key in ("image", "image_url", "picture", "cover", "banner", "thumbnail"):
            value = item.get(key)
            if isinstance(value, dict):
                value = value.get("url") or value.get("src")
            if isinstance(value, str) and value.strip().startswith(("https://", "http://")):
                image = value.strip()
                break
        if not image:
            image = image_from_page(event_url)

        end = event_start(item.get("end_datetime"))
        found.append({
            "source": source.get("name", "Fahrradtermine Berlin – Gancio"),
            "page": source["url"],
            "title": clean_html(item.get("title", "")),
            "url": event_url,
            "date": start.date().isoformat(),
            "start_time": start.isoformat(),
            "display_time": start.strftime("%d.%m.%Y %H:%M"),
            "end_time": end.isoformat() if end else None,
            "place": clean_html(place.get("name", "")),
            "address": clean_html(place.get("address", "")),
            "description": clean_html(item.get("description", "")),
            "tags": normalize_tags(item.get("tags")),
            "image": image,
            "status": "needs_review",
        })

    found.sort(key=lambda event: event["start_time"])
    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / "candidates_gancio.json"
    output.write_text(json.dumps(found, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Gancio: Einträge im Feed:", len(payload))
    print("Gancio: vergangen/begonnen:", skipped_past)
    print("Gancio: ohne gültige Startzeit:", skipped_invalid)
    print("Gancio: zukünftige Termine:", len(found))
    print("Gancio: Termine mit Plakat:", sum(bool(event["image"]) for event in found))
    print("Gancio: gespeichert:", output)


def main():
    scrape(source_config())


if __name__ == "__main__":
    main()
