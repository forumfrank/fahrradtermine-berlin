#!/usr/bin/env python3
"""Turn workshop opening-hour rules into individual dated occurrences."""
from datetime import date, datetime, time, timedelta
import re
import unicodedata

HORIZON_DAYS = 183  # about six months; every run refreshes the upcoming window
WEEKDAYS = {
    "mo": 0, "montag": 0, "montags": 0,
    "di": 1, "dienstag": 1, "dienstags": 1,
    "mi": 2, "mittwoch": 2, "mittwochs": 2,
    "do": 3, "donnerstag": 3, "donnerstags": 3,
    "fr": 4, "freitag": 4, "freitags": 4,
    "sa": 5, "samstag": 5, "samstags": 5,
    "so": 6, "sonntag": 6, "sonntags": 6,
}
DAY_PATTERN = re.compile(r"(?<![A-Za-zÄÖÜäöü])(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")(?![A-Za-zÄÖÜäöü])", re.I)
TIME_RANGE = re.compile(r"(?<!\d)(\d{1,2})(?:[:.](\d{2}))?\s*(?:h|uhr)?\s*(?:-|–|—|−|bis)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(?:h|uhr)?", re.I)


def _norm(s):
    return unicodedata.normalize("NFKC", str(s or "")).replace("\u00a0", " ")


def _weekday_numbers(text):
    vals = []
    for m in DAY_PATTERN.finditer(text):
        d = WEEKDAYS[m.group(1).lower()]
        if d not in vals:
            vals.append(d)
    # Handle explicit weekday ranges such as "Mi bis Fr".
    range_match = re.search(r"\b(Mo|Di|Mi|Do|Fr|Sa|So)\s*(?:bis|[-–])\s*(Mo|Di|Mi|Do|Fr|Sa|So)\b", text, re.I)
    if range_match:
        a = WEEKDAYS[range_match.group(1).lower()]
        b = WEEKDAYS[range_match.group(2).lower()]
        vals = []
        d = a
        while True:
            vals.append(d)
            if d == b:
                break
            d = (d + 1) % 7
    return vals


def _time_pair(m):
    sh, sm, eh, em = int(m.group(1)), int(m.group(2) or 0), int(m.group(3)), int(m.group(4) or 0)
    if sh > 23 or eh > 24 or sm > 59 or em > 59 or (eh == 24 and em != 0):
        return None
    return f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}"


def _rules(text):
    """Extract weekday/time pairs conservatively; avoid guessing missing hours."""
    text = _norm(text)
    # Make common wording more uniform, but preserve weekday and time boundaries.
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    rules = []
    matches = list(TIME_RANGE.finditer(text))
    previous_end = 0
    for m in matches:
        pair = _time_pair(m)
        if not pair:
            previous_end = m.end()
            continue
        # Do not mistake season limits such as SAISON=4-10 for opening hours.
        before_range = text[max(0, m.start() - 18):m.start()]
        if re.search(r"SAISON\s*=\s*$", before_range, re.I):
            previous_end = m.end()
            continue
        # The weekday labels for this time range normally occur after the previous range.
        prefix = text[previous_end:m.start()]
        # If the first time is preceded by an opening-hours label, allow a wider lookback.
        if not _weekday_numbers(prefix) and previous_end == 0:
            prefix = text[max(0, m.start() - 100):m.start()]
        days = _weekday_numbers(prefix)
        # Monthly first weekday, e.g. "1ter Do 16h-18h".
        monthly = bool(re.search(r"\b(?:1\.?\s*(?:ter|te|\.?)|erster|erste)\b", prefix, re.I))
        # "jeden Dienstag" may be just before the range and is covered by the weekday parser.
        if days:
            for day in days:
                local_context = text[max(0, m.start() - 70):m.start()]
                fortnightly = bool(re.search(r"alle\s+zwei\s+wochen|14[- ]täg", local_context, re.I))
                rule = {"weekday": day, "start_time": pair[0], "end_time": pair[1], "monthly_first": monthly, "fortnightly": fortnightly}
                if rule not in rules:
                    rules.append(rule)
        previous_end = m.end()
    # If a time range was preceded by a list of weekdays but the first extraction was blocked
    # by punctuation, recover a simple day/time phrase from the entire string.
    if not rules:
        for m in matches:
            pair = _time_pair(m)
            if not pair:
                continue
            days = _weekday_numbers(text[max(0, m.start() - 100):m.start()])
            for day in days:
                rules.append({"weekday": day, "start_time": pair[0], "end_time": pair[1], "monthly_first": False})
    return rules


