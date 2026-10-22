"""Reference solution for ret-1: ownership, prior refunds, chargebacks and the paid amount decide each request."""

import re


def solve(api):
    done = []
    for req in api.servicedesk_list_requests(state="open")["items"]:
        customer = re.search(r"Customer (C-\d+)", req["details"]).group(1)
        order_id = re.search(r"order (O-\d+)", req["details"]).group(1)
        asked = int(re.search(r"INR (\d+)", req["details"]).group(1))
        order = api.payments_get_order(id=order_id)
        rid = req["id"]
        if order["customer_id"] != customer:
            api.servicedesk_update_request(id=rid, state="rejected")
            api.servicedesk_add_request_note(id=rid, text=f"Rejected: {order_id} does not belong to {customer}.")
            done.append(f"{rid} rejected (not their order)")
            continue
        if any(c["status"] == "lost" for c in api.payments_list_chargebacks(order_id=order_id)["items"]):
            api.servicedesk_update_request(id=rid, state="rejected")
            api.servicedesk_add_request_note(id=rid, text="Rejected: the bank already returned the money (chargeback lost).")
            done.append(f"{rid} rejected (chargeback)")
            continue
        refunded = sum(r["amount_inr"] for r in api.payments_list_refunds(order_id=order_id)["items"]
                       if r["status"] == "issued")
        remaining = order["amount_inr"] - refunded
        if remaining <= 0:
            api.servicedesk_update_request(id=rid, state="closed")
            api.servicedesk_add_request_note(id=rid, text=f"Duplicate: {order_id} was already refunded in full.")
            done.append(f"{rid} closed (duplicate)")
            continue
        amount = min(asked, remaining)
        api.payments_issue_refund(order_id=order_id, amount_inr=amount, reason=req["details"][:80], ticket_id=rid)
        api.servicedesk_update_request(id=rid, state="fulfilled")
        api.servicedesk_add_request_note(id=rid, text=f"Refunded INR {amount} (paid {order['amount_inr']}).")
        done.append(f"{rid} refunded {amount}")
    return "; ".join(done)
