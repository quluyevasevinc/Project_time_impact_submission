# Notes

Covering 2026-04-27 to 2026-10-12: 24 complete weeks, 25 people, 13,328 logged
hours. Fiscal year taken to start 1 February, so this is FY27 Q1 (one week),
Q2 (13 weeks) and Q3 (10 weeks).

---

## 1. The metrics and views, and why

The brief asks where the team invests its time and what that investment
produces. The data answers the first question well and the second one barely at
all — so the dashboard is built to say so rather than to produce a confident
number with nothing underneath it.

**Person-weeks, not hours, as the default unit.** One person logging one week
counts as 1.0, split across their rows in proportion to the hours they booked.
Median weekly hours across the team run from 12.5h to 41.5h, and one person
booked a 104-hour week. That spread is reporting behaviour, not workload, and
raw hours silently weight the analysis toward whoever writes the biggest
numbers. Person-weeks make a 12-hour logger and a 40-hour logger comparable.
The raw-hours view is still one click away, because it is the right unit for
capacity questions — just not for priority questions.

**Two populations, shown separately wherever it matters.** Ten of 25 people
book most of a week to a single line; they are 36% of all logged hours. Person-
weeks fix the *volume* distortion this causes but not the *granularity* one — a
bulk logger's whole week still lands on one activity. So every activity bar
carries the share of itself that came from bulk logging, and a dedicated panel
recomputes the ranking over itemised loggers only. This is the difference
between "the team spends 39% of its time on Digital Experience Management" and
what is actually true.

**An evidence chain instead of an ROI number.** Logged hours → names an
opportunity → that opportunity found in the CRM → that deal was won. Each step
shows what survives the one before. The honest headline is that 1.3% of logged
hours can be traced to a closed deal, and the funnel shows exactly where the
other 98.7% falls out. Any win-rate or value-per-hour figure built on this data
today would be fabricated; the dashboard shows the gap instead of filling it.

**Reporting coverage as a first-class metric, not a footnote.** 72% of possible
person-weeks were actually filed, and the per-person strip shows which weeks
each person missed. Every absolute total understates reality by roughly that
much, unevenly by person, and leadership needs to see that before reading any
trend.

**Quarter as the primary cut**, since that is how leadership reviews, with
quarters holding fewer than four reported weeks marked as stubs so the one-week
Q1 at the edge of the export is never read as a collapse.

---

## 2. Data issues found, and how they were handled

**Structural**

- **Column names drift between exports.** `Opportunity Name` became
  `OpportunityName`; `HoursTotal` became `Hours Total`. The loader matches
  columns on letters and digits only, so punctuation and spacing changes cannot
  break it, and it reports any column it does not recognise rather than dropping
  it silently.
- **Nothing joins the time log to the CRM.** The time log names an opportunity
  by hand-typed text; the CRM extract identifies it by an id the time log never
  carries. Exact names matched 16 of 307. Matching was extended in tiers —
  exact name, then punctuation-normalised name, then a deal value unique enough
  to identify exactly one opportunity — which reached 39. Each match records
  which tier produced it, and the dashboard shows the mix. The remaining 268
  cannot be traced, and are not presented as if they could.
- **No close date in the CRM extract**, only a fiscal period, so the fiscal
  calendar had to be inferred. Every possible year-start was scored on whether
  matched work lands in or before the quarter the deal closed in; 1 February
  won (46% exact, 77% work-before-close) and the runners-up are shown on the
  Data health tab. It is one constant to change if that's wrong.

**Behavioural — the ones that actually distort the answer**

- **Bulk logging.** Ten people file one or two rows a week of 20–40h each,
  against a median of seven rows a week elsewhere, some as short as 15 minutes.
  Not an error, but it makes hours non-comparable and inflates whichever
  category those people default to. Handled by person-weeks, by per-bar
  bulk-share labels, and by an itemised-only recomputation.
- **Uneven reporting coverage.** From 25% to 100% of weeks filed. Shown per
  person rather than averaged away.
