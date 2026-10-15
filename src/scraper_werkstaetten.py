#!/usr/bin/env python3
"""Read the public HedgeDoc bicycle self-help workshop list."""
import html
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
NOTE_PAGE = "https://doc.adminforge.de/Fahradselbsthilfewerkst%C3%A4tten-Berlin"
NOTE_DOWNLOAD = NOTE_PAGE + "/download"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FahrradtermineBerlinBot/0.7; event research)",
    "Accept": "text/markdown, text/plain, text/html, */*",
}

FIELDS = {
    "title": {"titel", "title", "werkstatt", "name", "werkstattname", "einnam"},
    "image": {"bild", "plakat", "image", "foto", "bildurl"},
    "opening": {"offn", "oeffn", "offnung", "oeffnung", "offnungszeiten", "oeffnungszeiten", "zeiten"},
    "access": {"zugangsbesonderheiten", "zugang", "zugangbeson", "besonderheiten", "barrierefreiheit"},
    # AdrURLKont is the former combined field; Adresse/Kontakt are the newer split fields.
    "address": {"adrurlkont", "adrurlkontakt", "adresse", "ort"},
    "contact": {"kontakt", "website", "url", "quelle"},
}
LABELS = {
    "title": r"Titel|Title|Werkstatt(?:sname)?|Name",
    "image": r"Bild|Plakat|Image|Foto",
    "opening": r"Öffn(?:zeiten)?|Oeffn(?:zeiten)?|Öffnungszeiten|Oeffnungszeiten|Zeiten",
    "access": r"Zugangsbesonderheiten|Zugang|Besonderheiten|Barrierefreiheit",
    "address": r"AdrURLKont|AdrURLKontakt|Adresse|Ort",
    "contact": r"Kontakt|Website|URL|Quelle",
}


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def field_key(value):
    value = norm(value)
    for key, variants in FIELDS.items():
        if value in variants:
            return key
    return ""


def text_of(value):
    text = str(value or "")
    # Preserve address/contact destinations when they are written as Markdown links.
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"<((?:https?://|mailto:)[^>]+)>", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Only parse as HTML if there are actual tags; this also avoids a harmless
    # BeautifulSoup warning when the text happens to be a bare URL.
    if re.search(r"<[A-Za-z!/][^>]*>", text):
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\*\*(.*?)\*\*|__(.*?)__", lambda m: m.group(1) or m.group(2), text)
    return text


def title_text(value):
    # A linked title should stay just the visible title, without the destination URL.
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", str(value or ""))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text_of(text)


def slugify(value):
    # Stable ASCII IDs make it simple to add matching id attributes to the source note.
    value = text_of(value).strip().lower()
    value = (value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                 .replace("ß", "ss"))
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "werkstatt"


def get_img(value, node=None):
    if node is not None and hasattr(node, "find"):
        img = node.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                return urljoin(NOTE_PAGE + "/", src.strip())
        if getattr(node, "name", None) == "a":
            href = node.get("href", "")
            if re.search(r"\.(?:png|jpe?g|gif|webp|svg)(?:\?.*)?$", href, re.I):
                return urljoin(NOTE_PAGE + "/", href)
    raw = str(value or "")
    m = re.search(r"!\[[^\]]*\]\(([^)]+)\)", raw)
    if m:
        return urljoin(NOTE_PAGE + "/", m.group(1).strip())
    soup = BeautifulSoup(raw, "html.parser")
    img = soup.find("img")
    if img:
        src = img.get("src") or img.get("data-src") or ""
        if src:
            return urljoin(NOTE_PAGE + "/", src.strip())
    m = re.search(r"https?://[^\s)>]+\.(?:png|jpe?g|gif|webp|svg)(?:\?[^\s)]*)?", raw, re.I)
    return m.group(0) if m else ""


def anchor_for(node, title):
    if node is not None:
        if node.get("id"):
            return str(node.get("id"))
        for child in node.find_all(True):
            child_id = child.get("id")
            if child_id and not field_key(child_id):
                if child.name in ("h1", "h2", "h3", "h4", "h5", "h6") or child.name == "a":
                    return str(child_id)
            if child.name == "a" and (child.get("name") or child.get("id")):
                return str(child.get("name") or child.get("id"))
            href = child.get("href", "")
            if href.startswith(NOTE_PAGE) and "#" in href:
                return href.rsplit("#", 1)[1]
    return slugify(title)


