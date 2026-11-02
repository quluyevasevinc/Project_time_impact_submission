"""
Contract tests for the pipeline.

    python3 -m unittest -v

These are not unit tests for their own sake. Each one pins an assumption the
dashboard's conclusions rest on, so that a future export cannot quietly break a
number that leadership is reading. Where a test encodes a judgement call rather
than a fact, the docstring says so.

Standard library only, in keeping with the rest of the project.
"""

import collections
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
        allowed = {"exact name", "normalised name"}
        for match in self.built["matched"]:
            self.assertIn(match["tier"], allowed)

    def test_deal_value_is_never_used_as_a_join_key(self):
        """
        Regression. Matching on "this amount appears against exactly one
        opportunity" tripled the hit rate and was wrong: 93% of CRM amounts are
        already unique, so the test filters nothing, and 20 of the 23 matches
        it produced linked companies with no word in common. If a tier like
        that comes back, this fails.
        """
        for match in self.built["matched"]:
            self.assertNotIn("value", match["tier"])
            self.assertNotIn("amount", match["tier"])

    def test_matched_pairs_agree_on_deal_value(self):
        """
        Corroboration, in the direction that can actually fail: a name matched
        between the two files should carry the same deal value in both. It does
        for 15 of 16. Running this check the other way round — assuming a
        shared value implies a shared deal — is exactly the error that put 23
        false matches on the dashboard.

        Note the account name cannot be used for this. In the CRM extract
        itself, opportunity name and account name correspond only about half
        the time, so a mismatch there says nothing about the match.
        """
        loaded = pipeline.load(DATA)
        by_name = {o["opp_name"].strip(): o for o in loaded["opportunities"]}
        logged_value = {}
        for row in loaded["rows"]:
            name = row["opportunity_name"]
            if name and name in by_name and name not in logged_value:
                logged_value[name] = pipeline.to_float(row["opportunity_amount"])
        self.assertTrue(logged_value)
        agree = sum(1 for name, value in logged_value.items()
                    if abs(value - by_name[name]["_amount"]) < 0.01)
        self.assertGreaterEqual(agree / len(logged_value), 0.85,
                                "name-matched pairs have stopped agreeing on "
                                "deal value — the match is no longer corroborated")

    def test_no_opportunity_matches_twice(self):
        names = [m["name"] for m in self.built["matched"]]
        self.assertEqual(len(names), len(set(names)))

    def test_attribution_rate_is_reported_not_assumed(self):
        """
        This asserts the number is *low*. If a future change makes it look
        healthy without a capture-side fix, the matcher has started guessing
        and this test should fail loudly. The threshold is deliberately tight:
        a tier that tripled this figure has already shipped once.
        """
        self.assertLess(self.built["headline"]["crm_matched_pct"], 2.0)

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

    def test_deal_value_would_not_have_been_selective(self):
        """
        Documents why the amount tier was removed rather than tuned: almost
        every CRM amount is already unique, so "appears exactly once" is not a
        filter at all.
        """
        loaded = pipeline.load(DATA)
        amounts = [o["_amount"] for o in loaded["opportunities"] if o["_amount"] > 0]
        counts = collections.Counter(amounts)
        unique_share = sum(1 for v in counts.values() if v == 1) / len(counts)
        self.assertGreater(unique_share, 0.85,
                           "amounts are no longer near-unique — the reasoning "
                           "behind removing that tier should be revisited")


