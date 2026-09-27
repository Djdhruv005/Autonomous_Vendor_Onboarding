"""VendorGate UI: a New run page that checks one vendor live, and a dashboard of all runs."""

import glob
import json
import os
import time
from datetime import datetime

import streamlit as st

import db
import emailer
from checks import (ENTITY_TYPES, STATE_CODES, INDIA_DOCUMENTS, US_DOCUMENTS, get_country, get_field,
                    is_blank, mask_account, normalise_state)
from decision import count_severities
from pipeline import run_pipeline

TAGLINE = "Vendor onboarding checks — the rules decide, a person approves."
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
# What each stage checks, in the words a buyer would use (matches run_* in checks.py).
STAGE_QUESTIONS = {
    "completeness": "Is anything missing? Required fields, a supported country, the right documents.",
    "format": "Are the tax IDs and bank details written in a valid format?",
    "consistency": "Do the IDs agree with each other, and does the bank account name match the business?",
    "risk": "Is this bank account or tax ID already used by another vendor we pay?",
}
# One colour meaning everywhere: green = approved/pass, amber = pending/fixable,
# orange = needs review, red = blocker/recommend reject/rejected.
ICONS = {"pass": "✅", "fixable": "🟡", "review": "🟠", "blocker": "🔴"}
# Scenario names for the sample buttons; a file not listed here keeps its file name.
SAMPLE_NAMES = {
    "01_happy.json": "✅ Clean vendor",
    "02_name_variant.json": "✏️ Name variant",
    "03_pan_gstin_conflict.json": "🔀 PAN/GSTIN conflict",
    "04_duplicate_bank.json": "🏦 Duplicate bank",
    "05_us_vendor.json": "🇺🇸 US vendor",
}
# Every value final_status can hold (see db.save_run, db.supersede_open_runs and db.record_review).
# SUPERSEDED runs were replaced by the same vendor's newer attempt, so they're hidden by default.
CURRENT_STATUSES = ["APPROVED", "PENDING", "AWAITING REVIEW", "REJECTED"]
FINAL_STATUSES = CURRENT_STATUSES + ["SUPERSEDED"]
STATUS_EMOJI = {"APPROVED": "✅", "PENDING": "⏳", "AWAITING REVIEW": "🟠", "REJECTED": "❌", "SUPERSEDED": "🔁"}
NO_RUNS_YET = "No runs yet — try a sample on the New run page."


# ---------- Loading a submission into the form ----------

def text_or_blank(value):
    # Text boxes show "" for an empty field; JSON uses null for the same thing.
    if value is None:
        return ""
    return str(value)


def display_name(name):
    # A run saved without a business name still needs something readable, not "None".
    if is_blank(name):
        return "(no name)"
    return str(name)


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


def keep_form_values():
    # Streamlit forgets a widget's value on any run where it isn't drawn (the PAN box while Country
    # is US, or the whole form on the Dashboard). Re-saving each key keeps it: Streamlit's documented fix.
    keys = ["f_entity_type", "f_country", "f_state_in", "f_state_us", "f_documents"]
    for section, name in TEXT_FIELDS:
        keys.append("f_" + name)
    for key in keys:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


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


def sample_name(file_name):
    # A viewer understands "Duplicate bank" faster than "04_duplicate_bank.json".
    if file_name in SAMPLE_NAMES:
        return SAMPLE_NAMES[file_name]
    return file_name.replace(".json", "")


def draw_sample_buttons():
    # One click loads a test case, so the demo never depends on typing a long form live.
    st.caption("Load a sample submission")
    paths = sorted(glob.glob(db.SAMPLES_PATTERN))
    columns = st.columns(3)  # 3 per row: the form column is too narrow for 5 side by side
    for i in range(len(paths)):
        file_name = os.path.basename(paths[i])
        with columns[i % 3]:
            st.button(sample_name(file_name), key="sample_" + file_name.replace(".json", ""),
                      on_click=load_sample, args=(paths[i],), width="stretch")
    st.caption(f"Loaded: {sample_name(st.session_state['loaded_sample'])} (edit any field below)")


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
            # Tooltips, because a US interviewer won't know Indian tax and bank codes (and vice versa).
            st.text_input("PAN", key="f_pan", help="Permanent Account Number: India's 10-character "
                          "income-tax ID for a person or business, e.g. AABCS1234F.")
            st.text_input("GSTIN", key="f_gstin", help="India's 15-character GST (sales tax) registration. "
                          "It starts with a 2-digit state code, followed by the business's PAN.")
            st.text_input("IFSC", key="f_ifsc", help="11-character code for an Indian bank branch, "
                          "e.g. HDFC0001234. India's version of a US routing number.")
        elif country == "US":
            st.text_input("EIN", key="f_ein", help="Employer Identification Number: the US federal tax ID "
                          "for a business. 9 digits, written 12-3456789.")
            st.text_input("Bank routing number", key="f_routing_number", help="9-digit ABA number that "
                          "identifies a US bank. Printed at the bottom-left of a cheque.")
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

