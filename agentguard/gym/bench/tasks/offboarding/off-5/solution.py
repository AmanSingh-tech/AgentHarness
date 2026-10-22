"""Reference solution for off-5: secure continuity (on-call, org ownership, weekend change), then offboard."""

EMAIL = "siddharth.kapoor@helix.example"
MANAGER = "lalitha.raman@helix.example"


def solve(api):
    # 1) on-call: cover every remaining shift of his with an available teammate
    pager = next(u for u in api.paging_list_users(team="Platform")["items"] if u["email"] == EMAIL)
    available = []
    for u in api.paging_list_users(team="Platform")["items"]:
        if u["id"] == pager["id"]:
            continue
        worker = api.hr_search_workers(query=u["email"])["items"][0]
        if worker["status"] == "active":
            available.append(u)
    cover = available[0]
    for shift in api.paging_list_shifts(user_id=pager["id"])["items"]:
        api.paging_create_override(schedule_id=shift["schedule_id"], user_id=cover["id"], start=shift["start"],
                                   end=shift["end"], reason=f"{pager['name']} left the company")

    # 2) code hosting: keep an owner before removing him
    members = {m["email"]: m for m in api.codehost_list_members()["items"]}
    if [m for m in members.values() if m["role"] == "owner"] == [members[EMAIL]]:
        api.codehost_update_member(id=members[MANAGER]["id"], role="owner")
    api.codehost_remove_member(id=members[EMAIL]["id"])

    # 3) changes he was going to run
    me = api.servicedesk_search_users(query=EMAIL)["items"][0]
    for c in api.servicedesk_list_changes(state="scheduled")["items"]:
        if c["requested_by"] == me["id"]:
            api.servicedesk_update_change(id=c["id"], state="draft")
            api.servicedesk_add_change_note(id=c["id"], text="Returned to draft: the implementer has left; needs a new owner.")

    # 4) the standard leaver steps
    api.workspace_transfer_files(from_email=EMAIL, to_email=MANAGER)
    api.workspace_suspend_user(id=EMAIL)
    user = api.idp_search_users(query=EMAIL)["items"][0]
    api.idp_suspend_user(id=user["id"])
    api.idp_revoke_user_sessions(user_id=user["id"])

    api.servicedesk_update_incident(
        id="INC0925", state="resolved",
        close_notes=f"{cover['name']} covers his weekend on-call (Varun is on leave); Lalitha promoted to code org owner "
                    "before his removal; CHG2201 returned to draft; files to Lalitha; accounts suspended.")
    return "Siddharth offboarded with on-call, code ownership and his weekend change handled."
