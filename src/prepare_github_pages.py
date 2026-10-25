#!/usr/bin/env python3
"""Prepare the existing event calendars as an installable Android-friendly PWA."""
from __future__ import annotations
import html, re, json, struct, zlib, shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
SITE_DIR = ROOT / "_site"
ASSET_DIR = ROOT / "pwa-assets"
CALENDARS = [
    ("fahrradtermine.html", "Fahrradtermine", "Fahrradveranstaltungen aus dem Berliner Kalender", "F", "#c62828"),
    ("velodemo.html", "VELODEMO", "Raddemonstrationen und gemeinsame Ausfahrten", "V", "#a85b18"),
    ("adfc.html", "ADFC", "Veranstaltungen des ADFC", "A", "#247447"),
    ("werkstaetten.html", "Selbsthilfewerkstätten", "Werkstätten und ihre Öffnungstermine", "W", "#2463a6"),
    ("versammlungsbehoerde.html", "Versammlungsbehörde", "Passende Versammlungen und Aufzüge", "V", "#7653a5"),
]
BASE_CSS = r"""
:root{color-scheme:light;--red:#c62828;--ink:#202124;--muted:#62666b;--line:#e0e3e7;--paper:#f4f6f8;--card:#fff}
*{box-sizing:border-box}html{background:var(--paper)}body{margin:0;background:var(--paper);color:var(--ink);font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.5}
a{color:#145da0;overflow-wrap:anywhere}header.appbar{background:#fff;border-bottom:1px solid var(--line);padding:14px max(16px,calc((100% - 850px)/2));display:flex;align-items:center;gap:12px}.app-icon{width:42px;height:42px;border-radius:12px;flex:none}header strong{font-size:1.05rem}main{max-width:850px;margin:0 auto;padding:20px 16px 40px}h1{font-size:1.65rem;line-height:1.2;margin:8px 0}h2{font-size:1.2rem;margin:1.8em 0 .6em;padding-bottom:.25em;border-bottom:1px solid var(--line)}.intro{color:var(--muted);margin:.35em 0 1.2em}.calendar-list{display:grid;grid-template-columns:1fr;gap:12px;margin:18px 0;padding:0;list-style:none}.calendar-card{display:flex;align-items:center;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;text-decoration:none;color:var(--ink);box-shadow:0 1px 2px #00000008}.calendar-card:active{transform:scale(.99)}.calendar-dot{width:44px;height:44px;display:grid;place-items:center;border-radius:12px;color:#fff;font-weight:800;font-size:1.15rem;flex:none}.calendar-copy{flex:1;min-width:0}.calendar-copy strong{display:block;font-size:1.05rem}.calendar-copy span{display:block;color:var(--muted);font-size:.9rem;margin-top:2px}.chevron{font-size:1.5rem;color:#777}.small-note{color:var(--muted);font-size:.85rem;margin-top:22px}.backlink{display:inline-block;text-decoration:none;font-weight:600;margin-bottom:14px}.Rahmen{border:0!important}img,iframe{max-width:100%}.Zeit,.SH-Zeit{color:red!important}.Plakat img{height:auto}.install-tip{background:#fff4e5;border:1px solid #f0d8b4;border-radius:12px;padding:12px 14px;font-size:.92rem;margin-top:18px}
@media(min-width:650px){.calendar-list{grid-template-columns:1fr 1fr}main{padding-top:28px}h1{font-size:2rem}}
"""

