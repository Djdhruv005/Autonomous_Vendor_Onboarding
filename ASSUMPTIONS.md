# VendorGate: Assumptions and Rules

How VendorGate decides whether a new vendor can be paid, and what it deliberately leaves out.

## 1. Scope

**In scope**
- Vendors from India (companies, proprietorships, partnerships) and the US (LLCs and companies).
- A submission is a form or JSON file containing company details, tax IDs, bank details and a list of the documents the vendor says they've attached.
- Every run ends with a status, the reasons for it and, if the vendor isn't approved, an email telling them what to do.
- Checking our existing vendor list for duplicates.

**Out of scope**
- Reading the documents themselves. The vendor ticks which documents they attached, and we don't open the files.
- Live lookups on the GST portal, the Income Tax Department or the IRS. We check that the IDs are well-formed and consistent with each other. We don't confirm they're registered.
- Vendors outside India and the US.
- Indian vendors below the GST registration threshold. We require a GSTIN from every Indian vendor, because without one the buyer can't claim tax credit on their invoices. For reference, the threshold is approximately ₹40 lakh turnover for goods and ₹20 lakh for services, and lower in some special-category states.
- Sending emails. VendorGate drafts the email; a person on the procurement team reviews and sends it.
- User logins and roles. It's a single-user demo.

## 2. What the outcomes mean

| Outcome | Meaning | What happens next |
|---|---|---|
| **APPROVED** | Everything is complete and consistent. | The vendor can be set up for payment. |
| **PENDING** | Something is missing or mistyped, and the vendor can fix it. | The vendor gets an email with a numbered list of fixes. |
| **REJECTED** | The data can't be right, for example two tax IDs that belong to different businesses. | The vendor gets a polite email saying the application can't proceed, and what to do next. |
| **REJECTED + needs human review** | A possible fraud signal. The bank account or tax ID already belongs to another vendor, or the bank account is in a very different name. | A person on our team looks at it before anything is final. The vendor is only told their application is under additional review. |

Why this split: a typo shouldn't block a genuine vendor, and a possible fraudster shouldn't learn what gave them away.

## 3. The 14 rules

| # | Stage | What we check | If it fails |
|---|---|---|---|
| 1 | Completeness | All required details are filled in. Indian vendors also need PAN, GSTIN and IFSC. US vendors also need EIN and routing number. | PENDING |
| 2 | Completeness | The required documents are attached. India: GST certificate, PAN card, cancelled cheque. US: W-9 form, bank letter. | PENDING |
| 3 | Format | The PAN (Indian tax ID) has the right shape: 5 letters, 4 digits, 1 letter. | PENDING |
| 4 | Format | The GSTIN (Indian GST number) has the right 15-character shape. | PENDING |
| 5 | Format | The IFSC (Indian bank branch code) has the right shape, and the account number is digits only. | PENDING |
| 6 | Format | The US tax ID (EIN) is 9 digits, and the US routing number passes the standard bank checksum. | PENDING |
| 7 | Consistency | The PAN inside the GSTIN matches the PAN given. | REJECTED |
| 8 | Consistency | The state code in the GSTIN matches the state on the form. | PENDING |
| 9 | Consistency | The PAN's type (company, individual or firm) matches the business type. | PENDING |
| 10 | Consistency | The name on the bank account matches the business name (see section 4). | PENDING if close. REJECTED + human review if very different. |
| 11 | Risk | The bank account already belongs to another vendor on our list. | REJECTED + human review |
| 12 | Risk | The tax ID already belongs to another vendor on our list. | REJECTED + human review |
| 13 | Decision | Combine all the results. Any rejection wins, then any pending item. Otherwise the vendor is approved. | — |
| 14 | Email | The AI-written email must not contain the account number or the words "fraud", "duplicate" or "suspicious". | We send our standard template email instead. |

The AI only writes the wording of the email. It never decides the outcome.

## 4. Thresholds and the reasoning behind them

- **Tidying names before comparing.** We ignore capitals, punctuation and "M/s", and treat "Pvt Ltd" the same as "Private Limited". So "SHARMA TRADERS PVT LTD" matches "Sharma Traders Private Limited".
- **Name score of 90 or more: same name.** The vendor passes.
- **Name score from 70 to 89: probably the same business, worded differently.** A typical case is a sole proprietor whose account is in their personal name. This is common and legitimate, so we ask for proof (a cancelled cheque showing the business name) instead of rejecting.
- **Name score below 70: the money would go to someone else.** This is the most common way vendor payments get stolen, so a person reviews it.
- These numbers are a judgement call, not an official standard. They would be tuned once we see real submissions.
- **State check covers six states only:** Maharashtra, Gujarat, Karnataka, Delhi, Tamil Nadu and Goa. For any other state we skip the check rather than guess, because a wrong flag costs a genuine vendor a week.

## 5. What I'd build next

- Check the GSTIN's final check character, and cover every state code, to catch typos the shape check misses.
- Look up the GSTIN and PAN on the government portal to confirm they're active and that the registered name matches.
- Bank "penny drop": send ₹1 to the account and check the account-holder name the bank returns. This is the strongest defence against payments being redirected.
- Read the uploaded documents (starting with the GST certificate PDF) and compare them against the form, instead of relying on the tick-list.
- A link where the vendor can fix PENDING items and resubmit, with the earlier runs kept in the audit trail.
