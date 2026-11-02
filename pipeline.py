"""
VM Time & Impact — data pipeline.

Standard library only, on purpose: the dashboard has to run on a leadership
laptop with nothing installed. No pandas, no pip, no virtualenv.

Reads every CSV in data/, produces one dict that the renderer turns into a
self-contained HTML file.
"""

import csv
import collections
import datetime
import glob
import os
import re
import statistics

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Fiscal year starts 1 February: FY2027 = 2026-02-01 .. 2027-01-31.
# This is inferred, not given. See infer_fiscal_start() for the evidence.
FISCAL_START_MONTH = 2

# A standard working week, used only to express coverage as a percentage.
NOMINAL_WEEK_HOURS = 40.0

# A person is a "bulk logger" if they typically file <= 2 rows a week and
# their typical row is >= 16h. Those two tests together separate someone
# allocating a whole week in one line from someone logging real tasks.
BULK_MAX_ROWS_PER_WEEK = 2
BULK_MIN_MEDIAN_ROW_HOURS = 16.0

# A trailing week is treated as still filling in if it has less than this
# share of the median week's rows.
PARTIAL_WEEK_THRESHOLD = 0.40

# Stage names that close an opportunity without anyone winning or losing it:
# duplicates folded together, records imported for history, deals rejected
# before qualification. The CRM files all of these under the stage group
# "Lost", which is the trap — counting them as losses drags the win rate down
# by ten points and treats merged duplicates as defeats.
ADMINISTRATIVE_STAGES = ("Merged", "Historical Data Only",
                         "Reject Pre-Qualified", "Qual Out")

# Below this many contested deals, a win-rate comparison is noise. Used to
# label the figure, not to hide it.
MIN_DEALS_FOR_COMPARISON = 30


# ---------------------------------------------------------------------------
# Column handling — survives the weekly export changing its mind
# ---------------------------------------------------------------------------

def squash(name):
    """'Hours Total', 'HoursTotal' and 'hours_total' all collapse to the same key."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# canonical field -> every spelling seen in the wild
HOURS_ALIASES = {
    "week_of":            ["weekof", "weekbeginning", "weekstart"],
    "activity_type":      ["activitytype"],
    "account_name":       ["accountname", "account"],
    "opportunity_name":   ["opportunityname"],
    "opportunity_amount": ["opportunitysalesupliftusd", "opportunityamountusd"],
    "date_completed":     ["valuedatecompleted", "datecompleted"],
    "person":             ["valuemanager", "valuemanagername"],
    "department":         ["department"],
    "tenure_years":       ["tenureyears"],
    "manager":            ["vmmanager", "manager"],
    "activity_category":  ["valueactivitycategory", "activitycategory"],
    "activity":           ["valueactivity"],
    "audience":           ["valueaudience", "audience"],
    "prospect_facing":    ["prospectfacingactivity", "prospectfacing"],
    "activity_hours":     ["activityhours"],
    "prep_hours":         ["preparationhours", "prephours"],
    "travel_hours":       ["travelhours"],
    "hours_total":        ["hourstotal", "totalhours"],
    "notes":              ["notes"],
    "leader_notes":       ["leadernotes"],
}

OPP_ALIASES = {
    "account_id":     ["accountid"],
    "account_name":   ["accountname"],
    "opp_id":         ["opportunityid"],
    "opp_name":       ["opportunityname"],
    "stage_name":     ["opportunitystagename"],
    "owner":          ["opportunityownername"],
    "amount":         ["opportunityamountusd"],
    "stage_group":    ["opportunitystagegroup"],
    "fiscal_period":  ["opportunityclosedatefiscalperiod"],
    "segment":        ["opportunitysegment"],
    "region":         ["opportunityregion"],
    "sub_region":     ["opportunitysubregion"],
    "super_industry": ["superindustry"],
    "industry":       ["industry"],
    "sub_industry":   ["subindustry"],
    "account_type":   ["accounttype"],
    "opp_type":       ["opportunitytype"],
}


REGISTER_ALIASES = {
    "body_of_work":   ["vmcoebodyofwork", "bodyofwork"],
    "sub_body":       ["subbodiesofwork", "subbodyofwork"],
    "project":        ["projecttasks", "projecttask", "project"],
    "description":    ["projecttaskdescription", "description"],
    "leader":         ["leader"],
    "project_team":   ["projectteam"],
    "stakeholders":   ["stakeholders"],
    "target":         ["targetdelivery", "target"],
    "status":         ["status"],
}


def build_lookup(aliases):
    out = {}
    for canonical, spellings in aliases.items():
        for spelling in spellings:
            out[spelling] = canonical
    return out


def read_csv(path, aliases, warnings):
    """Read a CSV into canonical-keyed dicts, reporting any column we don't know."""
    lookup = build_lookup(aliases)
    records = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        unknown = [h for h in headers if squash(h) not in lookup]
        if unknown:
            warnings.append(
                f"{os.path.basename(path)}: {len(unknown)} column(s) not recognised and "
                f"ignored — {', '.join(repr(u) for u in unknown)}"
            )
        missing = set(aliases) - {lookup[squash(h)] for h in headers if squash(h) in lookup}
        if missing:
            warnings.append(
                f"{os.path.basename(path)}: expected column(s) absent — "
                f"{', '.join(sorted(missing))}"
            )
        for raw in reader:
            row = {key: "" for key in aliases}
            for header, value in raw.items():
                canonical = lookup.get(squash(header))
                if canonical:
                    row[canonical] = (value or "").strip()
            row["_source"] = os.path.basename(path)
            records.append(row)
    return records


# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------

def to_float(value, default=0.0):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def to_date(value):
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def fiscal_quarter(day, start_month=FISCAL_START_MONTH):
    """Return ('FY2027', 2, 'FY27 Q2') for a date."""
    offset = (day.month - start_month) % 12
    quarter = offset // 3 + 1
    year = day.year + (1 if day.month >= start_month else 0)
    return f"FY{year}", quarter, f"FY{str(year)[2:]} Q{quarter}"


def normalise_opp_name(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def normalise_department(name):
    """
    'VM Digital COE' and 'VM, Digital COE' are the same org unit typed two ways.
    They are kept apart in the source but roll up together here; the manager
    column still separates the sub-teams underneath.
    """
    squashed = squash(name)
    if squashed == "vmdigitalcoe":
        return "VM Digital COE"
    return name or "(unspecified)"


# ---------------------------------------------------------------------------
# Load and clean
# ---------------------------------------------------------------------------

def load(data_dir):
    warnings = []
    issues = collections.OrderedDict()

    hour_files = sorted(glob.glob(os.path.join(data_dir, "team_hours*.csv")))
    if not hour_files:
        raise SystemExit(
            f"No time-log files found in {data_dir}.\n"
            f"Expected at least one file named like "
            f"'team_hours_export_<start>_to_<end>.csv'."
        )

    rows = []
    for path in hour_files:
        rows.extend(read_csv(path, HOURS_ALIASES, warnings))
    raw_count = len(rows)

    # --- exact duplicate rows -------------------------------------------------
    seen = set()
    deduped = []
    duplicates = 0
    for row in rows:
        fingerprint = tuple(row[key] for key in sorted(HOURS_ALIASES))
        if fingerprint in seen:
            duplicates += 1
            continue
        seen.add(fingerprint)
        deduped.append(row)
    rows = deduped

    # --- parse ----------------------------------------------------------------
    unparsed_week = 0
    arithmetic_mismatch = 0
    for row in rows:
        week = to_date(row["week_of"])
        if week is None:
            unparsed_week += 1
            continue
        row["_week"] = week.isoformat()
        fy, q, label = fiscal_quarter(week)
        row["_fy"], row["_q"], row["_quarter"] = fy, q, label

        parts = sum(to_float(row[k]) for k in ("activity_hours", "prep_hours", "travel_hours"))
        total = to_float(row["hours_total"])
        if abs(parts - total) > 0.01:
            arithmetic_mismatch += 1
            total = parts if parts > 0 else total
        row["_hours"] = total

        row["_department"] = normalise_department(row["department"])
        row["_prospect_facing"] = row["prospect_facing"] == "Prospect Facing"
        row["_presented"] = bool(row["audience"]) and row["audience"] != "Not Presented"
        row["_opp_key"] = normalise_opp_name(row["opportunity_name"])
    rows = [r for r in rows if "_week" in r]

    # --- opportunities --------------------------------------------------------
    opp_path = os.path.join(data_dir, "closed_opportunities.csv")
    opportunities = read_csv(opp_path, OPP_ALIASES, warnings) if os.path.exists(opp_path) else []
    for opp in opportunities:
        opp["_amount"] = to_float(opp["amount"])
        opp["_key"] = normalise_opp_name(opp["opp_name"])
        opp["_won"] = opp["stage_group"] == "Won"
        opp["_administrative"] = any(s in opp["stage_name"]
                                     for s in ADMINISTRATIVE_STAGES)
        opp["_contested"] = not opp["_administrative"]

    register_path = os.path.join(data_dir, "project_register.csv")
    register = (read_csv(register_path, REGISTER_ALIASES, warnings)
                if os.path.exists(register_path) else [])
    register = [r for r in register if r["project"].strip()]

    issues["Duplicate rows removed"] = duplicates
    issues["Rows with an unreadable 'Week of'"] = unparsed_week
    issues["Rows where the hour columns did not add up"] = arithmetic_mismatch

    return {
        "rows": rows,
        "opportunities": opportunities,
        "register": register,
        "warnings": warnings,
        "issues": issues,
        "raw_count": raw_count,
        "files": [os.path.basename(p) for p in hour_files],
    }


# ---------------------------------------------------------------------------
# Opportunity matching — there is no shared key, so match in tiers
# ---------------------------------------------------------------------------

def match_opportunities(rows, opportunities):
    """
    The time log carries an opportunity *name* typed by hand; the CRM extract
    carries an opportunity *id*. Nothing joins them directly, so matching is
    done on the name alone, in two tiers, each recorded against the match.

    An earlier version added a third tier: if a logged deal value appeared
    against exactly one CRM opportunity, treat that as a match. It tripled the
    hit rate, and it was wrong. 93% of the CRM's deal values are already
    unique, so "appears exactly once" filters almost nothing — it matches on a
    coincidence of amount. Checking the results rather than the count, 20 of
    those 23 matches linked companies with no word in common, and two different
    logged opportunities both landed on the same deal. The three that did share
    a word shared only "retail", "insurance" or "services".

    The mistake was validating the rule in the direction that confirmed it:
    name-matched pairs were checked for agreement on amount, which they have,
    and amount-matched pairs were never checked for agreement on name, which
    they do not.
    """
    by_exact = {o["opp_name"].strip(): o for o in opportunities if o["opp_name"].strip()}
    by_key = {}
    for opp in opportunities:
        by_key.setdefault(opp["_key"], []).append(opp)
    matches = {}   # opportunity name as typed -> (opp, tier)
    for row in rows:
        name = row["opportunity_name"]
        if not name or name in matches:
            continue
        if name in by_exact:
            matches[name] = (by_exact[name], "exact name")
            continue
        candidates = by_key.get(row["_opp_key"], [])
        if len(candidates) == 1:
            matches[name] = (candidates[0], "normalised name")

    for row in rows:
        hit = matches.get(row["opportunity_name"])
        row["_matched_opp"] = hit[0] if hit else None
        row["_match_tier"] = hit[1] if hit else None
    return matches


def infer_fiscal_start(rows, matches):
    """
    Evidence for FISCAL_START_MONTH. The CRM extract gives a fiscal period but
    no close date, so the calendar has to be inferred. For each matched
    opportunity, work usually lands in or before the quarter it closes in.
    Score every possible year-start on that pattern.
    """
    weeks_by_opp = collections.defaultdict(list)
    for row in rows:
        if row["_matched_opp"]:
            weeks_by_opp[row["opportunity_name"]].append(datetime.date.fromisoformat(row["_week"]))

    scores = []
    for start_month in range(1, 13):
        same = before_or_same = total = 0
        for name, weeks in weeks_by_opp.items():
            opp = matches[name][0]
            period = opp["fiscal_period"]
            m = re.match(r"(\d{4})-Q(\d)", period or "")
            if not m:
                continue
            close = (int(m.group(1)), int(m.group(2)))
            fy, q, _ = fiscal_quarter(max(weeks), start_month)
            work = (int(fy[2:]), q)
            total += 1
            if work == close:
                same += 1
            if work <= close:
                before_or_same += 1
        if total:
            scores.append({
                "start_month": start_month,
                "month_name": datetime.date(2000, start_month, 1).strftime("%B"),
                "same_quarter_pct": round(100.0 * same / total),
                "work_before_close_pct": round(100.0 * before_or_same / total),
                "sample": total,
            })
    # Ranked on "no impossible cases" first: work logged *after* the quarter a
    # deal closed in should not happen for pre-sale work, so a calendar that
    # produces none of those is preferred over one that merely lands in the
    # same quarter more often. On this sample the two criteria disagree, and
    # the margin is thin either way — which the dashboard says out loud.
    scores.sort(key=lambda s: (-s["work_before_close_pct"], -s["same_quarter_pct"]))
    return scores


# ---------------------------------------------------------------------------
# People — how each person logs, which decides how their hours can be read
# ---------------------------------------------------------------------------

def profile_people(rows, all_weeks):
    """
    Coverage is measured from the start of the export, except for people who
    demonstrably were not there yet.

    Two people joined in late August and have filed every week since; against a
    24-week denominator they read as the worst reporters on the team at 29%,
    which is the opposite of the truth. But "first week they appear" alone is
    not enough to establish a start date — most people who first appear in week
    two simply missed week one, and several of them have four to six years of
    tenure. So the shortened denominator is applied only where tenure is
    recorded as zero, which is the one corroborating signal available.
    Unknown tenure is treated as present from the start: the conservative
    reading, since it costs a few points of coverage rather than inventing a
    hire date.
    """
    by_person = collections.defaultdict(list)
    for row in rows:
        by_person[row["person"]].append(row)

    people = {}
    for name, person_rows in by_person.items():
        weeks = collections.defaultdict(list)
        for row in person_rows:
            weeks[row["_week"]].append(row)
        weekly_hours = {w: sum(r["_hours"] for r in rs) for w, rs in weeks.items()}
        first_week = min(weeks)
        tenure = to_float(person_rows[0]["tenure_years"], default=None)
        joined_late = (first_week > all_weeks[0]) and tenure == 0
        weeks_since_joining = ([w for w in all_weeks if w >= first_week]
                               if joined_late else list(all_weeks))
        rows_per_week = statistics.median(len(rs) for rs in weeks.values())
        median_row = statistics.median(r["_hours"] for r in person_rows)
        is_bulk = (rows_per_week <= BULK_MAX_ROWS_PER_WEEK
                   and median_row >= BULK_MIN_MEDIAN_ROW_HOURS)
        people[name] = {
            "name": name,
            "department": person_rows[0]["_department"],
            "manager": person_rows[0]["manager"] or "(none recorded)",
            "tenure": tenure,
            "weeks_reported": len(weeks),
            "weeks_possible": len(weeks_since_joining),
            "weeks_in_export": len(all_weeks),
            "first_week": first_week,
            "joined_late": joined_late,
            "coverage_pct": round(100.0 * len(weeks) / len(weeks_since_joining))
                            if weeks_since_joining else 0,
            "coverage_pct_naive": round(100.0 * len(weeks) / len(all_weeks))
                                  if all_weeks else 0,
            "total_hours": round(sum(weekly_hours.values()), 1),
            "median_week_hours": round(statistics.median(weekly_hours.values()), 1),
            "max_week_hours": round(max(weekly_hours.values()), 1),
            "rows_per_week": rows_per_week,
            "median_row_hours": median_row,
            "style": "bulk" if is_bulk else "itemised",
            "weekly_hours": weekly_hours,
        }
    return people


def assign_person_weeks(rows, people):
    """
    The comparable unit.

    One person logging one week counts as 1.0 person-week of effort, split
    across their rows in proportion to the hours they logged. Someone who
    books 12h and someone who books 104h in the same week each contribute
    exactly one week of a person's attention — which is the truth, and which
    raw hours badly misstate.
    """
    totals = collections.defaultdict(float)
    counts = collections.Counter()
    for row in rows:
        totals[(row["person"], row["_week"])] += row["_hours"]
        counts[(row["person"], row["_week"])] += 1
    for row in rows:
        key = (row["person"], row["_week"])
        bucket = totals[key]
        if bucket > 0:
            row["_person_weeks"] = row["_hours"] / bucket
        else:
            # Someone filed the week but booked every row at zero hours. They
            # still reported, so the week must still count as 1.0 — otherwise
            # it vanishes from the totals and quietly deflates coverage.
            # Split it evenly, since there is nothing to weight by.
            row["_person_weeks"] = 1.0 / counts[key]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def share_table(rows, dimension, value_key, limit=None, bulk_names=None):
    """
    Share of effort by one dimension.

    When bulk_names is supplied, each entry also carries the share of its own
    effort that came from people who book a whole week to a single line. A
    category sitting at 60%+ on that figure is not a measurement of what the
    team did — it is a measurement of how four or five people fill in a form.
    """
    totals = collections.defaultdict(float)
    bulk_totals = collections.defaultdict(float)
    for row in rows:
        key = row[dimension] or "(blank)"
        totals[key] += row[value_key]
        if bulk_names and row["person"] in bulk_names:
            bulk_totals[key] += row[value_key]
    grand = sum(totals.values()) or 1.0
    table = []
    for key, value in totals.items():
        entry = {"label": key, "value": round(value, 2),
                 "pct": round(100.0 * value / grand, 1)}
        if bulk_names is not None:
            entry["bulk_pct"] = round(100.0 * bulk_totals[key] / value, 0) if value else 0
        table.append(entry)
    table.sort(key=lambda d: -d["value"])
    return table[:limit] if limit else table


# Workstream tags people write by hand, and their observed misspellings.
TAG_ALIASES = {"flexcredist": "flexcredits", "felxcredits": "flexcredits"}

# Words too common in this register to identify a project on their own.
PROJECT_STOPWORDS = {"the", "and", "for", "with", "value", "project", "support", "team"}

DECLARED_PROJECT = re.compile(r"Project\s*:\s*(.+?)\s*(?:\n|$)", re.I)
DECLARED_TAG = re.compile(r"#(\w[\w-]*)")


def project_tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in PROJECT_STOPWORDS}


