#!/usr/bin/env python3
"""Compile a per-client routing policy file into Xray `routing.rules` and apply
it to a remote node over SSH.

Reads a JSON archive of clients (uuid, email, allow/block lists for domains
and IPs), builds Xray routing rules scoped per client via the `user` field,
fetches the node's live config, merges in the new routing block, and applies
it remotely with a timestamped backup + validate + restart.

Configure the target via environment variables (no defaults point at any real
host):

    VPN_ARCHIVE_PATH   path to the client policy JSON (default: ./users_archive.json)
    VPN_HOST           node hostname or IP (required)
    VPN_SSH_USER       SSH user (default: deploy)
    VPN_SSH_KEY        SSH private key path (default: ~/.ssh/id_rsa)
    VPN_CONFIG_PATH    remote Xray config path (default: /usr/local/etc/xray/config.json)
"""
import json
import os
import subprocess
import datetime

ARCHIVE_PATH = os.environ.get("VPN_ARCHIVE_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "users_archive.json"))
VPS_HOST = os.environ.get("VPN_HOST")
VPS_USER = os.environ.get("VPN_SSH_USER", "deploy")
SSH_KEY = os.environ.get("VPN_SSH_KEY", "~/.ssh/id_rsa")
CONFIG_PATH = os.environ.get("VPN_CONFIG_PATH", "/usr/local/etc/xray/config.json")
TMP_LOCAL_CONFIG = "/tmp/xray_new_config.json"
TMP_REMOTE_CONFIG = "/tmp/config.json"


def run(cmd):
    res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if res.returncode != 0:
        print(f"Error running command: {cmd}")
        print(res.stderr)
        exit(1)
    return res


def fetch_current_config():
    print(f"Fetching current config from {VPS_HOST}...")
    cmd = f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no {VPS_USER}@{VPS_HOST} 'cat {CONFIG_PATH}'"
    res = run(cmd)
    return json.loads(res.stdout)


def build_routing_rules(archive_data):
    rules = []

    for user in archive_data.get('users', []):
        email = user.get('email')
        if not email:
            continue

        allowed_domains = user.get('allowed_domains', [])
        allowed_ips = user.get('allowed_ips', [])
        blocked_domains = user.get('blocked_domains', [])
        blocked_ips = user.get('blocked_ips', [])

        has_allow_list = bool(allowed_domains or allowed_ips)

        # 1. Allow rules (Whitelist)
        if allowed_domains:
            rules.append({
                "type": "field",
                "user": [email],
                "domain": allowed_domains,
                "outboundTag": "direct"
            })

        if allowed_ips:
            rules.append({
                "type": "field",
                "user": [email],
                "ip": allowed_ips,
                "outboundTag": "direct"
            })

        # 2. Block rules (Blacklist or default deny if whitelist exists)
        if has_allow_list:
            rules.append({
                "type": "field",
                "user": [email],
                "outboundTag": "block"
            })
        else:
            if blocked_domains:
                rules.append({
                    "type": "field",
                    "user": [email],
                    "domain": blocked_domains,
                    "outboundTag": "block"
                })
            if blocked_ips:
                rules.append({
                    "type": "field",
                    "user": [email],
                    "ip": blocked_ips,
                    "outboundTag": "block"
                })

    return rules


def main():
    if not VPS_HOST:
        print("VPN_HOST environment variable is required (node hostname or IP).")
        exit(1)

    if not os.path.exists(ARCHIVE_PATH):
        print(f"Archive file not found: {ARCHIVE_PATH}")
        exit(1)

    with open(ARCHIVE_PATH, 'r') as f:
        archive_data = json.load(f)

    config = fetch_current_config()

    new_rules = build_routing_rules(archive_data)

    if new_rules:
        config['routing'] = {
            "domainStrategy": "AsIs",
            "rules": new_rules
        }
        print(f"Generated {len(new_rules)} routing rule(s).")
    else:
        if 'routing' in config:
            del config['routing']
        print("No routing rules found. Clearing routing config.")

    with open(TMP_LOCAL_CONFIG, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"Uploading new config to {VPS_HOST}...")
    run(f"scp -i {SSH_KEY} -o StrictHostKeyChecking=no {TMP_LOCAL_CONFIG} {VPS_USER}@{VPS_HOST}:{TMP_REMOTE_CONFIG}")

    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

    print("Applying config and restarting Xray...")
    apply_script = f"""#!/bin/bash
set -e
CFG="{CONFIG_PATH}"
sudo -n cp "\\$CFG" "\\$CFG.bak.{ts}"
sudo -n cp {TMP_REMOTE_CONFIG} "\\$CFG"
sudo -n /usr/local/bin/xray -test -config "\\$CFG" >/dev/null
sudo -n /bin/systemctl restart xray
"""

    with open('/tmp/apply_xray.sh', 'w') as f:
        f.write(apply_script)

    run(f"scp -i {SSH_KEY} -o StrictHostKeyChecking=no /tmp/apply_xray.sh {VPS_USER}@{VPS_HOST}:/tmp/apply_xray.sh")
    run(f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no {VPS_USER}@{VPS_HOST} 'bash /tmp/apply_xray.sh'")

    print("Success! Routing rules from the archive have been applied to the node.")


if __name__ == "__main__":
    main()
