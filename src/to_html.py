#!/usr/bin/env python3
"""Convert candidates.json into separate HedgeDoc HTML files by source."""
import html
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output" / "candidates.json"
OUTPUTS = {
    "fahrradtermine": ROOT / "output" / "fahrradtermine.html",
    "velodemo": ROOT / "output" / "velodemo.html",
}
BERLIN = ZoneInfo("Europe/Berlin")


def esc(value):
    return html.escape(str(value or "").strip(), quote=True)


def slug_from_url(url):
    path = (url or "").split("?", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def event_datetime(event):
    value = event.get("start_time") or ""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=BERLIN)
        return parsed.astimezone(BERLIN)
    except (ValueError, TypeError):
        return None


def source_kind(event):
    source = str(event.get("source") or "").lower()
    page = str(event.get("page") or "").lower()
    url = str(event.get("url") or "").lower()
    if "velodemo" in source or "velodemo.de" in page or "velodemo.de" in url:
        return "velodemo"
    return "fahrradtermine"


def deduplicate(events):
    """Remove exact duplicate records within one source, not between sources."""
    result = []
    seen = set()
    for event in events:
        dt = event_datetime(event)
        date_key = event.get("date") or (dt.date().isoformat() if dt else "")
        title_key = re.sub(r"\s+", " ", str(event.get("title") or "")).strip().casefold()
        place_key = re.sub(
            r"\s+", " ", str(event.get("place") or event.get("address") or "")
        ).strip().casefold()
        # Source links on VELODEMO can all be the homepage, so use date/title/place.
        key = (date_key, title_key, place_key)
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def display_time(event, dt):
    if not dt:
        return event.get("date", "")
    weekday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][dt.weekday()]
    current_year = datetime.now(BERLIN).year
    date_part = (
        f"{dt.day}.{dt.month}."
        if dt.year == current_year
        else f"{dt.day}.{dt.month}.{dt.year}"
    )
    if event.get("time_unknown"):
        return f"{weekday}, {date_part} – Uhrzeit offen"
    time_part = f"{dt.hour}h" if dt.minute == 0 else f"{dt.hour}:{dt.minute:02d}h"
    return f"{weekday}, {date_part} {time_part}"


def week_heading(dt):
    iso = dt.isocalendar()
    monday = dt.date() - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    if monday.year == sunday.year:
        dates = f"{monday.day}.{monday.month}. - {sunday.day}.{sunday.month}."
    else:
        dates = (
            f"{monday.day}.{monday.month}.{monday.year} - "
            f"{sunday.day}.{sunday.month}.{sunday.year}"
        )
    return (iso.year, iso.week), f"# KW {iso.week} / {dates}"


def render(events, kind, output_file):
    events = deduplicate(events)
    prepared = [(event_datetime(event), event) for event in events]
    prepared.sort(
        key=lambda pair: (
            pair[0] is None,
            pair[0] or datetime.max.replace(tzinfo=BERLIN),
        )
    )

    label = "VELODEMO" if kind == "velodemo" else "Gancio"
    blocks = [
        f"<!-- Automatisch aus candidates.json erzeugt: {label}; vor Veröffentlichung prüfen. -->",
        "",
    ]
    current_week = None

    for dt, event in prepared:
        if dt:
            week_key, heading = week_heading(dt)
            if week_key != current_week:
                current_week = week_key
                blocks.extend([heading, ""])

        title = esc(event.get("title"))
        url = esc(event.get("url") or event.get("page"))
        place = esc(event.get("place") or event.get("address"))
        time_text = esc(display_time(event, dt))
        image_url = esc(event.get("image"))

        raw_tags = event.get("tags") or []
        if isinstance(raw_tags, list):
            tag_values = []
            for tag in raw_tags:
                if isinstance(tag, dict):
                    tag = tag.get("tag") or tag.get("name") or ""
                tag = str(tag).strip()
                if tag:
                    tag_values.append(tag)
            rubrik = esc(" · ".join(tag_values))
        else:
            rubrik = esc(raw_tags)

        note = str(event.get("note") or "")
        if not note and dt and dt.hour == 0 and dt.minute == 0 and "purple ride" in (event.get("title") or "").lower():
            note = "Uhrzeit im Feed unklar; bitte prüfen."

        if kind == "velodemo":
            identifier = (event.get("date") or "") + " " + (event.get("title") or "")
        else:
            identifier = slug_from_url(event.get("url", ""))
        identifier = identifier.replace("--", "—").strip()

        if image_url:
            poster = (
                f'<div class="Plakat"><a href="{url}">'
                f'<img src="{image_url}" alt="{title}" style="max-width:100%">'
                f"</a></div>"
            )
        else:
            poster = '<div class="Plakat"></div>'

        blocks.extend([
            f"<!-- {label}: {esc(identifier)} -->",
            "<p>",
            '<div class="Rahmen">',
            poster,
            f'<div class="Zeit">{time_text}</div>',
            
            f'<div class="Titel">{title}</div>',
            f'<div class="Rubrik">{rubrik}</div>',
            f'<div class="Ort">{place}</div>',
            f'<div class="Bemerkung">{esc(note)}</div>',
            f'<div class="Quelle"><a href="{url}">{url}</a></div>',
            "</div></p>",
            "<hr>",
            "",
        ])

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")
    print(f"HTML erzeugt: {output_file} ({len(prepared)} Termine nach Deduplizierung)")


def main():
    if not INPUT.exists():
        raise SystemExit(f"Datei nicht gefunden: {INPUT}")
    events = json.loads(INPUT.read_text(encoding="utf-8"))
    if not isinstance(events, list):
        raise SystemExit("candidates.json muss eine JSON-Liste enthalten.")

    grouped = {"fahrradtermine": [], "velodemo": []}
    for event in events:
        if isinstance(event, dict):
            grouped[source_kind(event)].append(event)

    for kind, output_file in OUTPUTS.items():
        print(f"{kind}: {len(grouped[kind])} Datensätze vor Deduplizierung")
        render(grouped[kind], kind, output_file)


if __name__ == "__main__":
    main()