def declared_projects(notes):
    """
    Project labels the person wrote themselves — "Project: X" lines and
    #hashtags. Only these are used. Matching free prose against the register
    was tried and abandoned: project names here share words like "customer",
    "evidence" and "strategy", so loose matching confidently filed recruitment
    notes under a platform project. A smaller trustworthy number beats a larger
    one built on guesses.
    """
    labels = [m.strip() for m in DECLARED_PROJECT.findall(notes or "")]
    labels += [TAG_ALIASES.get(t.lower(), t.lower())
               for t in DECLARED_TAG.findall(notes or "")]
    return [L for L in labels if L]


def match_projects(rows, register):
    """
    Tie logged time to the project register, in three tiers of decreasing
    certainty, and record which tier produced each match.

    Tier 1  the declared label is the register name
    Tier 2  one name contains the other
    Tier 3  every significant word of the register name appears in the label
            (catches "RHT/Manufacturing/Energy & Utilities Industry Evidence
            Gap Strategy" against the register's shorter wording)
    """
    indexed = []
    for entry in register:
        name = entry["project"].strip()
        indexed.append((name, squash(name), project_tokens(name), entry))

    def resolve(label):
        flat = squash(label)
        words = project_tokens(label)
        if len(flat) < 5:
            return None, None
        for _, reg_flat, _, entry in indexed:
            if flat == reg_flat:
                return entry, "exact name"
        for _, reg_flat, _, entry in indexed:
            if len(flat) >= 8 and (flat in reg_flat or reg_flat in flat):
                return entry, "name contains the other"
        for _, _, reg_words, entry in indexed:
            if len(reg_words) >= 3 and reg_words <= words:
                return entry, "every register word present"
        return None, None

    unregistered = collections.Counter()
    for row in rows:
        row["_project"] = None
        row["_project_tier"] = None
        labels = declared_projects(row["notes"])
        row["_declared_project"] = bool(labels)
        for label in labels:
            entry, tier = resolve(label)
            if entry:
                row["_project"] = entry["project"].strip()
                row["_project_tier"] = tier
                break
        if labels and not row["_project"]:
            unregistered[labels[0]] += 1
    return unregistered


