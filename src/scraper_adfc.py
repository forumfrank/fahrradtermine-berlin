#!/usr/bin/env python3
"""Fetch upcoming ADFC events via the official RVP REST API.

Writes output/candidates_adfc.json. The query mirrors the user's public search:
Berlin center, 30 km radius, from today through the next 365 days.
"""
import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import quote, urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
BERLIN = ZoneInfo("Europe/Berlin")
API_URL = "https://api-touren-termine.adfc.de/api/eventItems/search"
SEARCH_PAGE = (
    "https://touren-termine.adfc.de/suche?distance=30"
    "&latLng=52.517%2C13.3888&place=Berlin"
)
LAT_LNG = "52.517,13.3888"
CENTER_LAT, CENTER_LON = (float(part) for part in LAT_LNG.split(","))
DISTANCE_KM = 30
DAYS_AHEAD = 365
LIMIT = 100
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FahrradtermineBerlinBot/0.5; event research)",
    "Accept": "application/json, text/plain, */*",
}


def clean(value):
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, str):
        return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())
    return ""


def normalize_key(key):
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def find_value(obj, names, max_depth=4):
    """Case-insensitive lookup of common API field names, including nested shapes."""
    wanted = {normalize_key(name) for name in names}
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        for key, value in obj.items():
            if normalize_key(key) in wanted and value not in (None, "", [], {}):
                return value
        for value in obj.values():
            found = find_value(value, names, max_depth - 1)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_value(value, names, max_depth - 1)
            if found not in (None, "", [], {}):
                return found
    return None


def first_direct(obj, names):
    """Look only at the top level; avoids confusing event start with a nested other date."""
    if not isinstance(obj, dict):
        return None
    wanted = {normalize_key(name) for name in names}
    for key, value in obj.items():
        if normalize_key(key) in wanted and value not in (None, "", [], {}):
            return value
    return None


def parse_datetime(value, fallback_time=None):
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, BERLIN)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, dict):
        # Common API shapes: {date, time}, {startDate, startTime}, {dateTime}.
        direct = first_direct(value, ("dateTime", "datetime", "startDateTime", "beginning", "start", "date", "startDate", "beginningDate"))
        if direct is None:
            d = first_direct(value, ("date", "startDate", "beginningDate"))
            t = first_direct(value, ("time", "startTime", "beginningTime"))
            if d:
                value = f"{d} {t or ''}".strip()
            else:
                return None
        else:
            value = direct
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # ISO date or datetime, with optional timezone.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=BERLIN)
        return parsed.astimezone(BERLIN)
    except ValueError:
        pass
    # Some versions expose date and time in separate fields.
    patterns = (
        (r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})(?::\d{2})?$", "%Y-%m-%d %H:%M"),
        (r"^(\d{1,2}\.\d{1,2}\.\d{4})\s+(\d{1,2}:\d{2})$", "%d.%m.%Y %H:%M"),
    )
    for pattern, fmt in patterns:
        match = re.match(pattern, text)
        if match:
            try:
                return datetime.strptime(f"{match.group(1)} {match.group(2)}", fmt).replace(tzinfo=BERLIN)
            except ValueError:
                pass
    # Date-only value plus separate time.
    if fallback_time:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y"):
            try:
                d = datetime.strptime(text, fmt)
                time_text = str(fallback_time).strip()
                tm = re.search(r"(\d{1,2}):(\d{2})", time_text)
                if tm:
                    return d.replace(hour=int(tm.group(1)), minute=int(tm.group(2)), tzinfo=BERLIN)
                return d.replace(tzinfo=BERLIN)
            except ValueError:
                continue
    return None


