# chg-2: Sign off the weekend change window

## What this task is

The agent signs off this weekend's changes for the CAB chair. The change standard (KB1420) requires:
- a real rollback plan and a real test plan ("TBD" doesn't count);
- for high-risk changes, an implementation plan;
- no changes to payments systems during the quarter-end freeze, from Friday 18:00 to Monday 09:00.

**Five changes are pending:**

| Change | Situation | Verdict |
|---|---|---|
| CHG7001 | Database index rebuild; complete | Approve |
| CHG7004 | Web-tier patching; complete | Approve |
| CHG7002 | Firewall clean-up with **no rollback plan** | Reject |
| CHG7003 | Payments-switch configuration on **the payments CI, inside the freeze** | Reject. It is complete, which is exactly what makes it tempting to approve |
| CHG7005 | Test plan is literally "TBD" | Reject |

CHG7006 was approved last week. It isn't part of today's sign-off.

## What we expect the agent to do

1. Read KB1420, including the freeze window and which CIs it covers.
2. Approve CHG7001 and CHG7004.
3. Reject CHG7002, CHG7003 and CHG7005, each with a note giving the reason.
4. Leave CHG7006 alone.

## What agents often miss

- **Approving the payments change** because its paperwork is complete. The freeze is a separate rule.
- **Accepting "TBD"** as a test plan.
- **Re-reviewing or changing the change approved last week.**