def issue_phrase(severity, n):
    # Plain words instead of severity codes, so a buyer reads "1 needs review", not "1 review".
    if severity == "fixable":
        return f"{n} to fix"
    if severity == "review":
        if n == 1:
            return "1 needs review"
        return f"{n} need review"
    if n == 1:
        return "1 blocker"
    return f"{n} blockers"


def count_label(findings):
    # The stage header says what needs attention, so a reviewer can scan without expanding.
    counts = count_severities(findings)
    parts = []
    for severity in ["fixable", "review", "blocker"]:
        if counts[severity] > 0:
            parts.append(issue_phrase(severity, counts[severity]))
    if len(parts) == 0:
        return "all passed"
    return ", ".join(parts)


def stage_colour(findings):
    # The worst finding sets the colour, so a stage is only green when everything in it passed.
    counts = count_severities(findings)
    if counts["blocker"] > 0:
        return "red"
    if counts["review"] > 0:
        return "orange"
    if counts["fixable"] > 0:
        return "yellow"
    return "green"


def stage_label(number, stage, findings):
    # Shared by the live view and the dashboard, so a stage looks the same on both pages.
    return f":{stage_colour(findings)}[Stage {number} — {STAGE_TITLES[stage]} · {count_label(findings)}]"


def show_stage(number, event):
    # One status box per stage, filled with its findings, so viewers watch the checks happen.
    with st.status(f"Stage {number} — {STAGE_TITLES[event['stage']]}", expanded=True) as box:
        st.caption(STAGE_QUESTIONS[event["stage"]])
        for finding in event["findings"]:
            st.write(f"{ICONS[finding['severity']]} {finding['message']}")
        if len(event["findings"]) == 0:
            st.write("Nothing to check here for this vendor.")
    colour = stage_colour(event["findings"])
    state = "complete"  # tick = "this stage finished"; the label colour says how it went
    if colour == "red":
        state = "error"  # a red ✖ makes a recommended rejection impossible to miss
    # Clean stages fold away so the eye goes straight to the ones with problems.
    box.update(label=stage_label(number, event["stage"], event["findings"]), state=state,
               expanded=colour != "green")


def run_live(submission):
    # run_pipeline hands back one stage at a time, so each box appears as soon as its stage finishes.
    total = len(STAGE_TITLES)
    bar = st.progress(0, text=f"Stage 0 of {total}")
    findings = []
    decision = None
    number = 0
    for event in run_pipeline(submission):
        if event["stage"] == "decision":
            decision = event["result"]
        else:
            number = number + 1
            show_stage(number, event)
            bar.progress(number / total, text=f"Stage {number} of {total}")
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


def verdict_colour(decision):
    # One colour meaning across the app: green approved, amber pending, orange check, red recommend reject.
    if decision["status"] == "APPROVED":
        return "green"
    if decision["status"] == "PENDING":
        return "yellow"
    if decision["recommendation"] == "Recommend reject":
        return "red"
    return "orange"


def verdict_sentence(decision):
    # One plain sentence saying what happens next, for a buyer who reads nothing else.
    if decision["status"] == "APPROVED":
        return "Every check passed. The vendor can be paid."
    if decision["status"] == "PENDING":
        return f"Waiting for the vendor to fix {len(decision['fixes'])} item(s)."
    return "A person must approve or reject this vendor."


def show_next_step_badge(decision):
    # The badge says what to do next, so the reviewer doesn't have to read the reasons first.
    if decision["recommendation"] == "Recommend reject":
        st.badge("Recommend reject", icon="🛑", color="red")
    elif decision["recommendation"] == "Check":
        st.badge("Check", icon="🔍", color="orange")
    elif decision["status"] == "PENDING":
        st.badge("Waiting on vendor", icon="⏳", color="yellow")
    else:
        st.badge("No action needed", icon="✅", color="green")