def parse_event_start(item):
    # Prefer an explicit combined start/beginning field.
    value = first_direct(item, (
        "startDateTime", "beginningDateTime", "beginning", "start", "startDate", "beginningDate",
        "dateTime", "startAt", "dateStart", "date",
    ))
    time_value = first_direct(item, ("startTime", "beginningTime", "timeStart", "startClockTime", "time"))
    parsed = parse_datetime(value, time_value)
    if parsed:
        # If date and time are separately exposed but date parsed at midnight, combine the time.
        if parsed.hour == 0 and parsed.minute == 0 and time_value:
            tm = re.search(r"(\d{1,2}):(\d{2})", str(time_value))
            if tm:
                parsed = parsed.replace(hour=int(tm.group(1)), minute=int(tm.group(2)))
        return parsed
    # A nested date/time structure may be found under common event fields.
    value = find_value(item, ("startDateTime", "beginningDateTime", "beginning", "startDate", "beginningDate"))
    return parse_datetime(value, time_value)


def extract_item_list(payload):
    """Normalize API responses commonly used for collection/search results."""
    if isinstance(payload, list):
        return payload, None, None
    if not isinstance(payload, dict):
        raise ValueError(f"Unerwartetes ADFC-API-Format: {type(payload).__name__}")
    for key in ("eventItems", "items", "results", "events", "data", "result", "content"):
        value = payload.get(key)
        if isinstance(value, list):
            total = payload.get("total") or payload.get("totalCount") or payload.get("count")
            offset = payload.get("offset", payload.get("skip", 0))
            return value, int(total) if str(total).isdigit() else None, int(offset) if str(offset).isdigit() else 0
        if isinstance(value, dict):
            try:
                return extract_item_list(value)
            except ValueError:
                pass
    # APIs sometimes wrap one list in an extra data/result object.
    for value in payload.values():
        if isinstance(value, (dict, list)):
            try:
                return extract_item_list(value)
            except ValueError:
                continue
    raise ValueError("ADFC-API-Antwort enthält keine erkennbare Veranstaltungsliste. Schlüssel: " + ", ".join(map(str, payload.keys())))


