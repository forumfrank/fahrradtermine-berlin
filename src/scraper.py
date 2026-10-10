
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import feedparser

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "FahrradtermineBerlinBot/0.1 (event research)"
}


def fetch_html(url):
    response = requests.get(
        url, headers=HEADERS, timeout=25
    )
    response.raise_for_status()
    return response.text


def scan_html(source):
    html = fetch_html(source["url"])
    soup = BeautifulSoup(html, "html.parser")
    found = []

    for link in soup.select("a[href]"):
        title = link.get_text(" ", strip=True)
        url = urljoin(source["url"], link["href"])

        if len(title) < 8:
            continue

        # Erste grobe Vorauswahl; später durch
        # Datums- und Veranstaltungsparser ersetzen.
        context = link.parent.get_text(" ", strip=True)
        text = f"{title} {context}"

        if re.search(
            r"fahrrad|radverkehr|radtour|critical mass|"
            r"kidical mass|verkehrswende|radweg|"
            r"demo|demonstration|lastenrad",
            text,
            re.I,
        ):
            found.append({
                "source": source["name"],
                "page": source["url"],
                "title": title,
                "url": url,
                "context": context[:1200],
                "date": None,
                "status": "needs_review"
            })

    return found


def scan_feed(source):
    feed = feedparser.parse(source["url"])
    found = []

    for entry in feed.entries:
        found.append({
            "source": source["name"],
            "page": source["url"],
            "title": entry.get("title", ""),
            "url": entry.get("link", source["url"]),
            "context": entry.get("summary", "")[:1200],
            "date": entry.get("published", None),
            "status": "needs_review"
        })

    return found


def main():
    config = json.loads(
        (ROOT / "sources.json").read_text(
            encoding="utf-8"
        )
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

    # Links innerhalb eines Laufs deduplizieren.
    unique = {item["url"]: item for item in found}

    (OUT / "candidates.json").write_text(
        json.dumps(
            list(unique.values()),
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("Kandidaten:", len(unique))


if __name__ == "__main__":
    main()
