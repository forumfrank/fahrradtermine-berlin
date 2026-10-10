
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
import feedparser

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

BERLIN = ZoneInfo("Europe/Berlin")

HEADERS = {
    "User-Agent": "FahrradtermineBerlinBot/0.1 (event research)"
}

DATE_PATTERN = re.compile(
    r"(?:Beginn|Start|Termin)?\s*:?\s*"
    r"(\d{1,2})\.(\d{1,2})\.(\d{4})"
    r"\s*(?:um\s*)?"
    r"(\d{1,2})[:.](\d{2})\s*"
    r"(?:Uhr|h)?",
    re.IGNORECASE,
)


def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    return response.text


def scan_html(source):
    soup = BeautifulSoup(fetch_html(source["url"]), "html.parser")

    # Seitentitel möglichst aus der eigentlichen Überschrift holen
    heading = soup.find("h1")
    title = heading.get_text(" ", strip=True) if heading else ""

    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    # Für die Datumserkennung störende Elemente entfernen
    for element in soup.select("script, style, nav, footer, header"):
        element.decompose()

    text = soup.get_text(" ", strip=True)
    match = DATE_PATTERN.search(text)

    if not match:
        print("Kein Startdatum gefunden:", source["url"])
        return []

    day, month, year, hour, minute = map(int, match.groups())

    try:
        start = datetime(
            year, month, day, hour, minute, tzinfo=BERLIN
        )
    except ValueError:
        print("Ungültiges Datum:", source["url"])
        return []

    # Nur zukünftige Veranstaltungen übernehmen
    if start <= datetime.now(BERLIN):
        print("Vergangen:", title, start.isoformat())
        return []

    # Titel aufräumen
    title = re.sub(r"\s+", " ", title).strip()

    return [{
        "source": source["name"],
        "page": source["url"],
        "title": title,
        "url": source["url"],
        "context": text[:2000],
        "date": start.isoformat(),
        "start_time": start.isoformat(),
        "status": "needs_review"
    }]


def scan_feed(source):
    feed = feedparser.parse(source["url"])
    found = []

    for entry in feed.entries:
        published = entry.get("published", None)
        found.append({
            "source": source["name"],
            "page": source["url"],
            "title": entry.get("title", ""),
            "url": entry.get("link", source["url"]),
            "context": entry.get("summary", "")[:1200],
            "date": None,
            "start_time": None,
            "status": "needs_review",
            "feed_published": published
        })

    return found


def main():
    config = json.loads(
        (ROOT / "sources.json").read_text(encoding="utf-8")
    )

    found = []

    for source in config["sources"]:
        try:
            if source["type"] == "feed":
                found.extend(scan_feed(source))
            else:
                found.extend(scan_html(source))
            print("OK:", source["name"])
        except Exception as exc:
            print("FEHLER:", source["name"], str(exc))

    # Doppelte Veranstaltungsseiten entfernen
    unique = {item["url"]: item for item in found}

    # Chronologisch nach Beginn sortieren
    results = sorted(
        unique.values(),
        key=lambda item: item.get("start_time") or "9999"
    )

    (OUT / "candidates.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("Zukünftige Kandidaten:", len(results))


if __name__ == "__main__":
    main()
