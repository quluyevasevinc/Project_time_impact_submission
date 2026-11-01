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

    issues["Duplicate rows removed"] = duplicates
    issues["Rows with an unreadable 'Week of'"] = unparsed_week
    issues["Rows where the hour columns did not add up"] = arithmetic_mismatch

    return {
        "rows": rows,
        "opportunities": opportunities,
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
    carries an opportunity *id*. Nothing joins them directly. Match in three
    tiers, weakest last, and record which tier produced each match so the
    dashboard can show how much of the link is solid.
    """
    by_exact = {o["opp_name"].strip(): o for o in opportunities if o["opp_name"].strip()}
    by_key = {}
    for opp in opportunities:
        by_key.setdefault(opp["_key"], []).append(opp)
    by_amount = {}
    for opp in opportunities:
        by_amount.setdefault(round(opp["_amount"], 2), []).append(opp)

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
            continue
        amount = round(to_float(row["opportunity_amount"]), 2)
        if amount > 0:
            candidates = by_amount.get(amount, [])
            if len(candidates) == 1:
                matches[name] = (candidates[0], "unique deal value")

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
    scores.sort(key=lambda s: (-s["same_quarter_pct"], -s["work_before_close_pct"]))
    return scores


# ---------------------------------------------------------------------------
# People — how each person logs, which decides how their hours can be read
# ---------------------------------------------------------------------------

def profile_people(rows, all_weeks):
    by_person = collections.defaultdict(list)
    for row in rows:
        by_person[row["person"]].append(row)

    people = {}
    for name, person_rows in by_person.items():
        weeks = collections.defaultdict(list)
        for row in person_rows:
            weeks[row["_week"]].append(row)
        weekly_hours = {w: sum(r["_hours"] for r in rs) for w, rs in weeks.items()}
        rows_per_week = statistics.median(len(rs) for rs in weeks.values())
        median_row = statistics.median(r["_hours"] for r in person_rows)
        is_bulk = (rows_per_week <= BULK_MAX_ROWS_PER_WEEK
                   and median_row >= BULK_MIN_MEDIAN_ROW_HOURS)
        people[name] = {
            "name": name,
            "department": person_rows[0]["_department"],
            "manager": person_rows[0]["manager"] or "(none recorded)",
            "tenure": to_float(person_rows[0]["tenure_years"], default=None),
            "weeks_reported": len(weeks),
            "weeks_possible": len(all_weeks),
            "coverage_pct": round(100.0 * len(weeks) / len(all_weeks)) if all_weeks else 0,
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
    won = {n: o for n, o in matched_opps.items() if o["_won"]}

    return {
        "all_hours": round(sum(r["_hours"] for r in rows), 1),
        "opp_linked_hours": round(sum(r["_hours"] for r in opp_rows), 1),
        "crm_matched_hours": round(sum(r["_hours"] for r in matched_rows), 1),
        "won_hours": round(sum(r["_hours"] for r in matched_rows
                               if r["_matched_opp"]["_won"]), 1),
        "opps_touched": len(touched),
        "opps_matched": len(matched_opps),
        "opps_won": len(won),
        "value_touched": round(sum(touched.values())),
        "value_matched": round(sum(o["_amount"] for o in matched_opps.values())),
        "value_won": round(sum(o["_amount"] for o in won.values())),
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
        },
        "lens_gap": lens_gap(complete_rows, itemised_rows),
        # Whole-period funnel, built from the rows. The dashboard's "All
        # reported weeks" view uses this rather than adding the quarters up,
        # because an opportunity worked either side of a quarter boundary
        # would otherwise have its value counted twice.
        "period_funnel": funnel_for(complete_rows),
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
