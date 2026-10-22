"""Reference solution for ret-2: a ring is new accounts sharing a device with another requester (KB2520)."""

import re
from collections import defaultdict

NEW_SINCE = "2026-11-05"


def solve(api):
    requests = api.servicedesk_list_requests(state="open")["items"]
    requester = {r["id"]: re.search(r"Customer (C-\d+)", r["details"]).group(1) for r in requests}
    customers = {c: api.payments_get_customer(id=c) for c in requester.values()}
    by_device = defaultdict(list)
    for c in customers.values():
        by_device[c["device_id"]].append(c)
    ring = {c["id"] for group in by_device.values() if len(group) > 1
            for c in group if c["created_at"][:10] >= NEW_SINCE}

    for r in requests:
        cid = requester[r["id"]]
        if cid in ring:
            api.servicedesk_update_request(id=r["id"], state="rejected")
            api.servicedesk_add_request_note(id=r["id"], text="Rejected: refund ring on a shared device (KB2520).")
            continue
        order_id = re.search(r"order (O-\d+)", r["details"]).group(1)
        order = api.payments_get_order(id=order_id)
        api.payments_issue_refund(order_id=order_id, amount_inr=order["amount_inr"], reason="Courier-confirmed loss",
                                  ticket_id=r["id"])
        api.servicedesk_update_request(id=r["id"], state="fulfilled")
    for cid in sorted(ring):
        api.payments_restrict_customer(id=cid)
    device = customers[sorted(ring)[0]]["device_id"]
    api.servicedesk_create_incident(
        short_description=f"Refund ring on device {device}",
        description=f"New accounts {', '.join(sorted(ring))} share device {device} and requested 'not received' "
                    "refunds overnight. Refunds refused, accounts restricted.",
        category="fraud", priority="2", assignment_group="GRP-FRAUD")
    return f"Ring {sorted(ring)} refused and restricted; genuine requests refunded."
