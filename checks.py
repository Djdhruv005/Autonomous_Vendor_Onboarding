"""VendorGate checks. Every check takes the submission dict and returns a list of Finding dicts."""

import csv
import json
import os
import re
import sys

from rapidfuzz import fuzz

# Countries we know the tax and bank rules for, mapped to the name shown to the buyer.
SUPPORTED_COUNTRIES = {"IN": "India", "US": "the US"}

# Fields every vendor fills in, whatever the country: (section, key, label shown to the buyer).
# section is None for top-level fields, or "tax"/"bank" for fields one level down.
COMMON_FIELDS = [
    (None, "legal_name", "Legal business name"),
    (None, "entity_type", "Business type"),
    (None, "country", "Country"),
    (None, "state", "State"),
    (None, "address", "Registered address"),
    (None, "contact_email", "Contact email"),
    ("bank", "account_holder", "Bank account holder name"),
    ("bank", "account_number", "Bank account number"),
]

# Indian vendors need PAN + GSTIN and an IFSC to be paid.
INDIA_FIELDS = [
    ("tax", "pan", "PAN (Indian tax ID)"),
    ("tax", "gstin", "GSTIN (GST registration number)"),
    ("bank", "ifsc", "IFSC (bank branch code)"),
]

# US vendors need an EIN for tax reporting and a routing number to be paid.
US_FIELDS = [
    ("tax", "ein", "EIN (US tax ID)"),
    ("bank", "routing_number", "Bank routing number"),
]

# Documents the vendor must tick as attached: document name -> label shown to the buyer.
INDIA_DOCUMENTS = {
    "gst_certificate": "GST certificate",
    "pan_card": "PAN card",
    "cancelled_cheque": "cancelled cheque",
}
US_DOCUMENTS = {
    "w9_form": "W-9 form",
    "bank_letter": "bank letter",
}


# ---------- Helpers ----------

def make_finding(stage, check, severity, message, fix):
    # One place builds findings, so every check returns exactly the shape in CLAUDE.md.
    return {"stage": stage, "check": check, "severity": severity, "message": message, "fix": fix}


def normalise_text(text):
    # Vendors write the same name many ways; tidy it so comparisons only see real differences.
    if text is None:
        return ""
    text = str(text).strip().upper()
    if text.startswith("M/S"):
        text = text[3:]  # "M/s" means "Messrs", a courtesy prefix, not part of the name
    cleaned = ""
    for ch in text:
        if ch.isalnum():
            cleaned = cleaned + ch
        else:
            cleaned = cleaned + " "  # punctuation becomes a space, so "PVT.LTD." -> "PVT LTD"
    tidy_words = []
    for word in cleaned.split():  # split() also drops the extra spaces
        if word == "PVT":
            word = "PRIVATE"
        elif word == "LTD":
            word = "LIMITED"
        tidy_words.append(word)
    return " ".join(tidy_words)


def is_blank(value):
    # A field holding only spaces is as empty as a missing one.
    if value is None:
        return True
    return str(value).strip() == ""


def get_field(submission, section, key):
    # Tax and bank details sit one level down, e.g. submission["bank"]["ifsc"].
    if section is None:
        return submission.get(key)
    inner = submission.get(section)
    if inner is None:
        return None
    return inner.get(key)


def get_country(submission):
    # Accept "in" or " IN " the same as "IN".
    country = submission.get("country")
    if is_blank(country):
        return ""
    return str(country).strip().upper()


# ---------- Stage 1: Completeness ----------

def check_country(submission):
    # We only know the tax and bank rules for India and the US, so nobody else can be onboarded.
    country = get_country(submission)
    if country == "":
        return []  # check_required_fields already reports a missing country
    if country in SUPPORTED_COUNTRIES:
        name = SUPPORTED_COUNTRIES[country]
        return [make_finding("completeness", "supported_country", "pass",
                             f"The vendor is based in {name}, which we support.", None)]
    return [make_finding("completeness", "supported_country", "blocker",
                         "We currently onboard vendors from India and the US only.",
                         "If you have a registered business in India or the US, "
                         "apply again using that business's details.")]


