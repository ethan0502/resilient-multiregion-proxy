# Zero-Downtime Blue-Green Refresh

This document describes the deployment mechanism used to periodically refresh each node's proxy backend without dropping the public listener or disrupting live sessions. All IPs and identifiers below are placeholders.

## Motivation

A single long-lived proxy process accumulates session state over time, and in practice this deployment saw upload throughput measurably degrade the longer a single process had been running. The degradation was confirmed reproducible, not a one-off: after normal use, a bare `restart` of the process alone — no config or sysctl changes — reliably restored upload back to the node's tuned baseline (a fixed-payload client test that had read ~524 KB/s right after the original network tuning pass). That single observation is what motivated blue-green in the first place: a naive periodic restart (cron job, `systemctl restart`) would fix the degradation but drops every live session on the host simultaneously, which is exactly the client-visible disruption this design avoids — blue-green gets the same "always a recently-restarted process" property without ever taking the public listener down. See [`benchmarks/`](../benchmarks/README.md) for later multi-node throughput data collected once this design was already live (a different test methodology — larger payload, all nodes in one run — so treat the two data points as separate evidence, not a single before/after pair).

## Target design

```text
public <host>:443
  -> TCP front door (nginx stream / HAProxy — TCP passthrough, no TLS termination)
      -> backend-a on 127.0.0.1:1443   (active)
      -> backend-b on 127.0.0.1:2443   (draining standby)
```

This is blue-green, not load balancing. The front door's upstream has one backend marked active and the other marked `backup`:

- All new connections go to the active backend.
- The standby receives new connections only on active-backend failure — automatic failover, itself a reliability win independent of the refresh mechanism.
- Draining is inherent: after a flip, the old primary receives no new sessions and empties on its own via the proxy's built-in idle-connection timeout (short enough — a few minutes — that a parked backend converges to empty well before the next flip).

Why not `least_conn` / round-robin dual-active: both backends would accumulate session pressure simultaneously — the exact problem being solved — and every refresh would kill half of all long-lived sessions after only a short drain. Blue-green instead gives each backend a full drain window and keeps the actively-serving process always recently restarted.

Both backend processes share the same client-facing identity — same client list, same REALITY key pair, same SNI, same `shortId`s, same flow setting — generated from a single source-of-truth config so they cannot drift apart. Only the backend listen port differs. Client profiles keep using the public host and port unchanged; the flip is entirely server-side.

## Front-door settings that decide client-visible behavior

TCP passthrough front doors default to values tuned for short-lived HTTP connections, not long-lived proxy sessions — left at defaults, the front door itself would introduce disconnects that don't exist today.

```nginx
stream {
    include /etc/nginx/stream.d/active-upstream.conf;

    server {
        listen 443 so_keepalive=5m:75s:6;
        proxy_pass backend_pool;
        proxy_connect_timeout 5s;
        proxy_timeout 1h;
    }
}
```

Upstream variants — a flip is a symlink swap, not a config edit:

```nginx
# upstream-a-primary.conf
upstream backend_pool { server 127.0.0.1:1443; server 127.0.0.1:2443 backup; }

# upstream-b-primary.conf
upstream backend_pool { server 127.0.0.1:2443; server 127.0.0.1:1443 backup; }
```

Rationale for each setting:

- **`proxy_timeout 1h`** — the stream module's default idle timeout is far shorter than that; left at default, the front door would cut idle-but-legitimate sessions that survive today. This is an idle timeout between successive reads/writes, so active transfers are never affected — it sits as a backstop above the proxy's own (much shorter) idle-connection timeout, which normally closes truly-idle sessions first.
- **`proxy_connect_timeout 5s`** — fail fast, so a dead backend costs a client at most a few seconds before automatic retry.
- **`so_keepalive`** — TCP keepalive toward clients reaps dead connections (client rebooted, network changed) in minutes instead of never, attacking the session-accumulation problem directly rather than only working around it with scheduled flips.
- **`proxy_next_upstream`** (on by default in the stream module) — if a connect to the active backend fails mid-restart, the front door transparently retries the standby. Left on.
- **Do not set a worker/reload shutdown timeout.** On reload, old worker generations keep serving established connections until they close naturally; a shutdown timeout would kill draining sessions on every single flip and defeat the entire design.
- TCP passthrough only, always — the front door never terminates TLS or REALITY. (An optional future step is enabling `PROXY protocol` to restore real client IPs in proxy-side logs; deliberately left off in this design since it must be enabled on both sides simultaneously and adds nothing client-visible.)

