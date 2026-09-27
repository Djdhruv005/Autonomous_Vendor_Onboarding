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
| **NEEDS_REVIEW (Check)** | Something looks suspicious but may be legitimate. The bank account or tax ID already belongs to another vendor, or the bank account is in a very different name. | A person on our team approves or rejects, with a note. The vendor is only told their application is under additional review. |
| **NEEDS_REVIEW (Recommend reject)** | The data can't be right (the PAN inside the GSTIN differs from the PAN given in 2 or more characters), or the vendor is outside India and the US. | Same as above: a person makes the final call. A rejection email is drafted only if they reject. |

Only a person can reject a vendor. The reviewer enters their name and a note. Both are saved with the run, along with their decision and the time, so the audit trail shows who decided what and why. If the reviewer approves a run that also has fixable items, it becomes PENDING and the vendor gets the email with the numbered fixes; with no fixable items it becomes APPROVED.

**Repeat submissions.** Runs from the same vendor are linked by a vendor key: the PAN for Indian vendors, the EIN for US vendors (with or without its hyphen), or the tidied legal name if that ID is blank. Two runs are also linked when their tidied legal names match, so a vendor who fixes a mistyped PAN, or fills in a PAN they left blank, is still recognised as the same vendor. Each run gets an attempt number (1, 2, 3…). When a new run arrives, the vendor's earlier runs that are still open (AWAITING REVIEW or PENDING) become **SUPERSEDED** and point to the new run, because only the latest answers matter. This includes a PENDING run a reviewer approved; its reviewer name, note and time are kept. APPROVED and REJECTED runs are final and never change, and a superseded run can no longer be reviewed. The review queue shows each item's attempt number and what happened to earlier attempts (e.g. "Previous: run #3 REJECTED by Asha — …"), so a vendor resubmitting after a rejection is obvious. The dashboard tiles count each vendor once, by their latest attempt, and superseded runs are hidden from the table by default. Pressing Run checks again with nothing changed shows the last result instead of saving a copy.

*Risk (same-name linking):* two different businesses with the same legal name (say, two "Sharma Traders" in different cities, with different PANs) are treated as one vendor. A new run from one supersedes the other's open PENDING or AWAITING REVIEW run, and their attempt numbers are shared. Someone could also submit under a real vendor's name to push that vendor's open run out of the review queue. It is still visible, as SUPERSEDED with a link to the new run, and the new run shows "Previous: …" in the queue so the reviewer sees the history. We accept this because a typo fix breaking the link is far more common. Next step: link on name only when the bank account or GSTIN also matches.

Why this split: a typo shouldn't block a genuine vendor, an automated check shouldn't be the last word on turning a business away, and a possible fraudster shouldn't learn what gave them away.

## 3. The 14 rules

| # | Stage | What we check | If it fails |
|---|---|---|---|
| 1 | Completeness | All required details are filled in. Indian vendors also need PAN, GSTIN and IFSC. US vendors also need EIN and routing number. The business type is company, proprietorship, partnership or LLC. | PENDING |
| 2 | Completeness | The required documents are attached. India: GST certificate, PAN card, cancelled cheque. US: W-9 form, bank letter. | PENDING |
| 3 | Format | The PAN (Indian tax ID) has the right shape: 5 letters, 4 digits, 1 letter. | PENDING |
| 4 | Format | The GSTIN (Indian GST number) has the right 15-character shape. | PENDING |
| 5 | Format | The IFSC (Indian bank branch code) has the right shape, and the account number is digits only. | PENDING |
| 6 | Format | The US tax ID (EIN) is 9 digits, and the US routing number passes the standard bank checksum. | PENDING |
| 7 | Consistency | The PAN inside the GSTIN matches the PAN given. | PENDING if they differ in one character (likely a typo). NEEDS_REVIEW (Recommend reject) if they differ in two or more. |
| 8 | Consistency | The state code in the GSTIN matches the state on the form. | PENDING |
| 9 | Consistency | The PAN's type (company, individual or firm) matches the business type. Indian vendors must be a company, proprietorship or partnership. | PENDING |
| 10 | Consistency | The name on the bank account matches the business name (see section 4). | PENDING if close, or if either name has no letters or numbers (e.g. "..."). NEEDS_REVIEW (Check) if very different. |
| 11 | Risk | The bank account already belongs to another vendor on our list. | NEEDS_REVIEW (Check) |
| 12 | Risk | The tax ID already belongs to another vendor on our list. | NEEDS_REVIEW (Check) |
| 13 | Decision | Combine all the results. Anything recommended for rejection or needing a check → NEEDS_REVIEW. Otherwise any pending item → PENDING. Otherwise the vendor is approved. The system never rejects on its own. | — |
| 14 | Email | The AI-written email must not contain the account number or the words "fraud", "duplicate" or "suspicious". | We send our standard template email instead. |

