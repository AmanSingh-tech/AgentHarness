"""Reference solution for net-3: fix the typo, move the block above the broad allow, activate, add the 2nd IOC."""

import re


def solve(api):
    incident = api.servicedesk_get_incident(id="INC1300")
    iocs = re.findall(r"203\.0\.113\.\d+", incident["description"])
    allow = min(r["position"] for r in api.firewall_list_rules(action="allow", state="active")["items"]
                if r["destination"] == "any")
    night = next(r for r in api.firewall_list_rules(state="staged")["items"] if "INC1300" in r["name"])

    api.firewall_update_rule(id=night["id"], destination=iocs[0], position=allow - 3, comment="INC1300 C2 (fixed IP)")
    api.firewall_activate_rule(id=night["id"])
    for i, ip in enumerate(iocs[1:], start=1):
        rule = api.firewall_create_rule(name=f"Block C2 INC1300 #{i + 1}", position=allow - 3 + i, action="deny",
                                        source="any", destination=ip, port="any", comment="INC1300 C2")
        api.firewall_activate_rule(id=rule["id"])
    api.servicedesk_add_incident_note(
        id="INC1300", text=f"FR-95 had a typo (.71), was staged, and sat below FR-10 (allow any 443). Fixed: active deny "
                           f"rules for {', '.join(iocs)} at positions {allow - 3}-{allow - 3 + len(iocs) - 1}, before FR-10.")
    return "Both C2 addresses are now blocked by active rules ahead of the broad allow."
