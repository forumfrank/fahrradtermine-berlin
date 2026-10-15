#!/usr/bin/env python3
"""Scrape VELODEMO independently and write output/candidates_velodemo.json."""
import json
import re
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
MONTHS = {
    "januar": 1, "jan": 1, "februar": 2, "feb": 2,
    "märz": 3, "maerz": 3, "mrz": 3, "april": 4, "apr": 4,
    "mai": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "okt": 10, "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}


def clean_text(value):
    return " ".join(BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True).split())


def source_config():
    data = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    for source in data.get("sources", []):
        if source.get("type") == "velodemo_html":
            return source
    raise SystemExit("Keine Quelle mit type='velodemo_html' in sources.json gefunden.")


def parse_date(text):
    """Recognize dates like 'Samstag, 31. Oktober 2026' and '31.10.2026'."""
    text = clean_text(text)
    month_words = "|".join(sorted(MONTHS, key=len, reverse=True))
    match = re.search(
        rf"(?<!\d)(?P<day>\d{{1,2}})\.\s*(?:(?P<monthnum>\d{{1,2}})\.?|(?P<monthname>{month_words})\.?)\s*(?P<year>20\d{{2}})?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    if match.group("monthnum"):
        month = int(match.group("monthnum"))
    else:
        month = MONTHS[match.group("monthname").lower()]
    year = int(match.group("year") or datetime.now(BERLIN).year)
    try:
        return datetime(year, month, int(match.group("day")), tzinfo=BERLIN)
    except ValueError:
        return None


def image_date_matches(image_url, event_date):
    """If the filename includes a date, require it to match the event date."""
    filename = image_url.split("?", 1)[0].rsplit("/", 1)[-1]
    match = re.search(r"(?<!\d)(?P<year>20\d{2}|\d{2})[-_](?P<month>\d{1,2})[-_](?P<day>\d{1,2})(?!\d)", filename)
    if not match:
        return True
    year = int(match.group("year"))
    if year < 100:
        year += 2000
    try:
        return (year, int(match.group("month")), int(match.group("day"))) == (event_date.year, event_date.month, event_date.day)
    except ValueError:
        return False


def image_url_from_tag(img, page_url):
    value = (img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or img.get("src") or "").strip()
    if (not value or value.startswith("data:")) and img.get("srcset"):
        candidates = [part.strip().split()[0] for part in img.get("srcset", "").split(",") if part.strip()]
        if candidates:
            value = candidates[-1]
    if not value or value.startswith("data:"):
        return ""
    return urljoin(page_url, value)


def find_image(tags_before_heading, event_date, page_url):
    """Use only the image region after the previous heading; validate dated filenames."""
    images = [tag for tag in tags_before_heading if tag.name == "img"]
    if not images:
        return ""
    # The closest preceding image should belong to the following date heading.
    candidate = image_url_from_tag(images[-1], page_url)
    if not candidate:
        return ""
    filename = candidate.split("?", 1)[0].rsplit("/", 1)[-1].lower()
    if any(token in filename for token in ("logo", "favicon", "avatar", "header", "banner")):
        return ""
    if not image_date_matches(candidate, event_date):
        print(f"VELODEMO: Plakat wegen abweichendem Dateinamen nicht zugeordnet: {candidate} (Termin {event_date:%Y-%m-%d})")
        return ""
    return candidate


def scrape(source):
    response = requests.get(source["url"], headers=HEADERS, timeout=30)
    response.raise_for_status()
    # Parse bytes so BeautifulSoup can honor the page's declared encoding.
    soup = BeautifulSoup(response.content, "html.parser")
    all_tags = list(soup.find_all(True))
    tag_index = {id(tag): index for index, tag in enumerate(all_tags)}

    headings = []
    for tag in all_tags:
        if tag.name not in ("h1", "h2", "h3", "h4"):
            continue
        date = parse_date(tag.get_text(" ", strip=True))
        if date:
            headings.append((tag, date, tag_index[id(tag)]))

    all_heading_indices = [tag_index[id(tag)] for tag in all_tags if tag.name in ("h1", "h2", "h3", "h4")]
    now = datetime.now(BERLIN)
    found = []

    for item_index, (heading, event_date, index) in enumerate(headings):
        next_index = headings[item_index + 1][2] if item_index + 1 < len(headings) else len(all_tags)
        # For text, keep to the siblings after this heading until the next dated heading.
        lines = []
        links = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in ("h1", "h2", "h3", "h4") and parse_date(sibling.get_text(" ", strip=True)):
                break
            if not getattr(sibling, "name", None):
                continue
            if sibling.name in ("script", "style", "noscript"):
                continue
            value = sibling.get_text(" ", strip=True)
            if value:
                lines.append(" ".join(value.split()))
            if sibling.name == "a":
                links.append(sibling)
            links.extend(sibling.find_all("a"))

        # Pick the nearest image after the preceding heading, not any image on the site.
        prior_heading_indices = [i for i in all_heading_indices if i < index]
        boundary = prior_heading_indices[-1] if prior_heading_indices else 0
        preceding_region = all_tags[boundary + 1:index]
        image = find_image(preceding_region, event_date, source["url"])

        start_match = None
        place = ""
        for line in lines:
            match = re.search(r"\bStart\s*:?\s*(?:um\s*)?(\d{1,2})(?:[:.](\d{2}))?\s*(?:Uhr)?\s*[,–-]?\s*(.*)", line, re.IGNORECASE)
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
            # If title and start/place are on the same line, keep only title text.
            cleaned = re.sub(r"\bStart\s*:?.*$", "", line, flags=re.IGNORECASE).strip(" ,–-\t")
            if cleaned and not re.match(r"^(Treffen|Start|Zubringer|Ziel)\b", cleaned, re.IGNORECASE):
                title_candidates.append(cleaned)
        title = title_candidates[0] if title_candidates else f"Fahrraddemo am {event_date:%d.%m.%Y}"

        event_url = source["url"]
        for link in links:
            href = (link.get("href") or "").strip()
            label = link.get_text(" ", strip=True)
            if not href or not label or href.startswith(("mailto:", "#", "javascript:")):
                continue
            candidate = urljoin(source["url"], href)
            if candidate.rstrip("/") == source["url"].rstrip("/"):
                continue
            if re.search(r"\.(jpe?g|png|gif|webp|svg)(?:\?|$)", candidate, re.IGNORECASE):
                continue
            event_url = candidate
            break

        found.append({
            "source": source.get("name", "VELODEMO"),
            "page": source["url"],
            "title": clean_text(title),
            "url": event_url,
            "date": start.date().isoformat(),
            "start_time": start.isoformat(),
            "display_time": start.strftime("%d.%m.%Y %H:%M") if not time_unknown else start.strftime("%d.%m.%Y") + " – Uhrzeit offen",
            "end_time": None,
            "place": clean_text(place),
            "address": clean_text(place),
            "description": clean_text(" ".join(lines)),
            "tags": ["Fahrraddemo"],
            "image": image,
            "status": "needs_review",
            "time_unknown": time_unknown,
        })

    # Remove repeated entries on this source by date, title and place.
    unique = []
    seen = set()
    for event in found:
        key = (event["date"], re.sub(r"\s+", " ", event["title"]).strip().casefold(), re.sub(r"\s+", " ", event["place"]).strip().casefold())
        if key not in seen:
            seen.add(key)
            unique.append(event)
    unique.sort(key=lambda event: event["start_time"])

    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / "candidates_velodemo.json"
    output.write_text(json.dumps(unique, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("VELODEMO: Datumsüberschriften gefunden:", len(headings))
    print("VELODEMO: zukünftige Termine:", len(unique))
    print("VELODEMO: Termine mit zugeordnetem Plakat:", sum(bool(event["image"]) for event in unique))
    print("VELODEMO: gespeichert:", output)


def main():
    scrape(source_config())


if __name__ == "__main__":
    main()
