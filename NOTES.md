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
shows what survives the one before. 0.4% of logged hours can be found in the
CRM at all; **0.16% sit on a deal that was actually won** — 21 hours of
13,328. Half the matched *deals* turned out to be administrative closures,
which is 20.5 of the 54 matched hours. The front page carries both figures
rather than the kinder one. Any win-rate or value-per-hour figure built on this data
today would be fabricated; the dashboard shows the gap instead of filling it.

**Two signals the form already carries and nothing reads.** Preparation and
delivery hours sit in separate columns: Value Based Discovery is 68%
preparation, Case for Change Presentation 65% — activities that cost more to
get ready for than to do, which is a capacity fact no headline shows. And the
audience field records seniority, so the work that *is* presented can be placed:
55% of it reaches VP or above. Neither needed new data, only reading what was
already there.

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
  carries. Matching on the name reaches 16 of 307 — 0.4% of logged hours. The
  other 291 cannot be traced, and are not presented as if they could.
  I shipped a worse version of this first. A third tier treated a deal value
  appearing against exactly one CRM opportunity as a match, and took the count
  from 16 to 39. It was a coincidence detector: **93% of the CRM's amounts are
  already unique**, so "appears exactly once" filtered almost nothing. Reading
  the matches instead of the count, 20 of the 23 linked companies with no word
  in common — a logged "Bluepoint Retail" deal resolved to an account called
  Orchardmark Insurance — and two different logged opportunities both landed on
  the same $31,500 deal. Removed.
  The surviving 16 are corroborated in the direction that can fail: 15 of them
  also agree on deal value. The account name cannot be used for this, because
  in the CRM extract itself opportunity name and account name correspond only
  about half the time.
- **A quarter of the "closed" book was never won or lost.** 79 of 343
  opportunities are merged duplicates, records imported for history, or deals
  rejected before qualification — and the CRM files every one of them under the
  stage group `Lost`. Reading that field at face value, which is the obvious
  thing to do, puts the win rate at 32.4%. On genuinely contested deals it is
  42.0%. Ten points, purely from counting administrative housekeeping as
  defeat. The pipeline separates the two, the evidence chain has a step for it,
  and 8 of the 16 matched opportunities turned out to sit in that bucket —
  half of an already small evidence base.
- **No close date in the CRM extract**, only a fiscal period, so the fiscal
  calendar had to be inferred — and the inference is weaker than I would like,
  so here is exactly what it rests on. Candidates are ranked first on work
  never landing *after* the quarter a deal closed in, which is impossible for
  pre-sale work. **That test eliminates exactly one candidate: January, at
  94%.** The other eleven all score 100%, so the ranking falls through to
  same-quarter frequency, where February leads on 62% against March's 19%.
  The awkward part is that January — the one the first test eliminates — is
  also the one that would win on same-quarter frequency alone, at 75%. On
  sixteen matched deals none of this settles the question. February is used
  because it clears the first test and leads the remaining eleven on the
  second — not because the others failed anything; March also scores 100% and
  simply ranks lower on same-quarter frequency. The dashboard shows the
  alternative rather than presenting February as established. It is
  one constant to change if the real calendar is known.

**Behavioural — the ones that actually distort the answer**

- **Bulk logging.** Ten people file one or two rows a week of 20–40h each,
  against a median of seven rows a week elsewhere, some as short as 15 minutes.
  Not an error, but it makes hours non-comparable and inflates whichever
  category those people default to. Handled by person-weeks, by per-bar
  bulk-share labels, and by an itemised-only recomputation.
- **Uneven reporting coverage**, and the denominator matters. Two people whose
  tenure is recorded as zero first appear in late August and have filed every
  week since; a flat 24-week denominator put them at 29% — bottom of the team,
  when they are actually at 100%. Their coverage is counted from their first
  logged week instead.
  I first applied that rule on first-appearance alone, which flagged nine
  people — including several with four to six years of tenure who had simply
  missed the opening weeks, and whose scores it quietly improved. Tenure is the
  only corroborating signal in the data, so the shortened denominator now
  requires it. Unknown tenure counts as present from the start, which costs a
  few points rather than inventing a hire date.
  Coverage runs from 25% to 100%, shown per person rather than averaged away.
- **Weeks over 40 hours**, up to 104. These are not one thing, and I did not
  treat them as one: the 104-hour week is 18 rows carrying 10 distinct notes —
  four of them repeated two to four times, which reads as the same activity
  run for several customers rather than one entry duplicated. Two other large
  weeks *are* straightforward duplicates: one piece of work filed twice with
  different hours against identical notes, a correction nobody cleaned up. Person-weeks neutralise the effect of both on team totals
  without me having to guess which is which; the duplicates are left in place
  and flagged rather than silently deleted, since only the person who filed
  them can say which entry was right.
- **Three people log close to a flat 32h a week**, almost entirely to Training
  & Development with notes like "Onboarding Training". Two file exactly 32.0h
  every week; the third varies between 31h and 33h. Two of them have zero
  years' tenure, so onboarding fits — the third has two years, which does not,
  and is worth a question rather than an assumption. Either way it is a
  placeholder shape and says little about team priorities.

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
- **The project register joins, but only on what people declare.** The time
  form has no project field. What it does have is free text, and people put
  structure in it themselves: a `Project:` line or a `#tag`. Those labels carry
  12.4% of hours and match the register reliably — 10 of its 35 projects and
  1,034 hours, nineteen times what the CRM join can account for.
  I first tried matching the notes *as prose* against register names. It looked
  far better — 36% of hours — and it was wrong: register names share words like
  "customer", "evidence" and "strategy", so a recruitment note was confidently
  filed under a platform project and a healthcare study under an AI one. I
  checked a random sample rather than the headline, found roughly half the
  matches were false, and threw the approach away. The three tiers that
  survived are exact name, one name containing the other, and every significant
  register word appearing in the declared label.
  **The number that matters here is not what matched — it is that 25 of 35
  registered projects have no traceable time at all**, four of them already
  marked complete. The work happened; the time log cannot show it.