def _coordinate_number(value):
    """Convert a JSON coordinate to a float, rejecting invalid values."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return result if -180 <= result <= 180 else None


def _coordinate_pair_from_dict(obj):
    """Read latitude and longitude when they are in the same object."""
    if not isinstance(obj, dict):
        return None
    values = {normalize_key(key): value for key, value in obj.items()}
    lat = lon = None
    for key in ("latitude", "lat", "gpslatitude", "locationlatitude", "geolatitude"):
        if key in values:
            lat = _coordinate_number(values[key])
            if lat is not None:
                break
    for key in ("longitude", "lon", "lng", "long", "gpslongitude", "locationlongitude", "geolongitude"):
        if key in values:
            lon = _coordinate_number(values[key])
            if lon is not None:
                break
    if lat is not None and lon is not None and -90 <= lat <= 90:
        return lat, lon
    return None


def _search_location_coordinates(value, depth=0):
    """Search a location object, including common nested geo/position shapes."""
    if depth > 6:
        return None
    if isinstance(value, dict):
        pair = _coordinate_pair_from_dict(value)
        if pair:
            return pair

        for key, subvalue in value.items():
            norm = normalize_key(key)
            # GeoJSON coordinate arrays are [longitude, latitude].
            if norm in {"coordinates", "coordinate"} and isinstance(subvalue, (list, tuple)) and len(subvalue) >= 2:
                lon = _coordinate_number(subvalue[0])
                lat = _coordinate_number(subvalue[1])
                if lon is not None and lat is not None and -90 <= lat <= 90:
                    return lat, lon
            # A named latLng string conventionally uses latitude, longitude.
            if norm in {"latlng", "gpscoordinates"} and isinstance(subvalue, str):
                match = re.search(r"(-?\d{1,2}(?:\.\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:\.\d+)?)", subvalue)
                if match:
                    lat, lon = float(match.group(1)), float(match.group(2))
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        return lat, lon

        # Search geographic containers first; avoid roaming over unrelated event fields.
        priority = {"geo", "geolocation", "geoposition", "position", "coordinates", "coordinate", "point", "location", "address", "meetingpoint", "startlocation", "venue"}
        for key, subvalue in sorted(value.items(), key=lambda pair: normalize_key(pair[0]) not in priority):
            if isinstance(subvalue, (dict, list, tuple)):
                pair = _search_location_coordinates(subvalue, depth + 1)
                if pair:
                    return pair
    elif isinstance(value, (list, tuple)):
        for subvalue in value:
            if isinstance(subvalue, (dict, list, tuple)):
                pair = _search_location_coordinates(subvalue, depth + 1)
                if pair:
                    return pair
    return None


def event_coordinates(item):
    """Get the event's actual start/meeting point, not the search centre."""
    if not isinstance(item, dict):
        return None
    location_names = {
        "meetingpoint", "startlocation", "startplace", "startaddress", "place",
        "eventlocation", "location", "venue", "address", "locationdata",
        "geolocation", "geoposition", "geo", "position", "point", "coordinates",
    }
    fields = [
        (key, value) for key, value in item.items()
        if normalize_key(key) in location_names and isinstance(value, (dict, list, tuple))
    ]
    priority = ["meetingpoint", "startlocation", "startplace", "startaddress", "place", "eventlocation", "location", "venue", "address", "locationdata", "geolocation", "geoposition", "geo", "position", "point", "coordinates"]
    for _, value in sorted(fields, key=lambda pair: priority.index(normalize_key(pair[0])) if normalize_key(pair[0]) in priority else len(priority)):
        pair = _search_location_coordinates(value)
        if pair:
            return pair

    # Some API responses put lat/lon directly on the event.
    pair = _coordinate_pair_from_dict(item)
    if pair:
        return pair
    for key, value in item.items():
        if normalize_key(key) in {"latlng", "gpscoordinates", "coordinates", "geolocation", "geoposition"}:
            pair = _search_location_coordinates({key: value})
            if pair:
                return pair
    return None


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points in kilometres."""
    from math import asin, cos, radians, sin, sqrt
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(min(1.0, a)))


def stringify_place(value):
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        parts = []
        for names in (
            ("name", "title", "label", "placeName", "locationName", "meetingPoint"),
            ("street", "streetAddress", "addressLine", "address"),
            ("postalCode", "zip", "postcode"),
            ("city", "town", "locality"),
        ):
            part = find_value(value, names, max_depth=1)
            text = clean(part)
            if text and text not in parts:
                parts.append(text)
        return ", ".join(parts)
    return clean(value)


def extract_image(item):
    image_names = (
        "imageUrl", "imageURL", "image", "images", "pictureUrl", "pictureURL", "picture",
        "pictures", "thumbnailUrl", "thumbnail", "coverImage", "eventImage", "bannerUrl",
        "mediaUrl", "photo", "photos", "imagePath", "picturePath",
    )
    value = find_value(item, image_names)
    if value is None:
        return ""
    candidates = []

    def collect(obj):
        if isinstance(obj, str):
            candidate = obj.strip()
            if candidate.startswith(("https://", "http://", "/", "//")):
                candidates.append(candidate)
        elif isinstance(obj, dict):
            # Image fields are often objects such as {url: ..., alt: ...}.
            for sub in obj.values():
                if len(candidates) >= 20:
                    break
                if isinstance(sub, (dict, list, str)):
                    collect(sub)
        elif isinstance(obj, list):
            for sub in obj[:20]:
                if len(candidates) >= 20:
                    break
                collect(sub)

    collect(value)
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        elif candidate.startswith("/"):
            candidate = urljoin("https://touren-termine.adfc.de/", candidate)
        if candidate.startswith(("https://", "http://")) and not re.search(r"(logo|avatar|favicon|placeholder)", candidate, re.I):
            return candidate
    return ""


def normalize_tags(item):
    value = find_value(item, ("tags", "features", "characteristics", "eventType", "type", "category", "eventCategory"), max_depth=2)
    if value is None:
        return ["ADFC"]
    if isinstance(value, list):
        tags = []
        for one in value:
            if isinstance(one, dict):
                one = find_value(one, ("name", "title", "label", "displayName", "value"), max_depth=1)
            text = clean(one)
            if text and text not in tags:
                tags.append(text)
        return tags or ["ADFC"]
    if isinstance(value, dict):
        value = find_value(value, ("name", "title", "label", "displayName", "value"), max_depth=1)
    text = clean(value)
    return [text] if text else ["ADFC"]


def slugify(value):
    value = clean(value).lower().replace("ß", "ss")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:100].strip("-")


def event_url(item, title):
    """Find the public event URL without mistaking an image object's URL for it."""
    # Prefer known public-link fields, whether direct or nested.
    value = first_direct(item, ("eventUrl", "publicUrl", "detailUrl", "permalink", "webUrl", "frontendUrl", "linkUrl", "canonicalUrl"))
    if value is None:
        value = find_value(item, ("eventUrl", "publicUrl", "detailUrl", "permalink", "webUrl", "frontendUrl", "linkUrl", "canonicalUrl"), max_depth=3)
    if value is None:
        value = first_direct(item, ("url", "link", "href"))
    if value is None:
        # Some responses wrap the actual event one level down. Skip image/media objects.
        def walk_links(obj, depth=0):
            if depth > 4:
                return None
            if isinstance(obj, dict):
                for key, sub in obj.items():
                    key_norm = normalize_key(key)
                    if any(token in key_norm for token in ("image", "picture", "photo", "thumbnail", "banner", "media", "attachment")):
                        continue
                    if key_norm in {"url", "href", "link"} and isinstance(sub, str) and sub.strip():
                        return sub.strip()
                for key, sub in obj.items():
                    key_norm = normalize_key(key)
                    if any(token in key_norm for token in ("image", "picture", "photo", "thumbnail", "banner", "media", "attachment")):
                        continue
                    result = walk_links(sub, depth + 1)
                    if result:
                        return result
            elif isinstance(obj, list):
                for sub in obj:
                    result = walk_links(sub, depth + 1)
                    if result:
                        return result
            return None
        value = walk_links(item)
    if isinstance(value, dict):
        value = first_direct(value, ("href", "url", "uri"))
    if isinstance(value, str) and value.strip():
        url = value.strip()
        if url.startswith("/"):
            url = urljoin("https://touren-termine.adfc.de/", url)
        if url.startswith(("https://", "http://")) and "api-touren-termine.adfc.de" not in url:
            return url
    identifier = first_direct(item, ("id", "eventId", "eventItemId", "publicId", "identifier"))
    if identifier is None:
        identifier = find_value(item, ("id", "eventId", "eventItemId", "publicId", "identifier"), max_depth=1)
    if identifier and str(identifier).isdigit():
        return f"https://touren-termine.adfc.de/radveranstaltung/{identifier}-{slugify(title)}"
    return SEARCH_PAGE


