# Project: VendorGate — Zamp.ai AI Solutions Associate case study (PS-2 Vendor Onboarding)

## Who I am
I'm Dhruv, a final-year student. I know basic Python and basic JavaScript. I do NOT know React/MERN.
I must understand and explain every line in a live interview, so code must be simple and readable.
I'm on Windows, using VS Code with a Python venv in .venv.

## What we're building
A Streamlit app that takes a vendor submission (JSON/form) and runs 6 stages:
1 Completeness → 2 Format checks → 3 Cross-field consistency → 4 Risk & duplicates → 5 Decision → 6 Vendor email.
Output: APPROVED / PENDING / NEEDS_REVIEW + plain-English reasons + an email listing what the vendor must fix. The system never rejects: NEEDS_REVIEW runs wait for a person to Approve or Reject.
UI: (a) New run page, (b) live run view showing each stage as it executes, (c) dashboard of all runs from SQLite.
Brief: zamp_brief.md (text copy of the PDF, project root). Rules and assumptions: ASSUMPTIONS.md. Deadline: Sunday 27 Sep 2026.

## Fixed design rules (never change without asking me)
- Stack: Python 3.12, Streamlit, sqlite3 (stdlib), rapidfuzz, google-genai. Ask before installing anything else.
- Files: app.py, pipeline.py, checks.py, decision.py, emailer.py, db.py, data/vendor_master.csv, samples/*.json.
- Every check returns a list of Finding dicts: {"stage": str, "check": str, "severity": "pass"|"fixable"|"review"|"blocker", "message": str (plain English for a non-technical buyer), "fix": str|None (what the vendor must do)}.
- Severities: fixable = the vendor can correct it; review = suspicious but possibly legitimate, a person must check; blocker = the system recommends rejection (the data can't be right, or the country is unsupported). A blocker is a recommendation, never a rejection.
- Decision (system): any blocker or review → NEEDS_REVIEW with recommendation "Recommend reject" (if any blocker) or "Check" (review only); else any fixable → PENDING; else APPROVED. needs_human_review = True for every NEEDS_REVIEW run, and only for those.
- Decision (human, built in P7/P9): NEEDS_REVIEW runs show Approve / Reject buttons with a required reviewer name and a required note, saved as final_status, reviewer_name, reviewer_note, reviewed_at. The human decision is final. Only a human can reject. Approve → final_status PENDING (and the vendor gets the fixes email) if the run has any fixable items, otherwise APPROVED. Reject → final_status REJECTED and a rejection email is drafted.
- Repeat submissions: runs are linked by vendor key (PAN for IN, EIN without hyphen for US, else the normalised legal name) and numbered attempt 1, 2, 3…; a new run sets the same vendor's earlier AWAITING REVIEW / PENDING runs (even reviewer-approved PENDING ones) to final_status SUPERSEDED with superseded_by = new run id, keeping any reviewer fields; APPROVED and REJECTED runs are never changed.
- The LLM ONLY writes the vendor email. It never decides status. If the API call fails, use a template email.
- Mask bank account numbers in the UI (last 4 digits only).
- The submission schema is in "Submission schema" below. Don't add or rename fields.

## How to work with me
- Do ONE task at a time; only touch the files the task names.
- Before editing, restate the task in 2–3 lines and list the files you'll change. Wait for my OK on anything bigger than one function.
- Keep functions short (under ~25 lines) with a one-line comment explaining WHY each rule exists.
- No classes, no decorators, no async, no clever one-liners — beginner-readable Python.
- After every change, run the relevant command in the terminal (activate .venv first) and show me the real output. Never claim something works without running it.
- Never edit samples/ or data/ unless the task says so — they are my test cases.
- If you're unsure about a fact (a tax ID format, an API parameter, a Streamlit feature), SAY SO and show me how to verify it. Never invent library functions.
- End each task with: (1) what changed, (2) the command I can run to see it, (3) 3 bullet points I can say in the interview about this part.

## Decisions already made (settled, don't reopen)
- Hosting: Streamlit Community Cloud from a public GitHub repo, API key in Streamlit Secrets. Its disk isn't permanent, so SQLite can reset on restart/redeploy. That's accepted: db.seed_demo_runs() fills history at startup when the table is empty. Say this openly in the demo. When deploying, select Python 3.12 in Streamlit Cloud's "Advanced settings" (to match the local .venv).
- Deliverables: (1) live Streamlit link + GitHub repo, (2) Loom video ≤5 min: happy path + at least one edge case, narrated. Also send the Day-1 email "ASA Case Study — Dhruv — PS-2".
- Documents: no file uploads or parsing. The vendor ticks which documents they're attaching; submission["documents"] is a list of names. Required for IN company: gst_certificate, pan_card, cancelled_cheque. Required for US: w9_form, bank_letter. Missing or wrong document → fixable → PENDING. (Stretch only if time: read a GST certificate PDF with pypdf.)
- Emails: every non-approved run gets an email. PENDING → numbered list of fixes. NEEDS_REVIEW → says the application is under additional review and our team will contact them, plus a numbered list of any fixable items; it never mentions review or blocker findings. A rejection email (polite, says the application can't proceed and what to do next) is only drafted after a human clicks Reject.
- Dashboard: each run shows status, recommendation, reasons, stage-by-stage findings, the email sent, and the reviewer's decision and note if any. This is the audit trail the brief says is missing today.

## Edge cases (samples/ — each must produce exactly this)
| File | Scenario | Expected |
|---|---|---|
| 01_happy.json | IN private limited, everything consistent | APPROVED |
| 02_name_variant.json | Proprietorship; bank holder is a trade-name variant, e.g. "SHARMA TRADERS AND CO" vs "Sharma Traders" (score 80) | PENDING |
| 03_pan_gstin_conflict.json | Every ID valid on its own, but the PAN inside the GSTIN differs from the PAN field in 2+ characters | NEEDS_REVIEW (Recommend reject) |
| 04_duplicate_bank.json | Bank account already belongs to another vendor in data/vendor_master.csv | NEEDS_REVIEW (Check) |
| 05_us_vendor.json | US LLC with EIN + routing number, no GST/PAN | APPROVED |
Also: "Pvt Ltd" vs "Private Limited" must still pass (normalisation), not be flagged. A 1-character PAN/GSTIN difference is a typo → fixable → PENDING.

## Submission schema
{
  "legal_name": "Sharma Traders Private Limited",
  "entity_type": "company",            // company | proprietorship | partnership | llc
  "country": "IN",                      // IN | US
  "state": "Maharashtra",
  "address": "12 MG Road, Pune",
  "contact_email": "accounts@sharmatraders.in",
  "website": "sharmatraders.in",
  "tax": {"pan": "AABCS1234F", "gstin": "27AABCS1234F1Z5", "ein": null},
  "bank": {"account_holder": "SHARMA TRADERS PVT LTD", "account_number": "50100234567821", "ifsc": "HDFC0001234", "routing_number": null},
  "documents": ["gst_certificate", "pan_card", "cancelled_cheque"]
}
The values above are illustrative; samples must use valid formats (checked in P4).