def funnel_for(rows):
    """
    Logged hours -> names an opportunity -> found in the CRM -> deal was won.

    Opportunities and deal values are counted once each, by name, so a deal
    worked in six different weeks contributes its value once. This matters:
    summing quarter-level funnels would double-count any opportunity worked
    across a quarter boundary, which is why the whole-period funnel is built
    here from the rows rather than added up from the quarters.
    """
    opp_rows = [r for r in rows if r["opportunity_name"]]
    matched_rows = [r for r in opp_rows if r["_matched_opp"]]

    touched = {}
    for row in opp_rows:
        touched.setdefault(row["opportunity_name"], to_float(row["opportunity_amount"]))
    matched_opps = {}
    for row in matched_rows:
        matched_opps[row["opportunity_name"]] = row["_matched_opp"]
    # An opportunity that was merged into another, or imported for history,
    # was never won or lost. It is dropped from the outcome step rather than
    # counted as a defeat.
    contested = {n: o for n, o in matched_opps.items() if o["_contested"]}
    administrative = {n: o for n, o in matched_opps.items() if o["_administrative"]}
    won = {n: o for n, o in contested.items() if o["_won"]}
    contested_rows = [r for r in matched_rows if r["_matched_opp"]["_contested"]]

    return {
        "all_hours": round(sum(r["_hours"] for r in rows), 1),
        "opp_linked_hours": round(sum(r["_hours"] for r in opp_rows), 1),
        "crm_matched_hours": round(sum(r["_hours"] for r in matched_rows), 1),
        "contested_hours": round(sum(r["_hours"] for r in contested_rows), 1),
        "won_hours": round(sum(r["_hours"] for r in contested_rows
                               if r["_matched_opp"]["_won"]), 1),
        "opps_touched": len(touched),
        "opps_matched": len(matched_opps),
        "opps_contested": len(contested),
        "opps_administrative": len(administrative),
        "opps_won": len(won),
        "win_rate": round(100.0 * len(won) / len(contested), 1) if contested else 0,
        "value_touched": round(sum(touched.values())),
        "value_matched": round(sum(o["_amount"] for o in matched_opps.values())),
        "value_contested": round(sum(o["_amount"] for o in contested.values())),
        "value_won": round(sum(o["_amount"] for o in won.values())),
    }


