import os, sys, json, threading, unittest, urllib.request, urllib.error
from datetime import date
from http.server import HTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import _aeros as A
from _aeros import Monitor, validate, check_plan, slack_safe, num, format_digest
import ingest

AS_OF = date(2026, 10, 11)


def ev(i, exp=100, act=90, occ="2026-09-01", det="", proc="P"):
    return validate(dict(id=f"E{i}", process=proc, expected=exp, actual=act, occurred=occ, detected=det))


def mon(**k):
    return Monitor(as_of=AS_OF, **k)


class Detection(unittest.TestCase):
    def test_clean_event_no_alert(self):
        self.assertEqual(mon().process(ev(1, act=100)), [])

    def test_break_gives_one_alert_with_all_reasons(self):
        r = mon().process(ev(1, det="2026-09-30"))
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["rule"], "late_detection")
        self.assertEqual(set(r[0]["rules"]), {"reconciliation_break", "late_detection"})

    def test_tolerance_ignores_float_noise(self):
        self.assertEqual(mon().process(ev(1, exp=0.1 + 0.2, act=0.3)), [])
        self.assertEqual(len(mon().process(ev(1, exp=100, act=99.99))), 1)

    def test_within_limit_not_late(self):
        self.assertEqual(mon(limit=14).process(ev(1, act=100, det="2026-09-10")), [])

    def test_undetected_old_break_counts_as_late(self):
        r = mon(limit=14).process(ev(1, occ="2026-09-01", det=""))
        self.assertIn("late_detection", r[0]["rules"])

    def test_undetected_recent_break_not_late(self):
        r = mon(limit=14).process(ev(1, occ="2026-10-05", det=""))
        self.assertEqual(r[0]["rules"], ["reconciliation_break"])

    def test_repeat_escalates_once_per_window(self):
        m, sev = mon(repeat_n=3, window=20), []
        for i in range(10):
            sev += [a["severity"] for a in m.process(ev(i, occ="2026-10-05"))]
        self.assertEqual(sev.count("High"), 1)
        self.assertEqual(len(sev), 10)

    def test_small_sample_not_shown_as_rate(self):
        r = mon().process(ev(1))[0]["triage"]["impact"]
        self.assertIn("too few", r)
        self.assertNotIn("100", r)


class Validation(unittest.TestCase):
    def test_rejects_bad_input(self):
        base = dict(id="x", process="p", expected=1, actual=1, occurred="2026-01-01")
        bad = [dict(id="x"), dict(base, expected="nan"), dict(base, actual="inf"), dict(base, expected=True),
               dict(base, expected="abc"), dict(base, occurred="01/02/2026"),
               dict(base, occurred="2026-02-01", detected="2026-01-01"), "not an object"]
        for b in bad:
            with self.assertRaises(ValueError, msg=str(b)):
                validate(b)

    def test_large_numbers_not_scientific(self):
        r = mon().process(ev(1, exp=1234567, act=1234000))[0]["detail"]
        self.assertIn("1,234,567", r)
        self.assertNotIn("e+", r)
        self.assertEqual(num(1200), "1,200")

    def test_text_is_length_limited_and_single_line(self):
        e = validate(dict(id="a" * 500 + "\nB", process="p\r\nq", expected=1, actual=1, occurred="2026-01-01"))
        self.assertLessEqual(len(e["id"]), 64)
        self.assertNotIn("\n", e["process"])


class Safety(unittest.TestCase):
    def test_slack_markup_neutralised(self):
        s = slack_safe("<!channel> <https://evil.example|click> &")
        self.assertNotIn("<", s)
        self.assertNotIn(">", s)

    def test_digest_is_escaped_and_capped(self):
        m, alerts = mon(), []
        for i in range(25):
            alerts += m.process(ev(i, proc="<!channel>"))
        d = format_digest(alerts)
        self.assertNotIn("<!channel>", d)
        self.assertIn("more not shown", d)

    def test_check_plan_rejects_malformed(self):
        good = dict(likely_causes=["a"], impact="x", next_steps=["b"], confidence="low")
        self.assertIsNotNone(check_plan(good))
        for bad in (None, "str", [], dict(good, confidence="certain"), dict(good, next_steps="just a string"),
                    {k: v for k, v in good.items() if k != "confidence"}, dict(good, impact=5)):
            self.assertIsNone(check_plan(bad))


