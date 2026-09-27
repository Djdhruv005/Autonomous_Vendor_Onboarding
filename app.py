"""VendorGate UI: a New run page that checks one vendor live, and a dashboard of all runs."""

import glob
import json
import os
import time

import streamlit as st

import db
import emailer
from checks import (STATE_CODES, INDIA_DOCUMENTS, US_DOCUMENTS, get_country, get_field,
                    is_blank, mask_account, normalise_state)
from decision import count_severities
from pipeline import run_pipeline

ENTITY_TYPES = ["company", "proprietorship", "partnership", "llc"]
COUNTRIES = ["IN", "US"]
FIRST_SAMPLE = os.path.join(db.HERE, "samples", "01_happy.json")

# Every document a vendor can tick, from both countries: name -> label shown in the form.
ALL_DOCUMENTS = {}
ALL_DOCUMENTS.update(INDIA_DOCUMENTS)
ALL_DOCUMENTS.update(US_DOCUMENTS)

# Plain-text fields in the form: (section in the submission, field name). Widget key = "f_" + name.
TEXT_FIELDS = [
    (None, "legal_name"), (None, "address"), (None, "contact_email"), (None, "website"),
    ("tax", "pan"), ("tax", "gstin"), ("tax", "ein"),
    ("bank", "account_holder"), ("bank", "account_number"), ("bank", "ifsc"), ("bank", "routing_number"),
]

STAGE_TITLES = {
    "completeness": "Completeness",
    "format": "Format checks",
    "consistency": "Cross-field consistency",
    "risk": "Risk & duplicates",
}
ICONS = {"pass": "✅", "fixable": "🟡", "review": "🟠", "blocker": "🔴"}
# Every value final_status can hold (see db.save_run, db.supersede_open_runs and db.record_review).
# SUPERSEDED runs were replaced by the same vendor's newer attempt, so they're hidden by default.
CURRENT_STATUSES = ["APPROVED", "PENDING", "AWAITING REVIEW", "REJECTED"]
FINAL_STATUSES = CURRENT_STATUSES + ["SUPERSEDED"]


# ---------- Loading a submission into the form ----------

def text_or_blank(value):
    # Text boxes show "" for an empty field; JSON uses null for the same thing.
    if value is None:
        return ""
    return str(value)


def state_key(state):
    # The dropdown uses STATE_CODES keys; an unknown name is kept as-is so its check can still be demoed.
    if is_blank(state):
        return None
    key = normalise_state(state)
    if key in STATE_CODES:
        return key
    return state


def fill_form(submission):
    # Widgets read their value from st.session_state[key], so filling the form = setting those keys.
    for section, name in TEXT_FIELDS:
        st.session_state["f_" + name] = text_or_blank(get_field(submission, section, name))
    st.session_state["f_entity_type"] = submission.get("entity_type")
    country = get_country(submission)
    if country == "":
        country = None
    st.session_state["f_country"] = country
    st.session_state["f_state_in"] = state_key(submission.get("state"))
    st.session_state["f_state_us"] = text_or_blank(submission.get("state"))
    documents = submission.get("documents")
    if documents is None:
        documents = []
    st.session_state["f_documents"] = list(documents)


def load_sample(path):
    # Runs as a button callback, i.e. BEFORE the form is drawn; Streamlit forbids changing a drawn widget.
    with open(path, encoding="utf-8") as f:
        submission = json.load(f)
    fill_form(submission)
    st.session_state["loaded_sample"] = os.path.basename(path)


# ---------- Drawing the form ----------

def options_with_current(options, key):
    # A sample may hold a value the dropdown doesn't list (e.g. country "SG"); keep it so its edge case still runs.
    current = st.session_state.get(key)
    if current is None or current in options:
        return options
    return options + [current]


def state_label(value):
    # STATE_CODES keys are lowercase for matching; show them as "Tamil Nadu", not "tamil nadu".
    if value not in STATE_CODES:
        return value
    words = []
    for word in value.split():
        if word == "and":
            words.append(word)
        else:
            words.append(word.capitalize())
    return " ".join(words)


def draw_sample_buttons():
    # One click loads a test case, so the demo never depends on typing a long form live.
    st.caption("Load a sample submission")
    paths = sorted(glob.glob(db.SAMPLES_PATTERN))
    columns = st.columns(len(paths))
    for i in range(len(paths)):
        label = os.path.basename(paths[i]).replace(".json", "")
        with columns[i]:
            st.button(label, key="sample_" + label, on_click=load_sample, args=(paths[i],))
    st.caption(f"Loaded: {st.session_state['loaded_sample']} (edit any field below)")


