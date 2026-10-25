Fahrradtermine Berlin – PWA-Paket für Android

Dieses Paket macht die vorhandenen fünf Kalender über GitHub Pages als installierbare Web-App (PWA) erreichbar. Die bestehenden Scraper und deren Zeitplan bleiben unverändert.

Enthalten
- src/prepare_github_pages.py: ersetzt das gleichnamige Script im Repository.
- README-PWA.txt: Einbau über das GitHub-Webinterface.
- WORKFLOW-CHECK.txt: Kontrolle der bereits vorhandenen Pages-Schritte.

Einbau
1. Repository forumfrank/fahrradtermine-berlin öffnen.
2. Die Datei src/prepare_github_pages.py durch die Version aus diesem Paket ersetzen.
3. Die zuletzt gezeigte scrape.yml enthält bereits den Schritt `python src/prepare_github_pages.py`, danach `configure-pages`, `upload-pages-artifact` (path: _site) und `deploy-pages`. Daher muss der Workflow voraussichtlich nicht geändert werden.
4. Unter Settings → Pages → Build and deployment → Source `GitHub Actions` auswählen.
5. Unter Actions den Workflow „Fahrradtermine Berlin scraping“ mit „Run workflow“ starten.
6. Nach erfolgreichem Lauf öffnen: https://forumfrank.github.io/fahrradtermine-berlin/
7. Auf Android in Chrome die Seite öffnen → Menü ⋮ → „App installieren“ oder „Zum Startbildschirm hinzufügen“.

Was das Script tut
- Erstellt eine mobile Startseite mit fünf getrennten Kalender-Kacheln.
- Verpackt die Kalenderseiten mit mobiler Darstellung und einem „Alle Kalender“-Link.
- Erstellt manifest.webmanifest, Service Worker und App-Symbole 192x192/512x512 automatisch im Ordner _site.
- Erwartete Ausgabedateien: output/fahrradtermine.html, output/velodemo.html, output/adfc.html, output/werkstaetten.html, output/versammlungsbehoerde.html. Fehlt eine Datei, wird dieser Kalender auf der Startseite ausgelassen und im Log gemeldet.
- JSON-Dateien werden nicht auf die öffentliche Website kopiert.

Hinweise
- Die PWA ist öffentlich, genau wie die GitHub-Pages-Website.
- Kalenderseiten laden bevorzugt die aktuelle Online-Version. Bei Netzproblemen kann eine zuletzt geladene Kalenderseite als Fallback angezeigt werden.
- Die App ist erst nach erfolgreicher Veröffentlichung installierbar.
