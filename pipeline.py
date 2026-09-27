"""VendorGate pipeline: runs the check stages in order, then the decision."""

import json
import sys
import time

from checks import run_completeness, run_format, run_consistency, run_risk
from decision import decide, count_severities

# (name, function) pairs in the order they run; adding a stage means adding one line here.
STAGES = [
    ("completeness", run_completeness),
    ("format", run_format),
    ("consistency", run_consistency),
    ("risk", run_risk),
]


def run_pipeline(submission):
    # A generator: it hands back each stage as soon as it finishes, so the UI can show it live.
    all_findings = []
    for name, stage_function in STAGES:
        start = time.perf_counter()
        findings = stage_function(submission)
        seconds = time.perf_counter() - start
        all_findings = all_findings + findings
        yield {"stage": name, "findings": findings, "seconds": seconds}
    yield {"stage": "decision", "result": decide(all_findings)}


def print_numbered(title, items):
    # Numbered lists are how the fixes will read in the vendor email too.
    print(f"{title} ({len(items)}):")
    if len(items) == 0:
        print("  (none)")
    for i in range(len(items)):
        print(f"  {i + 1}. {items[i]}")


def print_event(event):
    # One line per check stage, then the final decision with its reasons and fixes.
    if event["stage"] != "decision":
        c = count_severities(event["findings"])
        print(f"{event['stage']:<13} pass={c['pass']} fixable={c['fixable']} "
              f"review={c['review']} blocker={c['blocker']}  ({event['seconds']:.3f}s)")
        return
    result = event["result"]
    print(f"STATUS: {result['status']}   recommendation: {result['recommendation']}")
    print_numbered("Reasons (internal)", result["reasons"])
    print_numbered("Fixes (vendor-facing)", result["fixes"])


if __name__ == "__main__":
    # Manual test: python pipeline.py [path to a submission JSON]. Defaults to the happy sample.
    path = "samples/01_happy.json"
    if len(sys.argv) > 1:
        path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        submission = json.load(f)
    for event in run_pipeline(submission):
        print_event(event)
