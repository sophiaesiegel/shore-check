"""
Shore Check data-checker.

Run on a schedule (GitHub Actions, see .github/workflows/check.yml) or by hand:

    python checker/check.py

Each run it:
  1. Reads which CDPH shellfish advisories are active right now.
  2. Compares them with the last run and logs "issued" / "lifted" events
     to data/advisory_history.json and data/advisory_history.csv.
  3. Saves the C-HARM nowcast + forecasts at fixed monitoring sites
     to data/charm_daily.csv (one row per site, forecast day and date).
  4. Sends alerts when something changes: a GitHub issue (when running in
     GitHub Actions) and/or a phone push via ntfy.sh (if NTFY_TOPIC is set).

Python standard library only, so there's nothing to install.
"""

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import florida  # checker/florida.py

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

CDPH_WEBMAP = "https://www.arcgis.com/sharing/rest/content/items/ad52187023f24b09b073d287f656df14/data?f=json"
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/"
CHARM_DAYS = {"wvcharmV3_0day": 0, "wvcharmV3_1day": 1, "wvcharmV3_2day": 2, "wvcharmV3_3day": 3}
CHARM_VARS = ["particulate_domoic", "cellular_domoic", "pseudo_nitzschia"]
ALL_BIVALVES = ["mussels", "clams", "razor", "scallops", "oysters"]

# Fixed places to track C-HARM every day. These are the long-running
# HABMAP pier sampling sites, so C-HARM can later be compared with real samples.
SITES = {
    "Trinidad Pier":     (41.057, -124.147),
    "Bodega Bay":        (38.317, -123.072),
    "Santa Cruz Wharf":  (36.958, -122.017),
    "Monterey Wharf":    (36.605, -121.889),
    "Cal Poly Pier":     (35.170, -120.741),
    "Stearns Wharf":     (34.408, -119.685),
    "Santa Monica Pier": (34.008, -118.499),
    "Newport Pier":      (33.607, -117.930),
    "Scripps Pier":      (32.867, -117.257),
}
RISK_ALERT = 0.5  # alert when a site's nowcast crosses this probability


