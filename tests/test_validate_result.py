"""离线验证每日结果绑定；不读取真实工作簿、不创建真实 Git worktree。"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/shopee-ugreen-topsales/scripts"
sys.path.insert(0, str(SCRIPTS))
import validate_result as validator  # noqa: E402


class ValidateResultTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve() / "project"
        self.daily = self.root / "worktrees/20260917_ugreen_topsales"
        self.daily.mkdir(parents=True)
        self.output = self.daily / "result/ugreen_topsales.xlsx"
        self.output.parent.mkdir()
        self.output.write_bytes(b"new daily workbook")
        self.old_output = self.root / "result/ugreen_topsales.xlsx"
        self.old_output.parent.mkdir()
        self.old_output.write_bytes(b"old main workbook")
        self.stats = SimpleNamespace(
            product_count=2,
            sku_count=3,
            main_image_count=2,
            secondary_image_count=4,
            audit_status="通过",
            collection_mode="full_topsales",
        )

    def git(self, cwd, *args, **kwargs):
        if args == ("rev-parse", "--show-toplevel"):
            output = str(self.daily) + "\n"
        elif args == ("worktree", "list", "--porcelain", "-z"):
            output = f"worktree {self.root}\0HEAD abc\0\0worktree {self.daily}\0HEAD def\0\0"
        else:
            self.fail(f"校验器使用了非预期 Git 命令：{args}")
        return subprocess.CompletedProcess(["git", *args], 0, stdout=output, stderr="")

    def invoke(self, *, root=None, daily=None, project_root=None, git=None, stats=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(validator, "_project_root", side_effect=project_root or (lambda path: self.root)), patch.object(validator, "_git", side_effect=git or self.git), patch.object(validator, "validate_excel", return_value=stats or self.stats) as validate, redirect_stdout(out), redirect_stderr(err):
            code = validator.main([
                "--project-root", str(root or self.root),
                "--worktree", str(daily or self.daily),
            ])
        return code, out.getvalue(), err.getvalue(), validate

    def assert_rejected(self, expected, **kwargs):
        code, out, err, validate = self.invoke(**kwargs)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn(expected, err)
        validate.assert_not_called()
        self.assertEqual(self.old_output.read_bytes(), b"old main workbook")

    def test_success_reads_only_daily_workbook_and_reports_path(self):
        code, out, err, validate = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), {
            "path": str(self.output),
            "collection_mode": "full_topsales",
            "product_count": 2,
            "sku_count": 3,
            "main_image_count": 2,
            "secondary_image_count": 4,
            "audit_status": "通过",
        })
        validate.assert_called_once_with(self.output)
        self.assertEqual(self.output.read_bytes(), b"new daily workbook")
        self.assertEqual(self.old_output.read_bytes(), b"old main workbook")

    def test_known_detail_scope_is_reported_without_claiming_full_topsales(self):
        self.stats.collection_mode = "known_product_details"
        code, out, _, _ = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["collection_mode"], "known_product_details")

    def test_main_result_cannot_substitute_missing_daily_workbook(self):
        self.output.unlink()
        self.assert_rejected("不会读取主项目历史结果")
        self.assertFalse(self.output.exists())

    def test_missing_result_directory_is_not_created(self):
        self.output.unlink()
        self.output.parent.rmdir()
        self.assert_rejected("找不到指定 worktree 的工作簿")
        self.assertFalse(self.output.parent.exists())

    def test_old_or_future_valid_worktree_dates_are_allowed(self):
        for name in ("20240229_ugreen_topsales", "20260101_ugreen_topsales", "20270918_ugreen_topsales"):
            with self.subTest(name=name):
                self.daily = self.daily.rename(self.daily.with_name(name))
                self.output = self.daily / "result/ugreen_topsales.xlsx"
                code, out, err, validate = self.invoke()
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)["path"], str(self.output))
                validate.assert_called_once_with(self.output)

    def test_bad_directory_name_or_date_rejected(self):
        cases = (
            ("20260230_ugreen_topsales", "日期无效"),
            ("20261301_ugreen_topsales", "日期无效"),
            ("00000101_ugreen_topsales", "日期无效"),
            ("2026-09-17_ugreen_topsales", "目录名必须"),
            ("20260917_other", "目录名必须"),
            ("２０２６０９１７_ugreen_topsales", "目录名必须"),
        )
        for name, expected in cases:
            with self.subTest(name=name):
                self.assert_rejected(expected, daily=self.daily.with_name(name))

    def test_missing_worktree_directory_rejected_without_creation(self):
        missing = self.daily.with_name("20260918_ugreen_topsales")
        self.assert_rejected("找不到指定每日 worktree", daily=missing)
        self.assertFalse(missing.exists())

    def test_literal_parent_traversal_rejected_for_both_arguments(self):
        self.assert_rejected("不能包含 ..", daily=self.daily / "../20260917_ugreen_topsales")
        self.assert_rejected("不能包含 ..", root=self.root / "../project")

    def test_external_or_nested_or_main_path_cannot_be_worktree(self):
        for candidate in (self.root, self.root.parent / self.daily.name, self.root / "worktrees/nested" / self.daily.name):
            with self.subTest(path=candidate):
                self.assert_rejected("必须位于主项目", daily=candidate)

    def test_project_argument_must_be_main_repository_root(self):
        nested = self.root / "nested"
        nested.mkdir()
        self.assert_rejected("必须指向主项目 Git 根目录", root=nested)

    def test_foreign_repository_worktree_rejected(self):
        self.assert_rejected("不属于主项目 Git 仓库", project_root=lambda path: self.root if path == self.root else self.root.parent / "foreign")

    def test_plain_subdirectory_cannot_masquerade_as_worktree(self):
        def git(cwd, *args, **kwargs):
            if args == ("rev-parse", "--show-toplevel"):
                return subprocess.CompletedProcess(["git", *args], 0, stdout=str(self.root) + "\n", stderr="")
            return self.git(cwd, *args, **kwargs)

        self.assert_rejected("不是独立的 Git worktree", git=git)

    def test_unregistered_worktree_rejected(self):
        def git(cwd, *args, **kwargs):
            result = self.git(cwd, *args, **kwargs)
            if args[0] == "worktree":
                result.stdout = f"worktree {self.root}\0HEAD abc\0\0"
            return result

        self.assert_rejected("未在主项目 Git 仓库注册", git=git)

    def test_git_failure_is_reported_without_traceback(self):
        def git(cwd, *args, **kwargs):
            raise validator.WorktreeError("Git 关联检查失败")

        self.assert_rejected("Git 关联检查失败", git=git)

    def test_worktree_symlink_is_rejected(self):
        link = self.daily.with_name("20260918_ugreen_topsales")
        link.symlink_to(self.daily, target_is_directory=True)
        self.assert_rejected("不能是符号链接", daily=link)

    def test_worktrees_directory_symlink_is_rejected(self):
        saved = self.root / "saved_worktrees"
        self.daily.parent.rename(saved)
        (self.root / "worktrees").symlink_to(saved, target_is_directory=True)
        self.assert_rejected("worktrees 目录不能是符号链接")

    def test_result_directory_symlink_is_rejected(self):
        self.output.unlink()
        self.output.parent.rmdir()
        self.output.parent.symlink_to(self.old_output.parent, target_is_directory=True)
        self.assert_rejected("结果目录和工作簿不能是符号链接")

    def test_result_file_symlink_is_rejected_even_if_broken(self):
        self.output.unlink()
        self.output.symlink_to(self.old_output)
        self.assert_rejected("结果目录和工作簿不能是符号链接")
        self.output.unlink()
        self.output.symlink_to(self.root / "missing.xlsx")
        self.assert_rejected("结果目录和工作簿不能是符号链接")

    def test_unknown_result_file_rejected_without_deletion(self):
        extra = self.output.parent / "notes.txt"
        extra.write_text("preserve", encoding="utf-8")
        self.assert_rejected("只能包含 ugreen_topsales.xlsx")
        self.assertEqual(extra.read_text(encoding="utf-8"), "preserve")

    def test_audit_failure_returns_two(self):
        self.stats.audit_status = "未通过"
        code, out, err, validate = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("审计状态不是", err)
        validate.assert_called_once_with(self.output)

    def test_invalid_excel_returns_two(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(validator, "_project_root", return_value=self.root), patch.object(validator, "_git", side_effect=self.git), patch.object(validator, "validate_excel", side_effect=ValueError("工作簿结构错误")), redirect_stdout(out), redirect_stderr(err):
            code = validator.main(["--project-root", str(self.root), "--worktree", str(self.daily)])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("工作簿结构错误", err.getvalue())

    def test_both_cli_arguments_are_required(self):
        for args in ([], ["--project-root", str(self.root)], ["--worktree", str(self.daily)]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                validator.main(args)
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
