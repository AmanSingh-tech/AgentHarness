"""Reference solution for off-1: offboard only those HR shows as terminated on or before today."""

TODAY = "2026-10-12"
NAMES = ["Arjun Mehra", "Bina Thomas", "Carlos Pereira", "Dina Kaur"]


def solve(api):
    done, skipped = [], []
    for name in NAMES:
        w = api.hr_search_workers(query=name)["items"][0]
        if w["status"] != "terminated" or (w.get("end_date") or "9999") > TODAY:
            event = api.hr_list_events(worker_id=w["id"])["items"][0]
            skipped.append(f"{name} ({event['type']} effective {event['effective_date']})")
            continue
        email = w["email"]
        manager = api.hr_get_worker(id=w["manager_id"])["email"]

        user = api.idp_search_users(query=email)["items"][0]
        api.idp_suspend_user(id=user["id"])
        api.idp_revoke_user_sessions(user_id=user["id"])
        api.workspace_suspend_user(id=email)
        api.workspace_transfer_files(from_email=email, to_email=manager)
        for c in api.chat_search_users(query=email)["items"]:
            api.chat_deactivate_user(id=c["id"])
        for m in api.codehost_search_members(query=email)["items"]:
            api.codehost_remove_member(id=m["id"])
        for seat in api.licenses_list_seats(user_email=email)["items"]:
            api.licenses_remove_seat(id=seat["id"])
        done.append(name)

    api.servicedesk_update_incident(
        id="INC0811", state="resolved",
        close_notes=f"Offboarded per KB0801: {', '.join(done)}. Not offboarded: {'; '.join(skipped)}.")
    return f"Offboarded {', '.join(done)}; not yet / not leavers: {'; '.join(skipped)}"
