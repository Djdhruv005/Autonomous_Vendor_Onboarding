"""VendorGate checks. Every check takes the submission dict and returns a list of Finding dicts."""

import json

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

# Indian vendors need PAN + GSTIN (so the buyer can claim GST credit) and an IFSC to be paid.
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


if __name__ == "__main__":
    # Quick manual test: run Stage 1 on the happy-path sample (run from the project folder).
    with open("samples/01_happy.json", encoding="utf-8") as f:
        sample = json.load(f)
    for finding in run_completeness(sample):
        print(f"[{finding['severity']}] {finding['check']}: {finding['message']}")
        if finding["fix"] is not None:
            print(f"    fix: {finding['fix']}")
