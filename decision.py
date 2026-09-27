"""VendorGate Stage 5: turn all findings into one status. The system recommends; only a person rejects."""

SEVERITIES = ["pass", "fixable", "review", "blocker"]


def count_severities(findings):
    # Start every severity at 0, so the UI can show "blocker=0" instead of a missing key.
    counts = {}
    for severity in SEVERITIES:
        counts[severity] = 0
    for finding in findings:
        counts[finding["severity"]] = counts[finding["severity"]] + 1
    return counts


def pick_status(counts):
    # Anything suspicious needs a person; anything the vendor can correct waits for them to fix it.
    if counts["blocker"] > 0 or counts["review"] > 0:
        return "NEEDS_REVIEW"
    if counts["fixable"] > 0:
        return "PENDING"
    return "APPROVED"


def pick_recommendation(counts):
    # The system only advises the reviewer; a blocker is a recommendation, never a rejection.
    if counts["blocker"] > 0:
        return "Recommend reject"
    if counts["review"] > 0:
        return "Check"
    return None


def decide(findings):
    # reasons are internal (for the reviewer); fixes go to the vendor, so only fixable items belong there.
    counts = count_severities(findings)
    status = pick_status(counts)
    reasons = []
    fixes = []
    for finding in findings:
        if finding["severity"] != "pass":
            reasons.append(finding["message"])
        if finding["severity"] == "fixable":
            fixes.append(finding["fix"])
    return {
        "status": status,
        "recommendation": pick_recommendation(counts),
        "needs_human_review": status == "NEEDS_REVIEW",
        "reasons": reasons,
        "fixes": fixes,
        "counts": counts,
    }
