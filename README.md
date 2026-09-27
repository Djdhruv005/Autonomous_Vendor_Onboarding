# VendorGate

VendorGate checks a vendor onboarding submission in 6 stages (completeness, formats, cross-field consistency, risk and duplicates, decision, vendor email) and returns APPROVED, PENDING or NEEDS_REVIEW with plain-English reasons.
It never rejects on its own: NEEDS_REVIEW runs wait for a person to approve or reject, and every run is saved to SQLite as an audit trail.

## Run locally (Windows)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Optional: to have Gemini write the vendor emails, create `.streamlit/secrets.toml` containing:

```
GEMINI_API_KEY = "your-key"
```

Without a key, the app uses template emails. The LLM only writes the email and never decides the status.

`vendorgate.db` is created on first start and filled with the 5 sample runs if it is empty.

## Sample scenarios (`samples/`)

| File | Scenario | Expected |
|---|---|---|
| 01_happy.json | Indian private limited company, everything consistent | APPROVED |
| 02_name_variant.json | Proprietorship; bank account holder is a trade-name variant of the legal name | PENDING |
| 03_pan_gstin_conflict.json | Every ID valid on its own, but the PAN inside the GSTIN differs from the PAN field in 2+ characters | NEEDS_REVIEW (Recommend reject) |
| 04_duplicate_bank.json | Bank account already belongs to another vendor in `data/vendor_master.csv` | NEEDS_REVIEW (Check) |
| 05_us_vendor.json | US LLC with EIN and routing number, no GST/PAN | APPROVED |

Each file can be loaded from the New run page.

## Rules and assumptions

The validation rules, severity levels and assumptions are in [ASSUMPTIONS.md](ASSUMPTIONS.md).