def fields_for_country(country):
    # India and the US use different tax and bank IDs, so each country gets its own list.
    if country == "IN":
        return COMMON_FIELDS + INDIA_FIELDS
    if country == "US":
        return COMMON_FIELDS + US_FIELDS
    return COMMON_FIELDS


def check_required_fields(submission):
    # Rule 1: we can't check or pay a vendor whose basic details are missing.
    findings = []
    for section, key, label in fields_for_country(get_country(submission)):
        if is_blank(get_field(submission, section, key)):
            findings.append(make_finding("completeness", "required_fields", "fixable",
                                         f"{label} is missing.",
                                         f"Please fill in: {label}."))
    if len(findings) == 0:
        findings.append(make_finding("completeness", "required_fields", "pass",
                                     "All required details are filled in.", None))
    return findings


def documents_for_country(country):
    # Each country has its own standard onboarding papers.
    if country == "IN":
        return INDIA_DOCUMENTS
    if country == "US":
        return US_DOCUMENTS
    return {}


def check_documents(submission):
    # Rule 2: procurement needs these papers on file before the first payment.
    required = documents_for_country(get_country(submission))
    if len(required) == 0:
        return []  # missing or unsupported country: already reported, nothing sensible to ask for
    attached = submission.get("documents")
    if attached is None:
        attached = []
    findings = []
    for name, label in required.items():
        if name not in attached:
            findings.append(make_finding("completeness", "required_documents", "fixable",
                                         f"The {label} is not attached.",
                                         f"Please attach your {label}."))
    if len(findings) == 0:
        findings.append(make_finding("completeness", "required_documents", "pass",
                                     "All required documents are attached.", None))
    return findings


def run_completeness(submission):
    # Stage 1 is these three checks together; pipeline.py will call just this function.
    findings = []
    findings = findings + check_country(submission)
    findings = findings + check_required_fields(submission)
    findings = findings + check_documents(submission)
    return findings


# ---------- Stage 2: Format ----------

# Patterns are used with re.fullmatch, so the WHOLE value must match (no extra characters).
PAN_PATTERN = r"[A-Z]{5}[0-9]{4}[A-Z]"
# GSTIN = 2-digit state code + 10-char PAN + entity number (1-9 or A-Z) + "Z" + check character.
GSTIN_PATTERN = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]"
IFSC_PATTERN = r"[A-Z]{4}0[A-Z0-9]{6}"
EIN_PATTERN = r"[0-9]{2}-?[0-9]{7}"  # the hyphen is optional: 12-3456789 or 123456789


def clean_id(value):
    # Vendors often type IDs in lowercase or with spaces; neither changes the ID itself.
    return str(value).replace(" ", "").upper()


def check_id_format(submission, section, key, pattern, check_name, label, shape):
    # Shared by the simple pattern checks, so each one gives exactly one pass or fixable finding.
    value = get_field(submission, section, key)
    if is_blank(value):
        return []  # Stage 1 already reported it missing; don't report it twice
    if re.fullmatch(pattern, clean_id(value)):
        return [make_finding("format", check_name, "pass",
                             f"The {label} has the right format.", None)]
    return [make_finding("format", check_name, "fixable",
                         f"The {label} '{value}' doesn't have the right format. It should be {shape}.",
                         f"Please check and re-enter your {label}. It should be {shape}.")]


def check_pan(submission):
    # Rule 3: a mistyped PAN breaks tax reporting and the PAN-vs-GSTIN check in Stage 3.
    return check_id_format(submission, "tax", "pan", PAN_PATTERN, "pan_format", "PAN",
                           "10 characters: 5 letters, 4 digits, then 1 letter (for example ABCDE1234F)")


def check_gstin(submission):
    # Rule 4: without a well-formed GSTIN the buyer can't claim GST credit on invoices.
    return check_id_format(submission, "tax", "gstin", GSTIN_PATTERN, "gstin_format", "GSTIN",
                           "15 characters: a 2-digit state code, your 10-character PAN, "
                           "then 3 more characters (for example 27ABCDE1234F1Z5)")


