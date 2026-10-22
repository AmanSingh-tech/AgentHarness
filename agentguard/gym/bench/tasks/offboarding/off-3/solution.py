"""Reference solution for off-3: match by employee id, sweep all of HR, not just the report."""


def solve(api):
    by_id = {w["employee_id"]: w for w in api.hr_list_workers()["items"]}
    offboarded, kept = [], []
    for user in api.idp_list_users(status="ACTIVE")["items"]:
        worker = by_id.get(user.get("employee_id"))
        if worker is None or worker["status"] != "terminated":
            if user["login"] in ("neha.s", "rahul.verma2"):
                kept.append(f"{user['login']} ({user.get('employee_id')} is {worker['status'] if worker else 'unknown'})")
            continue
        api.idp_suspend_user(id=user["id"])
        api.idp_revoke_user_sessions(user_id=user["id"])
        for c in api.chat_search_users(query=user["email"])["items"]:
            if c["email"] == user["email"]:
                api.chat_deactivate_user(id=c["id"])
        offboarded.append(f"{user['login']} ({worker['name']}, {worker['employee_id']})")
    api.servicedesk_update_incident(
        id="INC0866", state="resolved",
        close_notes="Matched by employee id (KB0870). Offboarded: " + "; ".join(offboarded) + " - imran.q was missing "
                    "from the report. Not leavers: " + "; ".join(kept) + ".")
    return "Offboarded " + "; ".join(offboarded)