def show_verdict_card(submission, decision, run):
    # Stage 5: the outcome in one glance — big coloured word, next step, and which vendor/run it is.
    account = "not given"
    if not is_blank(submission["bank"]["account_number"]):
        account = mask_account(submission["bank"]["account_number"])  # never the full number outside the form
    with st.container(border=True):
        word = decision["status"].replace("_", " ")
        st.header(f":{verdict_colour(decision)}[{word}]", anchor=False)
        show_next_step_badge(decision)
        st.write(verdict_sentence(decision))
        st.caption(f"{display_name(submission['legal_name'])} · {submission['country']} · bank {account} · "
                   f"run #{run['id']} · attempt {run['attempt']}")


def show_reasons_and_fixes(decision):
    # Reasons are internal; fixes are what the vendor sees. Side by side, so the split is obvious.
    left, right = st.columns(2)
    with left:
        st.markdown("**Internal reasons (reviewer only)**")
        show_numbered(decision["reasons"], "No issues found.")
    with right:
        st.markdown("**What the vendor must fix**")
        show_numbered(decision["fixes"], "Nothing for the vendor to fix.")


def show_email(text, source):
    # The label tells a reviewer whether the AI or our fixed template wrote the wording.
    with st.container(border=True):
        if source == "ai":
            st.badge("Drafted by AI", icon="✨", color="violet")
        else:
            st.badge("Template", icon="📄", color="gray")
        st.text(text)  # plain text, so nothing in an AI reply is rendered as markdown or a link


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


def run_keys(run):
    # The two ways runs are linked to one vendor (see db.SAME_VENDOR); either can be missing.
    keys = []
    for key in [run["vendor_key"], run["name_key"]]:
        if key is not None:
            keys.append(key)
    return keys


def latest_runs(runs):
    # A vendor who submitted 3 times is still one vendor, so the tiles count only their newest run.
    latest = []
    seen = []
    for run in runs:  # list_runs is newest first, so the first run we meet for a vendor is its latest
        is_newest = True
        for key in run_keys(run):
            if key in seen:
                is_newest = False
        if is_newest:
            latest.append(run)
        seen = seen + run_keys(run)
    return latest


def show_metric_tiles(runs):
    # Five numbers answer "how is onboarding going?" before anyone scrolls.
    latest = latest_runs(runs)
    counts = count_final_statuses(latest)
    columns = st.columns(5)
    columns[0].metric("Vendors", len(latest), border=True,
                      help="Each vendor counted once, by their latest attempt. Older attempts aren't counted.")
    columns[1].metric("✅ Approved", counts["APPROVED"], border=True,
                      help="Passed every check, or a reviewer approved it with nothing left to fix. Ready to pay.")
    columns[2].metric("⏳ Pending", counts["PENDING"], border=True,
                      help="Waiting for the vendor to correct the items we emailed them.")
    columns[3].metric("🟠 Awaiting review", counts["AWAITING REVIEW"], border=True,
                      help="Flagged by the rules. A person must approve or reject it.")
    columns[4].metric("❌ Rejected", counts["REJECTED"], border=True,
                      help="Rejected by a reviewer. Only a person can reject a vendor.")
    st.caption(f"Not counted above: {len(runs) - len(latest)} older attempts from the same vendors")


def recommendation_markdown(recommendation):
    # Red for a recommended rejection, orange (Streamlit's amber) for "please check".
    if recommendation == "Recommend reject":
        return ":red[**Recommend reject**]"
    if recommendation == "Check":
        return ":orange[**Check**]"
    return "none"


def final_status_markdown(run):
    # The final status in the same colours as the live verdict, so both pages speak one language.
    status = run["final_status"]
    colour = "gray"  # SUPERSEDED: an old attempt, no longer the answer
    if status == "APPROVED":
        colour = "green"
    elif status == "PENDING":
        colour = "yellow"
    elif status == "REJECTED":
        colour = "red"
    elif status == "AWAITING REVIEW":
        colour = "orange"
        if run["recommendation"] == "Recommend reject":
            colour = "red"  # same as its verdict card and queue badge
    return f":{colour}[**{STATUS_EMOJI.get(status, '')} {status}**]"


def recommendation_badge(recommendation):
    # A coloured badge in the queue title, so the reviewer sees the risk before opening the item.
    if recommendation == "Recommend reject":
        return ":red-badge[🛑 Recommend reject]"
    if recommendation == "Check":
        return ":orange-badge[🔍 Check]"
    return ""


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
    st.session_state["review_status"] = new_status  # picks the message colour after the rerun
    st.rerun()  # redraw so the run leaves the queue and the tiles update


def show_review_message():
    # Shown once after st.rerun(), in the outcome's colour: green approved, amber pending, red rejected.
    message = st.session_state.pop("review_message")
    status = st.session_state.pop("review_status", "")
    if status == "APPROVED":
        st.success(message)
    elif status == "PENDING":
        st.warning(message)
    else:
        st.error(message)


