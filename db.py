"""VendorGate storage: every run is saved to SQLite so the dashboard has a full audit trail."""

import glob
import json
import os
import sqlite3
from datetime import datetime

from checks import clean_id, get_country, get_field, is_blank, normalise_text
from pipeline import run_pipeline

# Paths are built from this file's folder, so they work wherever Streamlit is started from.
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "vendorgate.db")
SAMPLES_PATTERN = os.path.join(HERE, "samples", "*.json")

# Columns added after the first version: (name, SQLite type). init_db adds any an older database lacks.
NEW_COLUMNS = [("vendor_key", "TEXT"), ("attempt", "INTEGER"), ("superseded_by", "INTEGER")]


def connect():
    # sqlite3.Row lets us turn each row into a dict with column names as keys.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def vendor_key(submission):
    # Tax IDs identify a business; names are the fallback because vendors spell them differently.
    country = get_country(submission)
    tax_id = None
    if country == "IN":
        tax_id = get_field(submission, "tax", "pan")
    elif country == "US":
        tax_id = get_field(submission, "tax", "ein")
    if not is_blank(tax_id):
        # EINs are written 12-3456789 or 123456789; dropping the hyphen gives both the same key.
        return clean_id(tax_id).replace("-", "")
    name_key = normalise_text(submission.get("legal_name"))
    if name_key == "":
        return None  # nothing to link on, so this run is treated as a new vendor
    return name_key


def add_missing_columns(conn):
    # A database made before these columns existed gets them added, without losing any runs.
    existing = []
    for row in conn.execute("PRAGMA table_info(runs)").fetchall():
        existing.append(row["name"])
    for name, column_type in NEW_COLUMNS:
        if name not in existing:
            # Safe to build with an f-string: both parts come from NEW_COLUMNS, never from user input.
            conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {column_type}")


def next_attempt(conn, key, run_id):
    # Attempt number = how many earlier runs this vendor already has, plus one.
    row = conn.execute("SELECT COUNT(*) FROM runs WHERE vendor_key = ? AND id < ?",
                       (key, run_id)).fetchone()
    return row[0] + 1


def backfill_vendor_keys(conn):
    # Old runs get a key and attempt number, but are never superseded: past history stays as it was.
    rows = conn.execute("SELECT id, submission_json FROM runs WHERE attempt IS NULL ORDER BY id").fetchall()
    for row in rows:
        key = vendor_key(json.loads(row["submission_json"]))
        attempt = next_attempt(conn, key, row["id"])  # rows go oldest first, so earlier ones already have keys
        conn.execute("UPDATE runs SET vendor_key = ?, attempt = ? WHERE id = ?", (key, attempt, row["id"]))


def init_db():
    # IF NOT EXISTS + add_missing_columns make this safe to call every time the app starts.
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
    add_missing_columns(conn)  # the NEW_COLUMNS, so old and new databases end up the same
    backfill_vendor_keys(conn)
    conn.commit()
    conn.close()


def now_text():
    # One readable timestamp format for created_at and reviewed_at.
    return datetime.now().isoformat(timespec="seconds")


def supersede_open_runs(conn, key, new_run_id):
    # A newer attempt replaces this vendor's earlier runs still waiting on them or on a reviewer.
    # APPROVED and REJECTED are final answers, so they never change. A reviewer-approved PENDING
    # run keeps its reviewer name, note and time: only final_status and superseded_by are set.
    conn.execute(
        "UPDATE runs SET final_status = 'SUPERSEDED', superseded_by = ? "
        "WHERE vendor_key = ? AND id < ? AND final_status IN ('AWAITING REVIEW', 'PENDING')",
        (new_run_id, key, new_run_id))


def save_run(submission, findings, decision, email_text="", email_source=""):
    # NEEDS_REVIEW runs have no final answer until a person decides, so they start as AWAITING REVIEW.
    final_status = decision["status"]
    if decision["status"] == "NEEDS_REVIEW":
        final_status = "AWAITING REVIEW"
    key = vendor_key(submission)
    conn = connect()
    cursor = conn.execute(
        "INSERT INTO runs (created_at, vendor_name, country, status, recommendation, "
        "needs_human_review, submission_json, findings_json, decision_json, "
        "email_text, email_source, final_status, vendor_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_text(), submission.get("legal_name"), submission.get("country"),
         decision["status"], decision["recommendation"], int(decision["needs_human_review"]),
         json.dumps(submission), json.dumps(findings), json.dumps(decision),
         email_text, email_source, final_status, key))
    run_id = cursor.lastrowid
    # One commit for all three steps, so a crash can't leave a run without its attempt number.
    conn.execute("UPDATE runs SET attempt = ? WHERE id = ?", (next_attempt(conn, key, run_id), run_id))
    supersede_open_runs(conn, key, run_id)
    conn.commit()
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


def earlier_attempts(key, run_id):
    # The same vendor's older runs, oldest first, so a reviewer sees what happened before.
    conn = connect()
    rows = conn.execute("SELECT * FROM runs WHERE vendor_key = ? AND id < ? ORDER BY id",
                        (key, run_id)).fetchall()
    conn.close()
    runs = []
    for row in rows:
        runs.append(dict(row))
    return runs


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
    if run["final_status"] != "AWAITING REVIEW":
        # e.g. a page left open while the vendor resubmitted: review the newer attempt instead.
        raise ValueError(f"This run is {run['final_status']}, so it can no longer be reviewed.")
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
