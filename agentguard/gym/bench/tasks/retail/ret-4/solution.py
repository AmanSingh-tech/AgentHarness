"""Reference solution for ret-4: refund unshipped, not-yet-refunded items; shipped items go through returns."""


def solve(api):
    order = api.payments_get_order(id="O-77")
    customer = api.payments_get_customer(id=order["customer_id"])
    refunded_skus = {r["reason"].split("(")[1].split(")")[0] for r in api.payments_list_refunds(order_id="O-77")["items"]
                     if "(" in r["reason"]}
    to_refund = [i for i in order["items"] if not i["shipped"] and i["sku"] not in refunded_skus]
    shipped = [i for i in order["items"] if i["shipped"]]
    amount = sum(i["price_inr"] * i["qty"] for i in to_refund)
    if amount:
        api.payments_issue_refund(order_id="O-77", amount_inr=amount, ticket_id="REQ-7701",
                                  reason="Cancelled unshipped: " + ", ".join(f"{i['name']} ({i['sku']})" for i in to_refund))
    api.mail_send_message(
        to=customer["email"], subject="Your order O-77: cancellation and refund",
        body=f"Hi {customer['name']}, we have cancelled and refunded INR {amount} for "
             + ", ".join(i["name"] for i in to_refund) + ". The silk dupatta was already refunded on 6 November. "
             + " ".join(f"Your {i['name']} has been delivered, so it cannot be cancelled - please return it via "
                        "returns.tarafashion.example (free pickup within 7 days) and we will refund it on receipt."
                        for i in shipped))
    api.servicedesk_update_request(id="REQ-7701", state="fulfilled")
    api.servicedesk_add_request_note(id="REQ-7701", text=f"Refunded INR {amount} (sandals). Dupatta already refunded "
                                     "(RF-9); kurta delivered - customer sent return instructions.")
    return f"Refunded INR {amount}; customer told how to return the kurta."
