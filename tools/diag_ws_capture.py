"""
Diagnostic: connect to UC Remote 3 websocket, subscribe to events for the kodi
media_player entity, dump what the integration actually pushes — particularly
MEDIA_IMAGE_URL (truncated to first 80 chars to keep terminal sane). Run while
the user opens the activity card and starts playback.

Usage: python _diag_ws_capture.py [seconds]   # default 60
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import time

import websockets

UC3_HOST = "192.168.2.204"
UC3_TOKEN = "boyTP4V.MjhmNjJiZWI2YWJmNGY4NjlmZTE0MDRhYzgxY2Q1MTIuZGFmYzU3MWM5YTg5NGY0NmI1NDlhOGU2MzZhMDI4Njk"
ENTITY = "media_player.madteevee.local"
INTEGRATION_ID = "kodi_driver.main"


def auth_header() -> str:
    return f"Bearer {UC3_TOKEN}"


def short(v, n=80):
    s = str(v)
    return s if len(s) <= n else s[:n] + f"...({len(s)} total)"


def fmt_attrs(attrs: dict) -> str:
    if not isinstance(attrs, dict):
        return short(attrs)
    out = []
    for k, v in attrs.items():
        # Highlight media_image_url specifically — that's what we're chasing
        if k == "media_image_url":
            if not v:
                v_disp = "<EMPTY>"
            elif isinstance(v, str) and v.startswith("data:"):
                semi = v.find(";")
                mime = v[5:semi] if semi > 0 else "?"
                v_disp = f"<data URI mime={mime!r} len={len(v)}>"
            elif isinstance(v, str) and v.startswith(("http://", "https://")):
                v_disp = f"<URL len={len(v)}> {v[:120]}"
            else:
                v_disp = short(v, 120)
            out.append(f"{k}={v_disp}")
            continue
        if isinstance(v, str):
            v_disp = short(v, 80)
        else:
            v_disp = short(v, 100)
        out.append(f"{k}={v_disp}")
    return "; ".join(out)


async def main(duration_s: int = 60):
    url = f"ws://{UC3_HOST}/ws"
    print(f"[*] Connecting to {url} ...")
    headers = {"Authorization": auth_header()}
    async with websockets.connect(
        url,
        additional_headers=headers,
        max_size=20 * 1024 * 1024,
        open_timeout=10,
        ping_timeout=None,
    ) as ws:
        print("[*] Connected. Sending auth + subscribe...")
        # First, send an auth message in case the WS expects in-band auth
        await ws.send(json.dumps({"kind": "req", "id": 0, "msg": "auth", "msg_data": {"token": UC3_TOKEN}}))

        # UC Core API channel set per server's BAD_REQUEST hint:
        # all, configuration, entities, entity_button, entity_switch, entity_climate,
        # entity_media_player, ...
        subscribe_msgs = [
            {"kind": "req", "id": 1, "msg": "subscribe_events",
             "msg_data": {"channels": ["all"]}},
        ]
        for m in subscribe_msgs:
            await ws.send(json.dumps(m))

        print(f"[*] Listening for {duration_s}s. Filter: entity_id={ENTITY}")
        print(f"[*] Open the Kodi activity card NOW and reproduce the symptom.")
        print()

        deadline = time.monotonic() + duration_s
        msg_count = 0
        relevant_count = 0
        try:
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.monotonic())
                except asyncio.TimeoutError:
                    break
                msg_count += 1
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue

                msg = obj.get("msg")
                msg_data = obj.get("msg_data", {}) or {}

                # Filter: events about our kodi media_player
                ent_id = (
                    msg_data.get("entity_id")
                    or (msg_data.get("entity") or {}).get("entity_id")
                    or ""
                )
                ig_id = msg_data.get("integration_id") or msg_data.get("instance_id") or ""

                if ENTITY in str(obj) or INTEGRATION_ID in str(obj):
                    relevant_count += 1
                    ts = time.strftime("%H:%M:%S")
                    if msg == "entity_change":
                        new_state = msg_data.get("new_state") or {}
                        attrs = new_state.get("attributes") or msg_data.get("attributes") or {}
                        ent_id_real = msg_data.get("entity_id", "?")
                        et = msg_data.get("entity_type", "?")
                        ev = msg_data.get("event_type", "?")
                        print(f"[{ts}] entity_change ev={ev} ent_id={ent_id_real} type={et}")
                        if attrs:
                            print(f"           {fmt_attrs(attrs)}")
                        else:
                            print(f"           (no attributes in event)")
                    else:
                        print(f"[{ts}] msg={msg!r} kind={obj.get('kind')!r} req_id={obj.get('req_id')}")
                        if msg_data:
                            print(f"           data={short(json.dumps(msg_data), 250)}")

        finally:
            print()
            print(f"[*] {msg_count} total messages, {relevant_count} relevant to the Kodi entity.")


if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    asyncio.run(main(duration))