def _is_monthly_first(d):
    return 1 <= d.day <= 7


def _season_allowed(text, d):
    m = re.search(r"SAISON\s*=\s*(\d{1,2})\s*[-–]\s*(\d{1,2})", text, re.I)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if start <= end and not (start <= d.month <= end):
            return False
        if start > end and not (d.month >= start or d.month <= end):
            return False
    # Common plain-language season notes.
    if re.search(r"\bAPRIL\s*(?:BIS|[-–])\s*SEPTEMBER\b", text, re.I) and d.month not in range(4, 10):
        return False
    if re.search(r"\bWINTERPAUSE\b", text, re.I) and d.month in (12, 1, 2):
        return False
    # User-defined rule: semester break / lecture-free period is 15 February–31 March.
    if re.search(r"PAUSE\s*=\s*SEMESTERFERIEN|VORLESUNGSFREI", text, re.I):
        if (d.month == 2 and d.day >= 15) or d.month == 3:
            return False
    return True


def _date_exceptions(text):
    """Read explicit dd.mm.yy(yy) dates, e.g. a list of special opening dates."""
    out = []
    for m in re.finditer(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?!\d)", text):
        day, month, year = map(int, m.groups())
        if year < 100:
            year += 2000
        try:
            out.append(date(year, month, day))
        except ValueError:
            pass
    return sorted(set(out))


def expand_workshops(workshops, today=None, horizon_days=HORIZON_DAYS):
    """Return one record per dated opening day, plus unparsed records at the end."""
    today = today or date.today()
    last_day = today + timedelta(days=horizon_days)
    dated, unparsed = [], []
    for item in workshops:
        if not isinstance(item, dict):
            continue
        opening = str(item.get("opening_hours") or item.get("display_time") or "")
        if not opening.strip():
            unparsed.append({**item, "date": "", "schedule_status": "keine Öffnungszeit angegeben"})
            continue
        rules = _rules(opening)
        all_explicit_dates = _date_exceptions(opening)
        exceptions = [d for d in all_explicit_dates if today <= d <= last_day]
        # A dated list can establish openings even if the weekday rules are absent.
        if not rules and not exceptions:
            unparsed.append({**item, "date": "", "schedule_status": "Öffnungszeiten nicht automatisch interpretierbar"})
            continue
        dates = set(exceptions)
        for offset in range((last_day - today).days + 1):
            d = today + timedelta(days=offset)
            if not _season_allowed(opening, d):
                continue
            for rule in rules:
                if d.weekday() != rule["weekday"]:
                    continue
                if rule.get("monthly_first") and not _is_monthly_first(d):
                    continue
                if rule.get("fortnightly"):
                    anchors = [x for x in all_explicit_dates if x.weekday() == rule["weekday"]]
                    if not anchors:
                        # Without a dated anchor, do not invent which alternating week is correct.
                        continue
                    anchor = max(anchors)
                    if d < anchor or (d - anchor).days % 14 != 0:
                        continue
                dates.add(d)
        for d in sorted(dates):
            # For a date-specific exception without a parsed time, do not invent one.
            applicable = [r for r in rules if r["weekday"] == d.weekday()]
            if applicable:
                applicable.sort(key=lambda r: r["start_time"])
                times = applicable[0]
                start_time, end_time = times["start_time"], times["end_time"]
            else:
                start_time = end_time = None
            year, week, weekday = d.isocalendar()
            record = dict(item)
            record.update({
                "date": d.isoformat(),
                "start_time": start_time,
                "end_time": end_time,
                "display_time": f"{d.strftime('%d.%m.%Y')} ({('Mo','Di','Mi','Do','Fr','Sa','So')[d.weekday()]}, KW {week:02d})" + (f", {start_time}–{end_time}" if start_time and end_time else ""),
                "iso_year": year,
                "iso_week": week,
                "iso_weekday": weekday,
                "schedule_status": "Termin aus Öffnungsregel abgeleitet",
                "occurrence_id": f"{item.get('anchor') or item.get('title','werkstatt')}-{d.isoformat()}-{start_time or 'zeit-offen'}",
            })
            dated.append(record)
    dated.sort(key=lambda x: (x.get("iso_year", 9999), x.get("iso_week", 99), x.get("iso_weekday", 9), x.get("start_time") or "99:99", (x.get("title") or "").casefold()))
    # Unscheduled entries are kept at the end so a workshop is not silently lost.
    unparsed.sort(key=lambda x: (x.get("title") or "").casefold())
    return dated + unparsed
