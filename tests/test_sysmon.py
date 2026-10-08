import os, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sysmon

class OK(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

class Tests(unittest.TestCase):
    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), OK)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.db = sysmon.get_db(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.cfg = {"timeout_seconds": 2, "latency_warn_ms": 800, "failures_before_incident": 3}

    def tearDown(self):
        self.srv.shutdown()

    def test_http_up(self):
        ok, ms, d = sysmon.check_http(f"http://127.0.0.1:{self.port}", 2)
        self.assertTrue(ok); self.assertIn("200", d)

    def test_tcp_down(self):
        ok, ms, d = sysmon.check_tcp("127.0.0.1", 1, 1)
        self.assertFalse(ok)

    def test_incident_opens_after_3_failures_and_closes_on_recovery(self):
        bad = {"name": "svc", "type": "tcp", "host": "127.0.0.1", "port": 1}
        for _ in range(2):
            sysmon.process(self.db, self.cfg, bad)
        self.assertIsNone(sysmon.open_incident(self.db, "svc"))   # not yet
        sysmon.process(self.db, self.cfg, bad)
        self.assertIsNotNone(sysmon.open_incident(self.db, "svc"))  # opened on 3rd
        good = {"name": "svc", "type": "http", "url": f"http://127.0.0.1:{self.port}"}
        sysmon.process(self.db, self.cfg, good)
        self.assertIsNone(sysmon.open_incident(self.db, "svc"))   # closed

if __name__ == "__main__":
    unittest.main()
