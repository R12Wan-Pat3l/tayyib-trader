import os
import sys
import unittest

from _util import ROOT

sys.path.insert(0, os.path.join(ROOT, "tayyib-entry"))
import entry  # noqa: E402


def bar(d, o, h, l, c):
    return {"date": d, "open": o, "high": h, "low": l, "close": c, "volume": 1}


SIG = {"date": "2026-10-26", "trigger": 105.0, "invalidation": 95.0, "valid_days": 3}
B0 = [bar("2026-10-26", 100, 103, 99, 102)]


class Evaluate(unittest.TestCase):
    def test_waiting(self):
        r = entry.evaluate(SIG, B0 + [bar("2026-10-27", 102, 104, 101, 103)])
        self.assertEqual(r["status"], "WAITING")

    def test_triggered_and_gap_fill(self):
        r = entry.evaluate(SIG, B0 + [bar("2026-10-27", 102, 106, 101, 105.5)])
        self.assertEqual((r["status"], r["fill"]), ("TRIGGERED", 105.0))
        r = entry.evaluate(SIG, B0 + [bar("2026-10-27", 107, 108, 106, 107.5)])
        self.assertEqual(r["fill"], 107.0)                           # gap open over the trigger

    def test_extended(self):
        r = entry.evaluate(SIG, B0 + [bar("2026-10-27", 102, 106, 101, 105.5),
                                      bar("2026-10-28", 106, 112, 106, 111)])
        self.assertEqual(r["status"], "EXTENDED")

    def test_invalidated_and_expired(self):
        r = entry.evaluate(SIG, B0 + [bar("2026-10-27", 100, 101, 93, 94)])
        self.assertEqual(r["status"], "INVALIDATED")
        flat = [bar("2026-10-%d" % d, 100, 103, 99, 101) for d in (27, 28, 29)]
        self.assertEqual(entry.evaluate(SIG, B0 + flat)["status"], "EXPIRED")

    def test_live_price_heads_up(self):
        r = entry.evaluate(SIG, B0, live=105.2)
        self.assertEqual(r["status"], "TRIGGERING")


if __name__ == "__main__":
    unittest.main()