class AIBudget(unittest.TestCase):
    def setUp(self):
        self.calls, self.orig, self.key = [], A._call_llm, os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "test"

    def tearDown(self):
        A._call_llm = self.orig
        os.environ.pop("ANTHROPIC_API_KEY", None)
        if self.key:
            os.environ["ANTHROPIC_API_KEY"] = self.key

    def good(self, ctx, timeout):
        self.calls.append(ctx)
        return dict(likely_causes=["c"], impact="i", next_steps=["n"], confidence="medium")

    def alerts(self, m, n):
        out = []
        for i in range(n):
            out += m.process(ev(i, occ="2026-10-05"))
        return out

    def test_cap_is_per_run_not_per_event(self):
        A._call_llm = self.good
        m = mon(max_llm=5)
        al = self.alerts(m, 40)
        m.enrich(al)
        self.assertEqual(len(self.calls), 5)

    def test_high_severity_gets_ai_first(self):
        A._call_llm = self.good
        m = mon(max_llm=1)
        al = self.alerts(m, 10)
        m.enrich(al)
        enriched = [a for a in al if a["triage"]["source"] == "claude"]
        self.assertEqual([a["severity"] for a in enriched], ["High"])

    def test_malformed_ai_reply_falls_back(self):
        A._call_llm = lambda ctx, t: {"impact": "no other keys"}
        m = mon()
        al = self.alerts(m, 3)
        m.enrich(al)
        self.assertTrue(all(a["triage"]["source"] == "rules" for a in al))
        format_digest(al)  # must not raise

    def test_ai_exception_falls_back(self):
        def boom(ctx, t): raise TimeoutError()
        A._call_llm = boom
        al = self.alerts(mon(), 2)
        mon().enrich(al)
        self.assertTrue(all(a["triage"]["source"] == "rules" for a in al))

    def test_no_ai_when_deadline_near(self):
        A._call_llm = self.good
        m = mon(deadline_s=1)
        al = self.alerts(m, 3)
        m.enrich(al)
        self.assertEqual(self.calls, [])


class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), ingest.handler)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/api/ingest"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        ingest._hits.clear()
        os.environ.pop("AEROS_API_TOKEN", None)

    def post(self, body, headers=None, raw=False):
        data = body if raw else json.dumps(body).encode()
        req = urllib.request.Request(self.url, data, {"content-type": "application/json", **(headers or {})})
        try:
            r = urllib.request.urlopen(req)
            return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def E(self, i, **k):
        return dict(id=f"E{i}", process="P", expected=100, actual=90, occurred="2026-10-05", **k)

    def test_health_hides_config(self):
        r = json.load(urllib.request.urlopen(self.url))
        self.assertEqual(r, dict(service="aeros", status="ok"))

    def test_dry_run_works_and_sends_nothing(self):
        c, b = self.post({"events": [self.E(1)]})
        self.assertEqual((c, b["mode"], b["delivered"], b["ai_calls"]), (200, "dry_run", [], 0))

    def test_json_list_body_is_400(self):
        self.assertEqual(self.post([1, 2])[0], 400)

    def test_live_needs_token(self):
        self.assertEqual(self.post({"dry_run": False, "events": [self.E(1)]})[0], 401)
        os.environ["AEROS_API_TOKEN"] = "secret-token"
        self.assertEqual(self.post({"dry_run": False, "events": [self.E(1)]}, {"authorization": "Bearer wrong"})[0], 401)
        c, b = self.post({"dry_run": False, "events": [self.E(1)]}, {"authorization": "Bearer secret-token"})
        self.assertEqual((c, b["mode"]), (200, "live"))

    def test_bad_row_rejects_batch_unless_skip_invalid(self):
        evs = [self.E(1), dict(id="bad")]
        self.assertEqual(self.post({"events": evs})[0], 400)
        c, b = self.post({"events": evs, "skip_invalid": True})
        self.assertEqual((c, b["events"], len(b["rejected"])), (200, 1, 1))
        c, b = self.post({"events": [dict(id="bad")], "skip_invalid": True})   # only bad rows: no crash, no loop
        self.assertEqual((c, b["events"], len(b["rejected"]), b["alerts"]), (200, 0, 1, []))

    def test_demo_size_limit(self):
        self.assertEqual(self.post({"events": [self.E(i) for i in range(51)]})[0], 400)

    def test_rate_limit(self):
        codes = [self.post({"events": [self.E(1)]})[0] for _ in range(32)]
        self.assertIn(429, codes)

    def test_failed_auth_is_rate_limited(self):
        os.environ["AEROS_API_TOKEN"] = "t"
        codes = [self.post({"dry_run": False, "events": [self.E(1)]})[0] for _ in range(32)]
        self.assertIn(429, codes)


class VercelStyleImport(unittest.TestCase):
    def test_function_imports_with_clean_path_from_other_directory(self):
        """Vercel loads api/ingest.py by file path with the api folder NOT on sys.path."""
        import subprocess, tempfile
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api", "ingest.py"))
        code = ("import importlib.util, sys; "
                f"spec = importlib.util.spec_from_file_location('vc_entry', {path!r}); "
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
                "assert hasattr(m, 'handler'); print('imported ok')")
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-c", code], cwd=d, capture_output=True, text=True,
                               env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
        self.assertIn("imported ok", r.stdout, r.stderr)


if __name__ == "__main__":
    unittest.main()