def check_ifsc(submission):
    # Rule 5: a wrong IFSC sends the payment to the wrong bank branch, or it bounces.
    return check_id_format(submission, "bank", "ifsc", IFSC_PATTERN, "ifsc_format", "IFSC",
                           "11 characters: 4 letters, a zero, then 6 letters or digits "
                           "(for example HDFC0001234)")


def check_ein(submission):
    # Rule 6: the EIN goes on US tax forms, so it must at least be 9 digits.
    return check_id_format(submission, "tax", "ein", EIN_PATTERN, "ein_format", "EIN",
                           "9 digits, written as 123456789 or 12-3456789")


def check_account_number(submission):
    # Rule 5: bank account numbers are digits only; letters mean a typo.
    value = get_field(submission, "bank", "account_number")
    if is_blank(value):
        return []  # Stage 1 already reported it missing
    # The number itself is never put in the message: account numbers must stay masked.
    if re.fullmatch(r"[0-9]+", clean_id(value)):
        return [make_finding("format", "account_number_format", "pass",
                             "The bank account number contains only digits.", None)]
    return [make_finding("format", "account_number_format", "fixable",
                         "The bank account number contains characters other than digits.",
                         "Please re-enter your bank account number using digits only.")]


def routing_checksum_ok(digits):
    # ABA rule: multiply the 9 digits by 3,7,1,3,7,1,3,7,1; the total must divide evenly by 10.
    weights = [3, 7, 1, 3, 7, 1, 3, 7, 1]
    total = 0
    for i in range(9):
        total = total + int(digits[i]) * weights[i]
    return total % 10 == 0


def check_routing_number(submission):
    # Rule 6: a mistyped routing number sends money to the wrong bank; the checksum catches most typos.
    value = get_field(submission, "bank", "routing_number")
    if is_blank(value):
        return []  # Stage 1 already reported it missing
    digits = clean_id(value)
    if not re.fullmatch(r"[0-9]{9}", digits):
        message = f"The bank routing number '{value}' should be exactly 9 digits."
    elif not routing_checksum_ok(digits):
        message = f"The bank routing number '{value}' isn't a valid US routing number."
    else:
        return [make_finding("format", "routing_number_format", "pass",
                             "The bank routing number is valid.", None)]
    return [make_finding("format", "routing_number_format", "fixable", message,
                         "Please check the 9-digit routing number with your bank and re-enter it.")]


def run_format(submission):
    # Stage 2: only check the IDs that exist in the vendor's own country.
    country = get_country(submission)
    findings = []
    if country == "IN":
        findings = findings + check_pan(submission)
        findings = findings + check_gstin(submission)
        findings = findings + check_ifsc(submission)
        findings = findings + check_account_number(submission)
    elif country == "US":
        findings = findings + check_ein(submission)
        findings = findings + check_routing_number(submission)
        findings = findings + check_account_number(submission)
    return findings  # any other country was already blocked in Stage 1


# ---------- Stage 3: Consistency ----------

# GSTIN state code (first 2 digits) for each state/UT, keyed by the tidied name from normalise_state().
# A list, because two places also accept an old code that older registrations still carry.
STATE_CODES = {
    "jammu and kashmir": ["01"],
    "himachal pradesh": ["02"],
    "punjab": ["03"],
    "chandigarh": ["04"],
    "uttarakhand": ["05"],
    "haryana": ["06"],
    "delhi": ["07"],
    "rajasthan": ["08"],
    "uttar pradesh": ["09"],
    "bihar": ["10"],
    "sikkim": ["11"],
    "arunachal pradesh": ["12"],
    "nagaland": ["13"],
    "manipur": ["14"],
    "mizoram": ["15"],
    "tripura": ["16"],
    "meghalaya": ["17"],
    "assam": ["18"],
    "west bengal": ["19"],
    "jharkhand": ["20"],
    "odisha": ["21"],
    "chhattisgarh": ["22"],
    "madhya pradesh": ["23"],
    "gujarat": ["24"],
    "dadra and nagar haveli and daman and diu": ["26", "25"],  # 25 = old Daman & Diu code
    "maharashtra": ["27"],
    "karnataka": ["29"],
    "goa": ["30"],
    "lakshadweep": ["31"],
    "kerala": ["32"],
    "tamil nadu": ["33"],
    "puducherry": ["34"],
    "andaman and nicobar": ["35"],
    "telangana": ["36"],
    "andhra pradesh": ["37", "28"],  # 28 = code used before Telangana split off in 2014
    "ladakh": ["38"],
}

