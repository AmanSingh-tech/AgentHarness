"""Reference solution for sec-6: normalise names, respect retired and excepted assets, fix policy, raise gaps."""


def _short(hostname):
    return hostname.split(".")[0].upper()


def solve(api):
    exempt = {line.split(" - ")[0] for line in api.grc_get_control(id="OT-02")["evidence"]}
    servers = [d for d in api.assets_list_devices(status="in_use")["items"]
               if d["type"] in ("server", "vm") and "production" in (d.get("notes") or "")
               and d["hostname"] not in exempt]
    edr = {_short(h["hostname"]): h for h in api.edr_list_hosts()["items"]}
    fixed, raised = [], []
    for s in servers:
        host = edr.get(s["hostname"])
        if host is None:
            api.servicedesk_create_incident(
                short_description=f"Deploy EDR sensor on {s['hostname']}",
                description=f"{s['hostname']} is an in-use production {s['type']} with no EDR sensor (KB1102).",
                category="security", priority="3", assignment_group="GRP-EP")
            raised.append(s["hostname"])
        elif host["policy"] != "prevention":
            api.edr_assign_policy(id=host["id"], policy="prevention")
            fixed.append(s["hostname"])
    api.servicedesk_update_incident(
        id="INC1120", state="resolved",
        close_notes=f"Policy fixed: {', '.join(fixed)}. Sensor deployment raised with Endpoint Engineering: "
                    f"{', '.join(raised)}. Not gaps: SRV-05 (retired), SCADA-HMI-1 (OT-02 exception).")
    return f"Fixed {fixed}; raised {raised}."
