/*
 * Tests for the dashboard's computation layer.
 *
 * Plain ECMAScript with no file I/O, so the same file runs under Node, under
 * macOS's built-in jsc, or anywhere else. `run_js_tests.py` concatenates
 * dashboard_logic.js in front of this and feeds the result to whichever
 * engine is on the machine; `python3 -m unittest` runs that automatically.
 *
 * Number formatting follows the viewer's locale, so nothing here asserts on
 * thousands separators or decimal marks.
 */

var failures = [];
var checks = 0;

function ok(condition, name, detail) {
  checks++;
  if (!condition) failures.push(name + (detail ? " — " + detail : ""));
}

function eq(actual, expected, name) {
  ok(actual === expected, name, "expected " + JSON.stringify(expected) +
     ", got " + JSON.stringify(actual));
}

function near(actual, expected, name, tolerance) {
  tolerance = tolerance === undefined ? 1e-9 : tolerance;
  ok(Math.abs(actual - expected) <= tolerance, name,
     "expected ~" + expected + ", got " + actual);
}

// ---------------------------------------------------------------------------
// A fixture shaped like the pipeline's output. The quarters deliberately
// disagree with the period figures the way real data does: the same
// opportunity is worked in both quarters, and each quarter's activity table
// is truncated to its own top rows.
// ---------------------------------------------------------------------------

function fixture() {
  var activityQ1 = [
    { label: "Build", value: 60, pct: 60, bulk_pct: 70 },
    { label: "Advise", value: 20, pct: 20, bulk_pct: 0 }
  ];
  var activityQ2 = [
    { label: "Build", value: 40, pct: 40, bulk_pct: 50 },
    { label: "Advise", value: 30, pct: 30, bulk_pct: 0 }
  ];
  return {
    headline: { prospect_facing_pct: 9.1, people: 4, bulk_people: 2 },
    quarters: {
      "FY27 Q1": {
        label: "FY27 Q1", weeks: ["2026-05-04", "2026-05-11"], week_count: 2,
        people: ["Ana", "Bo"], person_count: 2, hours: 100, person_weeks: 4,
        funnel: {
          all_hours: 100, opp_linked_hours: 40, crm_matched_hours: 10, won_hours: 4,
          opps_touched: 3, opps_matched: 2, opps_won: 1,
          value_touched: 300, value_matched: 200, value_won: 100
        },
        by_activity_pw: activityQ1, by_activity_hours: activityQ1,
        by_category_pw: [{ label: "Delivery", value: 80, pct: 80 }]
      },
      "FY27 Q2": {
        label: "FY27 Q2",
        weeks: ["2026-05-18", "2026-05-25", "2026-06-01", "2026-06-08", "2026-06-15"],
        week_count: 5, people: ["Bo", "Cy"], person_count: 2,
        hours: 200, person_weeks: 8,
        funnel: {
          all_hours: 200, opp_linked_hours: 60, crm_matched_hours: 20, won_hours: 6,
          opps_touched: 4, opps_matched: 2, opps_won: 1,
          value_touched: 400, value_matched: 200, value_won: 100
        },
        by_activity_pw: activityQ2, by_activity_hours: activityQ2,
        by_category_pw: [{ label: "Delivery", value: 150, pct: 75 }]
      }
    },
    // One opportunity (worth 150, won) was worked in both quarters, so the
    // period totals are lower than the quarters added together.
    period_funnel: {
      all_hours: 300, opp_linked_hours: 100, crm_matched_hours: 30, won_hours: 10,
      opps_touched: 6, opps_matched: 3, opps_won: 1,
      value_touched: 550, value_matched: 250, value_won: 100
    },
    period_tables: {
      by_activity_pw: [
        { label: "Build", value: 100, pct: 33.3, bulk_pct: 60 },
        { label: "Advise", value: 50, pct: 16.7, bulk_pct: 0 }
      ],
      by_activity_hours: [
        { label: "Build", value: 100, pct: 33.3, bulk_pct: 60 }
      ],
      by_category_pw: [{ label: "Delivery", value: 230, pct: 76.7 }]
    }
  };
}

// ---------------------------------------------------------------------------
// makeAll — where both shipped bugs lived
// ---------------------------------------------------------------------------

var data = fixture();
var all = VMDash.makeAll(data);

eq(all.week_count, 7, "makeAll sums week counts");
eq(all.person_count, 3, "makeAll counts distinct people, not the sum per quarter");
near(all.hours, 300, "makeAll sums hours");
near(all.person_weeks, 12, "makeAll sums person-weeks");
near(all.hours_per_person_week, 25, "makeAll recomputes hours per person-week");
eq(all.prospect_facing_pct, 9.1, "makeAll takes prospect-facing from the headline");

// Regression 1: deal values must not be the sum of the quarters.
var summedValue = data.quarters["FY27 Q1"].funnel.value_touched +
                  data.quarters["FY27 Q2"].funnel.value_touched;
eq(summedValue, 700, "fixture: quarters add up to more than the period");
eq(all.funnel.value_touched, 550, "makeAll takes deal value from the period funnel");
ok(all.funnel.value_touched < summedValue,
   "deal value is not double-counted across quarters");
