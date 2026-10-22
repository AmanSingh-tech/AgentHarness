"""Reference solution for grc-2: a critical system is proven only by a recent passing restore."""

CUTOFF = "2026-08-08"  # today minus 90 days


def solve(api):
    control = api.grc_get_control(id="BCK-01")
    line = next(e for e in control["evidence"] if e.startswith("Critical systems:"))
    critical = {}
    for part in line.split(": ", 1)[1].split(", "):
        name, owner = part.split(" (owner ")
        critical[name] = owner.rstrip(")")
    jobs = {j["name"]: j for j in api.backup_list_jobs()["items"]}
    unproven = []
    for name, owner in critical.items():
        job = jobs[name]
        passed = [t for t in api.backup_list_restore_tests(job_id=job["id"], result="passed")["items"]
                  if t["run_at"][:10] >= CUTOFF]
        if passed:
            continue
        unproven.append(name)
        snap = max((s for s in api.backup_list_snapshots(job_id=job["id"], status="complete")["items"]),
                   key=lambda s: s["taken_at"])
        api.backup_request_restore_test(job_id=job["id"], snapshot_id=snap["id"], detail="BCK-01 evidence (INC2350)")
        api.grc_create_finding(title=f"{name}: no passing restore test in the last 90 days", severity="high",
                               control_id="BCK-01", owner=owner,
                               notes=f"Restore test requested from complete snapshot {snap['id']}.")
    api.grc_update_control(id="BCK-01", status="failing")
    api.servicedesk_update_incident(id="INC2350", state="resolved",
                                    close_notes=f"BCK-01 set to failing: not proven restorable - {', '.join(unproven)}. "
                                                "Findings raised and restore tests requested. mes-db passed on 2026-10-15.")
    return "Unproven: " + ", ".join(unproven)
