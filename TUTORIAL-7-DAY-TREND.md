# Tutorial: add a 7-day trend

**Goal:** when someone taps a spot, show a small line chart of C-HARM's domoic acid probability for that ocean cell over the past 7 days. Is risk rising or falling?

**You'll learn:** how ERDDAP URLs work, writing an `async` function, and drawing a simple SVG chart.

**Time:** 30–60 minutes. Everything goes in `index.html`. Save after each step and refresh the browser.

---

## Step 0: Open the project and run it

1. Open the `Shore Check` folder in VS Code (File → Open Folder).
2. Open a terminal in VS Code (Terminal → New Terminal) and run:
   ```
   python -m http.server 8765
   ```
3. Go to http://localhost:8765 and tap Monterey Bay to check it works.
4. Open the browser's developer tools (F12) and click the **Console** tab. Errors show up here. Keep it open.

## Step 1: Understand the data request (no code yet)

Paste this into your browser's address bar:

```
https://coastwatch.pfeg.noaa.gov/erddap/griddap/wvcharmV3_0day.htmlTable?particulate_domoic[(2026-09-28T00:00:00Z):(last)][(36.55)][(237.96)]
```

You should see a table with one row per day. Here's how the URL breaks down:

| Piece | Meaning |
|---|---|
| `wvcharmV3_0day` | The dataset: C-HARM nowcast |
| `.htmlTable` | Output format. The app uses `.json`; `.csv` is good for Excel or R |
| `particulate_domoic` | Which variable |
| `[(2026-09-28T00:00:00Z):(last)]` | **Time:** from that date up to the newest |
| `[(36.55)]` | **Latitude** |
| `[(237.96)]` | **Longitude, in degrees east.** C-HARM uses 0–360, so −122.04 becomes 237.96 |

**Try it:** change the start date to 30 days ago. Change `particulate_domoic` to `pseudo_nitzschia`. Change `.htmlTable` to `.csv`.

Note: the app already finds the nearest ocean cell for each tap (`first.latitude`, `first.longitude` in `checkSpot`). You'll reuse that cell, so the trend matches the numbers above it.

## Step 2: A function that fetches the trend

Find section **7. CHECK ONE SPOT** and the `charmAt` function. **Below** `charmAt`, add:

```js
// Past `days` days of the C-HARM nowcast for one grid cell.
async function charmTrend(cellLat, cellLon360, days = 7) {
  // Start date as "YYYY-MM-DDT00:00:00Z", `days` days ago
  const start = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10) + 'T00:00:00Z';
  const q = `particulate_domoic[(${start}):(last)][(${cellLat})][(${cellLon360})]`;
  const res = await jsonp(ERDDAP + 'wvcharmV3_0day.json?' + erddapEncode(q));
  // Each row is [time, latitude, longitude, value]; skip empty days
  return res.table.rows
    .filter(row => row[3] != null)
    .map(row => ({ time: row[0], p: row[3] }));
}
```

**What's going on:**
- `async` / `await`: the request takes time, and `await` waits for the answer without freezing the page.
- `jsonp(...)` is the helper already in the file. ERDDAP doesn't allow normal `fetch` from other websites (CORS), so the app loads the data as a script instead.
- `erddapEncode` turns `[` and `]` into `%5B` and `%5D`, which ERDDAP requires.

**Test it before moving on.** Refresh the page, then type this in the Console:

```js
await charmTrend(36.55, 237.96)
```

You should get a list of about 7 objects like `{time: "2026-09-28T12:00:00Z", p: 0.77}`. If you get an error, check for typos, especially backticks `` ` `` versus quotes `'`.

## Step 3: A function that draws the chart

Below `charmTrend`, add:

```js
// Small SVG line chart: one dot per day, dashed line at 50%.
function trendChart(points) {
  const W = 340, H = 100, pad = 20;
  const x = i => pad + (i * (W - 2 * pad)) / Math.max(1, points.length - 1);
  const y = p => H - pad - p * (H - 2 * pad);   // p = 0 at the bottom, 1 at the top

  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.style.width = '100%';
  const add = (tag, attrs) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    svg.append(node);
    return node;
  };

  add('line', { x1: pad, x2: W - pad, y1: y(0.5), y2: y(0.5), stroke: '#1c3348', 'stroke-dasharray': '3 3' });
  add('polyline', {
    points: points.map((d, i) => `${x(i)},${y(d.p)}`).join(' '),
    fill: 'none', stroke: '#5ad7e8', 'stroke-width': 2,
  });
  points.forEach((d, i) => {
    add('circle', { cx: x(i), cy: y(d.p), r: 4, fill: thermal(d.p) });
    add('text', { x: x(i), y: H - 4, 'text-anchor': 'middle', 'font-size': 10, fill: '#6b8299' }).textContent =
      new Date(d.time).toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
  });
  return svg;
}
```

**What's going on:**
- An SVG is a drawing made of shapes. `x(i)` turns "day number" into a horizontal position, and `y(p)` turns a probability into a vertical position. These are called *scales*, and every charting library works this way.
- `thermal(p)` is already in the file. It colours each dot to match the map legend.
- The dashed line marks 50%, the "High" threshold.

## Step 4: Show it when someone taps a spot

In `checkSpot`, find this line near the end:

```js
  // TODO (7-day trend): see TUTORIAL-7-DAY-TREND.md, Step 3 and Step 4.
```

Replace it with:

```js
  const trendBox = el('div', { class: 'small faint' }, 'Loading 7-day trend…');
  fc.append(el('p', { class: 'kicker' }, 'Past 7 days · C-HARM nowcast'), trendBox);
  charmTrend(first.latitude, first.longitude)
    .then(points => trendBox.replaceChildren(trendChart(points)))
    .catch(() => trendBox.replaceChildren('Couldn\'t load the 7-day trend.'));
```

Why `.then` instead of `await` here? The rest of the card can appear immediately while the trend loads in the background.

Save, refresh, and tap Monterey Bay. You should see a cyan line with coloured dots under the forecast bars.

## Step 5: Make it yours (optional)

Pick one:
1. **Change the window:** show 14 or 30 days. Hint: `charmTrend(first.latitude, first.longitude, 30)`. With 30 dots the date labels overlap. Can you label only every 5th day? (Hint: `if (i % 5 === 0)`.)
2. **Add y-axis labels:** add `text` elements reading "0%", "50%" and "100%" at `y(0)`, `y(0.5)` and `y(1)`.
3. **Rising or falling?** Compare the last value with the first and add a line of text like "↑ up 12 points this week."
4. **Use your own data:** your data-checker saves daily C-HARM values at 9 pier sites in `data/charm_daily.csv`. Once it has run for a few weeks, try charting that file instead.

## If something breaks

- **Blank page or nothing happens:** look at the Console (F12). The error message names the line.
- **`charmTrend is not defined`:** the function is in the wrong place, or there's a typo in its name.
- **`Unexpected token`:** usually a missing `}` or `)`, or a backtick/quote mix-up.
- **Chart shows but it's empty:** run `await charmTrend(36.55, 237.96)` in the Console and check whether it returns data.

When it works, ask me to review your code. I'll point out anything worth tidying.