def field_text(node, keep_links=False):
    """Extract readable text; for the address/contact field keep link destinations too."""
    if node is None:
        return ""
    value = text_of(node.get_text(" ", strip=True))
    if not keep_links:
        return value
    extras = []
    for link in node.find_all("a"):
        href = (link.get("href") or "").strip()
        label = text_of(link.get_text(" ", strip=True))
        if not href or href.startswith(("#", "javascript:")):
            continue
        readable_href = href[7:] if href.lower().startswith("mailto:") else href
        if readable_href and readable_href not in value and readable_href not in extras:
            # Include URL/contact target even when the visible link text is only "Quelle".
            extras.append(readable_href)
    if extras:
        value = (value + " · " if value else "") + " · ".join(extras)
    return value


def has_explicit_anchor(node):
    """True only when the source card actually has a DOM anchor we can link to."""
    if node is None:
        return False
    if node.get("id"):
        return True
    for child in node.find_all(True):
        if child.get("id") or child.get("name"):
            return True
        href = (child.get("href") or "").strip()
        if href.startswith(NOTE_PAGE) and "#" in href:
            return True
    return False


def combine_address_contact(address, contact):
    """Support both the old combined AdrURLKont field and split fields."""
    address = text_of(address)
    contact = text_of(contact)
    if not address:
        return contact
    if not contact or contact.casefold() in address.casefold():
        return address
    return f"{address} · {contact}"


def event_for(title, image, opening, access, address, anchor, description=""):
    title, opening, address = title_text(title), text_of(opening), text_of(address)
    access = text_of(access)
    if not title or not address:
        return None
    anchor = anchor or slugify(title)
    return {
        "source": "Fahrradselbsthilfewerkstätten Berlin",
        "page": NOTE_PAGE + "?both",
        "title": title,
        "url": NOTE_PAGE + "?both#" + quote(anchor, safe="-_.~"),
        "date": "",
        "start_time": None,
        "display_time": opening,
        "opening_hours": opening,
        "end_time": None,
        "place": address,
        "address": address,
        "description": text_of(description),
        "tags": [access] if access else [],
        "access_notes": access,
        "image": image or "",
        "status": "needs_review",
        "anchor": anchor,
    }


def parse_class_cards(soup):
    found = []
    classes = [n for n in soup.find_all(True) if n.get("class") or n.get("id")]
    eligible = []
    for node in classes:
        kinds = set()
        for desc in [node] + node.find_all(True):
            labels = list(desc.get("class") or []) + ([desc.get("id")] if desc.get("id") else [])
            kinds.update(field_key(label) for label in labels if label)
        if {"title", "opening", "address"}.issubset(kinds):
            eligible.append(node)
    eligible_set = set(eligible)
    for node in eligible:
        if any(child in eligible_set for child in node.find_all(True)):
            continue
        vals = {}
        for kind in FIELDS:
            for desc in [node] + node.find_all(True):
                labels = list(desc.get("class") or []) + ([desc.get("id")] if desc.get("id") else [])
                if any(field_key(label) == kind for label in labels if label):
                    vals[kind] = get_img("", desc) if kind == "image" else field_text(desc, keep_links=(kind in ("address", "contact")))
                    if vals[kind]:
                        break
        if not vals.get("title"):
            h = node.find(["h1", "h2", "h3", "h4"])
            vals["title"] = text_of(h.get_text(" ", strip=True)) if h else ""
        anchor = anchor_for(node, vals.get("title", ""))
        combined_address = combine_address_contact(vals.get("address"), vals.get("contact"))
        ev = event_for(
            vals.get("title"), vals.get("image") or get_img("", node),
            vals.get("opening"), vals.get("access"), combined_address,
            anchor,
        )
        if ev:
            ev["anchor_verified"] = has_explicit_anchor(node)
            found.append(ev)
    return found


def parse_html_tables(soup):
    found = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [field_key(text_of(c.get_text(" ", strip=True))) for c in rows[0].find_all(["th", "td"], recursive=False)]
        if not {"title", "opening", "address"}.issubset(set(headers)):
            continue
        for row in rows[1:]:
            cells = row.find_all(["td", "th"], recursive=False)
            vals = {headers[i]: cells[i] for i in range(min(len(headers), len(cells))) if headers[i]}
            def val(key):
                if key not in vals:
                    return ""
                if key in ("address", "contact"):
                    return field_text(vals[key], keep_links=True)
                return text_of(vals[key].get_text(" ", strip=True))
            title = val("title")
            image = get_img("", vals.get("image")) if vals.get("image") else ""
            address = combine_address_contact(val("address"), val("contact"))
            ev = event_for(title, image, val("opening"), val("access"), address, anchor_for(row, title))
            if ev:
                found.append(ev)
    return found


