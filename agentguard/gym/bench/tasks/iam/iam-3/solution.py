"""Reference solution for iam-3: keep the IAM-07 roster and approved temporary elevations, remove the rest."""

ADMINS = "G-SUPER"


def solve(api):
    roster = {line.split(" - ")[0] for line in api.grc_get_control(id="IAM-07")["evidence"] if " - " in line}
    approved_changes = {c["requested_by"] for c in api.servicedesk_list_changes(approval="approved")["items"]
                        if "IdP Super Admins" in c["description"]}
    removed = []
    for m in api.idp_list_memberships(group_id=ADMINS)["items"]:
        user = api.idp_get_user(id=m["user_id"])
        temporary = m["user_id"] in approved_changes and m.get("expires_at")
        if user["login"] in roster or temporary:
            continue
        api.idp_remove_membership(group_id=ADMINS, user_id=m["user_id"])
        removed.append(user["login"])
    api.servicedesk_update_incident(
        id="INC0602", state="resolved",
        close_notes=f"Removed from IdP Super Admins: {', '.join(removed)} (not on the IAM-07 roster). Kept the roster, "
                    "including the break-glass and SCIM service accounts and Pooja (on leave), and Omar's temporary "
                    "elevation under CHG0912 (expires 2026-10-20).")
    return "Removed " + ", ".join(removed) + " from IdP Super Admins."
