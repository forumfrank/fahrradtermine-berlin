#!/usr/bin/env python3
"""Render each upcoming workshop opening as a separate, week-sorted event."""
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output" / "termine_werkstaetten.json"
OUTPUT = ROOT / "output" / "werkstaetten.html"

CSS = r"""
<style>
	.Zeit {color: red
}
	.Rubrik {color: green
}
	.Titel {font-weight: bold
}
	.Rahmen {border: 4px solid #999;
}
</style>
"""


def esc(value):
    return html.escape(str(value or "").strip(), quote=True)


def safe_http_url(value):
    value = html.unescape(str(value or "").strip())
    parsed = urlparse(value)
    if parsed.scheme in ("https", "http") and parsed.netloc:
        return value
    return ""


def render_event(item):
    title = str(item.get("title") or "Werkstatt").strip()
    anchor = re.sub(r"[^A-Za-z0-9_-]+", "-", str(item.get("occurrence_id") or item.get("anchor") or title)).strip("-") or "werkstatt"
    image = safe_http_url(item.get("image") or item.get("image_url"))
    date_value = str(item.get("date") or "").strip()
    opening = str(item.get("display_time") or item.get("opening_hours") or "Termin noch nicht automatisch ermittelt").strip()
    start_time = str(item.get("start_time") or "").strip()
    end_time = str(item.get("end_time") or "").strip()
    address = str(item.get("address") or item.get("place") or "").strip()
    access = str(item.get("access_notes") or "").strip()
    url = safe_http_url(item.get("url") or item.get("page"))
    parts = [f'<p>\n<div class="Rahmen" id="{esc(anchor)}">']
    if date_value:
        parts.append(f'<div class="Zeit">{esc(opening)}</div>')
    else:
        parts.append(f'<div class="Zeit">Nicht datiert · {esc(item.get("schedule_status") or "Öffnungszeiten prüfen")}</div>')
    parts.append(f'<div class="Titel">{esc(title)}</div>')
    if address:
        parts.append(f'<div class="Ort">{esc(address)}</div>')
    if access:
        parts.append(f'<div class="Rubrik">{esc(access)}</div>')
    if image:
        parts.append(f'<div class="Plakat"><a href="{esc(url or image)}"><img src="{esc(image)}" alt="Bild: {esc(title)}" style="max-width:100%"></a></div>')
    if url:
        parts.append(f'<div class="Quelle"><a href="{esc(url)}">Werkstatt-Info / Quelle</a></div>')
    parts.append('</div>\n</p>')
    return "\n".join(parts)


def main():
    if not DATA.exists():
        raise FileNotFoundError(f"Fehlende Eingabedatei: {DATA}; zuerst scraper_werkstaetten.py ausführen.")
    items = json.loads(DATA.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("termine_werkstaetten.json muss eine JSON-Liste sein.")
    dated = [i for i in items if isinstance(i, dict) and i.get("date")]
    undated = [i for i in items if isinstance(i, dict) and not i.get("date") and i.get("title")]
    dated.sort(key=lambda i: (i.get("iso_year", 9999), i.get("iso_week", 99), i.get("iso_weekday", 9), i.get("start_time") or "99:99", str(i.get("title") or "").casefold()))
    blocks = []
    current_week = None
    for item in dated:
        key = (item.get("iso_year"), item.get("iso_week"))
        if key != current_week:
            blocks.append(f'<div class="KW">Kalenderwoche {int(key[1]):02d} / {int(key[0])}</div>')
            current_week = key
        blocks.append(render_event(item))
    if undated:
        blocks.append('<h2>Nicht automatisch terminierbare Werkstätten</h2>')
        blocks.extend(render_event(item) for item in undated)
    if not blocks:
        raise RuntimeError("Keine Werkstatttermine zum Rendern gefunden.")
    doc = "<!-- Automatisch erzeugt; Termine aus den Öffnungsangaben abgeleitet. Angaben vor Veröffentlichung prüfen. -->\n"
    doc += "# Fahrrad-Selbsthilfewerkstätten – Öffnungstermine\n\n" + CSS + "\n\n" + "\n\n".join(blocks) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(doc, encoding="utf-8")
    print(f"Werkstätten-Termine HTML: datierte Termine = {len(dated)}; ungeklärte Einträge = {len(undated)}")
    print(f"Gespeichert: {OUTPUT}")


if __name__ == "__main__":
    main()