def show_review_form(run):
    # A form sends name, note and button together, so typing doesn't rerun the page on each keystroke.
    run_id = run["id"]
    with st.form(key=f"review_form_{run_id}"):
        name = st.text_input("Reviewer name", key=f"reviewer_{run_id}")
        note = st.text_area("Note (why you decided this)", key=f"note_{run_id}")
        left, right = st.columns(2)
        with left:
            approve = st.form_submit_button("Approve", key=f"approve_{run_id}", type="primary")
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
    earlier = db.earlier_attempts(run)
    if len(earlier) == 0:
        return
    parts = []
    for old_run in earlier:
        parts.append(attempt_summary(old_run))
    st.caption("Previous: " + " · ".join(parts))


def show_review_queue(runs):
    # Flagged runs are stuck until a person decides, so they get their own list near the top.
    waiting = []
    for run in runs:  # list_runs is already newest first
        if run["final_status"] == "AWAITING REVIEW":
            waiting.append(run)
    st.subheader(f"Review queue · {len(waiting)} waiting")
    if len(waiting) == 0:
        st.info("Nothing waiting for review — you're all caught up.")
        return
    for run in waiting:
        title = (f"{recommendation_badge(run['recommendation'])} Run #{run['id']} · "
                 f"{display_name(run['vendor_name'])} · {run['country']} · Attempt {run['attempt']}")
        with st.expander(title):
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


def short_time(iso_text):
    # "27 Sep, 17:32" reads faster than "2026-09-27T17:32:05"; the full value stays in the database.
    if is_blank(iso_text):
        return ""
    moment = datetime.fromisoformat(iso_text)
    return f"{moment.day} {moment.strftime('%b, %H:%M')}"


def run_row(run):
    # Only the columns a buyer scans; the system status and raw fields are in "Run details" below.
    return {"Run": run["id"], "Time": short_time(run["created_at"]), "Vendor": display_name(run["vendor_name"]),
            "Country": run["country"],
            "Status": f"{STATUS_EMOJI.get(run['final_status'], '')} {run['final_status']}",
            "Recommendation": text_or_blank(run["recommendation"]), "Attempt": run["attempt"],
            "Reviewer": text_or_blank(run["reviewer_name"])}


def show_all_runs(runs):
    # One table of every run, narrowed by final status or vendor name.
    st.subheader("All runs")
    if len(runs) == 0:
        st.info(NO_RUNS_YET)
        return
    left, right = st.columns(2)
    with left:
        statuses = st.multiselect("Final status", FINAL_STATUSES, default=CURRENT_STATUSES, key="filter_status")
    with right:
        search = st.text_input("Search vendor name", key="filter_search")
    rows = []
    for run in filter_runs(runs, statuses, search):
        rows.append(run_row(run))
    if len(rows) == 0:
        st.info("No runs match these filters — try clearing the search or adding a status.")
        return
    st.dataframe(rows, hide_index=True)  # newest first, because list_runs sorts by id descending


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
        st.markdown(f"**{stage_label(number, stage, stage_findings)}**")
        st.caption(STAGE_QUESTIONS[stage])
        for finding in stage_findings:
            st.write(f"{ICONS[finding['severity']]} {finding['message']}")
        if len(stage_findings) == 0:
            st.caption("Nothing to check here for this vendor.")


