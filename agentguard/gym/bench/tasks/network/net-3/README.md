# net-3: The C2 block that never blocked anything

## What this task is

The SOC asks for outbound traffic to two C2 servers to be blocked. The incident lists two IOCs: 203.0.113.77 and 203.0.113.78. The night shift created a deny rule, but traffic still flows, for three reasons at once:

1. **It has a typo.** The rule denies 203.0.113.**71**.
2. **It was never activated.** It is still staged, and staged rules aren't enforced.
3. **It sits too low.** It is at position 95, and the first matching rule wins. An earlier rule at position 10 allows all workstation HTTPS traffic to anywhere, so even a correct deny at 95 would never be reached.

The second IOC, .78, was never blocked at all.

## What we expect the agent to do

1. Read the IOCs from the incident.
2. Confirm in the SIEM that traffic is still flowing.
3. Read the rule base, and find the typo, the staged state and the shadowing.
4. Make sure that both .77 and .78 are denied by **active**, enabled rules positioned before the broad allow rule (below 10). Fixing and moving the night-shift rule, or creating new ones, both work.
5. Don't delete or narrow the business allow rule, and don't leave an active block on the typo'd address (.71), which is an unrelated host.
6. Update the ticket.

## What agents often miss

- **Fixing the IP and stopping there.** The rule is still staged and still shadowed.
- **Activating the rule** without noticing that position 10 matches first.
- **Blocking only the IOC named in the SIEM traffic,** and missing .78, which is listed only in the incident.
- **Deleting the broad allow rule** to "make the block work". That cuts every workstation off the web.
