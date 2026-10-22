"""Reference solution for chg-4: the regression starts with checkout v4.2.0 - roll back, degrade, fail the change."""


def solve(api):
    failing = next(c for c in api.monitoring_list_checks(status="failing")["items"])
    service = api.monitoring_get_service(id=failing["service_id"])
    deploys = sorted(api.monitoring_list_deploys(service_id=service["id"])["items"], key=lambda d: d["deployed_at"])
    bad = deploys[-1]
    good = deploys[-2]
    api.monitoring_deploy_version(service_id=service["id"], version=good["version"],
                                  notes=f"Rollback of {bad['version']} (coupon regression since 08:03)")
    api.monitoring_update_service(id=service["id"], status_page="degraded")
    api.servicedesk_update_change(id=bad["change_id"], state="failed")
    api.servicedesk_update_incident(id="INC2210", state="in_progress")
    api.servicedesk_add_incident_note(
        id="INC2210", text=f"Cause: {service['name']} {bad['version']} ({bad['change_id']}) - coupon apply errors 64% "
                           f"from 08:03, one minute after the deploy. Rolled back to {good['version']}; status page "
                           "degraded until the synthetic coupon check passes.")
    return f"Rolled {service['name']} back to {good['version']}; keeping the incident open until verified."
