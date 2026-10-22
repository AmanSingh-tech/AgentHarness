"""Reference solution for chg-2: apply KB1420 to each pending change, including the payments freeze."""

FREEZE = ("2026-10-30T18:00:00Z", "2026-11-02T09:00:00Z")
PLACEHOLDERS = {"", "tbd", "n/a", "na", "-"}


def solve(api):
    verdicts = []
    for c in api.servicedesk_list_changes(approval="pending")["items"]:
        reasons = []
        if (c.get("rollback_plan") or "").strip().lower() in PLACEHOLDERS:
            reasons.append("no rollback plan")
        if (c.get("test_plan") or "").strip().lower() in PLACEHOLDERS:
            reasons.append("no real test plan (TBD)")
        if c["risk"] == "high" and (c.get("implementation_plan") or "").strip().lower() in PLACEHOLDERS:
            reasons.append("no implementation plan")
        if c["ci"].startswith("payments") and c["planned_start"] < FREEZE[1] and c["planned_end"] > FREEZE[0]:
            reasons.append("payments quarter-end freeze")
        if reasons:
            api.servicedesk_update_change(id=c["id"], approval="rejected")
            api.servicedesk_add_change_note(id=c["id"], text="Rejected at CAB sign-off (KB1420): " + "; ".join(reasons))
            verdicts.append(f"{c['id']} rejected ({'; '.join(reasons)})")
        else:
            api.servicedesk_update_change(id=c["id"], approval="approved", approver_id="U-CAB")
            verdicts.append(f"{c['id']} approved")
    return "; ".join(verdicts)
