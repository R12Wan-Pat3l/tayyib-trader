import json
import os
import subprocess
import sys
import unittest

from _util import OfflineCase, ROOT


class MCP(OfflineCase):
    def call(self, msgs):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "mcp", "server.py")],
                           input="\n".join(json.dumps(m) for m in msgs) + "\n",
                           capture_output=True, text=True, env=dict(os.environ, TAYYIB_DIR=self.dir), timeout=120)
        return [json.loads(l) for l in p.stdout.splitlines() if l.strip()]

    def test_handshake_list_call(self):
        self.build_universe()
        out = self.call([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "halal_check", "arguments": {"symbols": "ITC"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "scan", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "nope"},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "entry_check", "arguments": {}}},
        ])
        self.assertEqual([m["id"] for m in out], [1, 2, 3, 4, 5, 6])     # no reply to the notification
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "tayyib-trader")
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertIn("scan", names)
        self.assertFalse([n for n in names if "place" in n or "order" in n])
        self.assertEqual(json.loads(out[2]["result"]["content"][0]["text"])["stocks"][0]["status"], "excluded")
        self.assertIn("ALFA", out[3]["result"]["content"][0]["text"])
        self.assertEqual(out[4]["error"]["code"], -32601)
        self.assertTrue(out[5]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
