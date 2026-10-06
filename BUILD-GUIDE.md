# Shore Check: build guide

A prototype that combines California's official shellfish advisories (CDPH) with C-HARM domoic acid forecasts in one map, plus a scheduled data-checker that keeps an advisory history and sends alerts.

## What's in this folder

| Path | What it is |
|---|---|
| `index.html` | Landing page: choose California or Florida |
| `california.html` | The California app (CDPH advisories + C-HARM) |
| `florida.html` | The Florida app (FDACS harvest areas, FWC red tide samples, MODIS fluorescence) |
| `assets/shore.css` | Shared styles for all pages (matches sophiaesiegel.github.io) |
| `checker/check.py` | The data-checker (Python standard library only) |
| `checker/florida.py` | Florida part of the checker: FDACS daily status pages |
| `.github/workflows/check.yml` | Tells GitHub to run the checker every 3 hours |
| `data/` | Written by the checker: advisory history, current advisories, daily C-HARM values at 9 pier sites |
| `TUTORIAL-7-DAY-TREND.md` | Step-by-step: add a 7-day trend chart yourself |

## Run it locally

```
python -m http.server 8765
```

Then open http://localhost:8765. (Double-clicking the file won't work: "Use my location" and the history files need a real web address.)

To run the data-checker by hand:

```
python checker/check.py
```

## Florida data sources

| Layer | Source | How the app gets it |
|---|---|---|
| Harvest area open/closed + reason | FDACS daily status pages (5 regions) | Data-checker reads the pages → `data/florida_shellfish.json`; history in `data/florida_shellfish_history.csv` |
| Harvest area shapes | FDACS "Temporary Closures" ArcGIS layer | Live from the browser |
| *K. brevis* samples (8 days) | FWC HAB dashboard ArcGIS layer | Live from the browser |
| Chlorophyll fluorescence | MODIS Aqua nFLH, NOAA CoastWatch ERDDAP | Live (images + JSONP) |

Florida alerts fire when a harvesting area closes or reopens because of an algal toxin. Rain, seasonal and water-quality closures are logged in the history but not alerted.

## What's inside `california.html`

The script is split into numbered sections:

| Section | What it does | What to learn |
|---|---|---|
| 1. Data sources | URLs for CDPH, C-HARM and the checker's data files | What an API endpoint is |
| 3. Load CDPH advisories | Reads CDPH's ArcGIS map config and works out which areas are under which advisory | `fetch`, JSON, regular expressions |
| 4. Advisory history | Reads `data/advisory_history.json` from the checker | Working with your own data |
| 5. Map + counties | Leaflet map, greyscale hillshade basemap, county shapes, "which county is this point in?" | Leaflet, GeoJSON, tile layers |
| 6. C-HARM overlay | Requests forecast images from NOAA ERDDAP and lays them on the map | ERDDAP griddap URLs |
| 7. Check one spot | Per-species status, history, and the 4-day C-HARM outlook for the nearest ocean cell | Putting it together |

The styling matches sophiaesiegel.github.io: same colour tokens, Inter + JetBrains Mono, mono kickers, pill buttons and chips. To restyle, change the colours in `:root` at the top.

### Data sources (all live, all free)

- **CDPH advisories:** the ArcGIS web map behind CDPH's Recreational Shellfish Advisory Map (item `ad52187023f24b09b073d287f656df14`). CDPH stores which counties are under which advisory as *layer filters*, and hidden layers are inactive advisories. **This is fragile.** If CDPH rebuilds the map, this part breaks. The checker opens an alert if it can't read the map.
- **County / area shapes:** CDPH's `California_Coastal_Counties` ArcGIS feature service.
- **C-HARM v3.1:** NOAA CoastWatch ERDDAP datasets `wvcharmV3_0day` (nowcast) plus `_1day`, `_2day` and `_3day` (forecasts). 3 km grid, updated daily. Variables: `particulate_domoic`, `cellular_domoic`, `pseudo_nitzschia` (each a probability from 0 to 1). Its licence says it's "not intended for legal use."
- **Basemap:** Esri World Hillshade (Dark) and Dark Gray Canvas. Free, no key.

## The data-checker

Each run (every 3 hours on GitHub, or by hand):

