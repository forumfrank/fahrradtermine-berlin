Fahrradtermine in Berlin – GitHub-Pages-Veröffentlichung

Ziel
----
Nach jedem erfolgreichen Lauf der bestehenden Scraper werden die erzeugten HTML-
Kalender automatisch als Website veröffentlicht. Die PC muss dazu nicht laufen.

Datei
-----
src/prepare_github_pages.py

Sie wandelt die HedgeDoc-artigen HTML-Fragmente in vollständige Webseiten um,
übersetzt Markdown-Überschriften wie '# KW 42 / ...' in echte HTML-Überschriften,
legt _site/index.html als Linkübersicht an und kopiert keine JSON-Dateien auf Pages.

Einbau im GitHub-Webinterface
-----------------------------
1. Öffne dein Repository forumfrank/fahrradtermine-berlin.
2. Lege src/prepare_github_pages.py im Ordner src/ neu an oder lade diese Datei hoch.
3. Öffne .github/workflows/scrape.yml.
4. Ergänze die Berechtigungen, die Job-Umgebung und die vier Schritte aus
   workflow-snippet.txt. Die vier Schritte kommen in denselben Job, NACH allen
   Scraper-/Renderer-Schritten, welche die output/*.html erzeugen.
5. Committe die Änderungen.
6. Einmalig: Repository -> Settings -> Pages -> Build and deployment -> Source:
   GitHub Actions auswählen. Speichern, falls GitHub es verlangt.
7. Actions -> bestehenden Scrape-Workflow auswählen -> Run workflow starten.
8. Nach erfolgreichem Lauf findest du die Website unter:
   https://forumfrank.github.io/fahrradtermine-berlin/
   (Wenn GitHub unter Settings -> Pages eine andere URL zeigt, gilt diese.)

Wichtig
-------
- Die bestehende Zeitplanung in scrape.yml bleibt erhalten. Pages wird bei jedem
  Lauf nach der Generierung erneut veröffentlicht.
- Der Deploy-Schritt muss im selben Job nach der HTML-Erzeugung laufen. Eine separate
  Deploy-Datei würde ohne zusätzlichen Artefakt-Transfer die neuen Dateien nicht sehen.
- GitHub Pages ist öffentlich erreichbar; publiziere dort keine privaten Inhalte.
- Das Script benötigt nur die Python-Standardbibliothek.
