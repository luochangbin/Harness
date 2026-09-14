# -*- coding: utf-8 -*-
"""Delivery Contract 一致性门禁测试。"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "delivery_contract_check.py")


def _document(body):
    return textwrap.dedent(body).strip() + "\n"


class DeliveryContractCheckTest(unittest.TestCase):
    def run_check(self, design, verification):
        with tempfile.TemporaryDirectory() as root:
            design_path = os.path.join(root, "design.md")
            verification_path = os.path.join(root, "verification.md")
            with open(design_path, "w", encoding="utf-8") as handle:
                handle.write(design)
            with open(verification_path, "w", encoding="utf-8") as handle:
                handle.write(verification)
            result = subprocess.run(
                [
                    sys.executable,
                    CHECKER,
                    "--design",
                    design_path,
                    "--verification",
                    verification_path,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        self.assertTrue(os.path.isfile(CHECKER), "缺少确定性的 Delivery Contract 门禁")
        payload = json.loads(result.stdout)
        return result, payload

    def design(self, *, command="npm run dev", entry="http://127.0.0.1:5173/",
               listener="127.0.0.1:5173", mode="keep-running"):
        return _document(f"""
            # AR-001 设计

            ## Delivery Contract（可运行交付契约）

            - 交付类型：service
            - 交付启动命令：`{command}`
            - 交付访问入口：`{entry}`
            - 监听/宿主约束：`{listener}`
            - 交付运行模式：{mode}
            - 视觉验收：n/a
            - 最小产物：单页应用
            - 用户可观察结果：页面可访问
            - 最低证据层级：浏览器冒烟
        """)

    def verification(self, *, command="npm run dev",
                     entry="http://127.0.0.1:5173/",
                     listener="127.0.0.1:5173", state="running"):
        return _document(f"""
            # AR-001 验证记录

            ## Delivery Evidence（交付证据）

            - 实际启动命令：`{command}`
            - 实际访问入口：`{entry}`
            - 实际监听/宿主：`{listener}`
            - 回复前运行状态：{state}
        """)

    def assert_rejected(self, result, payload, code):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(payload["ok"])
        self.assertIn(code, {item["code"] for item in payload["errors"]})

    def test_rejects_verification_command_with_uncontracted_host_arguments(self):
        result, payload = self.run_check(
            self.design(),
            self.verification(
                command="npm run dev -- --host 127.0.0.1 --port 5173 --strictPort"
            ),
        )
        self.assert_rejected(result, payload, "DELIVERY_COMMAND_MISMATCH")

    def test_rejects_ambiguous_localhost_listener(self):
        result, payload = self.run_check(
            self.design(
                entry="http://localhost:5173/",
                listener="localhost:5173",
            ),
            self.verification(
                entry="http://localhost:5173/",
                listener="localhost:5173",
            ),
        )
        self.assert_rejected(result, payload, "AMBIGUOUS_LOOPBACK_HOST")

    def test_rejects_access_entry_that_differs_from_actual_listener(self):
        result, payload = self.run_check(
            self.design(),
            self.verification(listener="[::1]:5173"),
        )
        self.assert_rejected(result, payload, "DELIVERY_LISTENER_MISMATCH")

    def test_required_visual_contract_cannot_omit_visual_evidence(self):
        design = self.design() + _document("""
            - 视觉验收：required
        """)
        result, payload = self.run_check(design, self.verification())
        self.assert_rejected(result, payload, "MISSING_VISUAL_EVIDENCE")
    def test_rejects_unverified_required_visual_evidence(self):
        verification = self.verification() + _document("""
            ## Visual Evidence（仅可见界面需要）
            - 是否需要视觉验证：yes
            - 实际查看工具与截图路径：N/A
            - 真实图像查看结果：NOT_VERIFIED
        """)
        result, payload = self.run_check(self.design(), verification)
        self.assert_rejected(result, payload, "VISUAL_NOT_VERIFIED")
    def test_keep_running_requires_live_process_before_handoff(self):
        result, payload = self.run_check(
            self.design(mode="keep-running"),
            self.verification(state="stopped"),
        )
        self.assert_rejected(result, payload, "DELIVERY_NOT_RUNNING")

    def test_accepts_exact_ipv4_service_evidence(self):
        result, payload = self.run_check(self.design(), self.verification())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["errors"], [])

    def test_start_on_demand_allows_stopped_process(self):
        result, payload = self.run_check(
            self.design(mode="start-on-demand"),
            self.verification(state="stopped"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])

    def test_runnable_delivery_cannot_bypass_lifecycle_with_na(self):
        result, payload = self.run_check(
            self.design(mode="N/A"),
            self.verification(state="N/A"),
        )
        self.assert_rejected(result, payload, "INVALID_DELIVERY_MODE")
        self.assertIn(
            "INVALID_RUNTIME_STATE",
            {item["code"] for item in payload["errors"]},
        )


    def test_runnable_delivery_must_declare_visual_contract(self):
        design = self.design().replace("- 视觉验收：n/a", "")
        result, payload = self.run_check(design, self.verification())
        self.assert_rejected(result, payload, "MISSING_VISUAL_CONTRACT")

    def test_required_visual_evidence_rejects_na_screenshot_path(self):
        design = self.design() + _document("""
            - 视觉验收：required
        """)
        verification = self.verification() + _document("""
            ## Visual Evidence（仅可见界面需要）
            - 是否需要视觉验证：yes
            - 实际查看工具与截图路径：N/A
            - 真实图像查看结果：PASS
        """)
        result, payload = self.run_check(design, verification)
        self.assert_rejected(result, payload, "MISSING_VISUAL_EVIDENCE")

    def test_desktop_app_requires_visual_contract(self):
        design = self.design().replace("- 交付类型：service", "- 交付类型：desktop-app")
        result, payload = self.run_check(design, self.verification())
        self.assert_rejected(result, payload, "VISUAL_CONTRACT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
