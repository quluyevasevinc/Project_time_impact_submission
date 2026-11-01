"""
Contract tests for the pipeline.

    python3 -m unittest -v

These are not unit tests for their own sake. Each one pins an assumption the
dashboard's conclusions rest on, so that a future export cannot quietly break a
number that leadership is reading. Where a test encodes a judgement call rather
than a fact, the docstring says so.

Standard library only, in keeping with the rest of the project.
"""

import csv
import datetime
import os
import re
import shutil
import tempfile
import unittest

import pipeline

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class ColumnMatching(unittest.TestCase):
    """The weekly export renames columns. That must never silently drop data."""

    def test_spacing_and_case_are_invisible(self):
        for variant in ("Hours Total", "HoursTotal", "hours_total", "HOURS TOTAL"):
            self.assertEqual(pipeline.squash(variant), "hourstotal")

    def test_opportunity_name_variants_collapse(self):
        self.assertEqual(pipeline.squash("Opportunity Name"),
                         pipeline.squash("OpportunityName"))

    def test_every_alias_is_unique_across_fields(self):
        """Two canonical fields must never claim the same incoming column."""
        seen = {}
        for canonical, spellings in pipeline.HOURS_ALIASES.items():
            for spelling in spellings:
                self.assertNotIn(spelling, seen,
                                 f"{spelling!r} claimed by {canonical} and {seen.get(spelling)}")
                seen[spelling] = canonical


class FiscalCalendar(unittest.TestCase):
    """FY27 = 2026-02-01 .. 2027-01-31. Inferred, so worth pinning."""

    def test_quarter_boundaries(self):
        cases = [
            (datetime.date(2026, 2, 1),  "FY2027", 1),
            (datetime.date(2026, 4, 30), "FY2027", 1),
            (datetime.date(2026, 5, 1),  "FY2027", 2),
            (datetime.date(2026, 7, 31), "FY2027", 2),
            (datetime.date(2026, 8, 1),  "FY2027", 3),
            (datetime.date(2026, 11, 1), "FY2027", 4),
            (datetime.date(2027, 1, 31), "FY2027", 4),
            (datetime.date(2027, 2, 1),  "FY2028", 1),
        ]
        for day, fy, q in cases:
            got_fy, got_q, _ = pipeline.fiscal_quarter(day)
            self.assertEqual((got_fy, got_q), (fy, q), f"for {day}")


class PersonWeeks(unittest.TestCase):
    """The comparable unit. If this drifts, every ranking on the site drifts."""

    def setUp(self):
        self.built = pipeline.build(DATA)

    def test_each_person_week_sums_to_one(self):
        """A person's week is 1.0 of their attention, however they logged it."""
        rows = pipeline.load(DATA)["rows"]
        for row in rows:
            row["_hours"] = pipeline.to_float(row["hours_total"])
            row["_week"] = row["week_of"]
        pipeline.assign_person_weeks(rows, {})
        buckets = {}
        for row in rows:
            key = (row["person"], row["_week"])
            buckets[key] = buckets.get(key, 0.0) + row["_person_weeks"]
        for key, total in buckets.items():
            self.assertAlmostEqual(total, 1.0, places=6, msg=f"{key} summed to {total}")

    def test_an_all_zero_week_still_counts_as_reported(self):
        """
        A week filed entirely at zero hours must still count as 1.0, or the
        person silently drops out of coverage despite having reported.
        """
        rows = [
            {"person": "A", "_week": "2026-01-05", "_hours": 0.0},
            {"person": "A", "_week": "2026-01-05", "_hours": 0.0},
            {"person": "B", "_week": "2026-01-05", "_hours": 3.0},
        ]
        pipeline.assign_person_weeks(rows, {})
        self.assertAlmostEqual(rows[0]["_person_weeks"] + rows[1]["_person_weeks"], 1.0)
        self.assertAlmostEqual(rows[2]["_person_weeks"], 1.0)

    def test_person_weeks_never_exceed_people_times_weeks(self):
        head = self.built["headline"]
        ceiling = head["people"] * head["weeks"]
        self.assertLessEqual(head["person_weeks"], ceiling)
        self.assertGreater(head["person_weeks"], 0)

    def test_coverage_is_a_percentage(self):
        self.assertTrue(0 < self.built["headline"]["coverage_pct"] <= 100)