# The 4th character of a PAN says who holds it: C = company, P = individual, F = firm/partnership.
PAN_TYPE_LETTERS = {"company": "C", "proprietorship": "P", "partnership": "F"}


def id_is_usable(submission, section, key, pattern):
    # Comparing IDs only makes sense once Stages 1-2 found them present and well-formed.
    value = get_field(submission, section, key)
    if is_blank(value):
        return False
    return re.fullmatch(pattern, clean_id(value)) is not None


def count_differences(a, b):
    # How many positions differ between two same-length IDs; 1 usually means a typo.
    differences = 0
    for i in range(len(a)):
        if a[i] != b[i]:
            differences = differences + 1
    return differences


def check_pan_matches_gstin(submission):
    # Rule 7: characters 3-12 of a GSTIN are the holder's PAN, so the two must be the same business.
    if not id_is_usable(submission, "tax", "pan", PAN_PATTERN):
        return []  # Stage 1 or 2 already reported the PAN
    if not id_is_usable(submission, "tax", "gstin", GSTIN_PATTERN):
        return []  # Stage 1 or 2 already reported the GSTIN
    pan = clean_id(get_field(submission, "tax", "pan"))
    pan_in_gstin = clean_id(get_field(submission, "tax", "gstin"))[2:12]
    differences = count_differences(pan, pan_in_gstin)
    if differences == 0:
        return [make_finding("consistency", "pan_gstin_match", "pass",
                             "The PAN matches the PAN inside the GSTIN.", None)]
    if differences == 1:
        return [make_finding("consistency", "pan_gstin_match", "fixable",
                             f"The PAN '{pan}' and the PAN inside the GSTIN ('{pan_in_gstin}') "
                             "differ by one character, which looks like a typo.",
                             "Please check your PAN and GSTIN against your PAN card and "
                             "GST certificate, and correct the one that is wrong.")]
    return [make_finding("consistency", "pan_gstin_match", "blocker",
                         f"The PAN '{pan}' and the PAN inside the GSTIN ('{pan_in_gstin}') differ in "
                         f"{differences} characters, so they most likely belong to different businesses.",
                         "Please apply using the PAN and GSTIN of the same registered business.")]


def normalise_state(name):
    # Vendors write "Jammu & Kashmir" or "jammu and kashmir"; both should find the same state.
    words = str(name).lower().replace("&", " and ").split()
    return " ".join(words)  # split() + join squeezes any extra spaces


def check_gstin_state(submission):
    # Rule 8: a GSTIN's first 2 digits are the state it's registered in, so they should match the form.
    if not id_is_usable(submission, "tax", "gstin", GSTIN_PATTERN):
        return []  # Stage 1 or 2 already reported the GSTIN
    state = submission.get("state")
    if is_blank(state):
        return []  # Stage 1 already reported the missing state
    state_key = normalise_state(state)
    if state_key not in STATE_CODES:
        return [make_finding("consistency", "gstin_state_match", "fixable",
                             f"The state '{state}' isn't one we recognise as an Indian state or union territory.",
                             "We couldn't recognise the state name — please select it from the list.")]
    gst_code = clean_id(get_field(submission, "tax", "gstin"))[0:2]
    if gst_code in STATE_CODES[state_key]:
        return [make_finding("consistency", "gstin_state_match", "pass",
                             f"The GSTIN's state code ({gst_code}) matches {state}.", None)]
    expected = " or ".join(STATE_CODES[state_key])
    return [make_finding("consistency", "gstin_state_match", "fixable",
                         f"The GSTIN starts with state code {gst_code}, but the state on the form is "
                         f"{state} (code {expected}).",
                         "Please check the state on the form is where this GSTIN is registered, "
                         "or enter the GSTIN registered in that state.")]