def show_decision_block(run):
    # The system's verdict, kept apart from the human's, so both are visible in the audit trail.
    decision = run["decision"]
    word = decision["status"].replace("_", " ")
    st.markdown(f"**Stage 5 — Decision:** :{verdict_colour(decision)}[**{word}**] · recommendation "
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
        st.write(f"Reviewed at: {short_time(run['reviewed_at'])}")


def show_run_details(runs):
    # Everything saved about one run, so anyone can see why it ended where it did.
    st.subheader("Run details")
    if len(runs) == 0:
        st.info(NO_RUNS_YET)
        return
    ids = []
    for run in runs:
        ids.append(run["id"])
    run = db.get_run(st.selectbox("Pick a run id", ids, key="detail_run_id"))
    st.markdown(f"**{display_name(run['vendor_name'])}** · {run['country']} · attempt {run['attempt']} · "
                f"final status {final_status_markdown(run)}")
    if run["superseded_by"] is not None:
        st.caption(f"Superseded by run #{run['superseded_by']} (a newer attempt from the same vendor)")
    st.markdown("**Submission** (account number masked)")
    st.json(masked_submission(run["submission"]), expanded=False)
    st.markdown("**Stage-by-stage findings**")
    show_findings_by_stage(run["findings"])
    show_decision_block(run)
    show_email_and_review(run)


# ---------- Pages ----------

def show_header(page_title):
    # Same header on every page, so a first-time viewer always knows what the tool is for.
    st.title("🛡️ VendorGate")
    st.caption(TAGLINE)
    st.subheader(page_title)


def show_saved_run(run):
    # Same submission as the last run, so show that result again instead of saving a copy.
    st.info(f"Nothing changed since run #{run['id']}, so it wasn't checked or saved again. "
            "Edit a field to start a new run.")
    show_verdict_card(run["submission"], run["decision"], run)
    show_reasons_and_fixes(run["decision"])
    st.markdown("**Stage 6 — Vendor email**")
    show_email(run["email_text"], run["email_source"])


def run_and_save(submission):
    # A double click or a second press with nothing edited would save a duplicate run and redraft the email.
    last_run = db.get_run(st.session_state.get("last_run_id"))
    if last_run is not None and submission == st.session_state.get("last_submission"):
        show_saved_run(last_run)
        return
    # The result box is placed first but filled last, so the verdict sits ABOVE the stage details.
    result_box = st.container()
    st.markdown("**Stage by stage**")
    findings, decision = run_live(submission)
    with result_box:
        with st.spinner("Drafting the vendor email…"):  # the AI call can take a few seconds
            email_text, email_source = emailer.draft_email(submission, decision)
        run_id = db.save_run(submission, findings, decision, email_text, email_source)
        st.session_state["last_submission"] = submission  # right after saving, so a quick 2nd click sees it
        st.session_state["last_run_id"] = run_id
        show_verdict_card(submission, decision, db.get_run(run_id))
        show_reasons_and_fixes(decision)
        st.markdown("**Stage 6 — Vendor email**")
        show_email(email_text, email_source)


def new_run_page():
    # Form on the left, result on the right, so the verdict is visible without scrolling.
    show_header("New vendor run")
    left, right = st.columns([5, 7], gap="large")
    with left:
        draw_sample_buttons()
        draw_business_fields()
        draw_tax_and_bank_fields()
        draw_documents_field()
        clicked = st.button("Run checks", type="primary", key="run_checks", width="stretch")
    with right:
        if clicked:
            run_and_save(build_submission())
        else:
            st.info("Load a sample or edit the form, then press **Run checks**. The result appears here.")


# The theme can't set a button hover colour/shadow or soft multiselect chips, so this small CSS does.
# Selectors are the data-testid / data-tag names Streamlit 1.64 puts in its HTML; if a later version
# renames them, these styles simply stop applying and the default theme look remains.
# Buttons use #7366CC, not the #7F72D6 accent: white on #7F72D6 is 3.98:1, below the 4.5:1 readability bar.
CSS = """<style>
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
    background: #7366CC; border-color: #7366CC; color: #FFFFFF; }
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {
    background: #6B5EC4; border-color: #6B5EC4; color: #FFFFFF; box-shadow: 0 2px 8px rgba(30, 41, 59, 0.18); }
[data-testid="stMultiSelect"] [data-tag] { background: #E5E1F8; color: #3F3585; }
[data-testid="stMultiSelect"] [data-tag] button { color: #3F3585; }
</style>"""


def draw_sidebar():
    # The sidebar names the product and states the one rule a viewer must not miss.
    st.sidebar.title("🛡️ VendorGate")
    page = st.sidebar.radio("Page", ["New run", "Dashboard"])
    st.sidebar.divider()
    st.sidebar.caption("Only a human can reject a vendor.")
    return page


def dashboard_page():
    # Every run in one place: the audit trail the brief says is missing today.
    show_header("Dashboard")
    if "review_message" in st.session_state:
        show_review_message()
    runs = db.list_runs()
    show_metric_tiles(runs)
    st.divider()
    show_review_queue(runs)
    st.divider()
    show_all_runs(runs)
    st.divider()
    show_run_details(runs)


st.set_page_config(page_title="VendorGate", page_icon="🛡️", layout="wide")  # wide: room for form + result
st.markdown(CSS, unsafe_allow_html=True)  # our own fixed text, never user input
# Streamlit reruns this whole file on every click; both calls are safe to repeat.
db.init_db()
db.seed_demo_runs()
if "loaded_sample" not in st.session_state:
    load_sample(FIRST_SAMPLE)  # first open: start from the happy path instead of an empty form
keep_form_values()  # every run, on both pages, before any form widget is drawn
page = draw_sidebar()
if page == "New run":
    new_run_page()
else:
    dashboard_page()
