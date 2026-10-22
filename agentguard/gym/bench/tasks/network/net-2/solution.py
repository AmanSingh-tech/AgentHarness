"""Reference solution for net-2: check every A/CNAME target against the system that owns it."""

EDGE = ".edge.orion.example"


def solve(api):
    servers = {vs["name"] for vs in api.lb_list_virtual_servers()["items"]}
    public_ips = {i["public_ip"] for i in api.cloudnet_list_instances()["items"] if i.get("public_ip")}
    vendors = api.grc_list_vendors()["items"]

    def vendor_for(target):
        return next((v for v in vendors if target in v.get("notes", "")), None)

    removed = []
    for r in api.dns_list_records(zone="orion.example")["items"]:
        if r["type"] == "CNAME" and r["value"].endswith(EDGE):
            dangling = r["value"][: -len(EDGE)] not in servers
        elif r["type"] == "CNAME":
            v = vendor_for(r["value"])
            dangling = v is None or v["status"] != "approved" or "closed" in v["notes"]
        elif r["type"] == "A":
            dangling = r["value"] not in public_ips
        else:
            continue
        if dangling:
            api.dns_delete_record(id=r["id"])
            removed.append(f"{r['name']} ({r['type']} {r['value']})")
    api.servicedesk_update_incident(id="INC1240", state="resolved",
                                    close_notes="Removed dangling records: " + "; ".join(removed) + ".")
    return "Removed " + "; ".join(removed)
