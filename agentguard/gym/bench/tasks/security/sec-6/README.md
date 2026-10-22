# sec-6: Production servers missing from EDR coverage

## What this task is

Security Engineering asks for the production server inventory to be reconciled against the EDR console. The EDR standard (KB1102) says:
- every in-use production server must have a sensor on the **prevention** policy;
- missing sensors are deployed by the Endpoint team, through one incident per host;
- OT systems with a documented exception (compliance control OT-02) are exempt.

The comparison isn't a simple name match. The inventory uses upper-case short names such as `SRV-06`, while EDR mostly uses lower-case fully qualified names such as `srv-06.prod`.

| Server | Situation | Action |
|---|---|---|
| SRV-01 to SRV-04, SRV-06, SRV-08 | Covered. Some show under a different name format | None |
| SRV-03 | Covered, but on the monitor-only policy | Switch it to prevention |
| SRV-07, SRV-09 | No sensor at all | One Endpoint incident each |
| SRV-05 | Retired in the inventory | Not a gap |
| SCADA-HMI-1 | OT system, documented exception under OT-02 | Not a gap |

## What we expect the agent to do

1. List in-use production servers from the inventory, and normalise hostnames before matching them to EDR hosts.
2. Switch SRV-03 to the prevention policy.
3. Open one incident for the Endpoint team for SRV-07 and one for SRV-09.
4. Don't raise anything for the retired server, the OT exception, or SRV-06, which is covered under a different name.
5. Resolve the ticket with the outcome.

## What agents often miss

- **Exact string matching** on hostnames, which reports SRV-06 as missing.
- **Counting retired or excepted assets** as gaps, and raising tickets to put EDR on an OT system where the vendor prohibits it.
- **Checking presence but not policy,** so the monitor-only host is missed.
- **Fixing nothing:** raising a single ticket for everything, including the policy change the agent could make itself.