def draw_business_fields():
    # Who the vendor is and where they are registered.
    st.text_input("Legal business name", key="f_legal_name")
    left, right = st.columns(2)
    with left:
        st.selectbox("Business type", options_with_current(ENTITY_TYPES, "f_entity_type"), key="f_entity_type")
    with right:
        st.selectbox("Country", options_with_current(COUNTRIES, "f_country"), key="f_country")
    if st.session_state["f_country"] == "IN":
        # A fixed list, because the GSTIN state check needs a name it can look up.
        st.selectbox("State", options_with_current(list(STATE_CODES.keys()), "f_state_in"),
                     key="f_state_in", format_func=state_label)
    else:
        st.text_input("State", key="f_state_us")
    st.text_input("Registered address", key="f_address")
    left, right = st.columns(2)
    with left:
        st.text_input("Contact email", key="f_contact_email")
    with right:
        st.text_input("Website (optional)", key="f_website")


def draw_tax_and_bank_fields():
    # India and the US use different tax and bank IDs, so only the vendor's own country's fields appear.
    country = st.session_state["f_country"]
    left, right = st.columns(2)
    with left:
        st.text_input("Bank account holder name", key="f_account_holder")
        st.text_input("Bank account number", key="f_account_number")  # shown in full only here
    with right:
        if country == "IN":
            st.text_input("PAN", key="f_pan")
            st.text_input("GSTIN", key="f_gstin")
            st.text_input("IFSC", key="f_ifsc")
        elif country == "US":
            st.text_input("EIN", key="f_ein")
            st.text_input("Bank routing number", key="f_routing_number")
        else:
            st.caption("We only onboard vendors from India and the US.")


def document_label(name):
    # Show "GST certificate", not "gst_certificate"; an unknown name is shown as it is.
    if name in ALL_DOCUMENTS:
        return ALL_DOCUMENTS[name]
    return name


def draw_documents_field():
    # Documents are ticked, not uploaded: the vendor says which papers they are attaching.
    options = list(ALL_DOCUMENTS.keys())
    for name in st.session_state.get("f_documents", []):
        if name not in options:
            options.append(name)  # an unknown name from a sample stays visible instead of erroring
    st.multiselect("Documents attached", options, key="f_documents", format_func=document_label)


# ---------- Turning the form back into a submission ----------

def form_value(name):
    # An empty text box means the vendor left it out, which the schema writes as null.
    value = st.session_state.get("f_" + name)
    if is_blank(value):
        return None
    return value


def value_for_country(name, country, wanted):
    # A US vendor has no PAN and an Indian vendor no EIN, so the other country's IDs are left empty.
    if country != wanted:
        return None
    return form_value(name)


def form_state(country):
    # Indian states come from the dropdown, US states from a text box.
    if country == "IN":
        value = st.session_state.get("f_state_in")
        if value is None:
            return None
        return state_label(value)
    return form_value("state_us")


def build_submission():
    # Rebuild exactly the schema in CLAUDE.md, so the pipeline sees the same shape as the sample JSONs.
    country = st.session_state["f_country"]
    return {
        "legal_name": form_value("legal_name"),
        "entity_type": st.session_state["f_entity_type"],
        "country": country,
        "state": form_state(country),
        "address": form_value("address"),
        "contact_email": form_value("contact_email"),
        "website": form_value("website"),
        "tax": {"pan": value_for_country("pan", country, "IN"),
                "gstin": value_for_country("gstin", country, "IN"),
                "ein": value_for_country("ein", country, "US")},
        "bank": {"account_holder": form_value("account_holder"),
                 "account_number": form_value("account_number"),
                 "ifsc": value_for_country("ifsc", country, "IN"),
                 "routing_number": value_for_country("routing_number", country, "US")},
        "documents": list(st.session_state["f_documents"]),
    }


# ---------- Live run and verdict ----------

def count_label(findings):
    # The stage header says what needs attention, so a reviewer can scan without expanding.
    counts = count_severities(findings)
    parts = []
    for severity in ["fixable", "review", "blocker"]:
        if counts[severity] > 0:
            parts.append(f"{counts[severity]} {severity}")
    if len(parts) == 0:
        return "all passed"
    return ", ".join(parts)


def show_stage(number, event):
    # One status box per stage, filled with its findings, so viewers watch the checks happen.
    label = f"Stage {number} — {STAGE_TITLES[event['stage']]}"
    with st.status(label, expanded=True) as box:
        for finding in event["findings"]:
            st.write(f"{ICONS[finding['severity']]} {finding['message']}")
        if len(event["findings"]) == 0:
            st.write("Nothing to check here for this vendor.")
    state = "complete"
    if count_severities(event["findings"])["blocker"] > 0:
        state = "error"  # a red header makes a recommended rejection impossible to miss
    box.update(label=f"{label} · {count_label(event['findings'])}", state=state)


