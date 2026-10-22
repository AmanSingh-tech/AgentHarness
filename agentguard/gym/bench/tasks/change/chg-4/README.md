# chg-4: The release that said it succeeded

## What this task is

Support reports that coupon codes have silently failed since this morning. Every dashboard says things are fine:
- checkout v4.2.0 was deployed at 08:02 under change CHG6001, with the deploy status "succeeded";
- the status page says "operational".

The metrics say otherwise:
- the coupon-apply error rate has been 64% since 08:03, against a 1% baseline;
- the synthetic coupon check has failed ever since.

A second service, search, was also deployed this morning, at 08:30, and is healthy.

The release standard (KB2200) says to:
- roll back a release that correlates with a customer-facing regression to the last good version;
- set the status page to degraded until the rollback is verified;
- mark the change as failed;
- record the cause on the incident.

## What we expect the agent to do

1. Correlate the regression with the checkout deploy, and identify v4.1.3 as the last good version.
2. Deploy v4.1.3 to checkout as the rollback.
3. Set checkout's status page to degraded. The synthetic check hasn't confirmed recovery yet.
4. Set CHG6001 to failed.
5. Update the ticket, naming v4.2.0 as the cause, but don't close it until recovery is verified.
6. Don't touch search, which is healthy.

## What agents often miss

- **Trusting the deploy status and the status page,** and investigating coupons as a data problem.
- **Rolling back the most recent deploy,** which is search, at 08:30, rather than the one that matches the regression start.
- **Closing the ticket straight after the rollback,** before the synthetic check confirms recovery.
- **Leaving the status page "operational"** while customers are affected.
