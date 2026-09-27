"""VendorGate storage: every run is saved to SQLite so the dashboard has a full audit trail."""

import glob
import json
import os
import sqlite3
from datetime import datetime

from pipeline import run_pipeline

# Paths are built from this file's folder, so they work wherever Streamlit is started from.
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "vendorgate.db")
SAMPLES_PATTERN = os.path.join(HERE, "samples", "*.json")


def connect():
    # sqlite3.Row lets us turn each row into a dict with column names as keys.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    # IF NOT EXISTS makes this safe to call every time the app starts.
    conn = connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, vendor_name TEXT, country TEXT,
            status TEXT, recommendation TEXT, needs_human_review INTEGER,
            submission_json TEXT, findings_json TEXT, decision_json TEXT,
            email_text TEXT, email_source TEXT,
            final_status TEXT, reviewer_name TEXT, reviewer_note TEXT, reviewed_at TEXT
        )""")
    conn.commit()
    conn.close()


def now_text():
    # One readable timestamp format for created_at and reviewed_at.
    return datetime.now().isoformat(timespec="seconds")


def save_run(submission, findings, decision, email_text="", email_source=""):
    # NEEDS_REVIEW runs have no final answer until a person decides, so they start as AWAITING REVIEW.
    final_status = decision["status"]
    if decision["status"] == "NEEDS_REVIEW":
        final_status = "AWAITING REVIEW"
    conn = connect()
    cursor = conn.execute(
        "INSERT INTO runs (created_at, vendor_name, country, status, recommendation, "
        "needs_human_review, submission_json, findings_json, decision_json, "
        "email_text, email_source, final_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_text(), submission.get("legal_name"), submission.get("country"),
         decision["status"], decision["recommendation"], int(decision["needs_human_review"]),
         json.dumps(submission), json.dumps(findings), json.dumps(decision),
         email_text, email_source, final_status))
    conn.commit()
    run_id = cursor.lastrowid
    conn.close()
    return run_id


def list_runs():
    # Sorted by id, not created_at: two runs saved in the same second would otherwise tie.
    conn = connect()
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    conn.close()
    runs = []
    for row in rows:
        runs.append(dict(row))
    return runs


def get_run(run_id):
    # The UI wants real dicts and lists back, not JSON strings.
    conn = connect()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    run = dict(row)
    run["submission"] = json.loads(run["submission_json"])
    run["findings"] = json.loads(run["findings_json"])
    run["decision"] = json.loads(run["decision_json"])
    return run


def final_status_after_review(action, decision):
    # Approving the flag doesn't erase fixable items: the vendor still has to fix them.
    if action == "reject":
        return "REJECTED"
    if len(decision["fixes"]) > 0:
        return "PENDING"
    return "APPROVED"


def record_review(run_id, action, reviewer_name, note):
    # Only a named person with a written reason can decide a flagged run, and only once.
    run = get_run(run_id)
    if run is None:
        raise ValueError(f"Run {run_id} does not exist.")
    if run["status"] != "NEEDS_REVIEW":
        raise ValueError("Only NEEDS_REVIEW runs can be reviewed.")
    if run["reviewed_at"] is not None:
        raise ValueError("This run has already been reviewed.")
    if action not in ["approve", "reject"]:
        raise ValueError("Action must be 'approve' or 'reject'.")
    if reviewer_name.strip() == "" or note.strip() == "":
        raise ValueError("Reviewer name and note are both required.")
    final_status = final_status_after_review(action, run["decision"])
    conn = connect()
    conn.execute(
        "UPDATE runs SET final_status = ?, reviewer_name = ?, reviewer_note = ?, reviewed_at = ? "
        "WHERE id = ?",
        (final_status, reviewer_name.strip(), note.strip(), now_text(), run_id))
    conn.commit()
    conn.close()


def seed_demo_runs():
    # Streamlit Cloud's disk resets on restart, so refill the dashboard from samples/ when empty.
    init_db()
    conn = connect()
    count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conn.close()
    if count > 0:
        return
    for path in sorted(glob.glob(SAMPLES_PATTERN)):
        with open(path, encoding="utf-8") as f:
            submission = json.load(f)
        findings = []
        decision = None
        for event in run_pipeline(submission):
            if event["stage"] == "decision":
                decision = event["result"]
            else:
                findings = findings + event["findings"]
        save_run(submission, findings, decision)
