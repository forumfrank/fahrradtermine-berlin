#!/usr/bin/env python3
"""Convert output/candidates.json to HedgeDoc-ready HTML."""
import html
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output" / "candidates.json"
OUTPUT = ROOT / "output" / "fahrradtermine.html"
BERLIN = ZoneInfo("Europe/Berlin")


def esc(value):
    return html.escape(str(value or "").strip(), quote=True)


def slug_from_url(url):
    path = url.split("?", 1)[0].rstrip("/")
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


def display_time(event, dt):
    if not dt:
        return event.get("date", "")
    weekday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][dt.weekday()]
    current_year = datetime.now(BERLIN).year
    date_part = f"{dt.day}.{dt.month}." if dt.year == current_year else f"{dt.day}.{dt.month}.{dt.year}"
    time_part = f"{dt.hour}h" if dt.minute == 0 else f"{dt.hour}:{dt.minute:02d}h"
    return f"{weekday}, {date_part} {time_part}"


def main():
    if not INPUT.exists():
        raise SystemExit(f"Datei nicht gefunden: {INPUT}")
    events = json.loads(INPUT.read_text(encoding="utf-8"))
    if not isinstance(events, list):
        raise SystemExit("candidates.json muss eine JSON-Liste enthalten.")

    prepared = []
    for event in events:
        dt = event_datetime(event)
        prepared.append((dt, event))
    prepared.sort(key=lambda pair: (pair[0] is None, pair[0] or datetime.max.replace(tzinfo=BERLIN)))

    blocks = [
        "<!-- Automatisch aus output/candidates.json erzeugt; vor Veröffentlichung prüfen. -->",
        ""
    ]

    current_week = None
    
    for dt, event in prepared:

                if dt:
            iso = dt.isocalendar()
            week = (iso.year, iso.week)

            if week != current_week:
                current_week = week

                monday = dt.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                from datetime import timedelta
                monday = monday - timedelta(days=dt.weekday())
                sunday = monday + timedelta(days=6)

                def short_date(d):
                    return f"{d.day}.{d.month}."

                blocks.append(
                    f"# KW {iso.week} / "
                    f"{short_date(monday)} - "
                    f"{sunday.day}.{sunday.month}."
                )
                blocks.append("")
        
        title = esc(event.get("title"))
        url = esc(event.get("url"))
        
        image_url = esc(event.get("image"))
        
        place = esc(event.get("place") or event.get("address"))

        tags = event.get("tags") or []
        if isinstance(tags, list):
            rubrik = esc(" ".join(str(tag).strip() for tag in tags if str(tag).strip()))
        else:
            rubrik = esc(tags)
        
        time_text = esc(display_time(event, dt))
        slug = esc(slug_from_url(event.get("url", "")))
        note = ""
        # Gancio occasionally uses midnight as a placeholder for events with an unknown time.
        if dt and dt.hour == 0 and dt.minute == 0 and "purple ride" in (event.get("title") or "").lower():
            note = "Uhrzeit im Feed unklar; bitte prüfen."

        blocks.extend([
            f"<!-- Gancio: {slug} -->",
            "<p>",
            '<div class="Rahmen">',
            
            f'<div class="Plakat"><a href="{url}"><img src="{image_url}" alt="{title}" style="max-width:100%"></a></div>' if image_url else '<div class="Plakat"></div>',
            
            f'<div class="Zeit">{time_text}</div>',
           

            f'<div class="Rubrik">{rubrik}</div>',
            
            f'<div class="Titel">{title}</div>',
            f'<div class="Ort">{place}</div>',
            f'<div class="Bemerkung">{esc(note)}</div>',
            f'<div class="Quelle"><a href="{url}">Quelle</a></div>',
            "</div></p>",

            "<hr>",
            
            ""
        ])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")
    print(f"HTML erzeugt: {OUTPUT} ({len(prepared)} Termine)")


if __name__ == "__main__":
    main()
