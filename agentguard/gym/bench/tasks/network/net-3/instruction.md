# Service desk ticket INC1300 (security, P1)

**From:** SOC (day shift)

Last night's incident: workstations were talking to attacker command-and-control servers (IOCs are in this incident). The night shift started a firewall block, but we can still see traffic going out. Make sure outbound traffic to the C2 servers is actually blocked, then update this ticket.

## Tools

Call `search_operations` to discover the API operations available in each system, then use them to investigate and act.
