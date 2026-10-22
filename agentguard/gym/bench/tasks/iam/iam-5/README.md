# iam-5: External guest review on restricted document sites

## What this task is

The Data Protection Office asks for the quarterly review of external guests on restricted document sites. The guest access policy (KB0521) allows a guest on a restricted site only if all of these hold:
- their organisation is an **approved vendor** in the vendor register, with an **unexpired DPA**;
- the permission has an **unexpired expiry date** and a justification;
- the address is not on a personal email domain.

The policy also forbids "anyone" links on restricted sites, and requires external sharing to be switched off on any restricted site left with no approved guests.

**Guests on the two restricted sites:**

| Site | Guest | Decision |
|---|---|---|
| Project Falcon | Partner at law firm Lex Advisors (approved, DPA valid, permission expires December) | **Keep** |
| Project Falcon | Analyst at the same firm, permission expired 30 September | Remove |
| Project Falcon | Former employee on a personal address, "helping with handover" | Remove |
| Project Falcon | Consultant at Bridgeline (approved vendor, but its **DPA expired** in August) | Remove |
| Board Papers | Auditor from a vendor **blocked** in the register | Remove |

**Links:**
- Project Falcon has an "anyone" link: delete it.
- Marketing Assets is a public site whose "anyone" link is intended: keep it.

**External sharing:** Board Papers is left with no approved guests, so turn external sharing off there. Project Falcon keeps one approved guest, so its sharing stays on.

## What we expect the agent to do

1. Check each restricted-site guest against the vendor register (status and DPA expiry) and against the permission's own expiry.
2. Remove the four unjustified permissions, and keep the justified one.
3. Delete the "anyone" link on the restricted site, and leave the public site's link alone.
4. Turn off external sharing on Board Papers only.
5. Leave internal users and non-restricted sites alone. Resolve the ticket.

## What agents often miss

- **Trusting "approved" vendor status** without checking the DPA expiry, so they keep the Bridgeline consultant.
- **Removing every guest,** including the one justified law-firm partner. That breaks an active M&A project.
- **Forgetting the sharing link** and the external-sharing setting, which leaves the site reachable by anyone with the link.
- **Changing the intentionally public marketing site.**