def projects_view(rows, register, unregistered, total_hours, crm_hours=0.0):
    """
    What the register says the team is working on, against where time actually
    went. The interesting number is not the time that matched — it is the
    projects with no traceable time at all.
    """
    by_project = collections.defaultdict(
        lambda: {"hours": 0.0, "rows": 0, "people": set(), "tiers": collections.Counter()})
    for row in rows:
        if row["_project"]:
            bucket = by_project[row["_project"]]
            bucket["hours"] += row["_hours"]
            bucket["rows"] += 1
            bucket["people"].add(row["person"])
            bucket["tiers"][row["_project_tier"]] += 1

    tracked, dark = [], []
    for entry in register:
        name = entry["project"].strip()
        record = {
            "name": name,
            "body_of_work": entry["body_of_work"] or "(unspecified)",
            "leader": entry["leader"] or "(none recorded)",
            "status": entry["status"] or "(unknown)",
            "target": (entry["target"] or "").strip() or "(none)",
        }
        if name in by_project:
            bucket = by_project[name]
            record.update({
                "hours": round(bucket["hours"], 1),
                "rows": bucket["rows"],
                "people": sorted(bucket["people"]),
                "tier": bucket["tiers"].most_common(1)[0][0],
            })
            tracked.append(record)
        else:
            dark.append(record)
    tracked.sort(key=lambda d: -d["hours"])
    dark.sort(key=lambda d: (d["status"], d["name"]))

    declared_rows = [r for r in rows if r["_declared_project"]]
    matched_hours = sum(d["hours"] for d in tracked)

    return {
        "registered": len(register),
        "tracked": tracked,
        "dark": dark,
        "matched_hours": round(matched_hours, 1),
        "matched_pct": round(100.0 * matched_hours / total_hours, 1) if total_hours else 0,
        "declared_rows": len(declared_rows),
        "declared_hours": round(sum(r["_hours"] for r in declared_rows), 1),
        "declared_pct": round(
            100.0 * sum(r["_hours"] for r in declared_rows) / total_hours, 1)
            if total_hours else 0,
        "matched_hours_value": round(matched_hours, 1),
        # How this attribution compares with the CRM one. Computed, not
        # written down: the ratio moved from 6x to 19x when a bad matching
        # tier was removed, and a hard-coded "six times" survived that change
        # in three documents.
        "times_crm": round(matched_hours / crm_hours, 1) if crm_hours else None,
        "unregistered": [{"label": k, "rows": v}
                         for k, v in unregistered.most_common(12)],
        "by_body_of_work": share_table(
            [r for r in rows if r["_project"]], "_body_of_work", "_hours"),
    }


SENIORITY_RULES = [
    ("C-suite",  ("chro", "cio - cio", "cfo", "ceo", "coo", "c-suite")),
    ("VP",       ("vp",)),
    ("Director", ("director", "head of")),
    ("Manager",  ("manager",)),
]


def seniority(audience):
    """
    Bucket the audience field by seniority. The CHRO/VP/Director distinction is
    the only signal in this data about *who* the team reaches, and nothing
    currently uses it.
    """
    text = (audience or "").lower()
    if not text or text == "not presented":
        return None
    for label, needles in SENIORITY_RULES:
        for needle in needles:
            if needle in text:
                # "oCHRO - HR Director" is a director, not a CHRO: the role
                # after the dash wins.
                tail = text.split("-")[-1]
                if label == "C-suite" and ("director" in tail or "vp" in tail
                                           or "manager" in tail):
                    continue
                return label
    return "Other"


def executive_reach(rows):
    """Where presented work actually lands, by seniority of the audience."""
    presented = [r for r in rows if r["_presented"]]
    total = sum(r["_hours"] for r in presented)
    buckets = collections.defaultdict(float)
    for row in presented:
        buckets[seniority(row["audience"]) or "Other"] += row["_hours"]
    order = ["C-suite", "VP", "Director", "Manager", "Other"]
    table = [{"label": k, "value": round(buckets[k], 1),
              "pct": round(100.0 * buckets[k] / total, 1) if total else 0}
             for k in order if buckets[k] > 0]
    exec_hours = buckets["C-suite"] + buckets["VP"]
    return {
        "table": table,
        "presented_hours": round(total, 1),
        "exec_pct": round(100.0 * exec_hours / total, 1) if total else 0,
    }


