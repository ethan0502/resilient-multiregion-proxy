#!/usr/bin/env python3
"""Add/list/remove VLESS+REALITY clients on a remote Xray node over SSH.

Example:
    python3 vpn_user_manager.py --host vpn.example.com --user deploy list
    python3 vpn_user_manager.py --host vpn.example.com --user deploy create
    python3 vpn_user_manager.py --host vpn.example.com --user deploy remove --uuid <UUID>
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import urllib.parse
import uuid as uuidlib
from datetime import datetime


def run(cmd, check=True, capture=True):
    return subprocess.run(
        cmd,
        shell=True,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def q(s):
    return shlex.quote(s)


class VPNManager:
    def __init__(self, host, user, key_path, config_path):
        self.host = host
        self.user = user
        self.key_path = os.path.expanduser(key_path)
        self.config_path = config_path

    def ssh(self, remote_cmd, check=True):
        cmd = (
            f"ssh -i {q(self.key_path)} -o BatchMode=yes -o StrictHostKeyChecking=no "
            f"{q(self.user)}@{q(self.host)} {q(remote_cmd)}"
        )
        return run(cmd, check=check, capture=True)

    def get_config(self):
        out = self.ssh(f"cat {q(self.config_path)}").stdout
        return json.loads(out)

    def list_users(self):
        cfg = self.get_config()
        users = cfg["inbounds"][0]["settings"].get("clients", [])
        rows = []
        for i, c in enumerate(users, 1):
            rows.append({"index": i, "id": c.get("id", ""), "email": c.get("email", "")})
        return rows

    def add_user(self, user_uuid, email):
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        remote = (
            "set -e;"
            f' UUID="{user_uuid}";'
            f' EMAIL="{email}";'
            f' CFG="{self.config_path}";'
            f' cp "$CFG" "$CFG.bak.{ts}";'
            " jq --arg uuid \"$UUID\" --arg email \"$EMAIL\" "
            "'(.inbounds[0].settings.clients //= []) | "
            "if any(.inbounds[0].settings.clients[]; .id == $uuid) then . "
            "else .inbounds[0].settings.clients += [{\"id\":$uuid,\"alterId\":0,\"email\":$email}] end' "
            "\"$CFG\" > \"$CFG.tmp\";"
            " mv \"$CFG.tmp\" \"$CFG\";"
            " sudo -n /usr/local/bin/xray -test -config \"$CFG\" >/dev/null;"
            " sudo -n /bin/systemctl restart xray;"
            " sudo -n /bin/systemctl status xray >/dev/null;"
        )
        self.ssh(remote)

    def remove_user(self, user_uuid):
        users = self.list_users()
        if len(users) <= 1:
            raise RuntimeError("Refusing to remove the last remaining user.")
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        remote = (
            "set -e;"
            f' UUID="{user_uuid}";'
            f' CFG="{self.config_path}";'
            f' cp "$CFG" "$CFG.bak.{ts}";'
            " jq --arg uuid \"$UUID\" "
            "'if any(.inbounds[0].settings.clients[]; .id == $uuid) "
            "then .inbounds[0].settings.clients |= map(select(.id != $uuid)) "
            "else . end' "
            "\"$CFG\" > \"$CFG.tmp\";"
            " mv \"$CFG.tmp\" \"$CFG\";"
            " sudo -n /usr/local/bin/xray -test -config \"$CFG\" >/dev/null;"
            " sudo -n /bin/systemctl restart xray;"
            " sudo -n /bin/systemctl status xray >/dev/null;"
        )
        self.ssh(remote)

    def get_reality_params(self):
        cfg = self.get_config()
        inbound = cfg["inbounds"][0]
        port = inbound["port"]
        sni = inbound["streamSettings"]["realitySettings"]["serverNames"][0]
        sid = inbound["streamSettings"]["realitySettings"]["shortIds"][0]
        priv = inbound["streamSettings"]["realitySettings"]["privateKey"]
        remote = (
            f'PRIV="{priv}"; '
            "/usr/local/bin/xray x25519 -i \"$PRIV\" 2>/dev/null | sed -n 's/^Password: //p'"
        )
        pbk = self.ssh(remote).stdout.strip()
        return {"port": port, "sni": sni, "sid": sid, "pbk": pbk}


def ensure_qrcode_module():
    try:
        import qrcode  # noqa: F401
        return sys.executable
    except Exception:
        pass
    base = os.path.dirname(os.path.abspath(__file__))
    venv = os.path.join(base, ".tmp-qr-venv")
    py = os.path.join(venv, "bin", "python")
    pip = os.path.join(venv, "bin", "pip")
    if not os.path.isdir(venv):
        run(f"{q(sys.executable)} -m venv {q(venv)}", check=True, capture=True)
    run(f"{q(pip)} -q install qrcode", check=True, capture=True)
    return py


def render_cli_qr(data):
    py = ensure_qrcode_module()
    script = (
        "import qrcode,sys;"
        "qr=qrcode.QRCode(border=1);"
        "qr.add_data(sys.argv[1]);"
        "qr.make(fit=True);"
        "m=qr.get_matrix();"
        "print('\\n'.join(''.join('██' if c else '  ' for c in r) for r in m))"
    )
    out = run(f"{q(py)} -c {q(script)} {q(data)}", check=True, capture=True).stdout
    return out


def qr_link(data):
    return "https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=" + urllib.parse.quote(data, safe="")


def build_url(user_uuid, host, port, sni, pbk, sid, name):
    return (
        f"vless://{user_uuid}@{host}:{port}"
        f"?encryption=none&security=reality&sni={sni}&fp=chrome&pbk={pbk}&sid={sid}&type=tcp#{name}"
    )


def cmd_list(args):
    m = VPNManager(args.host, args.user, args.key_path, args.config_path)
    users = m.list_users()
    for u in users:
        print(f"{u['index']}. {u['id']}\t{u['email']}")


def cmd_create(args):
    m = VPNManager(args.host, args.user, args.key_path, args.config_path)
    new_uuid = args.uuid or str(uuidlib.uuid4())
    name = args.name or f"xray-user-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    m.add_user(new_uuid, name)
    rp = m.get_reality_params()
    url = build_url(new_uuid, args.host, rp["port"], rp["sni"], rp["pbk"], rp["sid"], name)
    print(f"UUID: {new_uuid}")
    print(f"URL: {url}")
    print(f"QR_URL: {qr_link(url)}")
    print("QR_CLI:")
    print(render_cli_qr(url))


def cmd_remove(args):
    m = VPNManager(args.host, args.user, args.key_path, args.config_path)
    target = args.uuid
    if not target:
        users = m.list_users()
        if not users:
            raise RuntimeError("No users found.")
        for u in users:
            print(f"{u['index']}. {u['id']}\t{u['email']}")
        sel = input("Select index to remove: ").strip()
        if not sel.isdigit():
            raise RuntimeError("Selection must be a number.")
        idx = int(sel)
        if idx < 1 or idx > len(users):
            raise RuntimeError("Selection out of range.")
        target = users[idx - 1]["id"]
    m.remove_user(target)
    print(f"Removed UUID: {target}")


def build_parser():
    p = argparse.ArgumentParser(prog="vpn_user_manager.py")
    p.add_argument("--host", required=True, help="Node hostname or IP, e.g. vpn.example.com")
    p.add_argument("--user", default="deploy", help="SSH user with access to the Xray config (default: deploy)")
    p.add_argument("--key-path", default="~/.ssh/id_rsa", help="SSH private key path")
    p.add_argument("--config-path", default="/usr/local/etc/xray/config.json", help="Remote Xray config path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_list = sub.add_parser("list")
    sp_list.set_defaults(func=cmd_list)

    sp_create = sub.add_parser("create")
    sp_create.add_argument("--uuid", default=None)
    sp_create.add_argument("--name", default=None)
    sp_create.set_defaults(func=cmd_create)

    sp_remove = sub.add_parser("remove")
    sp_remove.add_argument("--uuid", default=None)
    sp_remove.set_defaults(func=cmd_remove)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e)).strip()
        print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