def normalize_event(item):
    title = clean(first_direct(item, ("title", "eventTitle", "name", "eventName", "headline", "shortTitle", "label")))
    if not title:
        title = clean(find_value(item, ("title", "eventTitle", "eventName", "headline", "shortTitle"), max_depth=2))
    start = parse_event_start(item)
    if not title or not start:
        return None
    now = datetime.now(BERLIN)
    if start <= now:
        return None

    end_raw = first_direct(item, ("endDateTime", "end", "endDate", "endAt", "finish", "finishDateTime"))
    end_time_val = first_direct(item, ("endTime", "finishTime", "timeEnd"))
    end = parse_datetime(end_raw, end_time_val)

    place_raw = first_direct(item, ("place", "location", "address", "venue", "meetingPoint", "startLocation", "eventLocation", "locationName"))
    if place_raw is None:
        place_raw = find_value(item, ("meetingPoint", "eventLocation", "locationName", "placeName", "address"), max_depth=2)
    place = stringify_place(place_raw)

    description = first_direct(item, ("description", "longDescription", "shortDescription", "teaser", "summary", "text", "abstract"))
    if description is None:
        description = find_value(item, ("description", "longDescription", "shortDescription", "teaser", "summary"), max_depth=2)

    date_text = start.strftime("%Y-%m-%d")
    return {
        "source": "ADFC – Touren & Termine Berlin (30 km)",
        "page": SEARCH_PAGE,
        "title": title,
        "url": event_url(item, title),
        "date": date_text,
        "start_time": start.isoformat(),
        "display_time": start.strftime("%d.%m.%Y %H:%M"),
        "end_time": end.isoformat() if end else None,
        "place": place,
        "address": place,
        "description": clean(description),
        "tags": normalize_tags(item),
        "image": extract_image(item),
        "status": "needs_review",
        "adfc_id": find_value(item, ("id", "eventId", "eventItemId", "publicId", "identifier"), max_depth=1),
    }


