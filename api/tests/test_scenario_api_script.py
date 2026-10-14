import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_SCRIPT = REPO_ROOT / "scripts" / "run_scenario_api.sh"


class _HealthzHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/healthz":
            self.send_error(404)
            return
        body = b'{"status":"ok","seeded":false}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def test_scenario_script_refuses_port_owned_by_another_listener(tmp_path: Path) -> None:
    server = HTTPServer(("127.0.0.1", 0), _HealthzHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        result = subprocess.run(
            [str(SCENARIO_SCRIPT), str(tmp_path / "scratch"), str(port)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode != 0
    assert "already serves /healthz" in result.stderr
