"""Reference solution for iam-2: effective access through nesting, resolved per KB0310 and HR titles."""

import re

ENTRY, APPROVE, LEADS = "G-AP-ENTRY", "G-AP-APPROVE", "G-FIN-LEADS"
TODAY = "2026-10-05"


def solve(api):
    members = api.idp_list_memberships()["items"]
    direct = {}
    for m in members:
        direct.setdefault(m["user_id"], set()).add(m["group_id"])
    nested_into_approve = {m["user_id"] for m in members if m["group_id"] == APPROVE and m["user_id"].startswith("G-")}

    def effective(uid):
        groups = set(direct.get(uid, set()))
        if groups & nested_into_approve:
            groups.add(APPROVE)
        return groups

    exceptions = set()
    for r in api.servicedesk_list_requests(approval="approved")["items"]:
        until = re.search(r"Valid until (\d{4}-\d{2}-\d{2})", r["details"])
        if r["item"] == "SoD exception" and until and until.group(1) >= TODAY:
            exceptions.add(r["requested_for"])

    fixed = []
    for user in api.idp_list_users()["items"]:
        uid = user["id"]
        if not {ENTRY, APPROVE} <= effective(uid) or uid in exceptions:
            continue
        title = api.hr_search_workers(query=user["email"])["items"][0]["title"].lower()
        is_manager = any(w in title for w in ("manager", "controller", "head", "director"))
        if is_manager:
            api.idp_remove_membership(group_id=ENTRY, user_id=uid)
        elif APPROVE in direct.get(uid, set()):
            api.idp_remove_membership(group_id=APPROVE, user_id=uid)
        else:
            api.idp_remove_membership(group_id=LEADS, user_id=uid)
        fixed.append(user["login"])

    api.servicedesk_update_incident(id="INC0517", state="resolved",
                                    close_notes=f"SoD conflicts resolved per KB0310 for: {', '.join(fixed)}. "
                                                "Deepa Nair kept both under approved exception REQ-901 (to 2026-12-31).")
    return "Resolved SoD conflicts for " + ", ".join(fixed)
