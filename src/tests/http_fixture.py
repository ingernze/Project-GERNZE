"""Disposable authenticated local server for DOM integration tests."""
import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.server import WorkbenchServer

with tempfile.TemporaryDirectory(prefix='hebao-test-') as folder:
    server = WorkbenchServer(folder)
    worker = threading.Thread(target=server.serve, daemon=True)
    worker.start()
    print(json.dumps({'url':server.launch_url, 'origin':server.origin}), flush=True)
    try:
        sys.stdin.readline()
    finally:
        server.stop()
        worker.join(timeout=10)
        server.server_close()