class AdministrativeClosures(unittest.TestCase):
    """
    Nearly a quarter of the CRM's closed opportunities were never won or lost.
    They are filed under the stage group "Lost", which is the trap.
    """

    def setUp(self):
        self.built = pipeline.build(DATA)

    def test_administrative_deals_are_identified(self):
        head = self.built["headline"]
        self.assertGreater(head["opps_administrative"], 0)
        self.assertGreater(head["administrative_pct"], 10)

    def test_contested_win_rate_is_higher_than_the_naive_one(self):
        """
        The whole point: counting merged and imported records as defeats
        understates the win rate. If these ever match, the exclusion broke.
        """
        head = self.built["headline"]
        self.assertGreater(head["win_rate_contested"], head["win_rate_all_closed"])

    def test_merged_opportunities_are_not_counted_as_losses(self):
        loaded = pipeline.load(DATA)
        for opp in loaded["opportunities"]:
            if "Merged" in opp["stage_name"]:
                self.assertTrue(opp["_administrative"], opp["opp_name"])
                self.assertFalse(opp["_contested"])

    def test_a_plain_loss_stays_contested(self):
        loaded = pipeline.load(DATA)
        plain = [o for o in loaded["opportunities"]
                 if o["stage_name"].startswith("31-")]
        self.assertTrue(plain)
        for opp in plain:
            self.assertTrue(opp["_contested"], opp["stage_name"])

    def test_funnel_excludes_administrative_from_the_outcome_step(self):
        funnel = self.built["period_funnel"]
        self.assertEqual(funnel["opps_contested"] + funnel["opps_administrative"],
                         funnel["opps_matched"])
        self.assertGreaterEqual(funnel["crm_matched_hours"], funnel["contested_hours"])
        self.assertGreaterEqual(funnel["contested_hours"], funnel["won_hours"])

    def test_small_sample_comparison_is_flagged_unreliable(self):
        """
        The touched-versus-untouched win rate rests on a handful of deals. It
        must carry a reliability flag, not stand as a finding.
        """
        coverage = self.built["coverage"]
        if coverage["touched"] < coverage["min_deals_for_comparison"]:
            self.assertFalse(coverage["comparison_is_reliable"])


class ReachAndPreparation(unittest.TestCase):
    """Two signals the form has always carried and nothing read."""

    def setUp(self):
        self.built = pipeline.build(DATA)

    def test_seniority_demotes_a_director_inside_a_chief_title(self):
        self.assertEqual(pipeline.seniority("oCHRO - CHRO"), "C-suite")
        self.assertEqual(pipeline.seniority("oCHRO - HR Director/Functional"),
                         "Director")
        self.assertEqual(pipeline.seniority("oCHRO - HR VP"), "VP")
        self.assertEqual(pipeline.seniority("oCIO - IT Director/Functional"),
                         "Director")

    def test_not_presented_and_blank_have_no_seniority(self):
        self.assertIsNone(pipeline.seniority("Not Presented"))
        self.assertIsNone(pipeline.seniority(""))
        self.assertIsNone(pipeline.seniority(None))

    def test_reach_shares_sum_to_100(self):
        total = sum(r["pct"] for r in self.built["reach"]["table"])
        self.assertAlmostEqual(total, 100.0, delta=0.3)

    def test_preparation_splits_reconcile(self):
        for row in self.built["prep_load"]:
            self.assertAlmostEqual(row["prep"] + row["delivery"], row["value"],
                                   delta=0.2)
            self.assertAlmostEqual(row["pct"],
                                   100.0 * row["prep"] / row["value"], delta=0.2)

    def test_preparation_table_is_sorted_by_burden(self):
        shares = [r["pct"] for r in self.built["prep_load"]]
        self.assertEqual(shares, sorted(shares, reverse=True))


class CoverageDenominator(unittest.TestCase):
    """
    Coverage counts from a person's first logged week. Two people joined in
    late August and have filed every week since; a flat denominator showed
    them as the worst reporters on the team.
    """

    def setUp(self):
        self.built = pipeline.build(DATA)

    def test_late_joiners_are_identified(self):
        late = [p for p in self.built["people"] if p["joined_late"]]
        self.assertTrue(late, "nobody joined mid-period — fixture changed")

    def test_only_zero_tenure_people_get_a_shortened_denominator(self):
        """
        Appearing in week two is not evidence of joining in week two. An
        earlier version used first-appearance alone and flagged nine people,
        including several with four to six years of tenure who had simply
        missed the opening weeks.
        """
        for person in self.built["people"]:
            if person["joined_late"]:
                self.assertEqual(person["tenure"], 0,
                                 f"{person['name']} has tenure "
                                 f"{person['tenure']} and should not be "
                                 f"treated as a late joiner")

    def test_unknown_tenure_is_treated_as_present_from_the_start(self):
        for person in self.built["people"]:
            if person["tenure"] is None:
                self.assertFalse(person["joined_late"])
                self.assertEqual(person["weeks_possible"],
                                 person["weeks_in_export"])

    def test_a_perfect_late_joiner_reads_as_perfect(self):
        """The case that motivated the change must not regress."""
        perfect = [p for p in self.built["people"]
                   if p["joined_late"] and p["weeks_reported"] == p["weeks_possible"]]
        self.assertTrue(perfect)
        for person in perfect:
            self.assertEqual(person["coverage_pct"], 100)
            self.assertLess(person["coverage_pct_naive"], 60,
                            "this person no longer demonstrates the problem")

    def test_coverage_never_exceeds_100(self):
        for person in self.built["people"]:
            self.assertLessEqual(person["coverage_pct"], 100)
            self.assertGreater(person["coverage_pct"], 0)

    def test_full_period_people_are_unaffected(self):
        for person in self.built["people"]:
            if not person["joined_late"]:
                self.assertEqual(person["coverage_pct"], person["coverage_pct_naive"])


