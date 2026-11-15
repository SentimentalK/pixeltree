"""R5: OMP tool-call parsing / invalid rule, and the quota-error-out-of-denominator summary."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.shells.omp import analyze, omp, run  # noqa: E402


def assistant(content, usage=None, stop="toolUse", error=None):
    m = {"role": "assistant", "content": content, "stopReason": stop,
         "usage": usage or {"input": 100, "output": 10, "cacheRead": 50, "cacheWrite": 0, "reasoningTokens": 5,
                            "cost": {"total": 0.001}}}
    if error:
        m["errorMessage"] = error
    return {"type": "message_end", "message": m}


def call(cid, name, args=None):
    return {"type": "toolCall", "id": cid, "name": name, "arguments": args or {}}


def executed(cid, name, is_error=False):
    return [{"type": "tool_execution_start", "toolCallId": cid, "toolName": name, "args": {}},
            {"type": "tool_execution_end", "toolCallId": cid, "toolName": name, "result": {}, "isError": is_error}]


class ScanTest(unittest.TestCase):
    def test_p125_only_episode_is_valid_and_counted(self):
        events = [{"type": "session", "cwd": "/tmp/pixeltree_agent/x"},
                  assistant([call("a", "mcp__p125_observe")]), *executed("a", "mcp__p125_observe"),
                  assistant([{"type": "thinking", "thinking": "..."}, call("b", "mcp__p125_click", {"x": 1, "y": 2})]),
                  *executed("b", "mcp__p125_click"),
                  assistant([call("c", "mcp__p125_done", {"answer": "ok"})]), *executed("c", "mcp__p125_done"),
                  assistant([{"type": "text", "text": "finished"}], stop="stop"), {"type": "agent_end"}]
        s = omp.scan_events(events)
        self.assertFalse(omp.invalid(s))
        self.assertEqual(s["n_p125_calls"], 3)
        self.assertEqual(s["n_model_calls"], 4)
        self.assertEqual(s["tool_counts"], {"mcp__p125_observe": 1, "mcp__p125_click": 1, "mcp__p125_done": 1})
        self.assertEqual(s["usage"]["input_tokens"], 400)
        self.assertEqual(s["usage"]["reasoning_tokens"], 20)
        self.assertEqual(s["final_text"], "finished")
        self.assertTrue(s["has_end"])
        self.assertEqual(s["session_cwd"], "/tmp/pixeltree_agent/x")

    def test_any_non_p125_call_makes_the_episode_invalid_even_when_rejected(self):
        # the model asks for a tool that does not exist (OMP rejects it) and later for a near-miss MCP name
        events = [assistant([call("a", "mcp__p125_observe")]), *executed("a", "mcp__p125_observe"),
                  assistant([call("b", "bash", {"command": "cat /etc/hostname"})]), *executed("b", "bash", True),
                  assistant([call("c", "mcp__p125_read")]),
                  assistant([call("d", "mcp__p125_done", {"answer": "x"})]), *executed("d", "mcp__p125_done"),
                  {"type": "agent_end"}]
        s = omp.scan_events(events)
        self.assertTrue(omp.invalid(s))
        self.assertEqual([c["name"] for c in s["foreign_calls"]], ["bash", "mcp__p125_read"])
        self.assertEqual([(c["executed"], c["is_error"]) for c in s["foreign_calls"]], [(True, True), (False, None)])
        self.assertEqual(s["n_p125_calls"], 2)

    def test_provider_error_is_reported_and_recognised_as_quota(self):
        s = omp.scan_events([assistant([], stop="error", error="429 Too Many Requests: usage limit reached")])
        self.assertEqual(len(s["errors"]), 1)
        self.assertTrue(omp.is_quota_error(s["errors"][0]))
        self.assertFalse(omp.is_quota_error("ConnectionResetError: socket hang up"))


def row(task, cond, ok, stop="done", invalid=False, quota=False, attempt=1):
    r = {"task": task, "cond": cond, "rep": 0, "ok": ok, "stop_reason": stop, "invalid": invalid, "attempt": attempt,
         "steps": 5, "wall_s": 10.0, "foreign_calls": [{"name": "bash"}] if invalid else [], "omp_errors": [],
         "oracle_detail": ""}
    if quota:
        r.update(stop_reason="error", ok=False, omp_errors=["Weekly usage limit reached (429)"])
    return r


class SummaryTest(unittest.TestCase):
    def test_quota_rows_are_out_of_the_denominator_and_last_attempt_counts(self):
        rows = [row("t1", "T_ours", True),
                row("t2", "T_ours", False, quota=True, attempt=1), row("t2", "T_ours", True, attempt=2),
                row("t3", "T_ours", False, quota=True, attempt=1), row("t3", "T_ours", False, quota=True, attempt=2),
                row("t4", "T_ours", False),
                row("t5", "T_ours", True, invalid=True),
                row("t6", "T_ours", False, stop="error")]
        c = analyze.summarize(rows, ("T_ours",))["per_cond"]["T_ours"]
        # t1 ok, t2 ok on its retry, t3 only quota errors (out), t4 fail, t5 invalid (out), t6 harness error (out)
        self.assertEqual((c["ok"], c["valid"]), (2, 3))
        self.assertAlmostEqual(c["rate"], 2 / 3)
        self.assertEqual((c["quota"], c["error"], c["invalid"], c["invalid_ok"]), (1, 1, 1, 1))
        self.assertEqual(c["invalid_calls"], {"bash": 1})
        self.assertIsNone(c["ci"])                      # fewer than 48 tasks: no interval

    def test_pairs_use_tasks_valid_in_both_conditions(self):
        rows = [row("t1", "S_shot", True), row("t1", "T_ours", False),
                row("t2", "S_shot", False), row("t2", "T_ours", True),
                row("t3", "S_shot", True), row("t3", "T_ours", True),
                row("t4", "S_shot", True), row("t4", "T_ours", False, quota=True)]
        p = analyze.summarize(rows, ("S_shot", "T_ours"))["pairs"]["T_ours - S_shot"]
        self.assertEqual((p["n"], p["win"], p["loss"], p["tie"]), (3, 1, 1, 1))


class PostLimitTest(unittest.TestCase):
    def test_timeout_after_the_step_limit_counts_as_step_limit(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            Path(d, "step_limit.json").write_text("{}")
            looped = dict(row("t1", "T_ours", False, stop="timeout"), dir=d)
            slow = dict(row("t2", "T_ours", False, stop="timeout"), dir=str(Path(d, "none")))
            c = analyze.summarize([looped, slow], ("T_ours",))["per_cond"]["T_ours"]
        self.assertEqual((c["valid"], c["timeout"], c["post_limit_loops"]), (2, 1, 1))
        self.assertEqual(c["stop"], {"step_limit": 1, "timeout": 1})


class OrderedGateTest(unittest.TestCase):
    def test_calls_run_one_at_a_time_in_the_models_order(self):
        import random
        import threading
        import time
        from bench.shells.omp.mcp_server import OrderedGate

        # the model wrote: click, type, click, type, observe; the server threads start in scrambled order
        model = [(1, "click", {"x": 1, "y": 2}), (2, "type", {"text": "a"}), (3, "click", {"x": 3, "y": 4}),
                 (4, "type", {"text": "b"}), (5, "observe", {})]
        gate = OrderedGate(lambda: model, gather_s=0.05, fallback_s=2.0)
        order, active, peak = [], [0], [0]
        lock = threading.Lock()

        def work(name):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.01)
            with lock:
                order.append(name)
                active[0] -= 1

        calls = [("click", {"x": 1, "y": 2, "button": "left", "double": False}, "c1"), ("type", {"text": "a"}, "t1"),
                 ("click", {"x": 3, "y": 4, "button": "left", "double": False}, "c2"), ("type", {"text": "b"}, "t2"),
                 ("observe", {}, "o")]
        random.Random(3).shuffle(calls)
        threads = [threading.Thread(target=gate.run, args=(t, a, lambda n=n: work(n))) for t, a, n in calls]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(order, ["c1", "t1", "c2", "t2", "o"])
        self.assertEqual((peak[0], gate.fallbacks), (1, 0))

    def test_calls_queued_behind_a_long_batch_keep_their_order(self):
        import threading
        import time
        from bench.shells.omp.mcp_server import OrderedGate

        model = [(i + 1, "key", {"name": f"k{i}"}) for i in range(6)] + [(7, "observe", {})]
        gate = OrderedGate(lambda: model, gather_s=0.02, fallback_s=0.15)   # batch takes longer than fallback_s
        order = []
        calls = [("observe", {}, "o")] + [("key", {"name": f"k{i}"}, f"k{i}") for i in range(6)]
        threads = []
        for t, a, n in calls:
            th = threading.Thread(target=gate.run, args=(t, a, lambda n=n: (time.sleep(0.05), order.append(n))))
            th.start()
            threads.append(th)
            time.sleep(0.005)
        for th in threads:
            th.join()
        self.assertEqual(order, [f"k{i}" for i in range(6)] + ["o"])
        self.assertEqual(gate.fallbacks, 0)

    def test_without_a_log_the_gate_falls_back_to_running_the_call(self):
        from bench.shells.omp.mcp_server import OrderedGate

        gate = OrderedGate(lambda: [], gather_s=0.0, fallback_s=0.1)
        self.assertEqual(gate.run("observe", {}, lambda: "ran"), "ran")
        self.assertEqual(gate.fallbacks, 1)


class CalendarSkipTest(unittest.TestCase):
    def test_calendar_tasks_stop_after_nov_14_others_continue(self):
        cal, other = {"app": "gnome-calendar"}, {"app": "gitg"}
        self.assertFalse(run.skip_job(cal, today=20261114))
        self.assertTrue(run.skip_job(cal, today=20261115))
        self.assertFalse(run.skip_job(other, today=20261116))


if __name__ == "__main__":
    unittest.main()
