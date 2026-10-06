"""
Florida part of the Shore Check data-checker (called from check.py).

  1. FDACS daily open/closed status of every shellfish harvesting area
     (scraped from the five regional pages; FDACS has no data feed for this).
     Saves data/florida_shellfish.json and logs status changes to
     data/florida_shellfish_history.csv.
  2. NOAA's beach-level red tide respiratory forecast (a zip of CSVs that
     browsers can't fetch directly). Saves data/florida_respiratory.json.

Returns alert lines for check.py to send: biotoxin closures and reopenings,
and beaches forecast at Moderate or High respiratory risk.
"""

import csv
import io
import json
import re
import urllib.request
import zipfile
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
RESPIRATORY_ZIP = "https://nccospublicstor.blob.core.windows.net/hab-data/no_Explorer/rif_model/csv/RIFv2_currentmodelrun.zip"

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


def update_respiratory(now):
    z = zipfile.ZipFile(io.BytesIO(fetch(RESPIRATORY_ZIP)))
    beaches = {}
    run = None
    for name in sorted(z.namelist()):
        m = re.search(r"forecast_valid_(\d+)hrs", name)
        if not m:
            continue
        hours = int(m.group(1))
        for r in csv.DictReader(io.StringIO(z.read(name).decode("utf-8"))):
            run = r.get("Model Run Time") or run
            b = beaches.setdefault(r["Location Name"], {
                "name": r["Location Name"], "lat": float(r["Lat"]), "lon": float(r["Lon"]),
                "cell_count": r.get("Cell Count Category"), "sample_time": r.get("Sample Time"),
                "forecast": [],
            })
            b["forecast"].append({"hours": hours, "level": r["Forecast"], "confidence": r.get("Confidence")})
    for b in beaches.values():
        b["forecast"].sort(key=lambda f: f["hours"])

    # Beaches at Moderate/High in the next 24 h; alert only on newly risky ones.
    path = DATA / "florida_respiratory.json"
    before = set(json.loads(path.read_text()).get("risky", [])) if path.exists() else set()
    risky = sorted(b["name"] for b in beaches.values()
                   if any(f["level"] in ("Moderate", "High") for f in b["forecast"][:8]))
    path.write_text(json.dumps(
        {"checked_at": now, "model_run": run, "risky": risky, "beaches": list(beaches.values())}, indent=1))
    print(f"  NOAA respiratory forecast: {len(beaches)} beaches, run {run}")

    new = [n for n in risky if n not in before]
    return [f"Red tide respiratory risk now Moderate or High (next 24 h) at: {', '.join(new)}."] if new else []


def update(now):
    alerts = []
    print("Checking Florida (FDACS shellfish areas)…")
    alerts += update_shellfish(now)
    print("Checking Florida (NOAA respiratory forecast)…")
    try:
        alerts += update_respiratory(now)
    except Exception as err:
        alerts.append(f"Couldn't read NOAA's Florida respiratory forecast ({err}).")
    return alerts