class LossBreakdown(unittest.TestCase):
    """The split of losses must stay a split, not become a second win rate."""

    def setUp(self):
        self.losses = pipeline.build(DATA)["coverage"]["losses"]

    def test_losses_and_wins_account_for_every_contested_deal(self):
        built = pipeline.build(DATA)
        self.assertEqual(self.losses["won"] + self.losses["total_lost"],
                         built["coverage"]["contested_total"])

    def test_inaction_is_counted_as_a_loss(self):
        """
        Excluding "lost to do nothing" would lift the headline win rate from
        42% to 79%. It stays in: in enterprise software the status quo is the
        main competitor, and a deal lost to inaction is a real loss.
        """
        labels = {row["label"] for row in self.losses["table"]}
        self.assertIn("Lost to inaction", labels)
        inaction = next(r for r in self.losses["table"]
                        if r["label"] == "Lost to inaction")
        self.assertGreater(inaction["value"], 0)

    def test_breakdown_shares_sum_to_100(self):
        total = sum(row["pct"] for row in self.losses["table"])
        self.assertAlmostEqual(total, 100.0, delta=0.3)


class ProjectRegister(unittest.TestCase):
    """
    Project attribution uses only labels people wrote themselves. These tests
    pin that choice, because the tempting alternative — matching free prose
    against register names — produced a much larger number that was wrong.
    """

    def setUp(self):
        self.built = pipeline.build(DATA)
        self.projects = self.built["projects"]

    def test_every_register_project_is_either_tracked_or_dark(self):
        total = len(self.projects["tracked"]) + len(self.projects["dark"])
        self.assertEqual(total, self.projects["registered"])

    def test_most_projects_have_no_traceable_time(self):
        """
        The finding, pinned. If this ever flips without a project field being
        added at capture, the matcher has started guessing.
        """
        self.assertGreater(len(self.projects["dark"]),
                           len(self.projects["tracked"]))

    def test_matched_hours_never_exceed_self_declared_hours(self):
        """Only declared rows can match, so matched is a subset by construction."""
        self.assertLessEqual(self.projects["matched_hours"],
                             self.projects["declared_hours"])

    def test_every_match_records_its_tier(self):
        allowed = {"exact name", "name contains the other",
                   "every register word present"}
        for project in self.projects["tracked"]:
            self.assertIn(project["tier"], allowed)

    def test_undeclared_rows_are_never_attributed(self):
        loaded = pipeline.load(DATA)
        pipeline.match_projects(loaded["rows"], loaded["register"])
        for row in loaded["rows"]:
            if not row["_declared_project"]:
                self.assertIsNone(row["_project"], row["notes"][:60])

    def test_misspelled_tags_fold_together(self):
        self.assertEqual(pipeline.TAG_ALIASES["flexcredist"], "flexcredits")
        self.assertEqual(pipeline.TAG_ALIASES["felxcredits"], "flexcredits")

    def test_a_generic_phrase_matches_nothing(self):
        """
        The rejected approach in one assertion: a note full of register
        vocabulary but naming no project must not be attributed.
        """
        rows = [{"notes": "Customer evidence strategy discussion with the industry team",
                 "_hours": 4.0}]
        pipeline.match_projects(rows, pipeline.load(DATA)["register"])
        self.assertIsNone(rows[0]["_project"])

    def test_register_absence_is_survivable(self):
        tmp = tempfile.mkdtemp()
        try:
            for name in os.listdir(DATA):
                if name != "project_register.csv":
                    shutil.copy(os.path.join(DATA, name), tmp)
            built = pipeline.build(tmp)
            self.assertEqual(built["projects"]["registered"], 0)
            self.assertEqual(built["projects"]["tracked"], [])
        finally:
            shutil.rmtree(tmp)


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

    def test_every_tab_renders(self):
        """
        Runs the page's own drawing code against a DOM stub, across every tab,
        quarter and measure. Catches a renamed payload field or a typo in a
        draw function — the kind of break that only shows on one filter.
        """
        import run_render_tests
        passed, engine, output = run_render_tests.run()
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
