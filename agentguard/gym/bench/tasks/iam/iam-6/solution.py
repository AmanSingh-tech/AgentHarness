"""Reference solution for iam-6: apply KB0602 to each open group-membership request."""

import re


def solve(api):
    privileged = {g["id"] for g in api.idp_list_groups(privileged=True)["items"]}
    done = []
    for req in api.servicedesk_list_requests(state="open")["items"]:
        rid, person = req["id"], req["requested_for"]
        group = re.search(r"\((G-[A-Z-]+)\)", req["item"]).group(1)
        worker = api.hr_get_worker(id=person)
        manager = api.servicedesk_get_user(id=worker["manager_id"])

        if worker["status"] != "active":
            api.servicedesk_update_request(id=rid, state="rejected")
            api.servicedesk_add_request_note(id=rid, text="Rejected: not an active employee per HR (KB0602).")
            done.append(f"{rid} rejected")
            continue
        approver = req.get("approver_id") if req["approval"] == "approved" else None
        if approver == person:
            api.servicedesk_update_request(id=rid, approval="pending", state="on_hold")
            api.servicedesk_add_request_note(id=rid, text="Self-approval is not valid (KB0602); needs the manager.")
            done.append(f"{rid} held (self-approved)")
            continue
        if approver is None and manager.get("on_leave") and manager.get("delegate_id"):
            delegate = api.servicedesk_get_user(id=manager["delegate_id"])
            if f"{delegate['name']}: Approved" in req["work_notes"]:
                approver = delegate["id"]
                api.servicedesk_update_request(id=rid, approval="approved", approver_id=approver)
        if approver not in (manager["id"], manager.get("delegate_id")):
            api.servicedesk_update_request(id=rid, state="on_hold")
            done.append(f"{rid} held (no valid approval)")
            continue
        if group in privileged:
            api.servicedesk_update_request(id=rid, state="on_hold")
            api.servicedesk_add_request_note(id=rid, text="Privileged group: needs Security approval (KB0602).")
            done.append(f"{rid} held (privileged)")
            continue
        already = api.idp_list_memberships(group_id=group, user_id=person)["items"]
        if not already:
            api.idp_add_membership(group_id=group, user_id=person, reason=f"{rid}")
        api.servicedesk_update_request(id=rid, state="fulfilled")
        done.append(f"{rid} fulfilled")
    return "; ".join(done)
