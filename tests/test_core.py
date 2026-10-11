import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from _aeros import Monitor, validate

def ev(i, exp=100, act=100, occ="2026-09-01", det=""):
    return validate(dict(id=f"E{i}", process="Rewards", expected=exp, actual=act, occurred=occ, detected=det))

class Core(unittest.TestCase):
    def test_clean_event_no_alert(self):
        self.assertEqual(Monitor().process(ev(1)), [])
    def test_reconciliation_break(self):
        self.assertEqual([a["rule"] for a in Monitor().process(ev(1, act=90))], ["reconciliation_break"])
    def test_late_detection(self):
        r = Monitor(limit=14).process(ev(1, det="2026-09-30"))
        self.assertEqual([a["rule"] for a in r], ["late_detection"])
    def test_within_limit_not_late(self):
        self.assertEqual(Monitor(limit=14).process(ev(1, det="2026-09-10")), [])
    def test_repeat_escalates_to_high(self):
        m = Monitor(repeat_n=3); out = []
        for i in range(3): out = m.process(ev(i, act=50))
        self.assertIn("High", [a["severity"] for a in out])
    def test_validation(self):
        for bad in (dict(id="x"), dict(id="x", process="p", expected="a", actual=1, occurred="2026-01-01"),
                    dict(id="x", process="p", expected=1, actual=1, occurred="2026-02-01", detected="2026-01-01")):
            with self.assertRaises(ValueError): validate(bad)

if __name__ == "__main__": unittest.main()