def preparation_load(rows, min_hours=150):
    """
    Preparation hours against delivery hours, by activity.

    The form has carried these in separate columns all along and nothing reads
    them apart. Some activities cost nearly twice as much to prepare as to
    deliver, which is a capacity fact no headline number shows.
    """
    split = collections.defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        split[row["activity"]][0] += to_float(row["prep_hours"])
        split[row["activity"]][1] += to_float(row["activity_hours"])
    table = []
    for activity, (prep, delivery) in split.items():
        total = prep + delivery
        if total < min_hours:
            continue
        table.append({
            "label": activity,
            "prep": round(prep, 1),
            "delivery": round(delivery, 1),
            "value": round(total, 1),
            "pct": round(100.0 * prep / total, 1) if total else 0,
        })
    table.sort(key=lambda d: -d["pct"])
    return table


def closed_book_coverage(opportunities, touched_names):
    """
    The closed book the team did *not* touch.

    Only the matched opportunities can be placed here, so this understates
    coverage badly — but a dimension with zero matched deals against seventy
    closed ones is still worth a leadership question.
    """
    contested = [o for o in opportunities if o["_contested"]]

    def cut(field):
        closed = collections.Counter(o[field] or "(blank)" for o in contested)
        seen = collections.Counter(o[field] or "(blank)" for o in contested
                                   if o["opp_name"].strip() in touched_names)
        rows = []
        for label, total in closed.most_common():
            rows.append({"label": label, "closed": total,
                         "touched": seen.get(label, 0),
                         "pct": round(100.0 * seen.get(label, 0) / total, 1)})
        return rows

    touched = [o for o in contested if o["opp_name"].strip() in touched_names]
    untouched = [o for o in contested if o["opp_name"].strip() not in touched_names]

    def rate(group):
        return round(100.0 * sum(1 for o in group if o["_won"]) / len(group), 1) \
            if group else 0

    def median_amount(group):
        values = sorted(o["_amount"] for o in group)
        return round(statistics.median(values)) if values else 0

    return {
        "by_segment": cut("segment"),
        "by_industry": cut("super_industry")[:8],
        "by_type": cut("opp_type"),
        "contested_total": len(contested),
        "touched": len(touched),
        "untouched": len(untouched),
        "touched_win_rate": rate(touched),
        "untouched_win_rate": rate(untouched),
        "touched_median": median_amount(touched),
        "untouched_median": median_amount(untouched),
        "comparison_is_reliable": len(touched) >= MIN_DEALS_FOR_COMPARISON,
        "min_deals_for_comparison": MIN_DEALS_FOR_COMPARISON,
        "losses": loss_breakdown(contested),
    }


def loss_breakdown(contested):
    """
    How the contested deals were lost — not another win rate.

    Excluding "lost to do nothing" would lift the headline win rate from 42%
    to 79%, and that would be the flattering-number move this dashboard exists
    to avoid: in enterprise software the status quo is the main competitor, so
    a deal lost to inaction is a real loss. The split is worth seeing on its
    own terms, because losing four times as often to inaction as to a named
    competitor points at a different problem than losing on features.
    """
    lost = [o for o in contested if not o["_won"]]
    buckets = collections.Counter()
    for opp in lost:
        name = opp["stage_name"]
        if "Do Nothing" in name:
            buckets["Lost to inaction"] += 1
        elif "Competition" in name:
            buckets["Lost to a competitor"] += 1
        else:
            buckets["Lost, reason not recorded"] += 1
    total = len(lost) or 1
    return {
        "total_lost": len(lost),
        "won": len(contested) - len(lost),
        "table": [{"label": k, "value": v, "pct": round(100.0 * v / total, 1)}
                  for k, v in buckets.most_common()],
    }


def lens_gap(all_rows, itemised_rows):
    """
    The same activity ranking computed over everyone, and over only the people
    who log task by task. Where the two disagree most is where the headline
    number is really describing a form-filling habit.
    """
    everyone = {r["label"]: r["pct"] for r in share_table(all_rows, "activity", "_hours")}
    itemised = {r["label"]: r["pct"] for r in share_table(itemised_rows, "activity", "_hours")}
    out = []
    for label, pct in sorted(everyone.items(), key=lambda kv: -kv[1])[:10]:
        out.append({
            "label": label,
            "everyone": pct,
            "itemised": itemised.get(label, 0.0),
            "gap": round(pct - itemised.get(label, 0.0), 1),
        })
    out.sort(key=lambda d: -abs(d["gap"]))
    return out


