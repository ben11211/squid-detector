#!/usr/bin/env python3
"""Administer the Home Assistant side of the logger from the terminal.

    hactl.py influx "SHOW DATABASES"              InfluxQL as InfluxDB admin (--db noise)
    hactl.py supervisor get /addons               HA Supervisor API (add-ons, updates, host)
    hactl.py addon a0d7b954_grafana get /api/health  an add-on's own web API (via HA ingress)
    hactl.py add-esphome noise-outdoor.local KEY_FILE  add an ESPHome device to HA

Reads ~/.config/homelab/ha_host (or $HA_HOST) and ~/.config/homelab/ha_token (an admin
long-lived access token). Never prints either. Needs: pip install websockets
"""
import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

import websockets

CONFIG = os.path.expanduser("~/.config/homelab")
INFLUX_ADDON = "a0d7b954_influxdb"


def read_config(name):
    with open(os.path.join(CONFIG, name)) as f:
        return f.read().strip()


HA = (os.environ.get("HA_HOST") or read_config("ha_host")) + ":8123"
TOKEN = read_config("ha_token")


# --- Home Assistant connections -------------------------------------------------

def http(method, path, body=None, headers=None):
    """HTTP request to HA; returns parsed JSON (or text). Exits on HTTP errors."""
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(f"http://{HA}{path}", data=data, method=method.upper(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {method.upper()} {path}: {e.read().decode()[:300]}")
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return text


def rest(method, path, body=None):
    """HA REST API (/api/...) with the access token."""
    return http(method, path, body, {"Authorization": f"Bearer {TOKEN}"})


def supervisor(*calls):
    """Run Supervisor API calls, each (method, endpoint[, data]), over HA's WebSocket.

    The Supervisor isn't reachable from the LAN; HA relays it for admin tokens.
    Returns the list of results.
    """
    async def run():
        async with websockets.connect(f"ws://{HA}/api/websocket", max_size=None) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
            if json.loads(await ws.recv())["type"] != "auth_ok":
                sys.exit("HA rejected the token")
            results = []
            for i, (method, endpoint, *data) in enumerate(calls, 1):
                msg = {"id": i, "type": "supervisor/api", "method": method.lower(),
                       "endpoint": endpoint, "timeout": None}
                if data:
                    msg["data"] = data[0]
                await ws.send(json.dumps(msg))
                reply = json.loads(await ws.recv())
                while reply.get("id") != i:          # skip unrelated events
                    reply = json.loads(await ws.recv())
                if not reply["success"]:
                    sys.exit(f"Supervisor {endpoint}: {reply['error']}")
                results.append(reply["result"])
            return results
    return asyncio.run(run())


def addon(slug, method, path, body=None):
    """Call an add-on's web UI/API through HA ingress (no add-on port needs exposing)."""
    info, session = supervisor(("get", f"/addons/{slug}/info"), ("post", "/ingress/session"))
    base = info["ingress_url"].rstrip("/")
    headers = {"Cookie": f"ingress_session={session['session']}",
               "X-Requested-With": "XMLHttpRequest"}   # Chronograf requires it
    return http(method, base + path, body, headers)


def influx(query, db=""):
    """InfluxQL as admin: the InfluxDB add-on's admin user is only usable via its
    Chronograf UI, so send the query through Chronograf's proxy endpoint."""
    source = addon(INFLUX_ADDON, "get", "/chronograf/v1/sources")["sources"][0]
    return addon(INFLUX_ADDON, "post", source["links"]["proxy"], {"query": query, "db": db})


def add_esphome(host, key_file):
    """Run HA's 'add ESPHome device' flow with the device's API encryption key."""
    key = open(os.path.expanduser(key_file)).read().strip()
    step = rest("post", "/api/config/config_entries/flow", {"handler": "esphome"})
    answers = {"user": {"host": host, "port": 6053}, "encryption_key": {"noise_psk": key}}
    while step.get("type") == "form":
        if step["step_id"] not in answers:
            sys.exit(f"unexpected step {step['step_id']}: {step.get('data_schema')}")
        step = rest("post", f"/api/config/config_entries/flow/{step['flow_id']}",
                    answers[step["step_id"]])
    return {k: step.get(k) for k in ("type", "title", "reason")}


# --- command line ---------------------------------------------------------------

def body_arg(text):
    """JSON string, or @file containing JSON."""
    if text is None:
        return None
    return json.load(open(text[1:])) if text.startswith("@") else json.loads(text)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("influx", help="InfluxQL as admin")
    s.add_argument("query"); s.add_argument("--db", default="")
    s = sub.add_parser("supervisor", help="HA Supervisor API")
    s.add_argument("method"); s.add_argument("endpoint"); s.add_argument("body", nargs="?")
    s = sub.add_parser("addon", help="add-on web API via ingress")
    s.add_argument("slug"); s.add_argument("method"); s.add_argument("path"); s.add_argument("body", nargs="?")
    s = sub.add_parser("add-esphome", help="add an ESPHome device to HA")
    s.add_argument("host"); s.add_argument("key_file")
    a = p.parse_args()

    if a.cmd == "influx":
        out = influx(a.query, a.db)
    elif a.cmd == "supervisor":
        out = supervisor((a.method, a.endpoint, *([body_arg(a.body)] if a.body else [])))[0]
    elif a.cmd == "addon":
        out = addon(a.slug, a.method, a.path, body_arg(a.body))
    else:
        out = add_esphome(a.host, a.key_file)
    print(out if isinstance(out, str) else json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
