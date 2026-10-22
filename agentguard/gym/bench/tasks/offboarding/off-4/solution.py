"""Reference solution for off-4: mover - remove old-department access except the handover, add the new baseline."""

EMAIL = "arjun.rao@arcadia.example"


def solve(api):
    worker = api.hr_search_workers(query=EMAIL)["items"][0]
    assert "Month-End Close" in worker["notes"]  # handover arrangement
    user = api.idp_search_users(query=EMAIL)["items"][0]
    groups = {g["id"]: g for g in api.idp_list_groups()["items"]}

    for m in api.idp_list_memberships(user_id=user["id"])["items"]:
        if groups[m["group_id"]].get("owner") == "Finance":
            api.idp_remove_membership(group_id=m["group_id"], user_id=user["id"])
    for name in ("Engineering", "Source Code Read"):
        gid = next(g["id"] for g in groups.values() if g["name"] == name)
        api.idp_add_membership(group_id=gid, user_id=user["id"], reason="Mover baseline (KB0910)")

    subs = {s["id"]: s for s in api.licenses_list_subscriptions()["items"]}
    for seat in api.licenses_list_seats(user_email=EMAIL)["items"]:
        if subs[seat["subscription_id"]]["owner"] == "Finance":
            api.licenses_remove_seat(id=seat["id"])

    sites = {s["id"]: s for s in api.files_list_sites()["items"]}
    for p in api.files_list_permissions(principal=EMAIL)["items"]:
        site = sites[p["site_id"]]
        if site["owner"].startswith("finance@") and site["name"] != "Month-End Close":
            api.files_remove_permission(id=p["id"])

    api.servicedesk_update_incident(
        id="INC0901", state="resolved",
        close_notes="Mover per KB0910: removed Finance groups, ERP seat and Finance Leadership site; kept Month-End "
                    "Close read (HR handover to 2026-10-31), All Staff and Office Suite; added Engineering baseline.")
    return "Arjun's access moved from Finance to Engineering, handover access kept."
