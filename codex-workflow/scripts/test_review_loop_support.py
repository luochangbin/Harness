# -*- coding: utf-8 -*-
"""review_loop_support 审核-修复循环状态机的确定性测试。

测试直接使用 templates/ar-yaml.md 与 templates/verification.md 真实模板，
并通过公开操作入口登记问题，不手工写内部状态（恢复对账场景除外）。
"""
import contextlib
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

import review_loop_support as rl

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
TEMPLATES = os.path.join(SKILL_ROOT, "templates")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


AR_TEMPLATE = _read(os.path.join(TEMPLATES, "ar-yaml.md"))
VERIFICATION_TEMPLATE = _read(os.path.join(TEMPLATES, "verification.md"))


def _set_field(text, field, value):
    return re.sub(r"(?m)^{}:\s*.*$".format(field), "{}: {}".format(field, value), text)


class ReviewLoopTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.addCleanup(self._td.cleanup)
        self.dir = os.path.join(self.root, "codespec", "changes", "AR-001-test")
        os.makedirs(self.dir)
        self.state = os.path.join(self.dir, ".ar.yaml")
        self.verification = os.path.join(self.dir, "verification.md")
        self.write_state()
        self.write_verification(VERIFICATION_TEMPLATE)

    def write_state(self, **overrides):
        text = AR_TEMPLATE
        for field, value in {"phase": "build", "worker_transport": "server",
                             "worker_executor": "opencode",
                             "worker_session_id": "ses_1",
                             "worker_agent": "ar-worker", **overrides}.items():
            text = _set_field(text, field, value)
        with open(self.state, "w", encoding="utf-8") as f:
            f.write(text)

    def write_verification(self, text):
        with open(self.verification, "w", encoding="utf-8") as f:
            f.write(text)

    def run_loop(self, *args):
        buffer = io.StringIO()
        argv = [args[0], "--root", self.root, "--change", "AR-001-test", *args[1:]]
        with contextlib.redirect_stdout(buffer):
            code = rl.main(argv)
        text = buffer.getvalue().strip()
        return code, (json.loads(text) if text else None)

    def control(self):
        return rl._read_control(self.root, "AR-001-test")

    def state_data(self):
        return rl.read_loop_state(self.root, "AR-001-test")

    def _begin(self, **kw):
        code, out = self.run_loop("begin", "--loop-id", "L1", **kw)
        assert code == 0, out
        return out

    def test_real_templates_initialize_and_register_issue(self):
        self._begin()
        code, out = self.run_loop("open", "--issues", "R1,R2")
        self.assertEqual(code, 0, out)
        self.assertEqual(set(out["issues"]), {"R1", "R2"})
        code, out = self.run_loop("reserve", "--loop-id", "L1", "--round", "0",
                                  "--dispatch-id", "L1:1", "--expected-revision", "5",
                                  "--issues", "R1,R2")
        self.assertEqual(code, 0, out)

    def test_old_verification_without_marker_is_initialized(self):
        self.write_verification("# 旧验证文档\n\n结论 PASS\n")
        self._begin()
        with open(self.verification, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(rl.MARKER_START, text)
        self.assertIn("旧验证文档", text)
        code, out = self.run_loop("inspect")
        self.assertEqual(code, 0, out)

    def test_begin_rejects_inapplicable_ar(self):
        for overrides in ({"archived": "true"}, {"worker_transport": "cli"},
                          {"worker_executor": "subagent"}, {"phase": "design"},
                          {"tier": "tweak"}, {"tier": "bugfix"}):
            self.write_state(**overrides)
            code, _ = self.run_loop("begin", "--loop-id", "L1")
            self.assertEqual(code, 2, overrides)

    def test_binding_change_after_begin_stops_reserve(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        self.write_state(worker_session_id="ses_2")
        code, _ = self.run_loop("reserve", "--loop-id", "L1", "--round", "0",
                                "--dispatch-id", "L1:1", "--expected-revision", "1",
                                "--issues", "R1")
        self.assertEqual(code, 2)

    def test_malformed_issue_entry_fails_closed(self):
        self.write_verification("""<!-- review-loop-state:start -->
{"issues":{"R1":"not-an-object"},"dispatches":{},"binding":null}
<!-- review-loop-state:end -->
""")
        code, out = self.run_loop("inspect")
        self.assertEqual(code, 2)
        self.assertIn("结构非法", out["error"])

    def test_cross_referenced_loop_state_fails_closed(self):
        self.write_verification("""<!-- review-loop-state:start -->
{"issues":{"R1":{"status":"resolved","attempts":1,"dispatch_ids":["L1:1"],"blocked_by":null}},"dispatches":{"L1:1":{"issues":["UNKNOWN"],"reviewed":true}},"binding":null}
<!-- review-loop-state:end -->
""")
        code, out = self.run_loop("inspect")
        self.assertEqual(code, 2)
        self.assertIn("未知问题", out["error"])

    def test_passed_review_records_source_fingerprint(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        self.run_loop("reserve", "--loop-id", "L1", "--round", "0", "--dispatch-id", "L1:1",
                      "--expected-revision", "1", "--issues", "R1")
        self.run_loop("accepted", "--dispatch-id", "L1:1")
        code, out = self.run_loop("reviewed", "--loop-id", "L1", "--dispatch-id", "L1:1",
                                  "--attempted", "R1", "--resolved", "R1")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "passed")
        fingerprint = self.state_data()["source_fingerprint"]
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")

    def test_historical_reviewed_result_does_not_clear_current_dispatch(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        self.run_loop("reserve", "--loop-id", "L1", "--round", "0", "--dispatch-id", "L1:1",
                      "--expected-revision", "1", "--issues", "R1")
        self.run_loop("accepted", "--dispatch-id", "L1:1")
        self.run_loop("reviewed", "--loop-id", "L1", "--dispatch-id", "L1:1", "--resolved", "")
        self.run_loop("reserve", "--loop-id", "L1", "--round", "1", "--dispatch-id", "L1:2",
                      "--expected-revision", "2", "--issues", "R1")
        code, out = self.run_loop("reviewed", "--loop-id", "L1", "--dispatch-id", "L1:1",
                                  "--resolved", "R1")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["duplicate"], True)
        self.assertEqual(self.control()["review_loop_dispatch_id"], "L1:2")
        self.assertEqual(self.control()["review_loop_status"], "dispatching")

    def test_cross_file_inconsistency_blocks_reserve_then_recovers(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        self.run_loop("reserve", "--loop-id", "L1", "--round", "0", "--dispatch-id", "L1:1",
                      "--expected-revision", "1", "--issues", "R1")
        # Simulate a half-write: verification holds the dispatch but control did not advance.
        rl._write_control(self.root, "AR-001-test",
                          {"review_loop_status": "reviewing", "review_loop_dispatch_id": None})
        code, _ = self.run_loop("reserve", "--loop-id", "L1", "--round", "0",
                                "--dispatch-id", "L1:2", "--expected-revision", "2",
                                "--issues", "R1")
        self.assertEqual(code, 2)
        code, out = self.run_loop("recover")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "dispatching")
        control = self.control()
        self.assertEqual(control["review_loop_dispatch_id"], "L1:1")
        self.assertEqual(control["review_loop_round"], 1)
        self.assertEqual(control["review_loop_expected_revision"], 1)

    def test_recover_waiting_requires_durable_acceptance_evidence(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        self.run_loop("reserve", "--loop-id", "L1", "--round", "0",
                      "--dispatch-id", "L1:1", "--expected-revision", "7",
                      "--issues", "R1")
        state = self.state_data()
        state["dispatches"]["L1:1"]["accepted"] = True
        rl.write_loop_state(self.root, "AR-001-test", state)
        code, out = self.run_loop("recover")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "waiting")
        control = self.control()
        self.assertEqual(control["review_loop_round"], 1)
        self.assertEqual(control["review_loop_expected_revision"], 7)

    def test_reviewed_rejects_dispatch_without_acceptance(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        self.run_loop("reserve", "--loop-id", "L1", "--round", "0",
                      "--dispatch-id", "L1:1", "--expected-revision", "1",
                      "--issues", "R1")
        code, out = self.run_loop("reviewed", "--loop-id", "L1",
                                  "--dispatch-id", "L1:1",
                                  "--attempted", "R1", "--resolved", "R1")
        self.assertEqual(code, 2)
        self.assertIn("accepted", out["error"])

    def test_command_execution_serializes_same_ar_mutations(self):
        barrier = threading.Barrier(2)
        gate = threading.Event()
        active = 0
        maximum = 0
        results = []
        guard = threading.Lock()
        ns = SimpleNamespace(command="begin", root=self.root,
                             change="AR-001-test")

        def handler(_):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            gate.set()
            time.sleep(0.15)
            with guard:
                active -= 1
            return {"ok": True}

        def invoke():
            barrier.wait()
            try:
                results.append(rl.execute_command(ns, handler))
            except ValueError as error:
                results.append(error)

        threads = [threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads:
            thread.start()
        gate.wait(1)
        for thread in threads:
            thread.join()
        self.assertEqual(maximum, 1)
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertEqual(sum(isinstance(item, ValueError) for item in results), 1)

    def test_ordinary_verification_markdown_changes_source_fingerprint(self):
        path = os.path.join(self.root, "docs", "verification.md")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as file:
            file.write("before")
        before = rl.source_fingerprint(self.root, "AR-001-test")
        with open(path, "w", encoding="utf-8") as file:
            file.write("after")
        self.assertNotEqual(before, rl.source_fingerprint(self.root, "AR-001-test"))

    def test_active_ar_control_files_do_not_change_source_fingerprint(self):
        before = rl.source_fingerprint(self.root, "AR-001-test")
        with open(self.state, "a", encoding="utf-8") as file:
            file.write("\nreview_loop_status: paused\n")
        with open(self.verification, "a", encoding="utf-8") as file:
            file.write("\nreview output\n")
        self.assertEqual(before, rl.source_fingerprint(self.root, "AR-001-test"))

    def test_symlink_target_change_changes_source_fingerprint(self):
        first = os.path.join(self.root, "first.py")
        second = os.path.join(self.root, "second.py")
        link = os.path.join(self.root, "alias.py")
        with open(first, "w", encoding="utf-8") as file:
            file.write("same")
        with open(second, "w", encoding="utf-8") as file:
            file.write("same")
        try:
            os.symlink(first, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest("symlink unavailable: {}".format(error))
        before = rl.source_fingerprint(self.root, "AR-001-test")
        os.unlink(link)
        os.symlink(second, link)
        self.assertNotEqual(before, rl.source_fingerprint(self.root, "AR-001-test"))

    def test_duplicate_issue_ids_are_rejected(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        code, _ = self.run_loop("reserve", "--loop-id", "L1", "--round", "0",
                                "--dispatch-id", "L1:1", "--expected-revision", "1",
                                "--issues", "R1,R1")
        self.assertEqual(code, 2)

    def test_attempts_count_success_and_failure_but_not_unprocessed(self):
        self._begin()
        self.run_loop("open", "--issues", "R1,R2")
        self.run_loop("reserve", "--loop-id", "L1", "--round", "0", "--dispatch-id", "L1:1",
                      "--expected-revision", "1", "--issues", "R1,R2")
        self.run_loop("accepted", "--dispatch-id", "L1:1")
        self.run_loop("reviewed", "--loop-id", "L1", "--dispatch-id", "L1:1",
                      "--attempted", "R1", "--resolved", "R1")
        issues = self.state_data()["issues"]
        self.assertEqual((issues["R1"]["attempts"], issues["R1"]["status"]), (1, "resolved"))
        self.assertEqual((issues["R2"]["attempts"], issues["R2"]["status"]), (0, "open"))

    def test_third_unresolved_attempt_defers_and_needs_user(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        for attempt in range(3):
            code, _ = self.run_loop("reserve", "--loop-id", "L1", "--round", str(attempt),
                                    "--dispatch-id", "L1:{}".format(attempt + 1),
                                    "--expected-revision", "1", "--issues", "R1")
            self.assertEqual(code, 0)
            self.run_loop("accepted", "--dispatch-id",
                          "L1:{}".format(attempt + 1))
            code, out = self.run_loop("reviewed", "--loop-id", "L1",
                                      "--dispatch-id", "L1:{}".format(attempt + 1),
                                      "--attempted", "R1", "--resolved", "")
            self.assertEqual(code, 0, out)
        self.assertEqual(self.state_data()["issues"]["R1"]["status"], "deferred")
        self.assertEqual(out["status"], "needs_user")
        code, _ = self.run_loop("pass")
        self.assertEqual(code, 2, "deferred issue must not be passable")

    def test_reserve_rechecks_applicability_after_begin(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        self.write_state(phase="archive", archived="true")
        code, _ = self.run_loop("reserve", "--loop-id", "L1", "--round", "0",
                                "--dispatch-id", "L1:1", "--expected-revision", "1",
                                "--issues", "R1")
        self.assertEqual(code, 2)

    def test_explicit_empty_attempted_counts_nothing(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        self.run_loop("reserve", "--loop-id", "L1", "--round", "0", "--dispatch-id", "L1:1",
                      "--expected-revision", "1", "--issues", "R1")
        self.run_loop("accepted", "--dispatch-id", "L1:1")
        code, out = self.run_loop("reviewed", "--loop-id", "L1", "--dispatch-id", "L1:1",
                                  "--attempted", "", "--resolved", "")
        self.assertEqual(code, 0, out)
        entry = self.state_data()["issues"]["R1"]
        self.assertEqual(entry["attempts"], 0)
        self.assertEqual(entry["status"], "open")

    def test_pass_resume_and_reopen_flow(self):
        self._begin()
        self.run_loop("open", "--issues", "R1")
        code, _ = self.run_loop("pass")
        self.assertEqual(code, 2)  # R1 still open
        self.run_loop("pause", "--reason", "waiting user")
        code, out = self.run_loop("resume")
        self.assertEqual(code, 0, out)
        self.run_loop("block", "--issue", "R1", "--by", "R9")
        code, _ = self.run_loop("reserve", "--loop-id", "L1", "--round", "0",
                                "--dispatch-id", "L1:1", "--expected-revision", "1",
                                "--issues", "R1")
        self.assertEqual(code, 2)
        self.run_loop("reopen", "--issue", "R1")
        code, _ = self.run_loop("reserve", "--loop-id", "L1", "--round", "0",
                                "--dispatch-id", "L1:1", "--expected-revision", "1",
                                "--issues", "R1")
        self.assertEqual(code, 0)

    def test_dependency_release_reopen_allows_reserve(self):
        self._begin()
        self.run_loop("open", "--issues", "R1,R2")
        self.run_loop("block", "--issue", "R2", "--by", "R1")
        self.run_loop("reserve", "--loop-id", "L1", "--round", "0", "--dispatch-id", "L1:1",
                      "--expected-revision", "1", "--issues", "R1")
        self.run_loop("accepted", "--dispatch-id", "L1:1")
        code, out = self.run_loop("reviewed", "--loop-id", "L1", "--dispatch-id", "L1:1",
                                  "--attempted", "R1", "--resolved", "R1")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "needs_user")
        code, out = self.run_loop("reopen", "--issue", "R2")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["loop_status"], "reviewing")
        self.assertEqual(self.control()["review_loop_status"], "reviewing")
        code, out = self.run_loop("reserve", "--loop-id", "L1", "--round", "1",
                                  "--dispatch-id", "L1:2", "--expected-revision", "2",
                                  "--issues", "R2")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state_data()["issues"]["R2"]["attempts"], 0)

    def test_marker_duplication_fails_closed(self):
        self._begin()
        self.write_verification(VERIFICATION_TEMPLATE + VERIFICATION_TEMPLATE)
        code, _ = self.run_loop("inspect")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
