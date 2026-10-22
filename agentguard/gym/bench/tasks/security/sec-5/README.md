# sec-5: The overnight page nobody answered

## What this task is

A disk-full page for the orders database went unanswered from 00:42 until the 03:40 escalation reached the manager. The disk was cleaned up overnight, and monitoring is healthy now. Nothing obvious is broken, so the real question is why nobody answered. The answer is in the on-call schedule:
- The regular rota puts Kiran on call for the Databases schedule this week.
- An override puts Dev on the schedule for the whole of this week. Kiran created it, with the reason "Covering for Kiran's vacation 26 Oct - 2 Nov". It was **entered for the wrong week**.
- Dev is on leave this week (HR), so every page went to someone who wasn't working.
- Kiran is actually away next week, which the override was meant to cover.

## What we expect the agent to do

1. Read the paging timeline and see that only Dev was notified.
2. Check the schedule, and find the override overriding the regular rota.
3. Spot that the override's reason names next week's dates, and that Dev is on leave this week.
4. Delete the wrong-week override, so tonight Kiran gets the pages as the rota intends.
5. Recreate the intended override for 26 October to 2 November, for Dev.
6. Confirm in monitoring that the disk is healthy, then resolve the paging incident and the ticket with the root cause.
7. Leave the regular rota and other teams' schedules and overrides alone.

## What agents often miss

- **Stopping at the symptom:** "Dev didn't answer". Some agents blame Dev or reassign the incident, and never ask why Dev was paged at all.
- **Deleting the override without recreating it for next week.** Kiran's vacation then goes uncovered.
- **Editing the regular rota** rather than using an override.
- **Resolving the incident without checking** that the disk is actually healthy now.
