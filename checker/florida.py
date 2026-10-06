"""
Florida part of the Shore Check data-checker (called from check.py).

  1. FDACS daily open/closed status of every shellfish harvesting area
     (scraped from the five regional pages; FDACS has no data feed for this).
     Saves data/florida_shellfish.json and logs status changes to
     data/florida_shellfish_history.csv.

Returns alert lines for check.py to send: closures and reopenings caused by
algal toxins (rain, seasonal and water-quality closures are logged, not alerted).
"""

import csv
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

FDACS_PAGES = {
    "Atlantic": "https://shellfish.fdacs.gov/seas/seas_atlantic.htm",
    "West Gulf": "https://shellfish.fdacs.gov/seas/seas_westgulf.htm",
    "Central Gulf": "https://shellfish.fdacs.gov/seas/seas_centralgulf.htm",
    "Big Bend Gulf": "https://shellfish.fdacs.gov/seas/seas_bigbendgulf.htm",
    "South Gulf": "https://shellfish.fdacs.gov/seas/seas_southgulf.htm",
}

# Closure reasons that mean an algal toxin (vs rainfall, season, water quality...)
BIOTOXIN = re.compile(r"karenia|red tide|brevetoxin|pyrodinium|saxitoxin|PSP|NSP|domoic|pseudo-nitzschia|biotoxin|alexandrium|dinophysis", re.I)
CLASSIFICATIONS = r"(Conditionally Approved|Conditionally Restricted|Approved|Restricted|Prohibited|Unclassified)"


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "shore-check/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class TableRows(HTMLParser):
    """Collect every table row as a list of cell texts."""
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def summarize(lines):
    """'open', 'closed' or 'mixed' from the status lines of one area."""
    text = " ".join(l["status"] for l in lines).upper()
    has_open, has_closed = "OPEN" in text, ("CLOSED" in text or "CLOSES" in text)
    if has_open and has_closed:
        return "mixed"
    return "open" if has_open else "closed" if has_closed else "unknown"


def parse_page(region, html):
    p = TableRows()
    p.feed(html)
    published = None
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    m = re.search(r"published at (.+?\d{4})", text)
    if m:
        published = re.sub(r"\s+(st|nd|rd|th)\s*,", r"\1,", m.group(1))

    areas, current = {}, None
    for row in p.rows:
        if len(row) < 3:
            continue
        m = re.match(r"^(\d{4})\s+(.*)$", row[0])
        if m:
            name = m.group(2)
            cls = re.search(CLASSIFICATIONS + r"\s*$", name)
            current = {
                "id": m.group(1), "region": region,
                "name": name[: cls.start()].strip() if cls else name,
                "classification": cls.group(1) if cls else None,
                "lines": [],
            }
            areas[current["id"]] = current
            status, date, reason = (row[1:] + ["", "", ""])[:3]
        elif current and row[0] and not re.search(r"SHA\s*#", row[0]):
            # continuation row, e.g. "LEASES Open" under the area above
            status, date, reason = row[0], row[1], (row[2] if len(row) > 2 else "")
        else:
            continue
        if status:
            current["lines"].append({"status": status, "date": date, "reason": reason})

    for a in areas.values():
        a["state"] = summarize(a["lines"])
        reasons = " ".join(l["reason"] for l in a["lines"])
        a["biotoxin"] = bool(BIOTOXIN.search(reasons))
    return published, areas


def update_shellfish(now):
    alerts, areas, published = [], {}, {}
    for region, url in FDACS_PAGES.items():
        try:
            pub, found = parse_page(region, fetch(url).decode("latin-1"))
        except Exception as err:
            alerts.append(f"Couldn't read the FDACS {region} status page ({err}).")
            continue
        published[region] = pub
        areas.update(found)
    if not areas:
        return alerts

    path = DATA / "florida_shellfish.json"
    previous = json.loads(path.read_text())["areas"] if path.exists() else None
    path.write_text(json.dumps({"checked_at": now, "published": published, "areas": areas}, indent=1))

    hist = DATA / "florida_shellfish_history.csv"
    new_file = not hist.exists()
    with open(hist, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date", "event", "area_id", "name", "region", "state", "biotoxin", "reasons"])
        for aid, a in areas.items():
            reasons = "; ".join(l["reason"] for l in a["lines"] if l["reason"])
            old = previous.get(aid) if previous else None
            if previous is None:
                event = "status when record began"
            elif old is None:
                event = "new area"
            elif old["state"] != a["state"] or old.get("biotoxin") != a["biotoxin"]:
                event = f"{old['state']} -> {a['state']}"
            else:
                continue
            w.writerow([now, event, aid, a["name"], a["region"], a["state"], a["biotoxin"], reasons])
            if previous is not None and (a["biotoxin"] or (old and old.get("biotoxin"))):
                alerts.append(f"Florida shellfish area {aid} {a['name']} ({a['region']}): {event} ({reasons or 'no reason given'}).")
    print(f"  FDACS: {len(areas)} areas, {sum(a['biotoxin'] for a in areas.values())} with biotoxin closures")
    return alerts


def update(now):
    print("Checking Florida (FDACS shellfish areas)…")
    return update_shellfish(now)
