"""Send live data to the Log Evaluation Tool from your own code.

This is the part to adapt once you know how the car's data reaches a laptop: a CAN adapter, a radio
modem, a telemetry box. Replace ``read_samples`` with code that returns the latest readings, and
leave the rest alone. Run the tool, open the Live tab, choose "Pushed by another program", press
Wait for data, then run:

    python tools/live_bridge_example.py            # sends a demo signal
    python tools/live_bridge_example.py --url http://127.0.0.1:8000

Only the standard library is used, so this runs anywhere Python does.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import time
from urllib.parse import urlparse

UNITS = {"rpm": "rpm", "vehicleSpeed": "km/h", "tps1": "%"}


def read_samples(t: float) -> list[dict]:
    """Return the readings since the last call, as rows of {"t": seconds, "values": {channel: number}}.

    This demo invents a signal. A real bridge would read the adapter here and return what it got;
    ``t`` is optional (leave it out and the tool stamps rows with their arrival time).
    """
    rows = []
    for i in range(10):  # ten samples per call, so 100 a second at the default pace below
        x = t + i / 100
        rows.append(
            {
                "t": x,
                "values": {
                    "rpm": 6000 + 2500 * math.sin(x * 0.8),
                    "vehicleSpeed": 80 + 40 * math.sin(x * 0.5),
                    "tps1": max(0.0, 50 + 50 * math.sin(x * 0.8)),
                },
            }
        )
    return rows


def post(conn: http.client.HTTPConnection, rows: list[dict]) -> int:
    body = json.dumps({"rows": rows, "units": UNITS}).encode()
    conn.request("POST", "/api/live/ingest", body, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    if resp.status != 200:
        raise RuntimeError(f"the tool refused the rows: {resp.status} {data[:200]!r}")
    return json.loads(data)["accepted"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="where the tool is running (use 127.0.0.1, not localhost: on Windows localhost tries IPv6 first and is slow)")
    args = ap.parse_args()
    u = urlparse(args.url)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=5)  # one connection, reused
    t0 = time.monotonic()
    print(f"Sending to {args.url}. Press Ctrl+C to stop.")
    while True:
        accepted = post(conn, read_samples(time.monotonic() - t0))
        print(f"\r{accepted} rows accepted", end="", flush=True)
        time.sleep(0.1)


if __name__ == "__main__":
    main()
