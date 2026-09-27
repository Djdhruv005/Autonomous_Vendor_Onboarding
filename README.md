# 🛡️ VendorGate

VendorGate checks a new vendor's details before the company pays them.

A vendor submits their business details, tax IDs and bank account. VendorGate runs them through a set of checks, one stage at a time, and gives one of three answers:

- ✅ **Approved**: everything is in order.
- ⏳ **Pending**: something is missing or mistyped, and the vendor can fix it.
- 🟠 **Needs review**: something looks off, so a person on the team decides.

It also drafts the email back to the vendor, and it keeps a record of every submission and decision.

🔗 **Live app:** [https://vendorgate-dhruv.streamlit.app/]

Built by Dhruv for the Zamp.ai AI Solutions Associate case study (problem statement 2: vendor onboarding).

---

## 🤔 The problem it solves

Before a company can pay a new vendor, someone has to check that the vendor is real and that their details add up. Today that is usually done by hand:

- Forms come in half-filled, or with the wrong documents attached.
- The name on the bank account doesn't match the company name.
- A tax ID looks fine on its own but belongs to a different business.
- Someone has to email the vendor, explain what's missing and wait.
- The only record of any of this is somebody's inbox.

If a bad vendor slips through, the company can end up paying a fraudster, or sending tax filings with the wrong details.

VendorGate does the checking automatically, explains every result in plain English, and leaves the final call on anything suspicious to a person.

---

## ⚖️ One rule I built everything around

👤 **The software never rejects a vendor. Only a person can.**

The checks decide what is clearly fine (approve), what the vendor needs to fix (pending), and what looks suspicious (needs review). A suspicious case may still be legitimate, for example a group company sharing a bank account, or a sole trader whose account is in their own name. Software can't tell those apart from fraud, so it recommends and a named person decides. Their name, note and time are saved with the run.

The same idea applies to AI. The AI only writes the wording of the email to the vendor. It never decides the outcome.

---

## 🚀 Try it in two minutes

Open the live app. You don't need an account.

1. On the **New run** page, click **Clean vendor**, then **Run checks**. Watch the four stages run one by one and finish on **Approved**.
2. Click **Duplicate bank** and run it. Stage 4 finds that the bank account already belongs to another vendor, and the result is **Needs review**.
3. Open the **Dashboard**. That run is waiting in the **Review queue**. Enter a name and a note, then click **Reject**. The run leaves the queue, and its details show who rejected it and why.

💤 If the app has been idle, it may take 30 seconds to wake up. It resets to the sample runs when it does.

---

## 🔍 How a submission is checked

```
Vendor submission
      │
      ▼
 1. Completeness ─► Is everything there?
      │              (required details and documents for that country)
      ▼
 2. Formats ──────► Is each ID shaped correctly?
      │              (PAN, GSTIN, IFSC, EIN, US routing number)
      ▼
 3. Consistency ──► Do the details agree with each other?
      │              (PAN inside the GSTIN, state code, business type,
      │               bank account name vs company name)
      ▼
 4. Risk ─────────► Do we already pay this bank account or tax ID
      │              under a different vendor?
      ▼
 5. Decision ─────► Approved / Pending / Needs review
      │
      ▼
 6. Vendor email ─► What happens next, in plain language
```

Every check produces a finding, and each finding has one of four levels:

| Level | Meaning | Example |
|---|---|---|
| ✅ Pass | Fine | PAN has the right format |
| 🟡 Fixable | The vendor can correct it | A document is missing, or one character of the PAN is mistyped |
| 🟠 Review | Suspicious, but could be legitimate | Bank account already used by another vendor |
| 🔴 Blocker | The data can't be right. The system recommends rejection, and a person still decides | The PAN inside the GSTIN belongs to a different business |

The decision takes the worst finding. Any review or blocker leads to **Needs review**, any fixable item leads to **Pending**, and otherwise the vendor is **Approved**.

---

## 🧪 The sample vendors

The app comes with five ready-made submissions, one per button on the New run page.

| Sample | What's going on | Result |
|---|---|---|
| ✅ Clean vendor | An Indian private limited company with everything consistent | Approved |
| ✏️ Name variant | A sole trader whose bank account uses a slightly different trading name | Pending (the vendor is asked for proof) |
| 🔀 PAN/GSTIN conflict | Every ID looks valid on its own, but the tax number inside the GSTIN belongs to someone else | Needs review, with "recommend reject" |
| 🏦 Duplicate bank | The bank account already belongs to another vendor on file | Needs review, with "check" |
| 🇺🇸 US vendor | A US LLC with an EIN and routing number, and no Indian tax IDs | Approved |

The last one shows that the rules change by country: Indian and US vendors are checked differently.

---

## 💡 A few details worth knowing

- ✏️ **Typos vs. real problems.** If the PAN and the PAN inside the GSTIN differ by one character, that's treated as a typo and the vendor is asked to check. Two or more differences mean two different businesses, so it goes to review.
- 🔤 **Name matching.** Names are tidied first ("Pvt Ltd" and "Private Limited" count as the same), then scored out of 100. A score of 90 or more passes. From 70 to 89, the vendor is asked for proof. Below 70, a person looks at it.
- 🔁 **Resubmissions.** When a vendor fixes something and submits again, that's a new attempt, not a duplicate. The older open attempt is marked superseded, so each vendor appears in the review queue once. A person's decision on an earlier attempt is never overwritten.
- 🔒 **Privacy.** Bank account numbers are masked (for example `****8877`) everywhere outside the form. The vendor email never mentions internal findings like "duplicate account", so a fraudster doesn't learn what gave them away.
- ✉️ **The AI email.** Gemini drafts the email from the vendor name and the list of fixes only. Every draft is checked before use. If it contains an account number or words like "fraud", or the API is down, a plain template is used instead. The screen shows which one you're looking at.

The full list of rules, thresholds and reasoning is in [ASSUMPTIONS.md](ASSUMPTIONS.md).

---

## 💻 Run it on your own computer

You need Python 3.12.

```bash
git clone https://github.com/Djdhruv005/Autonomous_Vendor_Onboarding.git
cd Autonomous_Vendor_Onboarding
python -m venv .venv
.venv\Scripts\activate          # on Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at `http://localhost:8501`. On first start it creates `vendorgate.db` and loads the five sample runs.

🔑 **Optional: AI-written emails.** Create a file `.streamlit/secrets.toml` containing:

```toml
GEMINI_API_KEY = "your-key-here"
```

You can get a free key from Google AI Studio. Without a key, everything still works, and the emails just use templates.

---

## 📁 What's in the project

| File | What it does |
|---|---|
| `app.py` | The screens: New run (form and live checks) and Dashboard (review queue, history, run details) |
| `checks.py` | All the rules, one small function per check |
| `pipeline.py` | Runs the stages in order and passes each result on as it finishes |
| `decision.py` | Turns the findings into one outcome |
| `emailer.py` | Drafts the vendor email (AI with a template fallback) |
| `db.py` | Saves every run, review decision and email (SQLite) |
| `data/vendor_master.csv` | The list of existing vendors used for duplicate checks |
| `samples/` | The five demo submissions |
| `ASSUMPTIONS.md` | Every rule, threshold and trade-off in plain English |

🧰 Built with Python, Streamlit, SQLite, rapidfuzz (name matching) and Google Gemini (email wording only).

---

## 🚧 What it doesn't do (yet)

- **It doesn't confirm that IDs are registered.** It checks that they're well-formed and consistent, not that the government or the bank knows them. Next steps would be a GST portal lookup and a bank "penny drop" (sending ₹1 to confirm the account holder's name).
- **It doesn't read documents.** The vendor lists what they've attached, and the files themselves aren't opened.
- **It doesn't send emails.** It drafts them for a person to review and send.
- **It has no logins.** It's a single-user demo, and reviewers type their name.
- **The hosted history resets.** The free hosting doesn't keep files, so the dashboard returns to the sample runs whenever the app restarts.

Known edge cases are listed in [ASSUMPTIONS.md](ASSUMPTIONS.md).
