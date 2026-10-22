"""Reference solution for net-5: apply KB1360 rule by rule, honouring open risk acceptances."""

OFFICE = "203.0.113.0/26"


def solve(api):
    accepted = {f["title"].split("(")[1].split(")")[0] for f in api.grc_list_findings(status="open")["items"]
                if "(" in f["title"] and "accepted" in f["notes"].lower()}
    changed = []
    for r in api.cloudnet_list_sg_rules(cidr="0.0.0.0/0")["items"]:
        g = r["group_id"]
        if g == "sg-web-lb" and r["port"] in ("443", "80"):
            continue
        if g in accepted:
            continue
        if g == "sg-bastion" and r["port"] == "22":
            api.cloudnet_update_sg_rule(id=r["id"], cidr=OFFICE, description="SSH from office only (KB1360)")
            changed.append(f"{g}:22 narrowed to {OFFICE}")
            continue
        api.cloudnet_delete_sg_rule(id=r["id"])
        changed.append(f"{g}:{r['port']} removed")
    api.servicedesk_update_incident(id="INC1366", state="resolved",
                                    close_notes="Per KB1360: " + "; ".join(changed) + ". Kept sg-web-lb 443/80 and "
                                                "sg-api 8443 (risk accepted, FND-210).")
    return "; ".join(changed)