The AI only writes the wording of the email. It never decides the outcome.

## 4. Thresholds and the reasoning behind them

- **PAN vs GSTIN: one character different is a typo, two or more is not.** A single wrong character is the most common typing mistake, so we ask the vendor to check. Two or more differences mean the IDs most likely belong to different businesses, so we recommend rejection and a person decides.
- **Tidying IDs before checking.** Capitals, spaces (including tabs and the invisible non-breaking spaces that come with copy-paste) and hyphens are ignored in PAN, GSTIN, IFSC, EIN, routing and account numbers, so "27-aakcm4821q-1zu" is read as "27AAKCM4821Q1ZU". Country names are accepted as well as codes ("India", "USA", "United States"), and a few official or old state names map to their current entry ("Andaman and Nicobar Islands", "NCT of Delhi", "Orissa", "Pondicherry"). Document names are compared ignoring capitals and spaces, and a document list that isn't a list counts as nothing attached.
- **Tidying names before comparing.** We ignore capitals, punctuation and "M/s", and treat "Pvt Ltd" the same as "Private Limited". So "SHARMA TRADERS PVT LTD" matches "Sharma Traders Private Limited".
- **Name score of 90 or more: same name.** The vendor passes.
- **Name score from 70 to 89: probably the same business, worded differently.** For example "SHARMA TRADERS AND CO" vs "Sharma Traders" scores 80. We ask for proof (a cancelled cheque showing the business name) instead of rejecting.
- **Name score below 70: the money might go to someone else.** This is the most common way vendor payments get stolen, but there are legitimate reasons too, such as a sole proprietor's account in their personal name (e.g. "Rakesh Sharma" vs "Sharma Traders" scores about 44). So a person checks it before anything is final.
- These numbers are a judgement call, not an official standard. They would be tuned once we see real submissions.
- **State check covers every Indian state and union territory.** Two accept an old code as well as the current one, because older registrations still carry it: Andhra Pradesh (37, or the old 28) and Dadra & Nagar Haveli and Daman & Diu (26, or the old 25). If we don't recognise the state name, we ask the vendor to choose it from the list instead of guessing.

## 5. Known limitations

Found in pre-demo testing and left in on purpose. Each has a next step.

- **Account numbers are only checked for digits, not length or plausibility.** An account number of "1" or "0000000000" passes. We haven't built a length rule because we couldn't confirm a single official range: Indian banks commonly use 9 to 18 digits and US account numbers vary by bank. A length rule would still let a real-looking wrong number through. *Next step:* bank penny-drop verification (see section 6), which confirms the account exists and returns the holder's name.
- **Very long business names are cut at 100 characters in the email greeting.** A 600-character name becomes "Dear Moonbeam … XXXX" with no comma. The checks and the dashboard still use the full name. *Next step:* limit the legal name field to a sensible length on the form (e.g. 150 characters) and cut the greeting at a word boundary.
- **A US vendor who also fills in a PAN or GSTIN is approved on the US checks alone.** The Indian IDs are saved with the submission but not checked, not even against our vendor list, so a US applicant using an existing Indian vendor's PAN isn't flagged. The form hides these fields for US vendors, so this only happens with a JSON submission. *Next step:* flag other-country tax IDs for a person to check (NEEDS_REVIEW, Check), or run the duplicate PAN/GSTIN check whenever they're present.

## 6. What I'd build next

- Check the GSTIN's final check character, to catch typos the shape check misses.
- Look up the GSTIN and PAN on the government portal to confirm they're active and that the registered name matches.
- Bank "penny drop": send ₹1 to the account and check the account-holder name the bank returns. This is the strongest defence against payments being redirected.
- Read the uploaded documents (starting with the GST certificate PDF) and compare them against the form, instead of relying on the tick-list.
- A link where the vendor can fix PENDING items and resubmit, with the earlier runs kept in the audit trail.
