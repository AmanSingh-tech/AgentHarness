# ret-1: Refund queue with a duplicate, a paid chargeback and an over-claim

## What this task is

Five refund requests sit in the queue. The refund policy (KB2501) requires the agent to:
- check that the order belongs to the requesting customer;
- check existing refunds **and chargebacks**. A chargeback the company **lost** means the bank has already returned the money to the customer;
- refund at most what was paid minus what has already been refunded.

| Request | Situation | Outcome |
|---|---|---|
| REQ-1 | Damaged item, ₹2,400, delivered, nothing refunded | Refund ₹2,400, fulfilled |
| REQ-2 | Same customer and order as a refund **already issued yesterday** under REQ-0 | Duplicate: no refund, closed |
| REQ-3 | A ₹5,600 order with a chargeback the company **lost** | Customer already reimbursed: reject |
| REQ-4 | Customer asks for ₹3,000 on a ₹2,200 order | Refund ₹2,200, the amount paid |
| REQ-5 | The order belongs to a different customer | Reject |

## What we expect the agent to do

1. For each request, read the order, its customer, its refunds and its chargebacks.
2. Issue exactly the refunds for REQ-1 (₹2,400) and REQ-4 (₹2,200).
3. Close REQ-2 as a duplicate.
4. Reject REQ-3 and REQ-5, with notes.

## What agents often miss

- **Refunding the duplicate** because it reads like a fresh request.
- **Ignoring chargebacks.** Refunding REQ-3 pays the customer twice.
- **Refunding the claimed ₹3,000** rather than the ₹2,200 paid.
- **Not checking order ownership,** so a customer gets refunded for someone else's order.
