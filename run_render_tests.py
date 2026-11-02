#!/usr/bin/env python3
"""
Run the dashboard's rendering code head-first.

    python3 run_render_tests.py

Builds a bundle of: the DOM shim, the page's own scripts (taken from the built
dashboard.html, so this tests what actually ships), and a driver that walks
every tab under every filter. Runs it on the same engine as the other
JavaScript tests.

`python3 -m unittest` calls this, so one command still covers everything.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_js_tests  # noqa: E402

DRIVER = r"""
var problems = [];
var rendered = 0;

function sweep() {
  var keys = VMDash.quarterKeys(DATA_REF).concat(["__all__"]);
  var tabs = ["overview", "time", "people", "impact", "projects", "health"];
  keys.forEach(function (q) {
    ["pw", "hr"].forEach(function (measure) {
      tabs.forEach(function (tab) {
        STATE_REF.quarter = q;
        STATE_REF.measure = measure;
        STATE_REF.tab = tab;
        // Wipe everything first, so whatever is found afterwards was written
        // by this render and is attributed to the right tab. An earlier
        // version scanned only the tab element — but the page writes into
        // sibling containers, so almost nothing was actually being checked.
        resetHosts();
        try {
          RENDER_REF();
          rendered++;
        } catch (e) {
          problems.push(q + "/" + measure + "/" + tab + ": " + e);
          return;
        }
        var text = collectText(document._root);
        var bad = text.match(/NaN|undefined|Infinity|\[object Object\]/);
        if (bad) {
          problems.push(q + "/" + measure + "/" + tab
                        + ": rendered the literal " + bad[0]);
        }
      });
    });
  });
}

function collectText(node) {
  var out = (node._text || "") + " " + (node._html || "");
  node.childNodes.forEach(function (c) { out += " " + collectText(c); });
  return out;
}

sweep();

// Tables must actually carry rows, not just render without throwing. Each is
// re-rendered immediately before being measured, since the sweep clears hosts.
[
  ["projects", "projTable", 2, "projects table"],
  ["projects", "darkTable", 2, "registered-but-invisible table"],
  ["impact", "matchTable", 2, "matched-opportunities table"],
  ["people", "peopleTable", 2, "people table"],
  ["health", "issueTable", 2, "data-health table"]
].forEach(function (check) {
  resetHosts();
  STATE_REF.tab = check[0];
  STATE_REF.quarter = "__all__";
  RENDER_REF();
  var rows = document.getElementById(check[1]).childNodes.length;
  if (rows < check[2]) problems.push(check[3] + " rendered no body");
});

if (problems.length) {
  print_("RENDER TESTS FAILED (" + problems.length + " of " + rendered + " renders)");
  problems.forEach(function (p) { print_("  - " + p); });
} else {
  print_("RENDER TESTS PASSED (" + rendered + " renders across every tab, "
         + "quarter and measure)");
}

function print_(s) {
  if (typeof console !== "undefined" && console.log) console.log(s);
  else print(s);
}
"""


def page_scripts():
    """The scripts as they ship, read out of the built page."""
    path = os.path.join(HERE, "dashboard.html")
    if not os.path.exists(path):
        return None, None
    html = open(path, encoding="utf-8").read()
    payload = re.search(r'<script id="payload"[^>]*>(.*?)</script>', html, re.S)
    scripts = re.findall(
        r'<script(?![^>]*application/json)[^>]*>(.*?)</script>', html, re.S)
    return payload.group(1).replace("<\\/", "</"), scripts


def build_bundle():
    payload, scripts = page_scripts()
    if payload is None:
        return None

    html = open(os.path.join(HERE, "dashboard.html"), encoding="utf-8").read()
    element_ids = sorted(set(re.findall(r'\bid="([\w-]+)"', html)))
    if "payload" not in element_ids:
        raise SystemExit("could not find the page's elements — has the template "
                         "stopped using id attributes?")

    shim = open(os.path.join(HERE, "test_render.js"), encoding="utf-8").read()
    shim = shim.replace("PAYLOAD_JSON", json.dumps(payload))
    shim = shim.replace("ELEMENT_IDS", json.dumps(element_ids))

    # The page wraps itself in an IIFE and keeps its state private. Expose the
    # three handles the driver needs, without altering any behaviour.
    main = scripts[-1]
    main = main.replace(
        "render();\n})();",
        "render();\nwindow.__probe = {render: render, state: state, D: D};\n})();")
    if "__probe" not in main:
        raise SystemExit("could not attach to the page's render loop — "
                         "the template's closing lines changed")

    driver = (DRIVER
              .replace("DATA_REF", "window.__probe.D")
              .replace("STATE_REF", "window.__probe.state")
              .replace("RENDER_REF", "window.__probe.render"))

    return "\n;\n".join([shim] + scripts[:-1] + [main, driver])


def run():
    """Return (ok, engine_name, output); ok is None when nothing could run."""
    bundle = build_bundle()
    if bundle is None:
        return None, None, "dashboard.html not built yet — run python3 build.py first"

    name, argv = run_js_tests.find_engine()
    if not name:
        return None, None, "No JavaScript engine found."

    tmp = os.path.join(HERE, ".render_bundle.js")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(bundle)
        import subprocess
        if name == "jsc":
            proc = subprocess.run(argv + [tmp], capture_output=True, text=True)
        else:
            proc = subprocess.run(argv, input=bundle, capture_output=True, text=True)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    output = (proc.stdout + proc.stderr).strip()
    return ("RENDER TESTS PASSED" in output and proc.returncode == 0), name, output


def main():
    passed, name, output = run()
    if passed is None:
        print(output)
        return 0
    print(f"[{name}] {output}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
