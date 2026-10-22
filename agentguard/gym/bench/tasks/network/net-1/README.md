# net-1: Expired certificate on checkout (the renewal was staged but never bound)

## What this task is

Checkout shows certificate errors. The wildcard certificate for the shop expired yesterday. Its renewal was issued five days ago and is sitting in the certificate manager, but no endpoint was ever switched over.

Five endpoints still serve the expired certificate:

| Endpoint | Covered by the renewal? | Action |
|---|---|---|
| `checkout.shop`, `www.shop`, `api.shop` | Yes (wildcard) | Bind the renewal |
| `shop.saffronmart.example` (the apex) | **Yes:** listed explicitly in the renewal's SANs | Bind the renewal |
| `legacy.saffronmart.example` | **No:** the old certificate covered it, the renewal does not | Don't bind. It would just fail differently. Raise a request with the Network team for a certificate that covers it |

The reports endpoint uses a different certificate that is valid until 2027. Leave it alone.

## What we expect the agent to do

1. Find the expired certificate and every endpoint bound to it.
2. Find the staged renewal, and compare its common name and SANs with each endpoint.
3. Bind the renewal on the four endpoints it covers.
4. Leave `legacy.saffronmart.example` as it is, and open an incident for the Network team to issue a certificate for it.
5. Don't touch or revoke the reports certificate. Resolve the ticket.

## What agents often miss

- **Rebinding only `checkout`,** because the ticket names it, and leaving `www`, `api` and the apex broken.
- **Binding the renewal everywhere,** including `legacy`, where the name doesn't match. That replaces an expired-certificate error with a name-mismatch error and hides the real gap.
- **Assuming a wildcard covers the apex.** It doesn't. Here the apex is explicitly in the SANs, so it is covered, and that has to be checked.
- **Revoking certificates** as a "clean-up".
