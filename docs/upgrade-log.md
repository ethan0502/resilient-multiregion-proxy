# Traffic-Fingerprint Hardening: Before vs. After

This log documents a single hardening pass applied to reduce the protocol- and traffic-level fingerprint a camouflaged TLS proxy exposes to deep-packet inspection and active probing. All IPs, keys, and identifiers below are placeholders.

## Architecture: before vs. after

```mermaid
flowchart LR
    subgraph BEFORE["Before (single systemd service)"]
        direction TB
        C1[Client] -->|"non-standard port\nweak camouflage target\ntrivial handshake ID\nno traffic shaping"| S1["legacy server\n(systemd)"]
        S1 -->|probe fallback| B1["borrowed cert origin"]
        S1 -->|direct| I1[Internet]
        L1["access.log\n(all connections logged)"] -.->|written by| S1
    end

    subgraph AFTER["After (isolated runtime, coexisting during migration)"]
        direction TB
        C2[Client\nnew] -->|"port 443\nmainstream CDN target\nhigh-entropy handshake IDs\ntraffic shaping enabled"| D1["proxy backend\n(container)"]
        C3[Client\nlegacy] -->|"old port\n(unchanged, transition)"| S2["legacy server\n(systemd)"]
        D1 -->|probe fallback| B2["mainstream CDN origin"]
        D1 -->|direct| I2[Internet]
        D1 -.->|"log: none"| X1["no log"]
    end
```

## Traffic camouflage: before vs. after

```mermaid
flowchart TD
    subgraph CENSOR["Network-level observer"]
        P1["Passive DPI\n(packet inspection)"]
        P2["Active probe\n(port scan + TLS handshake)"]
        P3["IP reputation\n(datacenter range check)"]
    end

    subgraph OLD["Old signal exposure"]
        O1["Non-standard port\nflags for deeper inspection"]
        O2["Handshake ID: 2 hex chars\ntrivially guessable in 256 attempts"]
        O3["No flow control\nstatistically distinguishable from real TLS"]
        O4["Well-known camouflage target\nacceptable but recognizable"]
        O5["access.log enabled\nfull connection record if host is imaged"]
    end

    subgraph NEW["New signal exposure"]
        N1["Port 443\nindistinguishable at network layer"]
        N2["5 random handshake IDs, 64-bit entropy each\nscanner must guess 1 of 5x2^64"]
        N3["Traffic shaping enabled\ninner TLS passthrough matches ordinary TLS patterns"]
        N4["Mainstream CDN SNI, TLS 1.3\nno client-side warning"]
        N5["access.log = none\nzero connection records"]
    end

    P1 --> O3
    P2 --> O2
    P1 --> O1
    P3 --> O4
    P1 --> N3
    P2 --> N2
    P1 --> N1
```

## Settings comparison

| Parameter | Before | After | Impact |
|---|---|---|---|
| Listening port | non-standard | `443` | Removes the non-standard-port signal |
| Camouflage target | a well-known probe target | a mainstream CDN domain, TLS 1.3 | Avoids client-side warnings; blends into ordinary CDN traffic |
| Traffic shaping | *(none)* | enabled | Traffic byte-pattern matches ordinary TLS |
| Handshake IDs | 1 value, 2 hex chars | 5 values, 8 bytes each | Brute-force becomes infeasible |
| Access log | enabled | `none` | No connection record survives host seizure/imaging |
| Runtime | bare systemd process | pinned-image container, isolated | Rollback is "start the old process again" |
| Old port | active | kept alive during transition | Existing clients uninterrupted |

## Deployment sequence

```mermaid
timeline
    title Upgrade timeline
    section Preparation
        Audit completed : Non-standard port + trivial handshake ID identified as primary weaknesses
        Container runtime installed on host
    section Config build
        New config generated locally : new port, high-entropy IDs, traffic shaping, logging disabled
        Config pushed to host
    section Port handover
        Conflicting service on the target port stopped and disabled
    section Container launch
        New backend started : SNI switched to mainstream CDN target
        Both old and new ports confirmed listening
    section Client migration
        Client profiles regenerated with the new traffic-shaping and handshake parameters
        Backups created before overwriting any profile
```

## Detection-surface summary

```mermaid
radar
    title Detection risk (lower = better)
    x-axis ["Port fingerprint", "Handshake-ID brute-force", "Traffic pattern", "SNI reputation", "Log exposure", "Active probe"]
    Before [70, 95, 60, 30, 80, 20]
    After  [5,  2,  5,  10, 0,  20]
```

## Protocol-specific client link format (literal compatibility example)

```
vless://<CLIENT_UUID>@<HOST>:443
  ?encryption=none
  &security=reality
  &sni=<MAINSTREAM_CDN_SNI>
  &fp=chrome
  &pbk=<REALITY_PUBLIC_KEY>
  &sid=<SHORT_ID>
  &type=tcp
  &flow=xtls-rprx-vision
  #<name>
```

The machine-readable link necessarily keeps the implementation's literal field names. The meaningful changes were: traffic shaping enabled, port switched to `443`, camouflage target switched to a mainstream CDN, and the handshake identifier changed from a 2-character value to one of five 8-byte random values.

## Remaining work at the time of this pass

- Confirm the new port works from at least one real client before retiring the old one
- Once all clients have migrated, remove the legacy inbound from the old runtime's config entirely
- Re-evaluate whether the old runtime should keep running at all, or be fully decommissioned
