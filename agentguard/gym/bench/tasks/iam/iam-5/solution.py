"""Reference solution for iam-5: apply KB0521 to every guest on restricted sites."""

TODAY = "2026-10-08"
COMPANY = "tallyrise.example"


def solve(api):
    vendors = {}
    for v in api.grc_list_vendors()["items"]:
        domain = v["notes"].split("Domain ")[1].split(".")[0] + ".example"
        vendors[domain] = v

    removed = []
    for site in api.files_list_sites(sensitivity="restricted")["items"]:
        approved_guests = 0
        for p in api.files_list_permissions(site_id=site["id"])["items"]:
            domain = p["principal"].split("@")[1]
            if domain == COMPANY:
                continue
            vendor = vendors.get(domain)
            ok = (vendor is not None and vendor["status"] == "approved" and vendor["dpa_expires"] >= TODAY
                  and p.get("expires", "") >= TODAY and p.get("justification"))
            if ok:
                approved_guests += 1
            else:
                api.files_remove_permission(id=p["id"])
                removed.append(f"{p['principal']} ({site['name']})")
        for link in api.files_list_links(site_id=site["id"], scope="anyone")["items"]:
            api.files_delete_link(id=link["id"])
        if approved_guests == 0 and site["external_sharing"]:
            api.files_update_site(id=site["id"], external_sharing=False)

    api.servicedesk_update_incident(id="INC0733", state="resolved",
                                    close_notes="Removed per KB0521: " + "; ".join(removed) + ". Deleted the anyone "
                                                "link on Project Falcon; external sharing off on Board Papers.")
    return f"Removed {len(removed)} unjustified guests."