eq(all.funnel.opps_touched, 6, "opportunity counts come from the period funnel");
eq(all.funnel.opps_won, 1, "a deal won once is not counted once per quarter");

// Regression 2: activity shares must not be recomputed over a truncated total.
eq(all.by_activity_pw.length, 2, "makeAll takes activity tables from the period");
near(all.by_activity_pw[0].pct, 33.3, "activity share keeps the full denominator",
     0.05);
ok(all.by_activity_pw[0].pct + all.by_activity_pw[1].pct < 99,
   "a truncated table must not sum to 100%");
eq(all.by_activity_pw[0].bulk_pct, 60, "bulk share survives into the period view");

// makeAll must not mutate what it reads.
eq(data.quarters["FY27 Q1"].weeks.length, 2, "makeAll leaves quarter weeks alone");
eq(data.period_funnel.value_touched, 550, "makeAll leaves the period funnel alone");

// ---------------------------------------------------------------------------
// quarterKeys / isStub
// ---------------------------------------------------------------------------

data.quarters["__all__"] = all;
eq(VMDash.quarterKeys(data).length, 2, "quarterKeys excludes the synthetic bucket");
ok(VMDash.quarterKeys(data).indexOf("__all__") === -1,
   "quarterKeys never returns __all__");

ok(VMDash.isStub({ week_count: 1 }), "a one-week quarter is a stub");
ok(VMDash.isStub({ week_count: 3 }), "a three-week quarter is a stub");
ok(!VMDash.isStub({ week_count: 4 }), "a four-week quarter is not a stub");
ok(!VMDash.isStub({ week_count: 13 }), "a full quarter is not a stub");
ok(!VMDash.isStub({ week_count: 0 }), "an empty quarter is not labelled a stub");
ok(!VMDash.isStub(all), "the all-weeks view is never a stub");

// ---------------------------------------------------------------------------
// pairRows
// ---------------------------------------------------------------------------

var paired = VMDash.pairRows(
  [{ label: "Build", value: 1, pct: 40, bulk_pct: 60 }, { label: "Only here", value: 1, pct: 10 }],
  [{ label: "Build", value: 1, pct: 25 }]
);
eq(paired.length, 2, "pairRows keeps every primary row");
eq(paired[0].other, 25, "pairRows attaches the other measure by label");
eq(paired[0].bulk_pct, 60, "pairRows carries the bulk share through");
eq(paired[1].other, undefined,
   "a label absent from the other table gets no comparison, not a zero");
eq(VMDash.pairRows(null, null).length, 0, "pairRows tolerates missing tables");

// ---------------------------------------------------------------------------
// funnelSteps
// ---------------------------------------------------------------------------

var steps = VMDash.funnelSteps(all.funnel);
eq(steps.length, 4, "the evidence chain has four steps");
near(steps[0].share, 100, "the first step is the whole");
for (var i = 1; i < steps.length; i++) {
  ok(steps[i].hours <= steps[i - 1].hours,
     "funnel step " + i + " is a subset of the one before it");
  ok(steps[i].share <= steps[i - 1].share, "funnel share " + i + " never increases");
}
near(steps[2].share, 10, "crm-matched share is computed against all hours");

var emptyFunnel = VMDash.funnelSteps({
  all_hours: 0, opp_linked_hours: 0, crm_matched_hours: 0, won_hours: 0
});
ok(isFinite(emptyFunnel[0].share), "an empty funnel does not divide by zero");

// ---------------------------------------------------------------------------
// lensVerdict
// ---------------------------------------------------------------------------

eq(VMDash.lensVerdict(0), "solid", "no gap reads as solid");
eq(VMDash.lensVerdict(1.4), "solid", "a gap under the threshold reads as solid");
eq(VMDash.lensVerdict(-1.4), "solid", "a small negative gap reads as solid");
eq(VMDash.lensVerdict(18.7), "inflated", "a large positive gap reads as inflated");
eq(VMDash.lensVerdict(-3.9), "understated", "a negative gap reads as understated");

// ---------------------------------------------------------------------------
// formatting — shape only, never separators
// ---------------------------------------------------------------------------

eq(VMDash.money(1584500), "$1.6M", "millions round to one decimal");
eq(VMDash.money(51493300), "$51.5M", "the headline pipeline figure formats correctly");
eq(VMDash.money(2900), "$3k", "thousands round to whole thousands");
eq(VMDash.money(999), "$999", "under a thousand stays plain");
eq(VMDash.money(0), "$0", "zero formats as zero, not an empty string");
ok(VMDash.pct(38.8).indexOf("%") > 0, "pct carries a percent sign");
ok(VMDash.pct(38.8).indexOf("38") === 0, "pct keeps the integer part");
ok(VMDash.num(1.25, 1).indexOf("1") === 0, "num respects the requested precision");

// ---------------------------------------------------------------------------

if (failures.length) {
  print_("JS TESTS FAILED (" + failures.length + " of " + checks + " checks)");
  for (var f = 0; f < failures.length; f++) print_("  - " + failures[f]);
} else {
  print_("JS TESTS PASSED (" + checks + " checks)");
}

function print_(s) {
  if (typeof console !== "undefined" && console.log) console.log(s);
  else print(s);           // jsc
}
