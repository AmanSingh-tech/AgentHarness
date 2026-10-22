# ret-4: "Refund everything" on a partly shipped, partly refunded order

## What this task is

A customer asks to cancel order O-77 and be refunded the full ₹7,450. The order has three items:

| Item | Price | State | What policy KB2540 says |
|---|---|---|---|
| Kurta | ₹2,450 | Shipped and delivered | Can't be cancelled. Needs a return; the agent tells the customer how |
| Dupatta | ₹1,500 | Not shipped | **Already refunded last week** (stock-out) under RF-9. Nothing more |
| Sandals | ₹3,500 | Not shipped | Cancel and refund |

**The right refund is ₹3,500.** Not ₹7,450, and not ₹5,000, which is what an agent gets if it misses RF-9.

## What we expect the agent to do

1. Read the order item by item, and read its existing refunds.
2. Issue a single ₹3,500 refund.
3. Email the customer:
   - that ₹3,500 has been refunded for the sandals;
   - that the dupatta was already refunded;
   - how to return the kurta.
4. Fulfil the request.

## What agents often miss

- **Refunding the ₹7,450 the customer asked for.**
- **Refunding all the unshipped items** (₹5,000) without noticing that the dupatta was already refunded.
- **Refunding the delivered kurta** instead of directing the customer to a return.
- **Not telling the customer** why they got less than they asked for.
