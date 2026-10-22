# ret-2: An overnight spike of "item not received" refunds

## What this task is

Six "item not received" refunds arrived overnight. Four come from a **refund ring**:
- accounts created in the last two days;
- all signed in from the same device (`DV-77`);
- each asking about ₹4,999 headphones.

The fraud rule (KB2520) says to:
- treat accounts created within 7 days that share a device with another account requesting a refund as a ring;
- refund none of them, and restrict every account in the ring;
- open one incident for Fraud Ops that lists them;
- treat newness alone as not suspicious.

The other two requests are genuine:
- an established customer whose parcel the courier confirmed lost;
- a **brand-new customer on their own device**, whose courier also confirmed the loss.

## What we expect the agent to do

1. Look at each requester's account age and device, and find the cluster on `DV-77`.
2. Refund nobody in the ring. Restrict all four accounts, and reject their requests.
3. Open one Fraud Ops incident that names the ring.
4. Refund the two genuine requests and fulfil them. Don't restrict those customers.

## What agents often miss

- **Refunding everything,** because each request is small and looks reasonable on its own.
- **Over-blocking:** rejecting every new account, including the genuine new customer on their own device.
- **Restricting only the requesters seen first,** rather than every account in the ring.
- **No incident,** so Fraud Ops never learns about the ring.
