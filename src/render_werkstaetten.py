#!/usr/bin/env python3
"""Render workshop cards separately from date-based event HTML."""
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output" / "candidates_werkstaetten.json"
OUTPUT = ROOT / "output" / "werkstaetten.html"

CSS = r"""
<style>
.Rahmen { border: 4px solid #999; padding: 10px; margin: 12px 0; border-radius: 5px; }
.Foto img { width: 100%; max-width: 400px; border-radius: 10px; }
.einNam { font-size: 20px; font-weight: bold; margin-top: 10px; }
.Öffn, .ZugangBeson { margin-top: 6px; }
.Adresse, .Kontakt { border: 1px solid #999; padding: 5px; margin-top: 5px; width: fit-content; max-width: 100%; border-radius: 4px; background-color: #f9f9f9; overflow-wrap: anywhere; }
.geodat { border: none; overflow: hidden; width: 100%; height: 250px; max-width: 350px; }
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


def split_legacy_contact(value):
    """Best-effort split for older JSON made before contact was a separate key."""
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    if not value:
        return "", ""
    # Previous scraper versions merged address and contact. Cut at a clear
    # website/phone/email marker rather than guessing at a street boundary.
    match = re.search(r"\s+(?=https?://|www\.|Telefon\b|Tel\.?\b|mail\s*:|E-?Mail\s*:|Quelle\s*[·:]|Kalender\s*[·:])", value, re.I)
    if match:
        return value[:match.start()].strip(" ·,;"), value[match.start():].strip(" ·,;")
    if value.lower().startswith(("https://", "http://", "www.")) or value.lower().startswith(("quelle ·", "kalender ·")):
        return "", value
    return value, ""


def links_from_record(item, contact_override=""):
    links = item.get("contact_links") or []
    clean = []
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            url = str(link.get("url") or link.get("href") or "").strip()
            label = str(link.get("label") or url).strip()
            if url.startswith("mailto:") or safe_http_url(url):
                clean.append((label, url))
    contact = str(item.get("contact") or contact_override or "").strip()
    if not clean and contact:
        # Linkify only explicit URLs in the contact text.
        for url in re.findall(r"https?://[^\s<>]+", contact):
            url = url.rstrip(".,;)")
            if safe_http_url(url):
                clean.append((url, url))
    return clean


def render_card(item):
    title = str(item.get("title") or "Werkstatt").strip()
    anchor = re.sub(r"[^A-Za-z0-9_-]+", "-", str(item.get("anchor") or title)).strip("-") or "werkstatt"
    image = safe_http_url(item.get("image") or item.get("image_url"))
    address = str(item.get("address") or "").strip()
    contact = str(item.get("contact") or "").strip()
    if not contact and address:
        address, contact = split_legacy_contact(address)
    # If there's no explicit address but place is available, use it carefully.
    if not address and item.get("place"):
        address, extra_contact = split_legacy_contact(item.get("place"))
        if not contact:
            contact = extra_contact
    opening = str(item.get("opening_hours") or item.get("display_time") or "").strip()
    access = str(item.get("access_notes") or "").strip()
    if not access and item.get("tags"):
        tags = item.get("tags")
        access = ", ".join(str(t) for t in tags if t)
    map_url = safe_http_url(item.get("map_url") or item.get("map"))
    if map_url and "openstreetmap.org/export/embed.html" not in map_url:
        map_url = ""

    parts = [f'<div class="Rahmen" id="{esc(anchor)}">']
    if image:
        parts.append(f'<div class="Foto"><img src="{esc(image)}" alt="{esc(title)}"></div>')
    parts.append(f'<div class="einNam">{esc(title)}</div>')
    if opening:
        parts.append(f'<div class="Öffn">{esc(opening)}</div>')
    if access:
        parts.append(f'<div class="ZugangBeson">{esc(access)}</div>')
    if address:
        parts.append(f'<div class="Adresse">{esc(address)}</div>')
    contact_links = links_from_record(item, contact_override=contact)
    if contact or contact_links:
        rendered = esc(contact)
        for label, url in contact_links:
            if not (url.startswith("mailto:") or safe_http_url(url)):
                continue
            label_html = esc(label)
            link_html = f'<a href="{esc(url)}">{label_html}</a>'
            if label_html and label_html in rendered:
                rendered = rendered.replace(label_html, link_html, 1)
            else:
                rendered = (rendered + "<br/>" if rendered else "") + link_html
        parts.append(f'<div class="Kontakt">{rendered}</div>')
    if map_url:
        parts.append(f'<iframe class="geodat" loading="lazy" src="{esc(map_url)}"></iframe>')
    parts.append('<div class="BewDat"></div>')
    parts.append('</div>')
    return "\n".join(parts)


def main():
    if not DATA.exists():
        raise FileNotFoundError(f"Fehlende Eingabedatei: {DATA}")
    items = json.loads(DATA.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("candidates_werkstaetten.json muss eine JSON-Liste sein.")
    cards = [render_card(item) for item in items if isinstance(item, dict) and item.get("title")]
    if not cards:
        raise RuntimeError("Keine Werkstattkarten in candidates_werkstaetten.json gefunden.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = "<!-- Automatisch aus candidates_werkstaetten.json erzeugt: Fahrradselbsthilfewerkstätten; vor Veröffentlichung prüfen. -->\n"
    doc += "# Fahrradselbsthilfewerkstätten in Berlin\n\n" + CSS + "\n\n---\n\n" + "\n\n---\n\n".join(cards) + "\n"
    OUTPUT.write_text(doc, encoding="utf-8")
    print(f"Werkstätten-HTML: Karten = {len(cards)}")
    print(f"Werkstätten-HTML: Karten mit Bild = {sum(bool(i.get('image') or i.get('image_url')) for i in items if isinstance(i, dict))}")
    print(f"Werkstätten-HTML: Karten mit Karte = {sum(bool(i.get('map_url') or i.get('map')) for i in items if isinstance(i, dict))}")
    print(f"Gespeichert: {OUTPUT}")


if __name__ == "__main__":
    main()