1. **Advisories:** reads which CDPH advisories are active, compares with the last run, and logs `issued` / `lifted` events to `data/advisory_history.json` (for the app) and `data/advisory_history.csv` (for R, Python or Excel). The first run records everything as "active when record began", because CDPH doesn't publish start dates.
2. **C-HARM:** saves the nowcast and 1–3 day forecasts at 9 HABMAP pier sites (Trinidad to Scripps) to `data/charm_daily.csv`. Over time this becomes your own record for comparing C-HARM forecasts with CDPH advisories and pier samples.
3. **Alerts** when an advisory is issued or lifted, when a pier's C-HARM nowcast crosses 50%, or when the CDPH map can't be read:
   - **GitHub issue** (automatic once it's on GitHub). Turn on email or phone notifications under *Watch → Custom → Issues* on the repo, or use the GitHub mobile app.
   - **Phone push via ntfy** (optional, free, no account): install the ntfy app, subscribe to a hard-to-guess topic name (e.g. `shorecheck-` plus random letters), then add it on GitHub as a repository secret named `NTFY_TOPIC` (Settings → Secrets and variables → Actions). Anyone who knows the topic name can read it, so don't use anything personal.

**History limit:** the record starts on the day the checker first ran (Oct 5, 2026). Older advisories would have to be added by hand from CDPH press releases.

## Put it on GitHub (about 20 minutes)

This makes the checker run automatically and gives you a public link.

1. On github.com (you already have an account for your website), click **New repository**. Name it `shore-check`, make it **Public** (needed for free Pages and unlimited Actions minutes), and **don't** add a README.
2. In a terminal in this folder:
   ```
   git init
   git add .
   git commit -m "Shore Check prototype"
   git branch -M main
   git remote add origin https://github.com/sophiaesiegel/shore-check.git
   git push -u origin main
   ```
3. On the repo: **Settings → Pages**, Source "Deploy from a branch", branch `main`, folder `/ (root)`. Your app goes live at `https://sophiaesiegel.github.io/shore-check/`.
4. **Actions** tab → "Check advisories" → **Run workflow** to test it. After that it runs every 3 hours by itself and commits new data, and the live site picks it up.

Note: GitHub pauses scheduled workflows on public repos after 60 days with no repo activity. The checker's own data commits normally count as activity, but if it ever stops, re-enable it from the Actions tab.

## Roadmap

### Done
- Live map of CDPH advisories, per-species status, C-HARM 4-day outlook
- Scheduled checker with advisory history and alerts

### Next: learning steps
- **7-day trend:** follow `TUTORIAL-7-DAY-TREND.md`
- Add a "Dungeness crab" row from CDFW closure info
- Chart `data/charm_daily.csv` once a few weeks have accumulated

### Later
- **Saved beaches + personal alerts:** user accounts (Supabase or Firebase), so people get alerts for *their* harvesting spots instead of one repo-wide feed.
- **Phone app:** first a **PWA** (installable web app: add a manifest and service worker; a few hours of work). Then **React Native + Expo** if people use it.
- **B2B shellfish tag logging:** restaurants scan tags, keep them the required 90 days, and get alerts if a harvest area is closed after the fact. Needs accounts, a database and OCR/barcode scanning.

## Outside the code (do these early)

1. **Email CDPH's Marine Biotoxin Monitoring Program.** Ask whether they publish advisories and test results in a machine-readable form, or would. An official feed fixes the fragility problem.
2. **Talk to the C-HARM team** (Clarissa Anderson at Scripps/SCCOOS, Raphe Kudela at UCSC, and Dale Robinson at NOAA CoastWatch, who runs the ERDDAP feed). Ask how they'd want C-HARM described to the public and whether the risk bands make sense.
3. **Liability:** never write "safe." Keep the official status separate from the forecast. Before any public launch, have the disclaimer reviewed (Stanford's law clinics or tech-transfer office are a good free start).
4. **The research link:** the gap between "no advisory" and "high C-HARM probability" (Santa Cruz in early October 2026 had no bivalve advisory, but C-HARM showed ~77% just offshore) is a measurable question. How often do C-HARM highs come before CDPH advisories, and by how many days? Your `data/` folder is now collecting the evidence.

## Learning resources
- JavaScript basics: javascript.info (first ~10 chapters)
- Leaflet maps: leafletjs.com/examples
- ERDDAP: coastwatch.pfeg.noaa.gov/erddap/griddap/documentation.html
- GitHub Actions: docs.github.com/actions