def check_pan_entity_type(submission):
    # Rule 9: a PAN's 4th character shows who holds it, so it must fit the business type on the form.
    entity_type = submission.get("entity_type")
    if is_blank(entity_type):
        return []  # Stage 1 already reported the missing business type
    entity_type = str(entity_type).strip().lower()
    if entity_type not in PAN_TYPE_LETTERS:
        return [make_finding("consistency", "pan_entity_type_match", "fixable",
                             "This business type isn't valid for Indian vendors — please choose "
                             "company, proprietorship or partnership.",
                             "Please choose company, proprietorship or partnership as your business type.")]
    if not id_is_usable(submission, "tax", "pan", PAN_PATTERN):
        return []  # Stage 1 or 2 already reported the PAN
    letter = clean_id(get_field(submission, "tax", "pan"))[3]
    expected = PAN_TYPE_LETTERS[entity_type]
    if letter == expected:
        return [make_finding("consistency", "pan_entity_type_match", "pass",
                             f"The PAN's type ('{letter}') fits a {entity_type}.", None)]
    return [make_finding("consistency", "pan_entity_type_match", "fixable",
                         f"The PAN's 4th character is '{letter}', but a {entity_type}'s PAN has "
                         f"'{expected}' there.",
                         "Please check the business type you selected and the PAN you entered; "
                         "one of them is wrong.")]


def check_bank_name(submission):
    # Rule 10: an account in a different name is the most common way vendor payments get stolen.
    holder = get_field(submission, "bank", "account_holder")
    legal_name = submission.get("legal_name")
    if is_blank(holder) or is_blank(legal_name):
        return []  # Stage 1 already reported the missing name
    # token_sort_ratio sorts the words first, so word order doesn't lower the score (0-100).
    score = round(fuzz.token_sort_ratio(normalise_text(holder), normalise_text(legal_name)))
    score_text = f"Name match score: {score}/100."
    if score >= 90:
        return [make_finding("consistency", "bank_name_match", "pass",
                             f"The bank account name matches the business name. {score_text}", None)]
    if score >= 70:
        return [make_finding("consistency", "bank_name_match", "fixable",
                             f"The bank account name '{holder}' is close to, but not the same as, "
                             f"the business name '{legal_name}'. {score_text}",
                             "Please send a cancelled cheque or bank letter showing the account "
                             "is in your business's name.")]
    # fix is None: review findings are never shown to the vendor; a person checks them.
    return [make_finding("consistency", "bank_name_match", "review",
                         f"The bank account name '{holder}' is very different from the business name "
                         f"'{legal_name}'. {score_text}", None)]


def run_consistency(submission):
    # Stage 3: fields that are each fine on their own must also agree with each other.
    country = get_country(submission)
    findings = []
    if country == "IN":  # PAN and GSTIN only exist for Indian vendors
        findings = findings + check_pan_matches_gstin(submission)
        findings = findings + check_gstin_state(submission)
        findings = findings + check_pan_entity_type(submission)
    if country in SUPPORTED_COUNTRIES:
        findings = findings + check_bank_name(submission)
    return findings  # any other country was already flagged in Stage 1


# ---------- Stage 4: Risk ----------

# Built from this file's own folder, so it works wherever the app is started from.
MASTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vendor_master.csv")


def load_vendor_master(path):
    # csv keeps every value as text, so account numbers like 002205013344 keep their leading zeros.
    rows = []
    # utf-8-sig also copes with the hidden marker Excel adds at the start when it saves a CSV.
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):  # one dict per row, keyed by the header line
            rows.append(row)
    return rows


# Loaded once, when checks.py is first imported, not on every run.
VENDOR_MASTER = load_vendor_master(MASTER_PATH)


