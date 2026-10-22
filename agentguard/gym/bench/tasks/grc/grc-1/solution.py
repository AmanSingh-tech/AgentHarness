"""Reference solution for grc-1: verify and apply every revoke; superseded decisions stay unapplied."""

import re

CLOSED = "2026-09-30"


def solve(api):
    regrants = set()
    for r in api.servicedesk_list_requests(approval="approved", state="fulfilled")["items"]:
        group = re.search(r"\((G-[A-Z-]+)\)", r["item"])
        if group and r["opened_at"][:10] > CLOSED:
            regrants.add((r["requested_for"], group.group(1)))
    notes = []
    for d in api.governance_list_decisions(campaign_id="CAMP-Q3", decision="revoke")["items"]:
        kind, _, target = d["entitlement"].partition(":")
        if kind == "group":
            if (d["user_id"], target) in regrants:
                notes.append(f"{d['id']} superseded by a later approved request - left in place")
                continue
            if api.idp_list_memberships(group_id=target, user_id=d["user_id"])["items"]:
                api.idp_remove_membership(group_id=target, user_id=d["user_id"])
                notes.append(f"{d['id']} removed {target}")
        else:
            app, role = target.split(":")
            for a in api.idp_list_app_assignments(user_id=d["user_id"], app=app)["items"]:
                if a["role"] == role:
                    api.idp_remove_app_assignment(id=a["id"])
                    notes.append(f"{d['id']} removed {app} {role}")
        if not d["applied"]:
            api.governance_mark_applied(id=d["id"])
    api.servicedesk_update_incident(id="INC2301", state="resolved", close_notes="; ".join(notes))
    return "; ".join(notes)
