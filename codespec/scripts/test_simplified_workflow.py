"""Exercise artifact reduction without weakening archive and guard safety."""
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

from archive_change import apply_archive, capture_baseline, parse_incremental, plan_archive
from file_edit_guard import main as guard_main, scan_active
from test_archive_change import build_fixture, all_file_hashes


EVIDENCE = """# Tasks
- [x] 1.1 Implement password reset
## 验证记录
| 检查项 | 命令或证据 | 退出码 | 结果 |
| 测试 | python -m unittest | 0 | PASS |
结论: PASS
"""


class SimplifiedWorkflowTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.name = 'codespec-001-test'
        build_fixture(str(self.root), self.name)
        self.change = self.root / 'codespec' / 'changes' / self.name
        self.state = self.change / '.codespec.yaml'
        (self.change / 'tasks.md').write_text(EVIDENCE, encoding='utf-8')

    def optional_design(self):
        text = self.state.read_text(encoding='utf-8').replace('tier: full', 'tier: tweak')
        self.state.write_text(text + 'design_required: false\n', encoding='utf-8')
        (self.change / 'design.md').unlink()

    def assert_rejected_without_writes(self):
        before = all_file_hashes(str(self.root))
        plan = plan_archive(str(self.root), self.name)
        self.assertFalse(plan['ok'])
        self.assertEqual(before, all_file_hashes(str(self.root)))

    def test_legacy_tweak_state_is_rejected_without_writes(self):
        self.state.write_text(self.state.read_text(encoding='utf-8').replace('tier: full', 'tier: tweak'), encoding='utf-8')
        before = all_file_hashes(str(self.root))
        plan = plan_archive(str(self.root), self.name)
        self.assertFalse(plan['ok'])
        self.assertIn('状态 tier 必须为 full', plan['errors'])
        self.assertEqual(before, all_file_hashes(str(self.root)))

    def test_legacy_bugfix_state_is_rejected_without_writes(self):
        self.state.write_text(
            self.state.read_text(encoding='utf-8').replace('tier: full', 'tier: bugfix'),
            encoding='utf-8',
        )
        before = all_file_hashes(str(self.root))
        plan = plan_archive(str(self.root), self.name)
        self.assertFalse(plan['ok'])
        self.assertIn('状态 tier 必须为 full', plan['errors'])
        self.assertEqual(before, all_file_hashes(str(self.root)))

    def test_capture_baseline_rejects_legacy_tier_without_writes(self):
        self.state.write_text(self.state.read_text(encoding='utf-8').replace('tier: full', 'tier: tweak'), encoding='utf-8')
        before = all_file_hashes(str(self.root))
        with self.assertRaisesRegex(ValueError, '状态 tier 必须为 full'):
            capture_baseline(str(self.root), self.name)
        self.assertEqual(before, all_file_hashes(str(self.root)))

    def test_missing_design_without_opt_out_is_rejected(self):
        (self.change / 'design.md').unlink()
        self.assert_rejected_without_writes()

    def test_full_cannot_opt_out_of_design(self):
        self.state.write_text(self.state.read_text(encoding='utf-8') + 'design_required: false\n', encoding='utf-8')
        (self.change / 'design.md').unlink()
        before = all_file_hashes(str(self.root))
        plan = plan_archive(str(self.root), self.name)
        self.assertFalse(plan['ok'])
        self.assertIn('full 变更的 design_required 必须为 true', plan['errors'])
        self.assertEqual(before, all_file_hashes(str(self.root)))

    def test_opt_out_does_not_silently_ignore_existing_design(self):
        self.state.write_text(self.state.read_text(encoding='utf-8') + 'design_required: false\n', encoding='utf-8')
        before = all_file_hashes(str(self.root))
        plan = plan_archive(str(self.root), self.name)
        self.assertFalse(plan['ok'])
        self.assertIn('full 变更的 design_required 必须为 true', plan['errors'])
        self.assertEqual(before, all_file_hashes(str(self.root)))

    def test_tasks_are_required_even_when_state_says_pass(self):
        (self.change / 'tasks.md').unlink()
        self.assert_rejected_without_writes()

    def test_pending_task_prevents_archive(self):
        (self.change / 'tasks.md').write_text(EVIDENCE.replace('[x]', '[ ]'), encoding='utf-8')
        self.assert_rejected_without_writes()

    def test_verification_requires_actual_command_and_success(self):
        for evidence in (EVIDENCE.split('## 验证记录')[0],
                         EVIDENCE.replace('python -m unittest', '<实际命令>'),
                         EVIDENCE.replace('| 0 | PASS |', '| 1 | FAIL |'),
                         EVIDENCE.replace('结论: PASS', '结论: FAIL')):
            with self.subTest(evidence=evidence):
                (self.change / 'tasks.md').write_text(evidence, encoding='utf-8')
                self.assert_rejected_without_writes()

    def test_requirement_merge_excludes_change_context_after_delta(self):
        parsed = parse_incremental('## ADDED Requirements\n### Requirement: Reset\nBehavior\n## 变更说明\nPRIVATE_CONTEXT\n')
        self.assertNotIn('PRIVATE_CONTEXT', parsed['added'][0]['text'])

    def test_new_state_is_seen_by_guard(self):
        self.state.write_text('codespec: codespec-001\nphase: design\n', encoding='utf-8')
        self.assertEqual({self.name: 'design'}, scan_active(str(self.root)))

    def test_cli_archives_the_new_format_without_removed_documents(self):
        script = str(Path(__file__).with_name('archive_change.py'))
        for action in ('--capture-baseline', '--dry-run', '--apply'):
            run = subprocess.run([sys.executable, script, '--root', str(self.root),
                                  '--change', self.name, action], capture_output=True,
                                 encoding='utf-8', check=False)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            payload = json.loads(run.stdout)
            self.assertTrue(payload['ok'])
        archived = Path(payload['archive_path'])
        self.assertEqual({'spec.md', 'design.md', 'tasks.md'}, {p.name for p in archived.glob('*.md')})
        self.assertIn('archived: true', (archived / '.codespec.yaml').read_text(encoding='utf-8'))

    def test_mixed_state_formats_are_rejected(self):
        (self.change / '.ar.yaml').write_text('ar: AR-001\nphase: design\n', encoding='utf-8')
        self.assert_rejected_without_writes()

    def test_mixed_config_formats_are_rejected(self):
        legacy = self.root / 'codespec' / '.ar' / 'config.yaml'
        legacy.parent.mkdir()
        legacy.write_text('modules: []\n', encoding='utf-8')
        self.assert_rejected_without_writes()

    def test_manual_review_evidence_can_accompany_program_results(self):
        evidence = EVIDENCE.replace('结论: PASS', '| 审查 | review.txt:10 | N/A | PASS |\n结论: PASS')
        (self.change / 'tasks.md').write_text(evidence, encoding='utf-8')
        self.assertTrue(plan_archive(str(self.root), self.name)['ok'])

    def test_legacy_state_cannot_silently_disable_guard(self):
        self.state.rename(self.change / '.ar.yaml')
        payload = {'tool_name': 'Edit', 'tool_input': {'file_path': str(self.root / 'src' / 'app.py')}}
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', ['file_edit_guard.py']), mock.patch('sys.stdin', io.StringIO(json.dumps(payload))), mock.patch('sys.stdout', output), mock.patch.dict(os.environ, {'CODESPEC_GUARD_ROOT': str(self.root)}):
            guard_main()
        self.assertEqual('deny', json.loads(output.getvalue())['hookSpecificOutput']['permissionDecision'])

    def test_fenced_headings_do_not_truncate_requirements(self):
        delta = (self.change / 'spec.md').read_text(encoding='utf-8')
        delta += '\n```markdown\n## Sample heading\n### Requirement: Not a real requirement\n```\nTAIL_MUST_SURVIVE\n'
        (self.change / 'spec.md').write_text(delta, encoding='utf-8')
        plan = plan_archive(str(self.root), self.name)
        self.assertTrue(plan['ok'], plan.get('errors'))
        apply_archive(plan)
        spec = (self.root / 'codespec' / 'SPEC.md').read_text(encoding='utf-8')
        self.assertIn('TAIL_MUST_SURVIVE', spec)
        self.assertEqual(['找回密码'], list(plan['incremental']['added']['auth']))

    def test_duplicate_after_module_inheritance_is_rejected(self):
        delta = (self.change / 'spec.md').read_text(encoding='utf-8')
        delta += '\n## ADDED Requirements（模块：auth）\n### Requirement: 找回密码\nDifferent version\n'
        (self.change / 'spec.md').write_text(delta, encoding='utf-8')
        self.assert_rejected_without_writes()

    def test_failed_write_restores_original_crlf_bytes_and_baseline(self):
        master = self.root / 'codespec' / 'SPEC.md'
        master.write_bytes(master.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        before = master.read_bytes()
        capture_baseline(str(self.root), self.name)
        plan = plan_archive(str(self.root), self.name)
        real_replace = os.replace

        def fail_design(src, dst):
            if str(dst).endswith('DESIGN.md'):
                raise OSError('design write failed')
            return real_replace(src, dst)

        with mock.patch('archive_change.os.replace', side_effect=fail_design):
            with self.assertRaises(OSError):
                apply_archive(plan)
        self.assertEqual(before, master.read_bytes())
        self.assertTrue(plan_archive(str(self.root), self.name)['ok'])

    def test_alternative_bullet_pending_task_is_not_ignored(self):
        for bullet in ('*', '+', '1.'):
            with self.subTest(bullet=bullet):
                (self.change / 'tasks.md').write_text(EVIDENCE + '\n' + bullet + ' [ ] Still pending\n', encoding='utf-8')
                self.assert_rejected_without_writes()

    def test_windows_case_variant_still_protects_master_spec(self):
        from file_edit_guard import decide
        with mock.patch('file_edit_guard.os.name', 'nt'):
            self.assertFalse(decide('CodeSpec/spec.md', {})[0])

    def test_indented_or_malformed_state_does_not_disable_guard(self):
        from file_edit_guard import decide
        self.state.write_text('  codespec: codespec-001\n  phase: design\n', encoding='utf-8')
        self.assertFalse(decide('src/app.py', scan_active(str(self.root)))[0])
        self.state.write_text('invalid state content', encoding='utf-8')
        self.assertFalse(decide('src/app.py', scan_active(str(self.root)))[0])


if __name__ == '__main__':
    unittest.main()
