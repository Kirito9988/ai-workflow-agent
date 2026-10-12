"""Local demo UI and JSON API; only binds to loopback."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from .core import ROOT


def serve(engine, port):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, content, kind="application/json"):
            body = content.encode()
            self.send_response(status)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self.send(200, (ROOT / "agent/ui.html").read_text(), "text/html")
            elif self.path == "/static/input_forms.js":
                self.send(200, (ROOT / "agent/input_forms.js").read_text(), "text/javascript")
            elif self.path == "/api/catalog":
                self.send(200, json.dumps({"mode": engine.backend.mode, "workflows": [d["source"] for d in engine.catalog.workflows.values()], "input_guides": {wid: engine.input_guide(wid) for wid in engine.catalog.workflows}, "examples": json.loads((ROOT / "examples/requests.json").read_text())}))
            else:
                self.send(404, json.dumps({"error": "Not found"}))

        def do_POST(self):
            if self.path not in ("/api/run", "/api/prepare"):
                self.send(404, json.dumps({"error": "Not found"}))
                return
            origin = self.headers.get("Origin")
            allowed = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
            if origin and origin not in allowed:
                self.send(403, json.dumps({"error": "Origin rejected"}))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 200000:
                    raise ValueError("Request size must be 1–200000 bytes")
                data = json.loads(self.rfile.read(length))
                action = engine.prepare if self.path == "/api/prepare" else engine.run
                result = action(data["request"], data.get("inputs", {}))
                self.send(200, json.dumps(result))
            except (ValueError, KeyError, TypeError):
                self.send(400, json.dumps({"error": "Provide JSON with request and inputs"}))

    print(f"Workflow Agent ({engine.backend.mode}) → http://127.0.0.1:{port}", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
