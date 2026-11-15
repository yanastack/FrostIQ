"""Run on the UNO Q. Poll Person 1's router endpoint and feed the local API."""
import json
import socket
import sys
import time
from urllib.request import Request, urlopen

import msgpack


def read_packet():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect("/var/run/arduino-router.sock")
        client.sendall(msgpack.packb([0, 1, "frostiq_read_sensors", []]))
        unpacker = msgpack.Unpacker(raw=False, max_buffer_size=65536)
        while True:
            chunk = client.recv(4096)
            if not chunk:
                raise OSError("Incomplete reply from board router")
            unpacker.feed(chunk)
            for reply in unpacker:
                if reply[:2] != [1, 1] or reply[2] is not None:
                    raise ValueError(f"Unexpected router reply: {reply}")
                return json.loads(reply[3])


def main():
    last_id = None
    while True:
        try:
            packet = read_packet()
            sample_id = packet.get("sample_id")
            if sample_id is None or sample_id != last_id:
                request = Request("http://127.0.0.1:8000/api/ingest",
                                  data=json.dumps(packet).encode(),
                                  headers={"Content-Type": "application/json"})
                with urlopen(request, timeout=3) as response:
                    response.read()
                last_id = sample_id
        except (ValueError, OSError) as error:
            print("Sensor feed:", error, file=sys.stderr, flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main()