def wrap_calendar(source: str, title: str) -> str:
    styles = re.findall(r"(?is)<style\b[^>]*>.*?</style>", source)
    body = re.sub(r"(?is)<style\b[^>]*>.*?</style>", "", source)
    count = 0
    def heading(m):
        nonlocal count
        count += 1
        level = 1 if count == 1 else 2
        return f"<h{level}>{m.group(2).strip()}</h{level}>"
    body = re.sub(r"(?m)^\s*(#{1,6})\s+(.+?)\s*$", heading, body)
    return ('<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="theme-color" content="#c62828"><link rel="manifest" href="manifest.webmanifest">'
        '<link rel="icon" href="icons/icon-192.png"><title>' + html.escape(title) + '</title>'
        '<style>' + BASE_CSS + '</style>' + '\n'.join(styles) + '</head><body>'
        '<header class="appbar"><a href="index.html" aria-label="Zur Startseite">'
        '<img class="app-icon" src="icons/icon-192.png" alt=""></a><strong>' + html.escape(title) +
        '</strong></header><main><a class="backlink" href="index.html">← Alle Kalender</a>' + body +
        '</main><script>if("serviceWorker" in navigator){window.addEventListener("load",()=>navigator.serviceWorker.register("service-worker.js").catch(()=>{}));}</script></body></html>')

def make_index(available: set[str]) -> str:
    cards = []
    for filename, title, desc, letter, color in CALENDARS:
        if filename not in available:
            continue
        cards.append('<li><a class="calendar-card" href="' + filename + '"><span class="calendar-dot" style="background:' + color + '">' + letter + '</span><span class="calendar-copy"><strong>' + html.escape(title) + '</strong><span>' + html.escape(desc) + '</span></span><span class="chevron" aria-hidden="true">›</span></a></li>')
    updated = datetime.now().strftime('%d.%m.%Y, %H:%M')
    return ('<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="theme-color" content="#c62828"><meta name="description" content="Berliner Fahrradtermine, Demos und Selbsthilfewerkstätten.">'
        '<link rel="manifest" href="manifest.webmanifest"><link rel="icon" href="icons/icon-192.png">'
        '<link rel="apple-touch-icon" href="icons/icon-192.png"><title>Fahrradtermine Berlin</title><style>' + BASE_CSS +
        '</style></head><body><header class="appbar"><img class="app-icon" src="icons/icon-192.png" alt=""><strong>Fahrradtermine Berlin</strong></header>'
        '<main><h1>Dein Kalender für Berlin</h1><p class="intro">Wähle einen der fünf Kalender aus.</p><ul class="calendar-list">' + ''.join(cards) +
        '</ul><div class="install-tip"><strong>Auf dem Handy installieren</strong><br>In Chrome oben rechts auf ⋮ tippen und „App installieren“ oder „Zum Startbildschirm hinzufügen“ wählen.</div>'
        '<p class="small-note">Zuletzt erstellt: ' + updated + '. Die Termine werden beim nächsten erfolgreichen GitHub-Actions-Lauf aktualisiert.</p></main>'
        '<script>if("serviceWorker" in navigator){window.addEventListener("load",()=>navigator.serviceWorker.register("service-worker.js").catch(()=>{}));}</script></body></html>')

def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)

def make_icon(size: int, path: Path) -> None:
    rows = []
    scale = size / 100
    def segment_distance(px, py, x1, y1, x2, y2):
        dx, dy = x2-x1, y2-y1
        if dx == dy == 0: return ((px-x1)**2 + (py-y1)**2)**.5
        t = max(0, min(1, ((px-x1)*dx+(py-y1)*dy)/(dx*dx+dy*dy)))
        return ((px-(x1+t*dx))**2 + (py-(y1+t*dy))**2)**.5
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            inset = size * .12
            inside = (inset <= x < size-inset and inset <= y < size-inset)
            color = (198,40,40,255) if inside else (0,0,0,0)
            wheels = ((25*scale,66*scale),(75*scale,66*scale))
            if any(abs(((x-cx)**2+(y-cy)**2)**.5-14*scale) <= 2.5*scale for cx,cy in wheels): color=(255,255,255,255)
            segs = [((25,66),(44,66)),((44,66),(34,43)),((34,43),(59,43)),((59,43),(75,66)),((75,66),(44,66)),((59,43),(67,34)),((64,34),(75,34))]
            if any(segment_distance(x,y,a[0]*scale,a[1]*scale,b[0]*scale,b[1]*scale) <= 2.8*scale for a,b in segs): color=(255,255,255,255)
            row.extend(color)
        rows.append(bytes(row))
    raw = b''.join(rows)
    data = b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('!2I5B', size,size,8,6,0,0,0)) + png_chunk(b'IDAT', zlib.compress(raw,9)) + png_chunk(b'IEND',b'')
    path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)

