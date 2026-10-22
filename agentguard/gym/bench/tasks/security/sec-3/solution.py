"""Reference solution for sec-3: scope decides - authorised tests on rt-scope hosts, a real incident elsewhere."""


def solve(api):
    change = api.servicedesk_search_changes(query="red team exercise")["items"][0]
    assert change["approval"] == "approved" and "rt-scope" in change["description"]
    real = []
    for d in api.edr_list_detections(status="new")["items"]:
        host = api.edr_get_host(id=d["host_id"])
        alert = api.siem_list_alerts(entity=host["hostname"])["items"][0]
        if "rt-scope" in host["tags"]:
            api.edr_update_detection(id=d["id"], verdict="authorized_test", status="closed")
            api.siem_add_alert_note(id=alert["id"], text=f"Authorised red-team activity under {change['id']}.")
            api.siem_update_alert(id=alert["id"], status="closed", classification="benign_positive")
        else:
            api.edr_update_detection(id=d["id"], verdict="true_positive", status="in_progress")
            api.edr_contain_host(id=host["id"])
            api.siem_update_alert(id=alert["id"], status="investigating", classification="true_positive")
            real.append(host["hostname"])
    for hostname in real:
        api.servicedesk_create_incident(
            short_description=f"Credential dumping on {hostname} - outside red-team scope",
            description=f"{hostname} is not tagged rt-scope, so the credential-access tooling seen there is outside "
                        f"{change['id']} and treated as a real incident. Host contained; tooling hash not blocklisted "
                        "per the rules of engagement. Red team lead Karan Malhotra informed.",
            category="security", priority="1", assignment_group="GRP-SEC")
        api.servicedesk_add_change_note(id=change["id"], text=f"SOC: activity on {hostname} (out of scope) is being "
                                        "handled as a real incident - Karan, please confirm whether it was yours.")
    return "In-scope detections closed as authorised tests; " + ", ".join(real) + " contained as a real incident."
