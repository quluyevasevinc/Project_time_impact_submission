# VM Time & Impact

A local dashboard over the Value Management team's weekly time logs, and a
design for the system that would make its central question answerable.

**Start here:**

| Document | What it covers |
|---|---|
| [`NOTES.md`](NOTES.md) | The metrics chosen and why, the data issues found, three things for leadership, AI usage note |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Target-state design. The dashboard shows that 0.4% of logged hours can be traced to an outcome — this is the design for fixing that, upstream, where the defect is created |
| `dashboard.html` | The working dashboard. Build it with the steps below, then double-click |

## Running it

You need Python 3 (already on every Mac and most Linux machines; on Windows,
install it from python.org and tick "Add Python to PATH").

Nothing else. No `pip install`, no internet, no account.

1. Put the latest CSV exports in the `data` folder.
2. Open a terminal in this folder and run:

```bash
python3 build.py
```

3. Double-click `dashboard.html`.

That's the whole thing. `dashboard.html` is one self-contained file — it works
offline, it can be emailed, and a copy of it is a permanent snapshot of what
the numbers looked like that week.

## The weekly refresh

A new export arrives every week. To update the dashboard:

1. Drop the new file into `data`. Keep the old ones — the dashboard covers the
   whole history, and the pipeline reads every file matching `team_hours*.csv`.
2. Run `python3 build.py` again.

You do not need to rename anything, edit any code, or delete the previous
export. Specifically, the loader handles the things that actually go wrong with
a recurring export:

| What changes | What happens |
|---|---|
| A column is renamed `Opportunity Name` → `OpportunityName` | Absorbed silently. Columns are matched on letters and digits only, so spacing, punctuation and capitalisation changes are invisible to it. |
| A brand-new column appears | Reported as a `NOTE` when you run the build, so you know to decide whether it matters. Never silently dropped. |
| An expected column disappears | Reported the same way. |
| The same row appears in two exports | Byte-identical duplicates are removed. |
| The newest week is only half filled in | Detected and excluded from every figure, so Monday's dashboard doesn't show a fake collapse. Once later weeks arrive it is kept, but flagged in red as a reporting gap. |

If a run prints no `NOTE` lines, every column in every file was understood.

## What's in the folder

| File | What it is |
|---|---|
| `build.py` | What you run. Reads `data/`, writes `dashboard.html`. |
| `pipeline.py` | All the data logic: loading, cleaning, matching, aggregating. This is the file to read or change. |
| `dashboard_logic.js` | The page's computation — totals, shares, the evidence chain. Kept out of the page so it can be tested. |
| `template.html` | The page's appearance — layout, styling, charts. Not openable on its own; it says so if you try. |
| `test_pipeline.py` | Contract tests for the pipeline, plus the build and JavaScript checks. |
| `test_dashboard.js` | Contract tests for `dashboard_logic.js`. |
| `test_render.js` | A DOM stub, so the page's drawing code can run without a browser. |
| `run_js_tests.py` | Runs the JavaScript tests on whatever engine the machine has. |
| `run_render_tests.py` | Renders every tab head-first and fails on a thrown error or an unrendered value. |
| `data/` | The exports. |
| `dashboard.html` | The output. Regenerated each run. |
| `NOTES.md` | Why these metrics, what's wrong with the data, what I'd do next. |
| `ARCHITECTURE.md` | Target-state solution design. |
| `.github/workflows/` | CI: runs the tests and rebuilds the dashboard on every push, and reports any schema drift in the run summary. Publishing to GitHub Pages is opt-in — see the workflow's comments. |

## Tests

```bash
python3 -m unittest -v
```

One command covers both languages: 63 Python tests, 57 checks against the page's
computation layer, and 48 headless renders of every tab under every filter and
measure. Still no dependencies — the JavaScript runs on whatever engine is
already present (macOS ships JavaScriptCore, CI runners ship Node) and skips
rather than fails if there is none.

They are contract tests rather than unit tests: each pins an assumption the
dashboard's conclusions rest on, so a future export cannot quietly change a
number leadership is reading. Five are worth knowing about:

- One asserts the attribution rate stays **low**. If it ever looks healthy
  without a change at the point of capture, the matcher has started guessing.
- One asserts the whole-period figures are **smaller** than the quarters added
  together, because an opportunity worked across a quarter boundary belongs to
  both quarters but should be counted once overall.
- One asserts a truncated activity table **does not** sum to 100%, which is
  what it would do if its percentages were taken over a truncated total.
- One asserts most registered projects still have **no** traceable time, and
  another that a note full of register vocabulary naming no project matches
  nothing. Loose matching tripled the apparent coverage and was wrong about
  half the time; these two keep it from creeping back.
- One asserts the contested win rate stays **above** the naive one. If they
  ever match, merged duplicates and historical imports have started being
  counted as lost deals again.

The middle two are regressions. Both shipped as bugs, in page code that no test
could reach until the computation was moved into `dashboard_logic.js`.

## Two settings worth knowing about

Both are at the top of `pipeline.py`:

- **`FISCAL_START_MONTH = 2`** — the fiscal year is taken to start on 1 February.
  The CRM extract gives a fiscal period but never a close date, so the calendar
  had to be inferred rather than read. The **Data health** tab shows the evidence
  and the alternatives that were rejected. If the real calendar differs, change
  this one number and rebuild.
- **`BULK_MIN_MEDIAN_ROW_HOURS` / `BULK_MAX_ROWS_PER_WEEK`** — the test that
  separates people who log task by task from people who book a whole week to a
  single line. This distinction drives a lot of the dashboard's warnings; the
  **People** tab shows who falls on each side and why.