def main() -> None:
    if not OUTPUT_DIR.is_dir(): raise SystemExit(f"Ausgabeverzeichnis fehlt: {OUTPUT_DIR}")
    SITE_DIR.mkdir(parents=True,exist_ok=True)
    for p in SITE_DIR.iterdir():
        if p.is_file(): p.unlink()
        elif p.is_dir(): shutil.rmtree(p)
    available: set[str] = set()
    for filename, title, *_ in CALENDARS:
        src = OUTPUT_DIR / filename
        if not src.exists():
            print(f"Hinweis: {src.name} fehlt; Kalender wird auf der Startseite ausgelassen.")
            continue
        (SITE_DIR / filename).write_text(wrap_calendar(src.read_text(encoding='utf-8',errors='replace'), title), encoding='utf-8')
        available.add(filename)
        print(f"PWA-Kalender: {src.name} -> _site/{filename}")
    if not available: raise SystemExit("Keine der erwarteten Kalender-HTML-Dateien gefunden.")
    (SITE_DIR/'index.html').write_text(make_index(available),encoding='utf-8')
    manifest = {"id":"./","name":"Fahrradtermine Berlin","short_name":"Radtermine","description":"Fahrradtermine, Demos, ADFC und Selbsthilfewerkstätten in Berlin.","lang":"de-DE","start_url":"./index.html","scope":"./","display":"standalone","background_color":"#f4f6f8","theme_color":"#c62828","icons":[{"src":"icons/icon-192.png","sizes":"192x192","type":"image/png","purpose":"any"},{"src":"icons/icon-512.png","sizes":"512x512","type":"image/png","purpose":"any"}]}
    (SITE_DIR/'manifest.webmanifest').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (SITE_DIR/'service-worker.js').write_text('''const CACHE_NAME="fahrradtermine-shell-v1";
const SHELL=["./","./index.html","./manifest.webmanifest","./icons/icon-192.png","./icons/icon-512.png"];
self.addEventListener("install",e=>{e.waitUntil(caches.open(CACHE_NAME).then(c=>c.addAll(SHELL)));self.skipWaiting()});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE_NAME).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener("fetch",e=>{const r=e.request;if(r.method!=="GET"||new URL(r.url).origin!==self.location.origin)return;const u=new URL(r.url);const cal=u.pathname.endsWith(".html")&&!u.pathname.endsWith("index.html");if(cal){e.respondWith(fetch(r).then(res=>{if(res.ok)caches.open(CACHE_NAME).then(c=>c.put(r,res.clone()));return res}).catch(()=>caches.match(r)));return}e.respondWith(fetch(r).then(res=>{if(res.ok)caches.open(CACHE_NAME).then(c=>c.put(r,res.clone()));return res}).catch(()=>caches.match(r).then(c=>c||caches.match("./index.html"))))});
''',encoding='utf-8')
    # Verwende die mitgelieferten transparenten Logo-Icons, falls vorhanden.
    icon_dir = ASSET_DIR / 'icons'
    for size in (192, 512):
        target = SITE_DIR / 'icons' / f'icon-{size}.png'
        supplied = icon_dir / f'icon-{size}.png'
        # Zielordner muss existieren, bevor ein bereitgestelltes Logo kopiert wird.
        target.parent.mkdir(parents=True, exist_ok=True)
        if supplied.is_file():
            shutil.copy2(supplied, target)
            print(f"PWA-Logo übernommen: {supplied} -> {target}")
        else:
            make_icon(size, target)
            print(f"PWA-Logo erzeugt: {target}")
    (SITE_DIR/'.nojekyll').write_text('',encoding='utf-8')
    print(f"PWA bereit: _site/index.html; {len(available)} Kalender; Manifest, Service Worker und Icons erzeugt.")
if __name__ == '__main__': main()