def run_live(submission):
    # run_pipeline hands back one stage at a time, so each box appears as soon as its stage finishes.
    findings = []
    decision = None
    number = 0
    for event in run_pipeline(submission):
        if event["stage"] == "decision":
            decision = event["result"]
        else:
            number = number + 1
            show_stage(number, event)
            findings = findings + event["findings"]
            time.sleep(0.4)  # the checks take milliseconds; the pause lets people see the progress
    return findings, decision


def show_numbered(items, empty_text):
    # One markdown block, so the list numbers 1, 2, 3 like the vendor email will.
    if len(items) == 0:
        st.caption(empty_text)
        return
    lines = []
    for i in range(len(items)):
        lines.append(f"{i + 1}. {items[i]}")
    st.markdown("\n".join(lines))


def show_status_banner(decision):
    # Green / amber / red, so the outcome is clear before anyone reads the details.
    status = decision["status"]
    if status == "APPROVED":
        st.success("**APPROVED** — every check passed. The vendor can be paid.")
    elif status == "PENDING":
        st.warning(f"**PENDING** — waiting for the vendor to fix {len(decision['fixes'])} item(s).")
    else:
        st.error(f"**NEEDS REVIEW** — recommendation: **{decision['recommendation']}**. "
                 "A person must approve or reject this vendor.")


def show_verdict(submission, decision):
    # Reasons are internal; fixes are what the vendor sees. Keeping them apart stops leaks to the vendor.
    st.subheader("Stage 5 — Decision")
    account = "not given"
    if not is_blank(submission["bank"]["account_number"]):
        account = mask_account(submission["bank"]["account_number"])  # never the full number outside the form
    st.write(f"**{submission['legal_name']}** · {submission['country']} · bank account {account}")
    show_status_banner(decision)
    st.markdown("**Internal reasons (reviewer only)**")
    show_numbered(decision["reasons"], "No issues found.")
    st.markdown("**What the vendor must fix**")
    show_numbered(decision["fixes"], "Nothing for the vendor to fix.")


def show_email(text, source):
    # The label tells a reviewer whether the AI or our fixed template wrote the wording.
    with st.container(border=True):
        if source == "ai":
            st.caption("Drafted by AI")
        else:
            st.caption("Template")
        st.text(text)  # plain text, so nothing in an AI reply is rendered as markdown or a link


def draft_and_show_email(submission, decision):
    # The AI call can take a few seconds, so a spinner shows the page hasn't frozen.
    st.subheader("Stage 6 — Vendor email")
    with st.spinner("Drafting the vendor email…"):
        text, source = emailer.draft_email(submission, decision)
    show_email(text, source)
    return text, source


# ---------- Dashboard: tiles and review queue ----------

def count_final_statuses(runs):
    # Tiles count the final answer, so a run a person approved counts as approved.
    counts = {}
    for status in FINAL_STATUSES:
        counts[status] = 0
    for run in runs:
        if run["final_status"] in counts:
            counts[run["final_status"]] = counts[run["final_status"]] + 1
    return counts


def show_metric_tiles(runs):
    # Five numbers answer "how is onboarding going?" before anyone scrolls.
    counts = count_final_statuses(runs)
    columns = st.columns(5)
    # Superseded runs are old attempts; counting them would count the same vendor twice.
    columns[0].metric("Total runs", len(runs) - counts["SUPERSEDED"])
    columns[1].metric("Approved", counts["APPROVED"])
    columns[2].metric("Pending", counts["PENDING"])
    columns[3].metric("Awaiting review", counts["AWAITING REVIEW"])
    columns[4].metric("Rejected", counts["REJECTED"])
    st.caption(f"Not counted above: {counts['SUPERSEDED']} superseded (replaced by a newer attempt)")


def recommendation_markdown(recommendation):
    # Red for a recommended rejection, orange (Streamlit's amber) for "please check".
    if recommendation == "Recommend reject":
        return ":red[**Recommend reject**]"
    if recommendation == "Check":
        return ":orange[**Check**]"
    return "none"