- **Weeks over 40 hours**, up to 104. These are not one thing, and I did not
  treat them as one: the 104-hour week is 18 detailed rows of distinct work,
  while two of the others are a single piece of work filed twice in the same
  week with different hours against identical notes — a correction that was
  never cleaned up. Person-weeks neutralise the effect of both on team totals
  without me having to guess which is which; the duplicates are left in place
  and flagged rather than silently deleted, since only the person who filed
  them can say which entry was right.
- **Three people log close to a flat 32h a week**, mostly to Training &
  Development with notes like "Onboarding Training". Two file exactly 32.0h
  every week; the third varies between 31h and 33h and splits across three
  activities. Real work — they are new starters — but a placeholder shape, and
  their time says little about team priorities.

**Mechanical**

- Two byte-identical duplicate rows — removed.
- The final week (2026-10-12) had 17 rows against a median of 112 and two people
  reporting against a median of 18. Treated as still filling in and excluded
  from every figure. Once later weeks arrive it stays in the totals but is
  flagged red, because dropping a real reporting gap would flatter every average.
- Activity + preparation + travel reconciles to the stated total on every row —
  checked, zero mismatches, and the check stays in so a future export can't
  break it quietly.
- `VM Digital COE` and `VM, Digital COE` are one unit spelled two ways; rolled
  together for department totals with the manager column still separating the
  sub-teams. Two departments carry no manager at all and are shown as
  "(none recorded)" rather than grouped into a blank bucket.
- **Deliberately not done:** the project register was inspected by hand but is
  not loaded by the pipeline. Nothing in the time log carries a project id, so
  any link would have been a guess presented as a fact.

---

## 3. Three things I'd tell leadership

**1. You cannot currently answer the question you are asking, and the fix is one
field.** 16% of logged hours name an opportunity; 1.3% can be traced to a deal
that closed. The blocker is not effort or discipline — it is that the time log
captures a typed opportunity *name* while the CRM uses an *id*, so the two
systems cannot be joined. Thirty-nine of 307 opportunities could be matched, and
only by falling back on deal value as a fingerprint. Put an opportunity picker
in the time form that writes the id, and this dashboard starts answering "what
did the investment produce" in one quarter, with no other change.

**2. Your largest reported activity is mostly a measurement artefact.** Digital
Experience Management reads as 38.8% of team time. Among the 15 people who log
task by task it is 20.1%. The gap isn't extra work — it's ten people with
nowhere granular to put a week, defaulting to one bucket. Sixty-eight rows go
further and write the breakdown into free text — one 40-hour row lists four
separate workstreams with their own hours in the notes field — because the form
gives them nowhere else. That is 1,484 hours of detail the team is already
producing and the system throws away. Until the
form offers sub-activities, treat that 38.8% as *unclassified effort*, and don't
let it drive headcount or priority decisions.

**3. The split between customer work and practice-building is stable, and
deliberate-looking — confirm that it's deliberate.** Across both full quarters,
roughly three-quarters of effort goes to Practice Strategy & Management and
about a quarter to opportunity and account work (Q2 16.5% / 7.1%, Q3 18.4% /
6.1%); customer-facing effort sits at 8.5–9.5%. That is very steady, so it
reflects how the team is actually set up rather than quarterly noise. The team
touched $28.8M of pipeline in Q2 and $26.4M in Q3. If a 75/25 internal-to-
customer split is the intent for a value *management* function, the data says
it's being executed consistently. If leadership believes the team is mostly
deal-facing, the data disagrees — and that's the conversation to have, not a
number to optimise.

*Also worth knowing: 72% reporting coverage means every absolute total here
understates reality, unevenly by person. Fix the attribution problem first, and
the coverage problem second — improving coverage without the join just produces
a more precise number that still can't be connected to an outcome.*

---

## 4. What I'd do next

In rough order of value per hour spent:

1. **Parse the free-text notes.** 68 rows carry their own hour breakdown in
   plain English. A parser plus a reviewed mapping would recover 1,484 hours of
   detail that currently sits in the unclassified bucket, and would quantify how
   much the form is costing in lost resolution.