---

## 3. Three things I'd tell leadership

**1. You cannot currently answer the question you are asking, and the fix is one
field.** 16% of logged hours name an opportunity; **0.4%** can be traced to a
deal that closed. The blocker is not effort or discipline — it is that the time
log captures a typed opportunity *name* while the CRM uses an *id*, so the two
systems cannot be joined. Sixteen of 307 opportunities match, and only because
somebody happened to type the name exactly. Put an opportunity picker in the
time form that writes the id, and this dashboard starts answering "what did the
investment produce" in one quarter, with no other change.

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

*Also worth knowing, on the CRM rather than the team: 23% of the closed book
was never contested — merged duplicates, historical imports, pre-qualification
rejects — and all of it is filed as "Lost". Any win rate read straight off that
field understates the real one by about ten points (32.4% against 42.0%). That
is worth fixing before it reaches a board pack, and it is not a Value
Management problem to solve.*

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
2. **Fuzzy-match the remaining opportunities — with a review queue, not
   silently.** 291 are unmatched. Token-set matching on the account prefix,
   each candidate scored and shown to a human before it counts. I would not
   repeat the mistake of letting a rule add matches on its own authority:
   anything below a high confidence threshold should sit in a queue, and the
   dashboard should show the confidence mix so degradation is visible.
3. **A project field in the time form.** The same fix as the opportunity
   picker, and the same shape of win: project attribution would go from 7.8% of
   hours to near-complete, and the portfolio view would stop being an estimate.
   Until then, a tag picker instead of free-text hashtags would help on its own
   — `#flexcredits` is currently spelled three different ways.
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

8. **Separate "lost to inaction" from "lost to a competitor" in the pipeline
   review.** 124 of the 153 contested losses were to inaction, against 29 to a
   named rival — four to one. Excluding inaction would raise the headline win
   rate from 42% to 79%, which is why the dashboard shows the split and not a
   second win rate. But the ratio itself is the actionable part: losing mostly
   to "do nothing" is the problem a value case is built to solve, and it says
   the function is pointed at the right target even where the evidence chain
   cannot prove it.

9. **Portfolio coverage as a standing question.** 25 registered projects are
   invisible in the hours. Some are genuinely small; some are large and simply
   untagged. Only the project leaders can tell which, and that is a ten-minute
   conversation per leader, not an analysis.

**Not done, and deliberately:** no ROI or value-per-hour figure, and no
per-person productivity ranking. The first needs the CRM join; the second needs
comparable reporting behaviour. Both would have been easy to produce and wrong.

The touched-versus-untouched win rate is the one I *did* put on the page, and
deliberately so: someone always computes it, and it is better found with its
limits attached than quoted without them. It reads 75% against 41% and it is
not a finding — it rests on eight deals, two of which landing the other way
would move it twenty-five points, and Value Managers are assigned to the deals
most likely to close anyway. The card says all of that underneath the bars. The
honest version needs a matched control, and that is phase 4 of the architecture
note, not something this data supports.

---

## 5. AI usage note

I used Claude (in Claude Code) throughout: profiling the CSVs, building the
stdlib loader and aggregation, and writing the dashboard's HTML and charts. It
was fastest at the mechanical work — schema normalisation, the tiered matcher,
the SVG chart code — and at turning a finding I'd confirmed into readable prose.

Five things it got wrong that I caught:

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

**The one I would most want you to know about.** To bridge the missing join I
added a rule: if a logged deal value appears against exactly one CRM
opportunity, treat that as the same deal. Attribution went from 16 matches to
39, and I wrote it up as a clever recovery — deal value as a fingerprint.

I had even "validated" it. I checked that opportunities matched by name also
agreed on amount. They do, 15 of 16. What I never checked was the other
direction: whether opportunities matched by *amount* agreed on *name*. They do
not. 20 of the 23 linked companies with no word in common — a logged
"Bluepoint Retail" deal resolved to an account called Orchardmark Insurance —
and two separate logged opportunities both resolved to the same $31,500 deal.

The rule was never a fingerprint. 93% of the CRM's amounts are already unique,
so "appears exactly once" filtered essentially nothing; it matched on
coincidence. The headline figure fell from 1.3% to 0.4% when I removed it, and
the fiscal-calendar inference had been resting on those false matches too.

Two things I take from it. **Validating a rule in the direction that confirms
it is not validation** — the check has to be able to fail. And a number that
jumps when you add a clever step deserves more suspicion than a number that
does not: this is the third time in this project that the more impressive
figure turned out to be the wrong one.

**A join that looked three times better than it was.** Matching the time log's
free text against project names returned 36% of hours — a headline I wanted to
be true, and the model was happy to confirm. Reading a random sample of the
matches instead of the total showed roughly half were wrong: notes about
recruitment filed under a platform project, a healthcare study under an AI one,
because the register's names share ordinary words. Restricting the join to
labels people declare themselves cut the number to 7.8% and made every match
checkable. The lesson is the one that keeps recurring here: **a number that
improves when you stop looking closely is not an improvement.**

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