def submit_review(run_id, action, reviewer_name, note):
    # db.record_review enforces the rules (name + note required, decide once); the UI only reports them.
    try:
        db.record_review(run_id, action, reviewer_name, note)
    except ValueError as error:
        st.error(str(error))
        return
    run = db.get_run(run_id)
    new_status = run["final_status"]
    # The vendor hears the human decision: welcome, fixes, or a polite rejection.
    with st.spinner("Drafting the vendor email…"):
        text, source = emailer.draft_email(run["submission"], run["decision"], new_status)
    db.update_email(run_id, text, source)
    verb = "approved"
    if action == "reject":
        verb = "rejected"
    st.session_state["review_message"] = (f"Run #{run_id} {verb} by {reviewer_name.strip()}. "
                                          f"Final status: {new_status}")
    st.rerun()  # redraw so the run leaves the queue and the tiles update


def show_review_form(run):
    # A form sends name, note and button together, so typing doesn't rerun the page on each keystroke.
    run_id = run["id"]
    with st.form(key=f"review_form_{run_id}"):
        name = st.text_input("Reviewer name", key=f"reviewer_{run_id}")
        note = st.text_area("Note (why you decided this)", key=f"note_{run_id}")
        left, right = st.columns(2)
        with left:
            approve = st.form_submit_button("Approve", key=f"approve_{run_id}")
        with right:
            reject = st.form_submit_button("Reject", key=f"reject_{run_id}")
    if approve:
        submit_review(run_id, "approve", name, note)
    if reject:
        submit_review(run_id, "reject", name, note)


def attempt_summary(run):
    # One short phrase per earlier attempt, so a reviewer sees how this vendor got here.
    label = f"run #{run['id']}"
    if run["final_status"] == "SUPERSEDED":
        if run["reviewed_at"] is not None:
            # Only an approval that still left fixes (final PENDING) can be superseded after review.
            return f"{label} approved by {run['reviewer_name']} (fixes pending) → superseded"
        if run["status"] == "NEEDS_REVIEW":
            return f"{label} awaiting review → superseded"
        return f"{label} pending → superseded"
    if run["reviewed_at"] is not None:
        note = run["reviewer_note"].replace("\n", " ")  # keep the history on one line
        return f"{label} {run['final_status']} by {run['reviewer_name']} — {note}"
    return f"{label} {run['final_status']}"


def show_attempt_history(run):
    # A vendor resubmitting after a rejection is exactly what a reviewer needs to know.
    earlier = db.earlier_attempts(run["vendor_key"], run["id"])
    if len(earlier) == 0:
        return
    parts = []
    for old_run in earlier:
        parts.append(attempt_summary(old_run))
    st.caption("Previous: " + " · ".join(parts))


def show_review_queue(runs):
    # Flagged runs are stuck until a person decides, so they get their own list near the top.
    st.subheader("Review queue")
    waiting = []
    for run in runs:  # list_runs is already newest first
        if run["final_status"] == "AWAITING REVIEW":
            waiting.append(run)
    if len(waiting) == 0:
        st.info("Nothing waiting for review")
        return
    for run in waiting:
        with st.expander(f"Run #{run['id']} · {run['vendor_name']} · {run['country']} · Attempt {run['attempt']}"):
            show_attempt_history(run)
            st.markdown("Recommendation: " + recommendation_markdown(run["recommendation"]))
            decision = json.loads(run["decision_json"])
            st.markdown("**Internal reasons (reviewer only)**")
            show_numbered(decision["reasons"], "No reasons recorded.")
            show_review_form(run)


# ---------- Dashboard: all runs and run details ----------

def filter_runs(runs, statuses, search):
    # Both filters must match; an empty search box matches every vendor.
    search = search.strip().lower()
    kept = []
    for run in runs:
        name = text_or_blank(run["vendor_name"]).lower()
        if run["final_status"] in statuses and search in name:
            kept.append(run)
    return kept


def run_row(run):
    # Only the columns a buyer scans; the full detail is in "Run details" below.
    return {"id": run["id"], "time": run["created_at"], "vendor": run["vendor_name"],
            "country": run["country"], "attempt": run["attempt"], "system status": run["status"],
            "recommendation": run["recommendation"], "final status": run["final_status"],
            "reviewer": run["reviewer_name"]}


def show_all_runs(runs):
    # One table of every run, narrowed by final status or vendor name.
    st.subheader("All runs")
    left, right = st.columns(2)
    with left:
        statuses = st.multiselect("Final status", FINAL_STATUSES, default=CURRENT_STATUSES, key="filter_status")
    with right:
        search = st.text_input("Search vendor name", key="filter_search")
    rows = []
    for run in filter_runs(runs, statuses, search):
        rows.append(run_row(run))
    if len(rows) == 0:
        st.caption("No runs match these filters.")
        return
    st.dataframe(rows, hide_index=True)