2. **Fuzzy-match the remaining opportunities.** Token-set matching on the
   account prefix, scored and surfaced for human confirmation rather than
   applied silently. 268 opportunities are currently unmatched; recovering even
   a third of them would take the evidence base from 39 deals to over 120. The
   tiering is already in place to hold a confidence level per match.
3. **Join the project register** — but only after agreeing a project id in the
   time form. Guessing is worse than the gap.
4. **Track coverage as an operational metric** with a per-manager view, so the
   72% moves. The strip view is already there; it needs an owner.
5. **Trend over quarters** once there are three or more full ones. Two quarters
   plus a one-week stub is not a trend, and I'd rather show a stub label than a
   line with two points on it.
6. **Open-pipeline context.** The CRM extract holds only closed deals, so most
   opportunity work here has no outcome to point at *yet* — that's not missing
   data. An open-pipeline extract would show work in flight rather than only
   post-mortems.

7. **Property-based tests on the loader.** The contract tests pin the shapes I
   know about. Generating malformed exports — reordered columns, mixed date
   formats, stray encodings — would find the ones I don't.

**Not done, and deliberately:** no ROI or value-per-hour figure, no win-rate
comparison between touched and untouched deals, no per-person productivity
ranking. The first two need the CRM join; the third needs comparable reporting
behaviour. All three would have been easy to produce and wrong.

---

## 5. AI usage note

I used Claude (in Claude Code) throughout: profiling the CSVs, building the
stdlib loader and aggregation, and writing the dashboard's HTML and charts. It
was fastest at the mechanical work — schema normalisation, the tiered matcher,
the SVG chart code — and at turning a finding I'd confirmed into readable prose.

Three things it got wrong that I caught:

**The one that would have changed the answer.** Once I had person-weeks working,
the model treated the problem as solved and wrote the callout claiming the
measure made the two groups of loggers comparable. The numbers said otherwise:
Digital Experience Management only moved from 38.8% to 33.2% between the two
lenses, far less than the distortion I'd measured directly when I excluded bulk
loggers (38.8% → 20.1%). The reason is that person-weeks correct for *how many
hours* someone claims but not for *how few rows* they split them across — a bulk
logger's normalised week still lands entirely on one activity. I'd have shipped
a dashboard that advertised a fix it hadn't made. That's what the bulk-share
labels and the itemised-only panel exist for.

**A plausible normalisation that was wrong.** It wanted to merge
`VM Digital COE` and `VM, Digital COE` as an obvious typo pair. They do merge —
but checking first showed the two spellings split perfectly by manager (Umar
Kessler on one, Nikolai Grieve and Clara Zeller on the other), which is exactly
what two genuinely distinct sub-teams would look like. They're rolled up with
the manager column kept as the finer cut, and the ambiguity is noted on the Data
health tab rather than resolved silently.

**Two aggregation bugs that shipped, and what I changed because of them.** The
first version of the combined "all weeks" view added the quarters together.
Both the model and I were satisfied with it. Re-reading my own output against
the raw data later, it was wrong twice over: deal value was counted twice for
any opportunity worked either side of a quarter boundary ($57.2M reported
against a true $51.5M), and because each quarter's activity table keeps only
its top rows, summing them divided by a truncated total and inflated every
share — the headline activity read 43.8% instead of 38.8%.

Worse, the written note already claimed the first problem was handled. The
document described a safeguard the code did not have.

Fixing the arithmetic was the small part. The real problem was that this code
sat inside the HTML page, where no test could reach it, so both bugs were
invisible to the suite that was passing. I moved every calculation out into
`dashboard_logic.js`, wrote tests against it, then deliberately reintroduced
both bugs to confirm the tests actually fail — they do, on seven checks. That
is why the project now tests two languages from one command.

The broader pattern: AI was reliable on code and unreliable on *whether a
problem was actually solved* — including when the thing being assessed was its
own earlier work, and including when I was the one reviewing. Every number in
this dashboard is now checked against the raw CSVs by a test rather than by a
reading, because a reading is what missed these.
