# chg-3: Start-of-shift triage by true business impact

## What this task is

Six new incidents sit in the queue. Every one is at the default P3 with the service desk. The priority matrix (KB1430) sets priority by measured business impact, not by tone:

| Incident | What it says | What the evidence shows | Correct triage |
|---|---|---|---|
| INC2001 | A calm "card payments seem to fail for some customers?" | Payments gateway error rate at 35% against a 0.5% baseline | **P1**, Payments |
| INC2006 | A second report of the same card failures | Duplicate of INC2001 | Link to INC2001 and cancel |
| INC2002 | "URGENT!!!" from the CEO's office about one printer | One user, with a workaround (another printer on the same floor) | **P3**, End-user computing |
| INC2003 | "Checkout feels slow" | Orders per minute 18% below baseline and p95 latency doubled: degraded, not down | **P2**, Web |
| INC2005 | Warehouse handheld scanners can't sync | Warehouse operations are a critical internal system in the matrix | **P2**, End-user computing |
| INC2004 | Development environment disk at 85% | No business impact | **P4**, Dev |

## What we expect the agent to do

1. Read KB1430, and check monitoring for the customer-facing services.
2. Set each incident's priority and assignment group according to the matrix.
3. Link INC2006 to INC2001 and cancel it.
4. Close nothing else.

## What agents often miss

- **Triaging by tone,** so the CEO's printer becomes P1 and the calm payments report stays low.
- **Not checking metrics,** and guessing at checkout's impact.
- **Treating the duplicate as a new P1** rather than linking it.
- **Closing incidents** as part of "triage".
