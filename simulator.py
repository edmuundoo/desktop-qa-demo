"""TCP-сервис: синусоида для ручной проверки или снимки из файла."""

import argparse
import json
import math
import socketserver
import time
from datetime import datetime, timezone
from pathlib import Path


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        snapshot_index = 0
        # readline собирает запрос, даже если TCP доставил его частями.
        try:
            for command in self.rfile:
                if command != b"GET\n":
                    return
                if self.server.snapshots is not None:
                    snapshots = self.server.snapshots
                    snapshot = snapshots[min(snapshot_index, len(snapshots) - 1)]
                    snapshot_index += 1
                else:
                    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                    phase = time.monotonic()
                    snapshot = [
                        {"id": i, "name": f"Сигнал {i}",
                         "value": round(math.sin(phase + i) * 100, 3),
                         "quality": "GOOD", "time": now}
                        for i in range(1, 11)
                    ]
                message = (json.dumps(snapshot, ensure_ascii=False) + "\n").encode("utf-8")
                self.wfile.write(message)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=2001)
    parser.add_argument("--snapshots", type=Path)
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args()
    snapshots = None
    if args.snapshots:
        snapshots = json.loads(args.snapshots.read_text(encoding="utf-8"))
        if not isinstance(snapshots, list) or not snapshots:
            raise ValueError("Ожидается непустой список снимков")
    with Server(("127.0.0.1", args.port), Handler) as server:
        server.snapshots = snapshots
        # Маркер создаётся только после успешного bind/listen.
        if args.ready_file:
            args.ready_file.write_text("ready", encoding="utf-8")
        print(f"Listening on 127.0.0.1:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
