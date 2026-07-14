# Architecture

This document describes each node's runtime shape, why the runtimes are not interchangeable, and the production incident that motivated hardening the front-door process supervision. All IPs are placeholders (`203.0.113.0/24`, an RFC 5737 documentation range); all keys, UUIDs, and `shortId`s are placeholders.

## Node inventory

| Node | Public `443` front door | Backend supervision | Notable constraint |
|---|---|---|---|
| **Node A** (Tokyo) | nginx `stream` module, TCP passthrough, blue-green | Docker containers `xray-a` / `xray-b` | — |
| **Node B** (Malaysia) | HAProxy, TCP passthrough, blue-green | systemd units `xray-a.service` / `xray-b.service` | Plesk-managed box; bundled nginx build has no compatible stream module in its enabled repos, so HAProxy owns 443 instead |
| **Node C** (Japan) | nginx `stream` module (via `podman`-wrapped systemd units), TCP passthrough, blue-green | systemd units wrapping `podman run`, not bare containers | SELinux disabled on this host — no booleans/port-labels needed, unlike a hardened default install |

Every node is generated from the same config shape: one `vless` inbound, `network: tcp`, `security: reality`, `decryption: none`, client `flow: xtls-rprx-vision`, no top-level `routing` block by default. Two backend processes per node are produced from a single source-of-truth config file by a small generator script that copies everything **except** the listen port — so the two backends can never drift apart on REALITY keys, client lists, or `shortId`s.

### Node A also carries a legacy runtime

Node A additionally runs an older systemd-managed Xray instance on a non-standard port, kept alive during the migration to the Docker/blue-green runtime so existing clients weren't force-migrated. The two runtimes are **not the same source of truth** — different config file, different client list, different REALITY values — and the CLI tooling in this repo only ever targets the systemd-managed one. This distinction (which config is actually live, and which tool actually manages which config) had to be documented explicitly and re-verified repeatedly, because assuming they matched was the direct cause of at least one client-visible outage.

## The OOM / respawn-loop / logrotate incident (Node B)

A few days after Node B's blue-green front door went live, its proxy backend was found in a failed state with the legacy web server bound to `:443` instead. The naive read — "config drifted, redeploy" — was wrong. The actual causal chain, reconstructed from `systemctl status`, journal timestamps, and the unit file's own restart policy:

1. The kernel OOM killer selected the running Xray backend process under memory pressure and killed it.
2. The host's legacy web server (Apache/Plesk stack) had a drop-in override giving it `Restart=on-failure`. With `:443` suddenly free, its pending restart won the race and bound the port.
3. Xray's own restart attempts then failed with `bind: address already in use`; after several rapid failures, systemd gave up with "start request repeated too quickly."
4. Separately — and this is the part that made the first fix (`systemctl stop httpd`) not stick — the host's control-panel logrotate hook independently called into the panel's own Apache-management binary on its daily run, which could restart Apache *even while its systemd unit was disabled*. A closed-source panel binary reasserting state outside the normal `systemctl enable/disable` lifecycle is not something `systemctl stop` or `disable` alone defends against.

**Root cause, in one line:** memory pressure killed the proxy first; a legacy service's own respawn policy reclaimed the port before the proxy's restart could; and a control-panel hook was capable of undoing any purely-declarative fix to that legacy service.

**Fix that actually held:** `systemctl mask` on the legacy service, not just `stop`/`disable` — a mask is a hard block that the panel's internal restart calls cannot override, regardless of what that closed-source binary tries internally. This was verified directly: attempting to start or reload the masked unit fails with "Unit is masked," including via the panel's own reload path.

Independent re-verification (a second session, days later, checking every claim above from scratch) confirmed the fix held: no config drift, the mask still blocking every attempted revival path, and the blue-green mechanics behaving exactly as designed under both a live flip and a live incident.

## Cross-region relay chaining

One node's own upstream peering to a specific destination network is poor — confirmed by isolating the proxy stack entirely and measuring raw, VPN-free transfer throughput over the identical path, which reproduced the same slow number, proving the bottleneck was the network path itself and not the proxy stack. A different node happens to have excellent peering *to* that same destination. Rather than accept the slow direct path, a two-hop relay was built: a client connects to the well-peered node's dedicated relay-only inbound (its own REALITY keypair, separate from normal client traffic), which re-encapsulates the connection as a raw TCP client of the target node's egress-only fast path, exiting as the target node's IP.

This was root-caused before being built, not assumed:

- `traceroute` from the client network showed both candidate paths sharing the same upstream backbone for the first several hops, then diverging onto differently-peered transit for the final leg.
- Raw, non-proxied throughput tests (plain file transfer, no VPN/TLS stack at all) between the candidate relay node and the target node confirmed the relay leg itself was many times faster than the direct client-to-target path.
- The relay's own client credential is provisioned separately from normal end-user clients (distinct UUID, distinct label) so it can be revoked independently if the relay is ever decommissioned.

The result matched the goal (correct exit IP, meaningfully better throughput on the bottlenecked leg) without over-claiming: end-to-end client-side throughput was still bounded by the client's own path to the *entry* node, which the relay does not change. Distinguishing "this specific hop got faster" from "the client's overall experience got faster" mattered for setting the right expectation after deployment.
