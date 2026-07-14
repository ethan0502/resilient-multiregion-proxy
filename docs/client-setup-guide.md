# Client Setup Guide (for non-technical end users)

The live deployment ships each new client a small, self-contained installer folder plus a plain-language explanation of how the connection works and why it's safe to trust. This document is a genericized version of that explanation — the part meant to be read by someone with no networking background, not by an operator. (The actual installer bundle — a packaged client binary, a pre-filled profile, and a one-click PowerShell script — is deployment-specific and isn't included in this repo; what's reproduced here is the explanatory content itself, since writing it clearly for a non-technical audience was as much a part of this project as the systems work.)

## How it works — and why it is secure

Many conventional VPNs expose a recognizable traffic fingerprint. This deployment instead uses a camouflaged TLS proxy handshake designed to avoid presenting a stable VPN signature.

### The disguise

When a client connects to the proxy server, the initial exchange is designed to resemble an ordinary HTTPS visit to a well-known website. A network observer sees encrypted web-like traffic rather than a conventional VPN handshake or fixed protocol header. This reduces the observable fingerprint; it does not make blocking or detection impossible under every network condition.

The handshake uses a real public website as its camouflage target. An unauthenticated probe receives that site's ordinary TLS certificate, while a correctly configured client can complete the authenticated proxy handshake. The specific protocol fields remain in the generated client profile, but users do not need to configure them manually.

### Access uses cryptographic parameters, not a shared password

Access depends on server key material plus an allowlisted client identifier stored in the pre-filled profile. Capturing traffic does not reveal a reusable plaintext password, and an arbitrary client cannot use the proxy without the required profile parameters.

### Traffic is encrypted end-to-end

All data between the client and the proxy server is encrypted with TLS 1.3 — the same standard used by online banking. The proxy then forwards requests onward. A network observer sees only the encrypted outer shell; it cannot read what sites are being visited.

### Local-network sites bypass the proxy entirely

Traffic to domestic/local services is routed directly, without touching the proxy, so those services remain fast and unaffected — only traffic that actually needs the proxy goes through it.

## What "installation" looks like in practice

For a real client, the folder handed over contains: a one-click setup script, the client binary, a pre-filled connection profile (so there's nothing for the recipient to configure by hand), a routing database, and integrity checksums. The setup script installs the client, configures it to start automatically on login, enables full-traffic mode, and runs a connectivity test at the end — so the recipient gets a single pass/fail signal rather than having to interpret raw client logs.

## Design goal behind this document

The security properties above (camouflaged handshake, profile-based authentication, and encrypted transport) are the same regardless of audience, but the framing here is deliberately non-technical: no unnecessary protocol names, no assumption of networking background, and a troubleshooting section (omitted here, kept in the real deployment's copy) written entirely around "what did you observe" rather than "what did you configure." Writing this well mattered as much as the underlying design being correct — a proxy that's technically sound but that the intended recipient can't actually get running is not a solved problem.
