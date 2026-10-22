"""Reference solution for sec-4: reconnect the clean server, then finish the real malware response."""

UPDATER = "6b1f0c4e2d9a7f3b8e5c1a0d4f7e2b9c3a6d8e1f0b2c4d6e8f0a1b3c5d7e9f1a"
LOADER = "e3a9d1c7b5f2048e6a1c3d5f7b9e0a2c4e6f8a1b3d5c7e9f0a2b4c6d8e0f1a3c"


def solve(api):
    intake = api.edr_search_hosts(query="ORD-INTAKE-02")["items"][0]
    detection = api.edr_list_detections(host_id=intake["id"])["items"][0]
    assert "signed by EdiBridge" in detection["notes"] and detection["sha256"] == UPDATER

    # 1) the clean server: reconnect, close the false positive
    api.edr_lift_containment(id=intake["id"])
    api.edr_update_detection(id=detection["id"], verdict="false_positive", status="closed")
    api.edr_add_detection_note(id=detection["id"], text="Vendor-signed EdiBridge updater; same hash ran on ORD-INTAKE-01.")
    alert = api.siem_list_alerts(entity="ORD-INTAKE-02")["items"][0]
    api.siem_update_alert(id=alert["id"], status="closed", classification="false_positive")

    # 2) the real loader: every host with the file, whether or not it has a detection
    infected = {f["host_id"]: f for f in api.edr_list_files(sha256=LOADER)["items"]}
    for host_id, f in infected.items():
        api.edr_contain_host(id=host_id)
        api.edr_quarantine_file(id=f["id"])
        if api.edr_get_host(id=host_id)["policy"] != "prevention":
            api.edr_assign_policy(id=host_id, policy="prevention")
    for d in api.edr_list_detections(sha256=LOADER)["items"]:
        api.edr_update_detection(id=d["id"], verdict="true_positive", status="closed")
    api.edr_add_to_blocklist(sha256=LOADER, description="svchelper.exe loader (INC0308)")
    bad = next(e for e in api.edr_list_exclusions(created_by="svc-deploy")["items"] if "SvcCache" in e["value"])
    api.edr_delete_exclusion(id=bad["id"])

    hosts = sorted(api.edr_get_host(id=h)["hostname"] for h in infected)
    api.servicedesk_add_incident_note(
        id="INC0308", text=f"ORD-INTAKE-02 was a false positive (signed EdiBridge updater) and is reconnected. Real "
                           f"intrusion: loader {LOADER[:12]} on {', '.join(hosts)} - contained, quarantined, hash "
                           f"blocklisted, malicious exclusion EXC-14 (svc-deploy from 198.51.100.23) removed.")
    api.servicedesk_update_incident(id="INC0310", state="resolved",
                                    close_notes="ORD-INTAKE-02 reconnected: its detection was the vendor updater.")
    return "ORD-INTAKE-02 reconnected; real malware on " + ", ".join(hosts) + " contained and cleaned up."