def get_json(url, timeout=60, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": "shore-check/0.1"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as err:
            if err.code < 500 or attempt == tries - 1:  # retry only server hiccups
                raise
            time.sleep(5 * (attempt + 1))


def html_to_text(html):
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>|</(p|div)>", "\n", html, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


# ---------------------------------------------------------------- 1. CDPH

def fetch_advisories():
    """Return {key: advisory} for every advisory active right now."""
    webmap = get_json(CDPH_WEBMAP)
    layers = webmap.get("operationalLayers") or []
    if not layers:
        raise RuntimeError("CDPH web map has no layers - its format may have changed")

    active = {}
    for layer in layers:
        title = layer.get("title") or ""
        if not layer.get("visibility") or re.search(r"boundaries", title, re.I):
            continue
        expr = (layer.get("layerDefinition") or {}).get("definitionExpression") or ""
        areas = re.findall(r"'([^']+)'", expr)
        text = html_to_text((layer.get("popupInfo") or {}).get("description"))
        m = re.search(r"Updated\s+([A-Z][a-z]+ \d{1,2}, \d{4})", text)
        updated = m.group(1) if m else None

        if re.search(r"quarantine", title, re.I):
            active["Statewide|mussel quarantine"] = {
                "area": "Statewide", "label": "Mussel quarantine", "species": ["mussels"],
                "toxins": [], "updated": updated,
            }
            continue
        if re.search(r"lifted", title, re.I):
            continue
        if re.search(r"razor", title, re.I):
            species = ["razor"]
        elif re.search(r"bivalve", title, re.I):
            species = ALL_BIVALVES
        else:
            continue

        if re.search(r"special", title, re.I) and layer.get("url"):
            fs = get_json(layer["url"] + "/query?where=1%3D1&outFields=TITLE&returnGeometry=false&f=json")
            for f in fs.get("features", []):
                areas.append(re.sub(r"^Special Advisory Area\s*-\s*", "", str(f["attributes"]["TITLE"]), flags=re.I))

        src = title if re.search(r"PSP|paralytic|domoic", title, re.I) else text
        toxins = [t for t, pat in (("PSP toxins", r"PSP|paralytic"), ("domoic acid", r"domoic")) if re.search(pat, src, re.I)]
        toxin_text = " + ".join(toxins) or "toxin"
        label = f"Razor clam {toxin_text} advisory" if species == ["razor"] else f"{toxin_text[0].upper()}{toxin_text[1:]} advisory"

        for area in areas:
            active[f"{area}|{label}"] = {
                "area": area, "label": label, "species": species, "toxins": toxins, "updated": updated,
            }
    return active


def update_history(active, now):
    """Compare with the last run; append issued/lifted events. Returns new events."""
    current_file = DATA / "advisories_current.json"
    history_file = DATA / "advisory_history.json"
    previous = json.loads(current_file.read_text())["active"] if current_file.exists() else None
    history = json.loads(history_file.read_text()) if history_file.exists() else []

    events = []
    if previous is None:
        # First run: we don't know when these started, only that they're active now.
        for a in active.values():
            events.append({**a, "date": now, "event": "active when record began"})
    else:
        for key, a in active.items():
            if key not in previous:
                events.append({**a, "date": now, "event": "issued"})
        for key, a in previous.items():
            if key not in active:
                events.append({**a, "date": now, "event": "lifted"})

    history.extend(events)
    history_file.write_text(json.dumps(history, indent=1))
    current_file.write_text(json.dumps({"checked_at": now, "active": active}, indent=1))

    with open(DATA / "advisory_history.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "event", "area", "label", "species", "toxins", "cdph_updated"])
        for e in history:
            w.writerow([e["date"], e["event"], e["area"], e["label"], ";".join(e["species"]), ";".join(e["toxins"]), e.get("updated") or ""])

    return [e for e in events if e["event"] != "active when record began"]


# ---------------------------------------------------------------- 2. C-HARM

def charm_at(dataset, lat, lon):
    """Nearest ocean cell with data within ~15 km of (lat, lon)."""
    lon360 = lon + 360 if lon < 0 else lon
    d = 0.15
    box = f"[last][({lat - d:.2f}):({lat + d:.2f})][({lon360 - d:.2f}):({lon360 + d:.2f})]"
    query = ",".join(v + box for v in CHARM_VARS)
    url = ERDDAP + dataset + ".json?" + urllib.parse.quote(query, safe="(),:")
    table = get_json(url)["table"]
    cols = table["columnNames"]
    best, best_d = None, 1e9
    for row in table["rows"]:
        r = dict(zip(cols, row))
        if r["particulate_domoic"] is None:
            continue
        dist = ((r["latitude"] - lat) ** 2 + (r["longitude"] - lon360) ** 2) ** 0.5
        if dist < best_d:
            best, best_d = r, dist
    return best


def update_charm(now):
    """Append any new (site, forecast day, valid date) rows. Returns risk alerts."""
    path = DATA / "charm_daily.csv"
    fields = ["checked_at", "site", "lat", "lon", "forecast_day", "valid_date"] + CHARM_VARS
    rows = list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []
    seen = {(r["site"], r["forecast_day"], r["valid_date"]) for r in rows}

    alerts, new_rows = [], []
    for site, (lat, lon) in SITES.items():
        for dataset, day in CHARM_DAYS.items():
            try:
                r = charm_at(dataset, lat, lon)
            except Exception as err:  # one failed request shouldn't stop the run
                print(f"  C-HARM {dataset} {site}: {err}", file=sys.stderr)
                continue
            if not r:
                continue
            valid = r["time"][:10]
            if (site, str(day), valid) in seen:
                continue
            new_rows.append({
                "checked_at": now, "site": site, "lat": lat, "lon": lon,
                "forecast_day": day, "valid_date": valid,
                **{v: round(r[v], 4) if r[v] is not None else "" for v in CHARM_VARS},
            })
            if day == 0:
                prev = [x for x in rows if x["site"] == site and x["forecast_day"] == "0" and x["particulate_domoic"]]
                prev_p = float(prev[-1]["particulate_domoic"]) if prev else None
                p = r["particulate_domoic"]
                if prev_p is not None and prev_p < RISK_ALERT <= p:
                    alerts.append(f"C-HARM domoic acid risk at **{site}** rose to {p:.0%} (was {prev_p:.0%}).")

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows + new_rows)
    print(f"  C-HARM: {len(new_rows)} new rows")
    return alerts


# ---------------------------------------------------------------- 3. alerts

def send_alerts(lines):
    if not lines:
        return
    body = "\n".join(f"- {l}" for l in lines)
    body += "\n\nAlways confirm with CDPH: https://www.cdph.ca.gov/Programs/OPA/Pages/Shellfish-Advisories.aspx or 1-800-553-4133."
    title = f"Shore Check: {len(lines)} change{'s' if len(lines) != 1 else ''} ({datetime.now(timezone.utc):%b %d})"
    print("\n" + title + "\n" + body)
    (DATA / "last_alert.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")

    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if token and repo:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues",
            data=json.dumps({"title": title, "body": body}).encode(),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            method="POST")
        urllib.request.urlopen(req, timeout=30)
        print("  Opened GitHub issue")

    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}", data=body.replace("**", "").encode(),
            headers={"Title": title, "Tags": "shell"}, method="POST")
        urllib.request.urlopen(req, timeout=30)
        print("  Sent ntfy push")


def main():
    DATA.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    alerts = []

    print("Checking CDPH advisories…")
    try:
        active = fetch_advisories()
        events = update_history(active, now)
        print(f"  {len(active)} active, {len(events)} changes")
        for e in events:
            verb = "ISSUED" if e["event"] == "issued" else "LIFTED"
            alerts.append(f"{verb}: {e['label']}, {e['area']} ({', '.join(e['species'])})")
    except Exception as err:
        alerts.append(f"Couldn't read the CDPH advisory map ({err}). It may have changed format; check the parser.")

    print("Checking C-HARM…")
    alerts += update_charm(now)

    try:
        alerts += florida.update(now)
    except Exception as err:
        alerts.append(f"Florida check failed ({err}).")

    send_alerts(alerts)


if __name__ == "__main__":
    main()
