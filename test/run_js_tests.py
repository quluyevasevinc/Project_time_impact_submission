#!/usr/bin/env python3
"""
Run the dashboard's JavaScript tests on whatever engine the machine has.

    python3 run_js_tests.py

No install required. macOS ships JavaScriptCore; CI runners ship Node. The two
source files are concatenated and piped to the engine, so the test file itself
needs no module system and runs identically under both.

`python3 -m unittest` calls this too, so one command covers both languages.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Ordered by preference. jsc is first on macOS because it needs no install.
ENGINES = [
    ("jsc", ["/System/Library/Frameworks/JavaScriptCore.framework/"
             "Versions/A/Helpers/jsc"]),
    ("node", ["node"]),
    ("deno", ["deno", "run", "-"]),
    ("bun", ["bun", "run", "-"]),
]


def find_engine():
    """Return (name, argv) for the first usable engine, or (None, None)."""
    for name, argv in ENGINES:
        candidate = argv[0]
        if os.path.isabs(candidate):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return name, argv
        elif shutil.which(candidate):
            return name, argv
    return None, None


def build_script():
    parts = []
    for filename in ("dashboard_logic.js", "test_dashboard.js"):
        with open(os.path.join(HERE, filename), encoding="utf-8") as handle:
            parts.append(handle.read())
    return "\n;\n".join(parts)


def run():
    """Return (ok, engine_name, output). ok is None when no engine was found."""
    name, argv = find_engine()
    if not name:
        return None, None, (
            "No JavaScript engine found. Install Node (`brew install node`) or "
            "run on macOS, which ships JavaScriptCore."
        )

    script = build_script()
    if name in ("jsc",):
        # jsc reads a file, not stdin.
        tmp = os.path.join(HERE, ".js_tests_bundle.js")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(script)
            proc = subprocess.run(argv + [tmp], capture_output=True, text=True)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    else:
        proc = subprocess.run(argv, input=script, capture_output=True, text=True)

    output = (proc.stdout + proc.stderr).strip()
    passed = "JS TESTS PASSED" in output and proc.returncode == 0
    return passed, name, output


def main():
    passed, name, output = run()
    if passed is None:
        print(output)
        return 0          # not a failure, just nothing to run on
    print(f"[{name}] {output}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