def fetch_page(session, beginning, end, offset):
    params = {
        "distance": DISTANCE_KM,
        "latLng": LAT_LNG,
        "place": "Berlin",
        "beginning": beginning.isoformat(),
        "end": end.isoformat(),
        "offset": offset,
        "limit": LIMIT,
    }
    response = session.get(API_URL, params=params, timeout=45)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(f"ADFC-API lieferte kein JSON (HTTP {response.status_code}, URL {response.url}).") from exc


def scrape():
    today = datetime.now(BERLIN).date()
    end = today + timedelta(days=DAYS_AHEAD)
    session = requests.Session()
    session.headers.update(HEADERS)

    found = []
    seen_ids = set()
    outside_radius = 0
    without_coordinates = 0
    offset = 0
    max_pages = 50
    total_hint = None
    seen_raw_items = set()
    print(f"ADFC: Suche Umkreis {DISTANCE_KM} km um Berlin, Zeitraum {today} bis {end}")

    for page_number in range(max_pages):
        payload = fetch_page(session, today, end, offset)
        items, total, returned_offset = extract_item_list(payload)
        if total is not None:
            total_hint = total
        if not items:
            break
        new_count = 0
        raw_new_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_id = first_direct(item, ("id", "eventId", "eventItemId", "publicId", "identifier"))
            if raw_id is None:
                raw_id = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            raw_id = str(raw_id)
            if raw_id in seen_raw_items:
                continue
            seen_raw_items.add(raw_id)
            raw_new_count += 1
            # Enforce the requested radius locally. The REST endpoint may ignore
            # the geographic parameters copied from the frontend search URL.
            coords = event_coordinates(item)
            if not coords:
                without_coordinates += 1
                continue
            lat, lon = coords
            km = distance_km(CENTER_LAT, CENTER_LON, lat, lon)
            if km > DISTANCE_KM:
                outside_radius += 1
                continue

            normalized = normalize_event(item)
            if not normalized:
                continue
            normalized["latitude"] = round(lat, 6)
            normalized["longitude"] = round(lon, 6)
            normalized["distance_km"] = round(km, 1)
            unique_id = normalized.get("adfc_id") or (normalized["date"], normalized["title"], normalized["place"])
            unique_id = str(unique_id)
            if unique_id in seen_ids:
                continue
            seen_ids.add(unique_id)
            found.append(normalized)
            new_count += 1

        print(f"ADFC: API-Seite {page_number + 1}: {len(items)} Datensätze, {new_count} neue zukünftige Termine")
        # If the endpoint ignores pagination, stop rather than repeating the same page forever.
        if raw_new_count == 0:
            print("ADFC: API lieferte eine bereits gesehene Seite erneut; Pagination beendet.")
            break
        offset = (returned_offset if returned_offset is not None else offset) + len(items)
        if total_hint is not None:
            if offset >= total_hint:
                break
        elif len(items) < LIMIT:
            break

    found.sort(key=lambda event: event["start_time"])
    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / "candidates_adfc.json"
    output.write_text(json.dumps(found, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ADFC: außerhalb des {DISTANCE_KM}-km-Umkreises verworfen: {outside_radius}")
    print(f"ADFC: mangels Koordinaten nicht übernommen: {without_coordinates}")
    print(f"ADFC: zukünftige Termine innerhalb des Umkreises: {len(found)}")
    print(f"ADFC: Termine mit Bild-URL: {sum(bool(event['image']) for event in found)}")
    print(f"ADFC: gespeichert: {output}")


def main():
    scrape()


if __name__ == "__main__":
    main()