def split_pipe(line):
    line = line.strip().strip("|")
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line)]


def parse_markdown_tables(raw):
    lines, found, i = raw.splitlines(), [], 0
    while i < len(lines) - 1:
        if "|" not in lines[i] or "|" not in lines[i + 1]:
            i += 1
            continue
        headers, sep = split_pipe(lines[i]), split_pipe(lines[i+1])
        if not sep or not all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in sep):
            i += 1
            continue
        idx = {field_key(text_of(h)): j for j, h in enumerate(headers) if field_key(text_of(h))}
        if not {"title", "opening", "address"}.issubset(idx):
            i += 2
            continue
        i += 2
        while i < len(lines) and "|" in lines[i] and lines[i].strip():
            cells = split_pipe(lines[i])
            vals = {key: cells[pos] if pos < len(cells) else "" for key, pos in idx.items()}
            title = title_text(vals.get("title"))
            image = get_img(vals.get("image", ""))
            address = combine_address_contact(vals.get("address"), vals.get("contact"))
            ev = event_for(title, image, vals.get("opening"), vals.get("access"), address, slugify(title))
            if ev:
                found.append(ev)
            i += 1
    return found


def parse_heading_sections(raw):
    lines, sections, current = raw.splitlines(), [], None
    for line in lines:
        h = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if h:
            if current:
                sections.append(current)
            current = {"title": text_of(h.group(2)), "lines": [line]}
        elif current is not None:
            current["lines"].append(line)
    if current:
        sections.append(current)
    found = []
    for sec in sections:
        raw_section = "\n".join(sec["lines"])
        vals = {}
        for kind, label in LABELS.items():
            m = re.search(rf"(?im)^\s*(?:[-*+]\s*)?(?:\*\*)?\s*(?:{label})\s*(?:\*\*)?\s*[:：|]\s*(.*)$", raw_section)
            if m:
                vals[kind] = m.group(1).strip()
        if not vals.get("opening") or not vals.get("address"):
            continue
        title = vals.get("title") or sec["title"]
        address = combine_address_contact(vals.get("address"), vals.get("contact"))
        ev = event_for(title, get_img(vals.get("image", "")) or get_img(raw_section), vals["opening"], vals.get("access", ""), address, slugify(sec["title"]), raw_section)
        if ev:
            found.append(ev)
    return found


def dedupe(events):
    out, seen = [], set()
    for ev in events:
        key = (ev["title"].casefold(), ev["place"].casefold(), ev["display_time"].casefold())
        if key not in seen:
            seen.add(key)
            out.append(ev)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    response = requests.get(NOTE_DOWNLOAD, headers=HEADERS, timeout=40)
    response.raise_for_status()
    raw = response.content.decode(response.encoding or "utf-8", errors="replace").lstrip("\ufeff")
    if not raw.strip():
        raise RuntimeError("HedgeDoc-Download war leer.")
    soup = BeautifulSoup(raw, "html.parser")
    found = parse_class_cards(soup)
    mode = "HTML-Karten"
    if not found:
        found = parse_html_tables(soup)
        mode = "HTML-Tabelle"
    if not found:
        found = parse_markdown_tables(raw)
        mode = "Markdown-Tabelle"
    if not found:
        found = parse_heading_sections(raw)
        mode = "Markdown-Abschnitte"
    found = dedupe(found)
    if not found:
        preview = re.sub(r"\s+", " ", raw[:600])
        raise RuntimeError("Keine Werkstatt-Einträge erkannt; bitte Parserformat anpassen. Anfang des Downloads: " + preview)
    output = OUT / "candidates_werkstaetten.json"
    output.write_text(json.dumps(found, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Werkstätten: Parserformat = {mode}")
    print(f"Werkstätten: Einträge erkannt = {len(found)}")
    print(f"Werkstätten: Einträge mit Bild = {sum(bool(e['image']) for e in found)}")
    print(f"Werkstätten: Einträge mit Zeitfeld = {sum(bool(e['display_time']) for e in found)}")
    print(f"Werkstätten: mit vorhandener Sprungmarke = {sum(bool(e.get('anchor_verified')) for e in found)}")
    print(f"Werkstätten: Sprungmarke muss ggf. in der Quelle ergänzt werden = {sum(not e.get('anchor_verified') for e in found)}")
    print(f"Gespeichert: {output}")


if __name__ == "__main__":
    main()
