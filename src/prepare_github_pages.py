#!/usr/bin/env python3
"""Turn the generated HedgeDoc-style calendar fragments into a GitHub Pages site.

Reads output/*.html, wraps each fragment in a complete HTML document, converts
Markdown-style '# heading' lines to HTML headings, and writes a small homepage
plus the calendar pages into _site/.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
SITE_DIR = ROOT / "_site"

KNOWN_TITLES = {
    "fahrradtermine": "Fahrradtermine in Berlin",
    "fahrradtermine-berlin": "Fahrradtermine in Berlin",
    "werkstaetten": "Fahrrad-Selbsthilfewerkstätten",
    "werkstaetten-termine": "Fahrrad-Selbsthilfewerkstätten",
    "versammlungsbehoerde": "Anmeldungen der Versammlungsbehörde",
    "adfc": "ADFC-Termine",
}

BASE_CSS = r"""
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f5f6f7; color: #202124; font-family: Arial, Helvetica, sans-serif; line-height: 1.5; }
.site-nav { padding: 12px max(16px, calc((100% - 900px) / 2)); background: #fff; border-bottom: 1px solid #ddd; }
.site-nav a { color: #1756a9; text-decoration: none; }
main { max-width: 900px; margin: 20px auto; padding: 20px; background: #fff; }
h1 { margin: 0 0 1em; font-size: 1.7rem; line-height: 1.25; }
h2 { margin: 1.8em 0 .7em; padding-bottom: .25em; border-bottom: 1px solid #ddd; font-size: 1.2rem; }
img { max-width: 100%; height: auto; }
iframe { max-width: 100%; }
a { overflow-wrap: anywhere; }
.Rahmen { border: 0 !important; }
.index-list { display: grid; gap: 12px; padding: 0; list-style: none; }
.index-list a { display: block; padding: 16px; border: 1px solid #d7dce1; border-radius: 8px; background: #fff; color: #1756a9; text-decoration: none; }
.index-list a:hover { border-color: #1756a9; }
.small-note { color: #5f6368; font-size: .9rem; }
@media (max-width: 640px) { main { margin: 0; padding: 14px; } h1 { font-size: 1.45rem; } }
"""


def heading_text(source: str) -> str:
    match = re.search(r"(?m)^#{1,6}\s+(.+?)\s*$", source)
    if match:
        return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", source)
    if match:
        return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
    return ""


def page_title(path: Path, source: str) -> str:
    key = path.stem.casefold()
    if key in KNOWN_TITLES:
        return KNOWN_TITLES[key]
    title = heading_text(source)
    if title and not title.casefold().startswith("kw "):
        return title
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def make_page(source: str, title: str) -> str:
    # Files produced for HedgeDoc can contain CSS and Markdown-style headings.
    if re.search(r"(?is)<!doctype\s+html|<html\b", source):
        # Already a complete page; leave the content intact.
        return source

    styles = re.findall(r"(?is)<style\b[^>]*>.*?</style>", source)
    body = re.sub(r"(?is)<style\b[^>]*>.*?</style>", "", source)

    heading_count = 0
    def replace_heading(match: re.Match[str]) -> str:
        nonlocal heading_count
        heading_count += 1
        level = 1 if heading_count == 1 else 2
        text = match.group(2).strip()
        return f"<h{level}>{text}</h{level}>"

    body = re.sub(r"(?m)^\s*(#{1,6})\s+(.+?)\s*$", replace_heading, body)
    style_markup = "\n".join(styles)
    return f'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{BASE_CSS}</style>
{style_markup}
</head>
<body>
<nav class="site-nav"><a href="index.html">← Kalenderübersicht</a></nav>
<main>
{body}
</main>
</body>
</html>
'''


def make_index(entries: list[tuple[str, str]]) -> str:
    updated = datetime.now().strftime("%d.%m.%Y, %H:%M")
    links = "\n".join(
        f'<li><a href="{html.escape(filename, quote=True)}">{html.escape(title)}</a></li>'
        for filename, title in entries
    )
    return f'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fahrradtermine in Berlin</title>
<style>{BASE_CSS}</style>
</head>
<body>
<main>
<h1>Fahrradtermine in Berlin</h1>
<p>Automatisch erstellte Terminlisten.</p>
<ul class="index-list">{links}</ul>
<p class="small-note">Zuletzt veröffentlicht: {html.escape(updated)} Uhrzeiten nach Berliner Ortszeit, soweit die Quelle sie angibt.</p>
</main>
</body>
</html>
'''


def main() -> None:
    if not OUTPUT_DIR.is_dir():
        raise SystemExit(f"Fehler: Ausgabeverzeichnis fehlt: {OUTPUT_DIR}")
    inputs = sorted(p for p in OUTPUT_DIR.glob("*.html") if p.name.casefold() != "index.html")
    if not inputs:
        raise SystemExit(f"Fehler: Keine HTML-Kalender in {OUTPUT_DIR}; zuerst die Scraper und Renderer ausführen.")

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    # Clear old HTML pages so a calendar removed from output is not left online.
    for old_page in SITE_DIR.glob("*.html"):
        old_page.unlink()

    entries: list[tuple[str, str]] = []
    for source_path in inputs:
        source = source_path.read_text(encoding="utf-8", errors="replace")
        title = page_title(source_path, source)
        destination = SITE_DIR / source_path.name
        destination.write_text(make_page(source, title), encoding="utf-8")
        entries.append((destination.name, title))
        print(f"GitHub Pages: {source_path.name} -> _site/{destination.name} ({title})")

    (SITE_DIR / "index.html").write_text(make_index(entries), encoding="utf-8")
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Startseite: _site/index.html; veröffentliche {len(entries)} Kalenderseite(n).")


if __name__ == "__main__":
    main()