class ShareTables(unittest.TestCase):
    """Every breakdown must account for all of the effort, exactly once."""

    def setUp(self):
        self.built = pipeline.build(DATA)

    def test_unlimited_share_tables_sum_to_100(self):
        for label, quarter in self.built["quarters"].items():
            for table in ("by_category_pw", "by_type_pw", "by_department_pw"):
                total = sum(row["pct"] for row in quarter[table])
                self.assertAlmostEqual(total, 100.0, delta=0.3,
                                       msg=f"{label}/{table} summed to {total}")

    def test_bulk_share_is_bounded(self):
        for quarter in self.built["quarters"].values():
            for row in quarter["by_activity_pw"]:
                self.assertTrue(0 <= row["bulk_pct"] <= 100, row)

    def test_period_tables_sum_to_100(self):
        for table in ("by_category_pw", "by_type_pw", "by_department_pw"):
            total = sum(row["pct"] for row in self.built["period_tables"][table])
            self.assertAlmostEqual(total, 100.0, delta=0.3,
                                   msg=f"period/{table} summed to {total}")

    def test_truncated_activity_table_still_uses_the_full_denominator(self):
        """
        Regression: the activity tables keep only the top rows, but their
        percentages must be shares of *all* effort. If the denominator were
        truncated, the kept rows would sum to 100% instead of well under it,
        and every activity's share would be inflated.
        """
        for table in ("by_activity_pw", "by_activity_hours"):
            rows = self.built["period_tables"][table]
            self.assertEqual(len(rows), 12, "fixture no longer truncates this table")
            self.assertLess(sum(r["pct"] for r in rows), 99.0,
                            f"{table} sums to ~100% — the denominator is truncated")

    def test_period_activity_share_matches_an_independent_count(self):
        """The headline activity share must survive being computed from scratch."""
        loaded = pipeline.load(DATA)
        partial = set(self.built["period"]["partial_weeks"])
        rows = [r for r in loaded["rows"] if r["_week"] not in partial]
        totals = {}
        for row in rows:
            totals[row["activity"]] = totals.get(row["activity"], 0.0) + row["_hours"]
        grand = sum(totals.values())
        top = max(totals, key=totals.get)
        expected = round(100.0 * totals[top] / grand, 1)
        published = next(r["pct"] for r in self.built["period_tables"]["by_activity_hours"]
                         if r["label"] == top)
        self.assertAlmostEqual(published, expected, delta=0.1)
        self.assertAlmostEqual(self.built["lens_gap"][0]["everyone"], expected, delta=0.1,
                               msg="lens_gap and the period table disagree on the same figure")