def mask_account(number):
    # Account numbers are sensitive, so we only ever show the last 4 digits.
    digits = clean_id(number)
    return "****" + digits[-4:]


def same_bank_account(account, ifsc, row):
    # Compare as text, never as numbers, so leading zeros count.
    if clean_id(row["bank_account_number"]) != account:
        return False
    if ifsc is None or is_blank(row["ifsc"]):
        return True  # no usable IFSC on one side: the account number alone decides
    return clean_id(row["ifsc"]) == ifsc


def check_duplicate_bank(submission):
    # Rule 11: two vendors paid into one account is a classic sign of a fake or hijacked vendor.
    account = get_field(submission, "bank", "account_number")
    if is_blank(account) or not re.fullmatch(r"[0-9]+", clean_id(account)):
        return []  # Stage 1 or 2 already reported the account number
    account = clean_id(account)
    ifsc = None  # US vendors have no IFSC, so they match on the account number alone
    if get_country(submission) == "IN" and id_is_usable(submission, "bank", "ifsc", IFSC_PATTERN):
        ifsc = clean_id(get_field(submission, "bank", "ifsc"))
    # A missing or mistyped IFSC leaves ifsc as None, so mistyping it can't dodge this check.
    findings = []
    for row in VENDOR_MASTER:
        if same_bank_account(account, ifsc, row):
            findings.append(make_finding("risk", "duplicate_bank_account", "review",
                                         f"This bank account ({mask_account(account)}) is already used by "
                                         f"{row['vendor_id']} – {row['legal_name']}.", None))
    if len(findings) == 0:
        findings.append(make_finding("risk", "duplicate_bank_account", "pass",
                                     "No other vendor on our list uses this bank account.", None))
    return findings


def check_duplicate_tax_id(submission, key, pattern, check_name, label):
    # Shared by PAN and GSTIN; key is also the column name in vendor_master.csv.
    if not id_is_usable(submission, "tax", key, pattern):
        return []  # Stage 1 or 2 already reported it
    value = clean_id(get_field(submission, "tax", key))
    findings = []
    for row in VENDOR_MASTER:
        if clean_id(row[key]) == value:
            # fix is None: review findings are never shown to the vendor; a person checks them.
            findings.append(make_finding("risk", check_name, "review",
                                         f"This {label} ({value}) is already on file for "
                                         f"{row['vendor_id']} – {row['legal_name']}.", None))
    if len(findings) == 0:
        findings.append(make_finding("risk", check_name, "pass",
                                     f"No other vendor on our list has this {label}.", None))
    return findings


def check_duplicate_pan(submission):
    # Rule 12: review, not reject: one company can register a new GSTIN per state under the same PAN.
    return check_duplicate_tax_id(submission, "pan", PAN_PATTERN, "duplicate_pan", "PAN")


def check_duplicate_gstin(submission):
    # Rule 12: a GSTIN is one registration, so a match is a repeat sign-up or someone using its identity.
    return check_duplicate_tax_id(submission, "gstin", GSTIN_PATTERN, "duplicate_gstin", "GSTIN")


def run_risk(submission):
    # Stage 4: compare the vendor against everyone we already pay.
    country = get_country(submission)
    findings = []
    if country in SUPPORTED_COUNTRIES:
        findings = findings + check_duplicate_bank(submission)
    if country == "IN":  # the master has no EINs, so US vendors skip rule 12
        findings = findings + check_duplicate_pan(submission)
        findings = findings + check_duplicate_gstin(submission)
    return findings  # any other country was already flagged in Stage 1


if __name__ == "__main__":
    # Quick manual test: python checks.py [path to a submission JSON]. Defaults to the happy sample.
    path = "samples/01_happy.json"
    if len(sys.argv) > 1:
        path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        sample = json.load(f)
    all_findings = run_completeness(sample) + run_format(sample) + run_consistency(sample) + run_risk(sample)
    for finding in all_findings:
        print(f"[{finding['stage']}] [{finding['severity']}] {finding['check']}: {finding['message']}")
        if finding["fix"] is not None:
            print(f"    fix: {finding['fix']}")
