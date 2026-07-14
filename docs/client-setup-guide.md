# Client Setup Guide (for non-technical end users)

The live deployment ships each new client a small, self-contained installer folder plus a plain-language explanation of how the connection works and why it's safe to trust. This document is a genericized version of that explanation — the part meant to be read by someone with no networking background, not by an operator. (The actual installer bundle — a packaged client binary, a pre-filled profile, and a one-click PowerShell script — is deployment-specific and isn't included in this repo; what's reproduced here is the explanatory content itself, since writing it clearly for a non-technical audience was as much a part of this project as the systems work.)

## How it works — and why it is secure

Most VPNs are easy for censors to detect because their traffic has a distinctive fingerprint. This deployment uses a different approach called **VLESS + REALITY**, specifically designed to be undetectable.

### The disguise

When a client connects to the proxy server, the connection looks — to any observer on the network — exactly like an ordinary HTTPS visit to a well-known website. A network-level censor sees normal, legitimate encrypted web traffic and has no grounds to block it. There is no VPN handshake, no distinctive header, nothing to flag.

This works because REALITY "borrows" the TLS certificate of a real public website. The server presents that certificate during the handshake, making the connection genuinely indistinguishable from a real visit to that site. Only a client holding the correct private key can tell the difference and proceed to use it as a proxy.

### The credential is a key pair, not a password

Access is controlled by a pair of cryptographic keys — a public key on the server, a private key baked into the client's profile. Even if every packet is intercepted, nothing can connect to the proxy without the matching private key. There is no password to guess or brute-force.

### Traffic is encrypted end-to-end

All data between the client and the proxy server is encrypted with TLS 1.3 — the same standard used by online banking. The proxy then forwards requests onward. A network observer sees only the encrypted outer shell; it cannot read what sites are being visited.

### Local-network sites bypass the proxy entirely

Traffic to domestic/local services is routed directly, without touching the proxy, so those services remain fast and unaffected — only traffic that actually needs the proxy goes through it.

## What "installation" looks like in practice

For a real client, the folder handed over contains: a one-click setup script, the client binary, a pre-filled connection profile (so there's nothing for the recipient to configure by hand), a routing database, and integrity checksums. The setup script installs the client, configures it to start automatically on login, enables full-traffic mode, and runs a connectivity test at the end — so the recipient gets a single pass/fail signal rather than having to interpret raw client logs.

## Design goal behind this document

The security properties above (undetectable handshake, key-pair-only auth, end-to-end encryption) are the same regardless of audience, but the framing here is deliberately non-technical: no protocol names beyond the one the client sees on screen, no assumption of networking background, and a troubleshooting section (omitted here, kept in the real deployment's copy) written entirely around "what did you observe" rather than "what did you configure." Writing this well mattered as much as the underlying design being correct — a proxy that's technically sound but that the intended recipient can't actually get running is not a solved problem.
