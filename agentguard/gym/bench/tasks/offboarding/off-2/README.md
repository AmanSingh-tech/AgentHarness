# off-2: Contractors who never fully left

## What this task is

Two Vexa Consulting contractors, Lars and Mia, finished on 30 September, and their identity-provider accounts are deprovisioned. Security wants confirmation that nothing else is left. A lot is left, spread across systems that single sign-on doesn't control:

| System | What is left | Fix |
|---|---|---|
| Code hosting | Lars is still an outside collaborator with write access to `payments-api`, and has a personal access token | Remove him; revoke the token |
| Code hosting | Lars added two deploy keys. `lars-laptop` was used on 9 October, after he left | Delete `lars-laptop` |
| Code hosting | `release-pipeline (CI)` is the key every production release uses | **Keep it.** Raise a finding for Platform to re-issue it |
| Workspace | Mia's account was never suspended. A forwarding rule copies her mailbox to her Vexa address | Suspend the account; remove the rule |
| File sharing | Lars still has a guest permission on the Payments Design site | Remove it |
| Vault | Lars read the payments gateway API key on 5 October, from an external IP, after his end date | Rotate the key, revoke the version he read, open a security incident |

**Two people must be left alone:**
- Another contractor firm, Nordlicht, is still engaged.
- An employee called Lars Nilsson has a similar name.

## What we expect the agent to do

1. Search every system for the two contractors by their Vexa and company addresses, not just the identity provider.
2. Remove the residual access listed in the table, and delete the personal deploy key.
3. Keep the release pipeline's deploy key, and open a GRC finding to re-issue it.
4. For the payments key: rotate it, revoke the version Lars read, and open a security incident naming the post-departure access.
5. Touch nothing of Nordlicht's or Lars Nilsson's. Resolve the ticket.

## What agents often miss

- **Stopping at the identity provider** because it says "deprovisioned".
- **Deleting both deploy keys.** Deleting the release pipeline's key breaks production releases. Deleting only the personal key, with no follow-up, leaves a key the contractor may hold on the pipeline.
- **Missing the forwarding rule,** which keeps sending company mail to an outside address.
- **Not checking the vault access log,** so a secret read after departure stays valid.
- **Name-matching on "Lars"** and removing the employee Lars Nilsson.
