# DPI-Evasion Hardening: Before vs. After

This log documents a single hardening pass applied to reduce the protocol- and traffic-level fingerprint a VLESS+REALITY deployment exposes to deep-packet inspection and active probing. All IPs, keys, and identifiers below are placeholders.

## Architecture: before vs. after

```mermaid
flowchart LR
    subgraph BEFORE["Before (single systemd service)"]
        direction TB
        C1[Client] -->|"non-standard port\nVLESS+REALITY\nweak SNI\ntrivial shortId\nno flow"| S1["xray.service\n(systemd)"]
        S1 -->|probe fallback| B1["borrowed cert origin"]
        S1 -->|direct| I1[Internet]
        L1["access.log\n(all connections logged)"] -.->|written by| S1
    end

    subgraph AFTER["After (isolated runtime, coexisting during migration)"]
        direction TB
        C2[Client\nnew] -->|"port 443\nVLESS+REALITY\nmainstream CDN SNI\nhigh-entropy shortId\nflow: xtls-rprx-vision"| D1["proxy backend\n(container)"]
        C3[Client\nlegacy] -->|"old port\n(unchanged, transition)"| S2["xray.service\n(systemd)"]
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
        O2["shortId: 2 hex chars\ntrivially guessable in 256 attempts"]
        O3["No flow control\nstatistically distinguishable from real TLS"]
        O4["Well-known REALITY target SNI\nacceptable but recognizable"]
        O5["access.log enabled\nfull connection record if host is imaged"]
    end

    subgraph NEW["New signal exposure"]
        N1["Port 443\nindistinguishable at network layer"]
        N2["5 random shortIds, 64-bit entropy each\nscanner must guess 1 of 5x2^64"]
        N3["xtls-rprx-vision\ninner TLS passthrough — byte-pattern matches real TLS"]
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
| SNI / dest | a well-known REALITY probe target | a mainstream CDN domain, TLS 1.3 | Avoids client-side warnings; blends into ordinary CDN traffic |
| Flow control | *(none)* | `xtls-rprx-vision` | Traffic byte-pattern matches real TLS |
| `shortId`s | 1 value, 2 hex chars | 5 values, 8 bytes each | Brute-force becomes infeasible |
| Access log | enabled | `none` | No connection record survives host seizure/imaging |
| Runtime | bare systemd process | pinned-image container, isolated | Rollback is "start the old process again" |
| Old port | active | kept alive during transition | Existing clients uninterrupted |

## Deployment sequence

```mermaid
timeline
    title Upgrade timeline
    section Preparation
        Audit completed : Non-standard port + trivial shortId identified as primary weaknesses
        Container runtime installed on host
    section Config build
        New config generated locally : new port, new shortIds, xtls-rprx-vision, logging disabled
        Config pushed to host
    section Port handover
        Conflicting service on the target port stopped and disabled
    section Container launch
        New backend started : SNI switched to mainstream CDN target
        Both old and new ports confirmed listening
    section Client migration
        Client profiles regenerated with the new flow/SNI/shortId
        Backups created before overwriting any profile
```

## Detection-surface summary

```mermaid
radar
    title Detection risk (lower = better)
    x-axis ["Port fingerprint", "ShortId brute-force", "Traffic pattern", "SNI reputation", "Log exposure", "Active probe"]
    Before [70, 95, 60, 30, 80, 20]
    After  [5,  2,  5,  10, 0,  20]
```

## Client link format (after)

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

Key diff from the pre-hardening format: `flow=xtls-rprx-vision` added, port switched to `443`, SNI switched to a mainstream CDN target, `shortId` switched from a 2-character value to one of five 8-byte random values.

## Remaining work at the time of this pass

- Confirm the new port works from at least one real client before retiring the old one
- Once all clients have migrated, remove the legacy inbound from the old runtime's config entirely
- Re-evaluate whether the old runtime should keep running at all, or be fully decommissioned
