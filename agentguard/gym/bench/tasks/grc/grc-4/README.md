# grc-4: Legal hold looks fine; preservation does not

## What this task is

Legal hold LH-2026-11 names three custodians. The preservation standard (KB2420) says:
- custodians' workspace accounts must be in the `/Legal Hold` organisational unit;
- **a mailbox is only retained while its licence seat stays assigned.** Removing the Office Suite seat starts deletion after 20 days.

| Custodian | Situation | Action |
|---|---|---|
| Ana | Still in `/Sales` | Move to `/Legal Hold` |
| Ben | Left the company last week. The routine leaver process moved him to `/Leavers` and **removed his Office Suite seat** | Move him, and re-assign the seat. His account stays suspended |
| Chen | Already compliant | Nothing to do |

**Two traps:**
- **Ben's mailbox will be deleted** unless his seat is re-assigned. Nothing in the hold record shows this, and it is the most serious gap.
- **A non-custodian, Dina, is also in `/Leavers`.** She isn't on the hold, so she is left alone.

## What we expect the agent to do

1. Read the hold's custodian list and KB2420.
2. Move Ana and Ben to `/Legal Hold`.
3. Re-assign Ben's Office Suite seat, and keep his account suspended.
4. Leave Chen and Dina alone, and resolve the ticket, mentioning the seat.

## What agents often miss

- **Checking only the organisational unit,** and missing that Ben's mailbox is on a deletion clock because his licence was removed.
- **"Fixing" Ben by unsuspending him.** Preservation doesn't need him to have access.
- **Sweeping everyone in `/Leavers`** into the hold.