## Liveness probe

Used throughout deployment and the daily flip: an unauthorized TLS client is forwarded by REALITY to the borrowed origin, so a plain probe against a backend must return that origin's real certificate.

```bash
openssl s_client -connect 127.0.0.1:1443 -servername <CDN_SNI> -tls1_3 </dev/null 2>/dev/null \
  | openssl x509 -noout -subject
# expect: subject includes the borrowed CDN domain
```

The same probe runs against the standby's port before every flip, and against the public host:443 after every flip, as the final confirmation.

## Daily flip routine

At a fixed low-traffic hour, with backend A active and backend B the standby that has been draining since the previous flip:

1. **Drain gate** — check established-connection count on the standby's port; expect ~0. Anything still present has been continuously active since before the last flip and is the only traffic the flip can drop.
2. **Restart the standby** (not the active backend). Failover coverage is briefly absent for the few seconds this takes, at the lowest-traffic hour deliberately.
3. **Verify the standby** — listener present, liveness probe returns the borrowed certificate. **Never flip to an unverified backend** — this check is not optional and is not skipped even when previous flips have been reliable.
4. **Flip** — repoint the upstream symlink to the newly-verified backend, validate the front door's config syntax, then reload (never a hard restart, so existing connections on the previous config generation keep draining).
5. The old active backend is now the draining standby until the next cycle. Its established sessions are untouched — the reload keeps the old worker generation alive purely to finish serving them.

The next cycle runs the mirror image with roles swapped. In production this ran manually for the first several days to build confidence, then was wrapped into a script (drain gate → restart → probe → symlink swap → config test → reload, aborting immediately on any failure) driven by cron.

## Refresh frequency

One flip per day at low-traffic time is the steady-state cadence — each backend serves at most 24 hours of traffic before resting/draining for 24 hours, so the actively-serving process is never more than a day old. This was tuned empirically after initial deployment: if throughput degradation reappears within a day, flip more often (down to a 12-hour floor); if throughput stays stable for a week, relaxing the cadence is safe. Flipping much faster than the drain window shrinks the drain time below what's needed and starts dropping ordinary, non-abandoned sessions — 12 hours is treated as a hard floor outside of emergencies.

## Expected interruption

- **One-time cutover** (switching from a single bare process to the front-door architecture): a one-to-two-second gap on the public port; all live sessions drop once; clients reconnect automatically.
- **Steady state**: the public port never stops listening. A flip can drop only sessions that survived the *entire* drain window continuously — i.e., were active the whole time, since the idle timeout reaps everything else. In practice this is close to zero sessions.
- **Bonus failure mode removed**: if the active backend crashes between scheduled flips, the front door sends new connections to the standby automatically instead of going dark.
- This design improves *maintenance-induced* disruption specifically. It does not fix upstream provider congestion, noisy-neighbor effects, or peering-quality problems, because both backends still share the same host and the same network path.

## Rollback plan

If the front door ever breaks client connectivity outright:

1. Remove (or comment out) the front door's `stream {}` listener and reload — the front door keeps serving whatever else it was already serving (e.g. plain HTTP).
2. Stop both blue-green backends.
3. Start the original single-process runtime again with the last-known-good backed-up config — it was stopped, never removed, specifically to remain a valid rollback target.
4. Confirm the original runtime now owns the public port.
5. Re-run end-to-end client validation against the restored path.

The original config backup and the stopped legacy runtime are kept intact until the new front-door design has been stable in production for several days — deleting the rollback path early was treated as a real risk, not just tidiness.
