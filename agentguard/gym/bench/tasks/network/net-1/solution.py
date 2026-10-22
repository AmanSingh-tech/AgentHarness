"""Reference solution for net-1: bind the staged renewal where its names cover the endpoint; raise the rest."""

TODAY = "2026-10-26"


def _covers(cert, host):
    for name in cert["sans"]:
        if name == host or (name.startswith("*.") and host.endswith(name[1:]) and host.count(".") == name.count(".")):
            return True
    return False


def solve(api):
    certs = api.certs_list_certificates()["items"]
    expired = [c for c in certs if c["not_after"][:10] < TODAY and c["status"] == "issued"]
    rebound, uncovered = [], []
    for old in expired:
        renewal = next(c for c in certs if c["common_name"] == old["common_name"] and c["not_after"] > old["not_after"])
        for b in api.certs_list_bindings(certificate_id=old["id"])["items"]:
            if _covers(renewal, b["endpoint"]):
                api.certs_bind_certificate(id=b["id"], certificate_id=renewal["id"])
                rebound.append(b["endpoint"])
            else:
                uncovered.append(b["endpoint"])
    for host in uncovered:
        api.servicedesk_create_incident(
            short_description=f"Certificate needed for {host}",
            description=f"{host} still serves the expired certificate; the renewal's names do not cover "
                        f"{host}. Please issue a certificate that covers it.",
            category="network", priority="2", assignment_group="GRP-NET")
    api.servicedesk_update_incident(
        id="INC1201", state="resolved",
        close_notes=f"Bound the renewed certificate on {', '.join(rebound)}. Not covered by the renewal: "
                    f"{', '.join(uncovered)} - raised with Network Engineering.")
    return f"Rebound {len(rebound)} endpoints; raised {uncovered}."