def build(data_dir):
    loaded = load(data_dir)
    rows = loaded["rows"]
    opportunities = loaded["opportunities"]
    issues = loaded["issues"]

    matches = match_opportunities(rows, opportunities)
    fiscal_evidence = infer_fiscal_start(rows, matches)

    unregistered = match_projects(rows, loaded["register"])
    body_by_project = {e["project"].strip(): (e["body_of_work"] or "(unspecified)")
                       for e in loaded["register"]}
    for row in rows:
        row["_body_of_work"] = body_by_project.get(row["_project"], "(unspecified)")

    all_weeks = sorted({r["_week"] for r in rows})

    # --- trailing partial week -------------------------------------------------
    rows_per_week = collections.Counter(r["_week"] for r in rows)
    median_rows = statistics.median(rows_per_week.values())
    thin = {w for w in all_weeks if rows_per_week[w] < median_rows * PARTIAL_WEEK_THRESHOLD}

    # Only a thin week at the *end* is still filling in, and only those are
    # excluded. A thin week in the middle is a reporting gap that already
    # happened: it stays in the totals but is flagged, because dropping it
    # would quietly flatter every average built on top of it.
    partial_weeks = []
    for week in reversed(all_weeks):
        if week in thin:
            partial_weeks.append(week)
        else:
            break
    thin_mid_weeks = sorted(thin - set(partial_weeks))
    complete_rows = [r for r in rows if r["_week"] not in partial_weeks]
    complete_weeks = [w for w in all_weeks if w not in partial_weeks]

    people = profile_people(complete_rows, complete_weeks)
    assign_person_weeks(complete_rows, people)
    bulk_names = {name for name, p in people.items() if p["style"] == "bulk"}

    issues["Rows in a still-filling week (excluded from totals)"] = \
        len(rows) - len(complete_rows)

    # --- per-quarter ----------------------------------------------------------
    quarters = collections.OrderedDict()
    for label in sorted({r["_quarter"] for r in complete_rows}):
        q_rows = [r for r in complete_rows if r["_quarter"] == label]
        q_weeks = sorted({r["_week"] for r in q_rows})
        q_people = sorted({r["person"] for r in q_rows})
        hours = sum(r["_hours"] for r in q_rows)
        person_weeks = sum(r["_person_weeks"] for r in q_rows)

        quarters[label] = {
            "label": label,
            "weeks": q_weeks,
            "week_count": len(q_weeks),
            "people": q_people,
            "person_count": len(q_people),
            "hours": round(hours, 1),
            "person_weeks": round(person_weeks, 1),
            "hours_per_person_week": round(hours / person_weeks, 1) if person_weeks else 0,
            "prospect_facing_pct": round(
                100.0 * sum(r["_person_weeks"] for r in q_rows if r["_prospect_facing"])
                / person_weeks, 1) if person_weeks else 0,
            "presented_pct": round(
                100.0 * sum(r["_person_weeks"] for r in q_rows if r["_presented"])
                / person_weeks, 1) if person_weeks else 0,
            "funnel": funnel_for(q_rows),
            "by_category_hours": share_table(q_rows, "activity_category", "_hours", None, bulk_names),
            "by_category_pw": share_table(q_rows, "activity_category", "_person_weeks", None, bulk_names),
            "by_activity_hours": share_table(q_rows, "activity", "_hours", 12, bulk_names),
            "by_activity_pw": share_table(q_rows, "activity", "_person_weeks", 12, bulk_names),
            "by_type_hours": share_table(q_rows, "activity_type", "_hours", None, bulk_names),
            "by_type_pw": share_table(q_rows, "activity_type", "_person_weeks", None, bulk_names),
            "by_department_pw": share_table(q_rows, "_department", "_person_weeks"),
            "by_activity_itemised": share_table(
                [r for r in q_rows if r["person"] not in bulk_names],
                "activity", "_person_weeks", 12),
        }

    # --- whole period ---------------------------------------------------------
    total_hours = sum(r["_hours"] for r in complete_rows)
    total_pw = sum(r["_person_weeks"] for r in complete_rows)
    bulk_people = [p for p in people.values() if p["style"] == "bulk"]
    bulk_hours = sum(r["_hours"] for r in complete_rows
                     if r["person"] in bulk_names)
    itemised_rows = [r for r in complete_rows if r["person"] not in bulk_names]

    weekly = []
    for week in all_weeks:
        w_rows = [r for r in rows if r["_week"] == week]
        weekly.append({
            "week": week,
            "hours": round(sum(r["_hours"] for r in w_rows), 1),
            "rows": len(w_rows),
            "people": len({r["person"] for r in w_rows}),
            "partial": week in partial_weeks,
            "thin": week in thin_mid_weeks,
        })

    matched_detail = []
    for name, (opp, tier) in sorted(matches.items()):
        opp_rows = [r for r in complete_rows if r["opportunity_name"] == name]
        if not opp_rows:
            continue
        matched_detail.append({
            "name": name,
            "account": opp["account_name"],
            "tier": tier,
            "stage_group": opp["stage_group"],
            "stage": opp["stage_name"],
            "administrative": opp["_administrative"],
            "outcome": ("Administrative" if opp["_administrative"]
                        else opp["stage_group"]),
            "segment": opp["segment"],
            "industry": opp["super_industry"],
            "amount": round(opp["_amount"]),
            "fiscal_period": opp["fiscal_period"],
            "segment": opp["segment"],
            "hours": round(sum(r["_hours"] for r in opp_rows), 1),
            "people": sorted({r["person"] for r in opp_rows}),
            "first_week": min(r["_week"] for r in opp_rows),
            "last_week": max(r["_week"] for r in opp_rows),
        })
    matched_detail.sort(key=lambda d: -d["hours"])

    # notes that contain their own hour breakdown
    hour_in_notes = re.compile(r"\b\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours)\b", re.I)
    self_itemised = [r for r in complete_rows if hour_in_notes.search(r["notes"] or "")]

    people_out = []
    for person in sorted(people.values(), key=lambda p: -p["total_hours"]):
        p_rows = [r for r in complete_rows if r["person"] == person["name"]]
        out = {k: v for k, v in person.items() if k != "weekly_hours"}
        out["person_weeks"] = round(sum(r["_person_weeks"] for r in p_rows), 1)
        out["top_activities"] = share_table(p_rows, "activity", "_person_weeks", 3)
        out["prospect_facing_pct"] = round(
            100.0 * sum(r["_person_weeks"] for r in p_rows if r["_prospect_facing"])
            / max(out["person_weeks"], 1e-9), 1)
        out["weeks_by_week"] = sorted({r["_week"] for r in p_rows})
        people_out.append(out)

    opp_stage_mix = share_table(
        [{"s": o["stage_group"], "v": 1} for o in opportunities], "s", "v")

    return {
        "generated": datetime.datetime.now().strftime("%d %b %Y, %H:%M"),
        "files": loaded["files"],
        "warnings": loaded["warnings"],
        "issues": [{"label": k, "count": v} for k, v in issues.items()],
        "period": {
            "first_week": all_weeks[0],
            "last_week": all_weeks[-1],
            "week_count": len(complete_weeks),
            "partial_weeks": partial_weeks,
            "thin_weeks": thin_mid_weeks,
        },
        "fiscal": {
            "start_month": FISCAL_START_MONTH,
            "start_month_name": datetime.date(2000, FISCAL_START_MONTH, 1).strftime("%B"),
            "evidence": fiscal_evidence[:4],
            # The candidate that would win on same-quarter frequency alone.
            # It is usually not in the top four above, and leaving it out
            # would make a thin call look settled.
            "same_quarter_winner": (
                max(fiscal_evidence, key=lambda s: s["same_quarter_pct"])
                if fiscal_evidence else None),
        },
        "headline": {
            "total_hours": round(total_hours),
            "person_weeks": round(total_pw),
            "people": len(people),
            "weeks": len(complete_weeks),
            "avg_logged_per_person_week": round(total_hours / total_pw, 1) if total_pw else 0,
            "coverage_pct": round(100.0 * total_pw / (len(people) * len(complete_weeks)))
                            if people and complete_weeks else 0,
            "bulk_people": len(bulk_people),
            "bulk_hours_pct": round(100.0 * bulk_hours / total_hours) if total_hours else 0,
            "opp_linked_pct": round(
                100.0 * sum(r["_hours"] for r in complete_rows if r["opportunity_name"])
                / total_hours, 1) if total_hours else 0,
            "crm_matched_pct": round(
                100.0 * sum(r["_hours"] for r in complete_rows if r["_matched_opp"])
                / total_hours, 1) if total_hours else 0,
            "prospect_facing_pct": round(
                100.0 * sum(r["_person_weeks"] for r in complete_rows if r["_prospect_facing"])
                / total_pw, 1) if total_pw else 0,
            "opps_touched": len({r["opportunity_name"] for r in complete_rows
                                 if r["opportunity_name"]}),
            "opps_in_crm": len(opportunities),
            "opps_matched": len(matched_detail),
            "notes_with_own_breakdown": len(self_itemised),
            "notes_breakdown_hours": round(sum(r["_hours"] for r in self_itemised)),
            "opps_administrative": sum(1 for o in opportunities if o["_administrative"]),
            "administrative_pct": round(
                100.0 * sum(1 for o in opportunities if o["_administrative"])
                / len(opportunities), 1) if opportunities else 0,
            "win_rate_all_closed": round(
                100.0 * sum(1 for o in opportunities if o["_won"])
                / len(opportunities), 1) if opportunities else 0,
            "win_rate_contested": round(
                100.0 * sum(1 for o in opportunities if o["_won"] and o["_contested"])
                / sum(1 for o in opportunities if o["_contested"]), 1)
                if any(o["_contested"] for o in opportunities) else 0,
            "exec_reach_pct": executive_reach(complete_rows)["exec_pct"],
            "won_hours_pct": round(
                100.0 * funnel_for(complete_rows)["won_hours"] / total_hours, 2)
                if total_hours else 0,
            "audience_blank_row_pct": round(
                100.0 * sum(1 for r in complete_rows if not r["audience"])
                / len(complete_rows), 1) if complete_rows else 0,
        },
        "lens_gap": lens_gap(complete_rows, itemised_rows),
        # Whole-period funnel, built from the rows. The dashboard's "All
        # reported weeks" view uses this rather than adding the quarters up,
        # because an opportunity worked either side of a quarter boundary
        # would otherwise have its value counted twice.
        "period_funnel": funnel_for(complete_rows),
        "projects": projects_view(complete_rows, loaded["register"], unregistered,
                                  total_hours,
                                  funnel_for(complete_rows)["crm_matched_hours"]),
        "reach": executive_reach(complete_rows),
        "prep_load": preparation_load(complete_rows),
        "coverage": closed_book_coverage(
            opportunities,
            {r["opportunity_name"] for r in complete_rows if r["_matched_opp"]}),
        # Whole-period breakdowns, for the same reason. Adding the quarters up
        # would divide by a truncated denominator, because each quarter's
        # activity table keeps only its own top rows — which silently inflates
        # every share in the combined view.
        "period_tables": {
            "by_category_hours": share_table(complete_rows, "activity_category", "_hours", None, bulk_names),
            "by_category_pw": share_table(complete_rows, "activity_category", "_person_weeks", None, bulk_names),
            "by_activity_hours": share_table(complete_rows, "activity", "_hours", 12, bulk_names),
            "by_activity_pw": share_table(complete_rows, "activity", "_person_weeks", 12, bulk_names),
            "by_type_hours": share_table(complete_rows, "activity_type", "_hours", None, bulk_names),
            "by_type_pw": share_table(complete_rows, "activity_type", "_person_weeks", None, bulk_names),
            "by_department_pw": share_table(complete_rows, "_department", "_person_weeks"),
        },
        "quarters": quarters,
        "weekly": weekly,
        "people": people_out,
        "matched": matched_detail,
        "opp_stage_mix": opp_stage_mix,
        "activity_catalogue": sorted({r["activity"] for r in complete_rows if r["activity"]}),
    }