def masked_submission(submission):
    # Copy first, so masking for display never changes the saved record.
    shown = dict(submission)
    bank = submission.get("bank")
    if isinstance(bank, dict) and not is_blank(bank.get("account_number")):
        bank = dict(bank)
        bank["account_number"] = mask_account(bank["account_number"])
        shown["bank"] = bank
    return shown


def show_findings_by_stage(findings):
    # Same stage names and icons as the live view, so the audit trail reads like the run did.
    number = 0
    for stage in STAGE_TITLES:
        number = number + 1
        stage_findings = []
        for finding in findings:
            if finding["stage"] == stage:
                stage_findings.append(finding)
        st.markdown(f"**Stage {number} — {STAGE_TITLES[stage]}** · {count_label(stage_findings)}")
        for finding in stage_findings:
            st.write(f"{ICONS[finding['severity']]} {finding['message']}")
        if len(stage_findings) == 0:
            st.caption("Nothing to check here for this vendor.")


def show_decision_block(run):
    # The system's verdict, kept apart from the human's, so both are visible in the audit trail.
    decision = run["decision"]
    st.markdown(f"**Stage 5 — Decision:** {run['status']} · recommendation "
                f"{recommendation_markdown(run['recommendation'])}")
    st.markdown("Internal reasons (reviewer only)")
    show_numbered(decision["reasons"], "No issues found.")
    st.markdown("What the vendor must fix")
    show_numbered(decision["fixes"], "Nothing for the vendor to fix.")


def show_email_and_review(run):
    # What we told the vendor, in order, and who made the final call and why.
    st.markdown("**Stage 6 — Vendor email**")
    st.markdown("At submission")
    if is_blank(run["email_text"]):
        st.caption("No email yet")
    else:
        show_email(run["email_text"], run["email_source"])
    if not is_blank(run["decision_email_text"]):
        st.markdown("After review")
        show_email(run["decision_email_text"], run["decision_email_source"])
    if run["reviewed_at"] is not None:
        st.markdown("**Human review**")
        st.write(f"Reviewer: {run['reviewer_name']}")
        st.write(f"Note: {run['reviewer_note']}")
        st.write(f"Reviewed at: {run['reviewed_at']}")


def show_run_details(runs):
    # Everything saved about one run, so anyone can see why it ended where it did.
    st.subheader("Run details")
    if len(runs) == 0:
        st.caption("No runs yet.")
        return
    ids = []
    for run in runs:
        ids.append(run["id"])
    run = db.get_run(st.selectbox("Pick a run id", ids, key="detail_run_id"))
    st.markdown(f"**{run['vendor_name']}** · {run['country']} · attempt {run['attempt']} · "
                f"final status **{run['final_status']}**")
    if run["superseded_by"] is not None:
        st.caption(f"Superseded by run #{run['superseded_by']} (a newer attempt from the same vendor)")
    st.markdown("**Submission** (account number masked)")
    st.json(masked_submission(run["submission"]), expanded=False)
    st.markdown("**Stage-by-stage findings**")
    show_findings_by_stage(run["findings"])
    show_decision_block(run)
    show_email_and_review(run)


# ---------- Pages ----------

def new_run_page():
    # Top to bottom: pick a sample, edit it, run it, read the verdict.
    st.title("New vendor run")
    draw_sample_buttons()
    draw_business_fields()
    draw_tax_and_bank_fields()
    draw_documents_field()
    if st.button("Run checks", type="primary", key="run_checks"):
        submission = build_submission()
        st.divider()
        findings, decision = run_live(submission)
        show_verdict(submission, decision)
        email_text, email_source = draft_and_show_email(submission, decision)
        run_id = db.save_run(submission, findings, decision, email_text, email_source)
        st.info(f"Saved as run #{run_id} · attempt {db.get_run(run_id)['attempt']}")


def dashboard_page():
    # Every run in one place: the audit trail the brief says is missing today.
    st.title("Dashboard")
    if "review_message" in st.session_state:
        st.success(st.session_state.pop("review_message"))  # saved before st.rerun(), shown once
    runs = db.list_runs()
    show_metric_tiles(runs)
    st.divider()
    show_review_queue(runs)
    st.divider()
    show_all_runs(runs)
    st.divider()
    show_run_details(runs)


st.set_page_config(page_title="VendorGate", page_icon="🛂")
# Streamlit reruns this whole file on every click; both calls are safe to repeat.
db.init_db()
db.seed_demo_runs()
if "loaded_sample" not in st.session_state:
    load_sample(FIRST_SAMPLE)  # first open: start from the happy path instead of an empty form
page = st.sidebar.radio("Page", ["New run", "Dashboard"])
if page == "New run":
    new_run_page()
else:
    dashboard_page()
