/*
 * Pure computation for the dashboard. No DOM, no I/O, no globals beyond the
 * one export below, so it can be run head-first by a JavaScript engine in a
 * test and inlined into the page at build time.
 *
 * Everything that decides *what a number is* lives here. The template keeps
 * only the code that decides what it looks like. That split is deliberate:
 * both of the real bugs found in review were aggregation bugs, in code that
 * was unreachable from a test while it sat inside the page.
 */
var VMDash = (function () {
  "use strict";

  // --- formatting ---------------------------------------------------------
  // Separators follow the viewer's locale on purpose. Tests must not assert
  // on them; assert on the shape instead.
  function num(n, d) {
    d = d || 0;
    return Number(n).toLocaleString(undefined,
      { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function pct(n) { return num(n, 1) + "%"; }

  function money(n) {
    if (n >= 1e6) return "$" + (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return "$" + Math.round(n / 1e3) + "k";
    return "$" + num(n);
  }

  // --- quarter helpers ----------------------------------------------------

  /** Real quarter keys, never the synthetic "all" bucket. */
  function quarterKeys(data) {
    return Object.keys(data.quarters).filter(function (k) { return k !== "__all__"; });
  }

  /**
   * A quarter clipped by the edge of the export is not comparable with a full
   * one, and must be labelled rather than charted as a decline.
   */
  function isStub(quarter) {
    return quarter.week_count > 0 && quarter.week_count < 4;
  }

  /**
   * The whole-period view.
   *
   * Only weeks, hours, person-weeks and the people set are summed, because
   * those are additive. Everything else is taken from the pipeline, which
   * computes it once from the rows:
   *
   *  - deal values and opportunity counts would double-count an opportunity
   *    worked either side of a quarter boundary;
   *  - the activity tables keep only each quarter's top rows, so summing them
   *    divides by a truncated denominator and inflates every share.
   *
   * Both of those shipped as bugs before this function was testable.
   */
  function makeAll(data) {
    var out = {
      label: "All reported weeks",
      weeks: [], people: [], week_count: 0, person_count: 0,
      hours: 0, person_weeks: 0
    };
    var peopleSet = {};

    quarterKeys(data).forEach(function (k) {
      var q = data.quarters[k];
      out.weeks = out.weeks.concat(q.weeks);
      out.hours += q.hours;
      out.person_weeks += q.person_weeks;
      q.people.forEach(function (p) { peopleSet[p] = 1; });
    });

    out.funnel = data.period_funnel;
    Object.keys(data.period_tables).forEach(function (t) {
      out[t] = data.period_tables[t];
    });

    out.week_count = out.weeks.length;
    out.people = Object.keys(peopleSet).sort();
    out.person_count = out.people.length;
    out.hours = Math.round(out.hours * 10) / 10;
    out.person_weeks = Math.round(out.person_weeks * 10) / 10;
    out.hours_per_person_week = out.person_weeks
      ? Math.round(10 * out.hours / out.person_weeks) / 10 : 0;
    out.prospect_facing_pct = data.headline.prospect_facing_pct;
    return out;
  }

  // --- chart data ---------------------------------------------------------

  /**
   * Pair each row of the selected measure with the same label's share under
   * the other measure. A label missing from the other table leaves `other`
   * undefined, and the caller draws no comparison rather than a false zero.
   */
  function pairRows(primary, secondary) {
    var map = {};
    (secondary || []).forEach(function (r) { map[r.label] = r.pct; });
    return (primary || []).map(function (r) {
      return {
        label: r.label, value: r.value, pct: r.pct,
        other: map[r.label], bulk_pct: r.bulk_pct
      };
    });
  }

  /** How to read a gap between counting everyone and counting itemised loggers. */
  function lensVerdict(gap) {
    if (Math.abs(gap) < 1.5) return "solid";
    return gap > 0 ? "inflated" : "understated";
  }

  /** The four evidence-chain steps, each a subset of the one before it. */
  function funnelSteps(funnel) {
    var top = funnel.all_hours || 1;
    var rows = [
      { key: "all", label: "All effort logged", hours: funnel.all_hours },
      { key: "opp", label: "Names an opportunity", hours: funnel.opp_linked_hours },
      { key: "crm", label: "Found in the CRM extract", hours: funnel.crm_matched_hours },
      { key: "won", label: "On a deal that was won", hours: funnel.won_hours }
    ];
    return rows.map(function (r) {
      r.share = 100 * r.hours / top;
      return r;
    });
  }

  return {
    num: num, pct: pct, money: money,
    quarterKeys: quarterKeys, isStub: isStub, makeAll: makeAll,
    pairRows: pairRows, lensVerdict: lensVerdict, funnelSteps: funnelSteps
  };
})();

if (typeof module === "object" && module.exports) { module.exports = VMDash; }
