#!/usr/bin/env python3
"""
Build the dashboard.

    python3 build.py

Reads every CSV in data/ and writes dashboard.html — one self-contained file
with no external requests, which means it opens by double-clicking, works
offline, and can be emailed or archived as a snapshot of the week.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pipeline  # noqa: E402


def main():
    data_dir = os.path.join(HERE, "data")
    out_path = os.path.join(HERE, "dashboard.html")
    template_path = os.path.join(HERE, "template.html")

    print("Reading  " + data_dir)
    payload = pipeline.build(data_dir)

    for name in payload["files"]:
        print("  found  " + name)
    for warning in payload["warnings"]:
        print("  NOTE   " + warning)

    with open(template_path, encoding="utf-8") as handle:
        template = handle.read()
    with open(os.path.join(HERE, "dashboard_logic.js"), encoding="utf-8") as handle:
        logic = handle.read()

    # </script> inside the JSON or the script would close the host tag early.
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("__DATA__", blob)
    html = html.replace("__LOGIC__", logic.replace("</script", "<\\/script"))

    for placeholder in ("__DATA__", "__LOGIC__"):
        if placeholder in html:
            raise SystemExit(f"{placeholder} was not substituted — the template "
                             f"and build step are out of step.")

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(html)

    head = payload["headline"]
    period = payload["period"]
    print("")
    print("Wrote    dashboard.html  ({:,} KB)".format(len(html) // 1024))
    print("  {} complete weeks, {} to {}".format(
        head["weeks"], period["first_week"], period["last_week"]))
    print("  {:,} hours  ·  {:,} person-weeks  ·  {} people".format(
        head["total_hours"], head["person_weeks"], head["people"]))
    print("  reporting coverage {}%  ·  {}% of hours traceable to a closed deal".format(
        head["coverage_pct"], head["crm_matched_pct"]))
    if period["partial_weeks"]:
        print("  excluded still-filling week(s): "
              + ", ".join(period["partial_weeks"]))
    print("")
    print("Open dashboard.html in any browser.")


if __name__ == "__main__":
    main()
