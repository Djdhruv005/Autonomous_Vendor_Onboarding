"""VendorGate UI: a New run page that checks one vendor live, and (in P9) a dashboard of all runs."""

import glob
import json
import os
import time

import streamlit as st

import db
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
    st.subheader("Stage 6 — Vendor email")
    st.info("Email drafting comes in the next step.")


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
        run_id = db.save_run(submission, findings, decision)
        st.info(f"Saved as run #{run_id}")


def dashboard_page():
    # Placeholder until P9; the count shows the database and demo seeding already work.
    st.title("Dashboard")
    st.info(f"The dashboard of all runs comes in P9. Runs saved so far: {len(db.list_runs())}")


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
