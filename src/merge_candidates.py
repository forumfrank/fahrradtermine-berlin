#!/usr/bin/env python3
"""Combine the separate source files for the shared HTML converter."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
INPUTS = [
    OUT / "candidates_gancio.json",
    OUT / "candidates_velodemo.json",
    OUT / "candidates_adfc.json",
]


def main():
    combined = []
    for path in INPUTS:
        if not path.exists():
            raise SystemExit(f"Quelldatei fehlt: {path}. Bitte vorher beide Scraper ausführen.")
        items = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise SystemExit(f"Die Datei enthält keine JSON-Liste: {path}")
        print(f"Zusammenführen: {path.name}: {len(items)} Datensätze")
        combined.extend(item for item in items if isinstance(item, dict))

    combined.sort(key=lambda item: (item.get("start_time") or "", item.get("source") or ""))
    output = OUT / "candidates.json"
    output.write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Zusammengeführt: {len(combined)} Datensätze -> {output}")


if __name__ == "__main__":
    main()
