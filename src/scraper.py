from pathlib import Path
import zipfile, textwrap

base = Path("/mnt/data/fahrradtermine_automation")
(base / "src").mkdir(parents=True, exist_ok=True)
(base / ".github" / "workflows").mkdir(parents=True, exist_ok=True)

converter = r'''#!/usr/bin/env python3
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
    # Prefer the display string already created by the scraper, if present.
    existing = (event.get("display_time") or "").strip()
    if existing:
        return existing
    if not dt:
        return event.get("date", "")
    weekday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][dt.weekday()]
    if dt.year == datetime.now(BERLIN).year:
        date_part = f"{dt.day}.{dt.month}."
    else:
        date_part = f"{dt.day}.{dt.month}.{dt.year}"
    time_part = f"{dt.hour}:{dt.minute:02d}h"
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
    for dt, event in prepared:
        title = esc(event.get("title"))
        url = esc(event.get("url"))
        place = esc(event.get("place") or event.get("address"))
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
            '<div class="Plakat"></div>',
            f'<div class="Zeit">{time_text}</div>',
            '<div class="Rubrik"></div>',
            f'<div class="Titel">{title}</div>',
            f'<div class="Ort">{place}</div>',
            f'<div class="Bemerkung">{esc(note)}</div>',
            f'<div class="Quelle"><a href="{url}">Quelle</a></div>',
            "</div></p>",
            ""
        ])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")
    print(f"HTML erzeugt: {OUTPUT} ({len(prepared)} Termine)")


if __name__ == "__main__":
    main()
'''

workflow = r'''name: Fahrradtermine Berlin scraping

on:
  workflow_dispatch:
  schedule:
    - cron: "37 5 * * *"

permissions:
  contents: read

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - name: Repository auschecken
        uses: actions/checkout@v4

      - name: Python einrichten
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Abhängigkeiten installieren
        run: pip install -r requirements.txt

      - name: Termine scrapen
        run: python src/scraper.py

      - name: HedgeDoc-HTML erzeugen
        run: python src/to_html.py

      - name: JSON und HTML als Artefakte bereitstellen
        uses: actions/upload-artifact@v4
        with:
          name: fahrradtermine-json-und-html
          path: |
            output/candidates.json
            output/fahrradtermine.html
          if-no-files-found: error
          retention-days: 14
'''

(base / "src" / "to_html.py").write_text(converter, encoding="utf-8")
(base / ".github" / "workflows" / "scrape.yml").write_text(workflow, encoding="utf-8")

readme = """# Integration: Scraping erzeugt zusätzlich HedgeDoc-HTML

## Dateien im Paket
- `src/to_html.py`: wandelt `output/candidates.json` in `output/fahrradtermine.html` um.
- `.github/workflows/scrape.yml`: führt nach dem Scraping den Konverter aus und stellt JSON + HTML als Actions-Artefakt bereit.

## Einbau in das vorhandene GitHub-Repository
1. Lade `src/to_html.py` in deinem Repository in den Ordner `src` hoch.
2. Öffne `.github/workflows/scrape.yml` und ersetze den bisherigen Inhalt durch die Datei aus diesem Paket.
3. Speichere die Änderungen (Commit).
4. Öffne **Actions** → **Fahrradtermine Berlin scraping** → **Run workflow**.
5. Öffne den erfolgreichen Lauf und lade unter **Artifacts** `fahrradtermine-json-und-html` herunter.
6. Darin liegt `output/fahrradtermine.html`, die du prüfen und anschließend in HedgeDoc kopieren kannst.

Wichtig:
- Der Workflow veröffentlicht nichts automatisch in HedgeDoc.
- Der Cron-Zeitplan `37 5 * * *` läuft in GitHub Actions in UTC (also 07:37 Berliner Sommerzeit bzw. 06:37 Winterzeit). Das entspricht dem bisherigen Zeitplan, ist aber nicht ganzjährig dieselbe Berliner Uhrzeit.
- Dieses Paket ersetzt nicht `src/scraper.py`, `sources.json` oder `requirements.txt`.
"""
(base / "README.txt").write_text(readme, encoding="utf-8")

zip_path = Path("/mnt/data/fahrradtermine_html_automation.zip")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for p in base.rglob("*"):
        if p.is_file():
            z.write(p, p.relative_to(base))

print(f"Erstellt: {zip_path}")