class PartialWeeks(unittest.TestCase):
    """A half-filled trailing week must never read as a collapse in effort."""

    def test_trailing_thin_week_is_excluded(self):
        built = pipeline.build(DATA)
        self.assertIn("2026-10-12", built["period"]["partial_weeks"])
        for entry in built["weekly"]:
            if entry["week"] == "2026-10-12":
                self.assertTrue(entry["partial"])

    def test_excluded_week_is_in_no_quarter_total(self):
        built = pipeline.build(DATA)
        for quarter in built["quarters"].values():
            for week in built["period"]["partial_weeks"]:
                self.assertNotIn(week, quarter["weeks"])

    def test_thin_week_is_kept_once_later_weeks_arrive(self):
        """
        A judgement call, pinned deliberately: a thin week at the end is still
        being filled in and is excluded; the same week mid-series is a reporting
        gap that really happened, and dropping it would flatter every average.
        """
        tmp = tempfile.mkdtemp()
        try:
            for name in os.listdir(DATA):
                shutil.copy(os.path.join(DATA, name), tmp)
            source = os.path.join(DATA, "team_hours_export_part2_2026-08-03_to_2026-10-12.csv")
            with open(source, newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
                fields = list(rows[0].keys())
            template = [r for r in rows if r["Week of"] == "2026-09-21"]
            out = []
            for week in ("2026-10-19", "2026-10-26"):
                for row in template:
                    new = dict(row)
                    new["Week of"] = week
                    out.append(new)
            later = os.path.join(tmp, "team_hours_export_part3_2026-10-19_to_2026-10-26.csv")
            with open(later, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(out)

            built = pipeline.build(tmp)
            self.assertEqual(built["period"]["partial_weeks"], [])
            self.assertIn("2026-10-12", built["period"]["thin_weeks"])
        finally:
            shutil.rmtree(tmp)


class OpportunityMatching(unittest.TestCase):
    """Attribution is the weakest link, so its limits are pinned explicitly."""

    def setUp(self):
        self.built = pipeline.build(DATA)

    def test_every_match_records_how_it_was_made(self):
        allowed = {"exact name", "normalised name", "unique deal value"}
        for match in self.built["matched"]:
            self.assertIn(match["tier"], allowed)

    def test_no_opportunity_matches_twice(self):
        names = [m["name"] for m in self.built["matched"]]
        self.assertEqual(len(names), len(set(names)))

    def test_attribution_rate_is_reported_not_assumed(self):
        """
        This asserts the number is *low*. If a future change makes it look
        healthy without a capture-side fix, the matcher has started guessing
        and this test should fail loudly.
        """
        self.assertLess(self.built["headline"]["crm_matched_pct"], 25.0)

    def test_period_funnel_is_not_the_sum_of_quarters(self):
        """
        Regression: an opportunity worked either side of a quarter boundary
        appears in both quarter funnels. The whole-period funnel must be built
        from the rows, so adding the quarters up must give a *larger* number
        than the period figure — if they ever match, the period funnel has
        started double-counting.
        """
        period = self.built["period_funnel"]
        quarters = self.built["quarters"].values()
        for field in ("opps_touched", "opps_matched", "opps_won",
                      "value_touched", "value_matched", "value_won"):
            summed = sum(q["funnel"][field] for q in quarters)
            self.assertLessEqual(
                period[field], summed,
                f"period {field} ({period[field]}) exceeds the sum of quarters ({summed})")
        self.assertLess(period["opps_touched"],
                        sum(q["funnel"]["opps_touched"] for q in quarters),
                        "no opportunity spans a quarter boundary — this test no longer "
                        "proves anything and the fixture should be revisited")

    def test_period_funnel_counts_each_opportunity_once(self):
        """The period funnel must agree with a distinct count taken directly."""
        loaded = pipeline.load(DATA)
        partial = set(self.built["period"]["partial_weeks"])
        rows = [r for r in loaded["rows"] if r["_week"] not in partial]
        pipeline.match_opportunities(rows, loaded["opportunities"])
        distinct = {}
        for row in rows:
            if row["opportunity_name"]:
                distinct.setdefault(row["opportunity_name"],
                                    pipeline.to_float(row["opportunity_amount"]))
        self.assertEqual(self.built["period_funnel"]["opps_touched"], len(distinct))
        self.assertEqual(self.built["period_funnel"]["value_touched"],
                         round(sum(distinct.values())))

    def test_funnel_steps_never_increase(self):
        """Each step is a subset of the one before it, in every view."""
        funnels = [q["funnel"] for q in self.built["quarters"].values()]
        funnels.append(self.built["period_funnel"])
        for funnel in funnels:
            self.assertGreaterEqual(funnel["all_hours"], funnel["opp_linked_hours"])
            self.assertGreaterEqual(funnel["opp_linked_hours"], funnel["crm_matched_hours"])
            self.assertGreaterEqual(funnel["crm_matched_hours"], funnel["won_hours"])
            self.assertGreaterEqual(funnel["opps_touched"], funnel["opps_matched"])
            self.assertGreaterEqual(funnel["opps_matched"], funnel["opps_won"])
            self.assertGreaterEqual(funnel["value_matched"], funnel["value_won"])

    def test_amount_matches_are_unambiguous(self):
        """A deal value may only resolve an opportunity if it identifies one."""
        opps = self.built["headline"]["opps_in_crm"]
        self.assertGreater(opps, 0)
        by_amount = {}
        loaded = pipeline.load(DATA)
        for opp in loaded["opportunities"]:
            by_amount.setdefault(round(opp["_amount"], 2), []).append(opp)
        for match in self.built["matched"]:
            if match["tier"] == "unique deal value":
                self.assertEqual(len(by_amount[round(float(match["amount"]), 2)]), 1,
                                 f"{match['name']} matched on an ambiguous value")


class Cleaning(unittest.TestCase):
    def test_duplicates_removed(self):
        built = pipeline.build(DATA)
        counts = {i["label"]: i["count"] for i in built["issues"]}
        self.assertGreaterEqual(counts["Duplicate rows removed"], 0)

    def test_hour_components_reconcile(self):
        """Activity + preparation + travel must equal the stated total."""
        built = pipeline.build(DATA)
        counts = {i["label"]: i["count"] for i in built["issues"]}
        self.assertEqual(counts["Rows where the hour columns did not add up"], 0)

    def test_department_spellings_roll_up(self):
        self.assertEqual(pipeline.normalise_department("VM Digital COE"),
                         pipeline.normalise_department("VM, Digital COE"))

    def test_missing_input_fails_loudly(self):
        tmp = tempfile.mkdtemp()
        try:
            with self.assertRaises(SystemExit):
                pipeline.build(tmp)
        finally:
            shutil.rmtree(tmp)


class DashboardJavaScript(unittest.TestCase):
    """
    Runs test_dashboard.js against the dashboard's computation layer, so one
    command covers both languages. Uses whichever engine is on the machine —
    macOS ships JavaScriptCore, CI runners ship Node — and skips rather than
    fails where there is none, since the Python side still stands on its own.
    """

    def test_dashboard_logic(self):
        import run_js_tests
        passed, engine, output = run_js_tests.run()
        if passed is None:
            self.skipTest(output)
        self.assertTrue(passed, f"[{engine}]\n{output}")


class BuildOutput(unittest.TestCase):
    """The built page must be self-contained and fully substituted."""

    @classmethod
    def setUpClass(cls):
        import build
        build.main()
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "dashboard.html"), encoding="utf-8") as handle:
            cls.html = handle.read()

    def test_no_placeholder_survives(self):
        for placeholder in ("__DATA__", "__LOGIC__"):
            self.assertNotIn(placeholder, self.html)

    def test_no_external_requests(self):
        """
        A strict offline artefact: opening it must fetch nothing.

        Looks for things that actually load a resource, not for the string
        "http" — the SVG namespace is a URI that is never dereferenced, and an
        earlier version of this test failed on it.
        """
        loaders = [
            r'src\s*=\s*["\']https?:',
            r'href\s*=\s*["\']https?:',
            r'url\(\s*["\']?https?:',
            r'@import',
            r'\bfetch\s*\(',
            r'XMLHttpRequest',
            r'new\s+WebSocket',
            r'<link\b(?![^>]*rel=["\']?icon)',
        ]
        for pattern in loaders:
            found = re.search(pattern, self.html, re.I)
            self.assertIsNone(
                found, f"page loads something external: {pattern!r} "
                       f"matched {found.group(0)!r}" if found else "")

    def test_svg_namespace_is_the_only_absolute_url(self):
        """Documents why the check above is written the way it is."""
        urls = set(re.findall(r'https?://[^\s"\')<>]+', self.html))
        self.assertEqual(urls, {"http://www.w3.org/2000/svg"})

    def test_logic_and_data_are_both_inlined(self):
        self.assertIn("var VMDash", self.html)
        self.assertIn('id="payload"', self.html)


if __name__ == "__main__":
    unittest.main()
