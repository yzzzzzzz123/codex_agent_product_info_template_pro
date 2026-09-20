"""Run the deterministic crawl phase for the AI-driven daily skill."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import math
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from excel import write_excel
from browser_fingerprint import APPROVED_PROFILE_IDS
from scraper import (
    DEFAULT_CHROME,
    BrowserConfig,
    ScrapeError,
    scrape_all,
    scrape_known_details,
    verify_access,
)


def _slow_interval_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("访问间隔必须是至少 10 秒的数字") from exc
    if not math.isfinite(seconds) or seconds < 10:
        raise argparse.ArgumentTypeError("访问间隔必须至少为 10 秒；只允许调慢")
    return seconds


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_scrape.py",
        description=(
            "抓取 Shopee Philippines UGREEN 店铺 Top Sales 的全部列表页与全部商品详情页，"
            "最终只写出 Excel。"
        ),
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="主项目根目录；结果仅写启动日 worktrees/YYYYMMDD_ugreen_topsales/result/ugreen_topsales.xlsx",
    )
    parser.add_argument(
        "--verify-access",
        action="store_true",
        help="只验证列表及跨页商品详情访问，不创建 worktree、不生成或覆盖 Excel",
    )
    parser.add_argument(
        "--manual-access", "--manual-list-handoff",
        dest="manual_list_handoff",
        action="store_true",
        help="访问复测或全量：遇到验证保留窗口，用户处理后终端输入 resume；正常页面自动验收继续",
    )
    parser.add_argument(
        "--historical-list-preflight",
        action="store_true",
        help="复现历史顺序：同一临时profile先严校验第2页，再从第1页开始；预访问不计入全量",
    )
    parser.add_argument(
        "--refresh-known-products",
        action="store_true",
        help="按明确参考工作簿的全部唯一商品链接刷新详情；不访问列表，不复用旧指标",
    )
    parser.add_argument(
        "--confirm-no-new-products",
        action="store_true",
        help="用户已确认本次没有新增商品；已知清单详情全量发布必须显式提供",
    )
    parser.add_argument(
        "--reference-workbook",
        type=Path,
        help="复测的 URL 来源，或已知商品详情刷新必须明确指定的清单来源",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无界面运行 Chrome；默认使用已验证的可见窗口模式",
    )
    parser.add_argument(
        "--detail-shards",
        "--detail-workers",
        dest="detail_shards",
        type=int,
        default=1,
        metavar="N",
        help="独立临时 Chrome 档案/详情分片数（默认：1，慢速串行）",
    )
    parser.add_argument(
        "--list-interval-seconds",
        type=_slow_interval_seconds,
        default=10.0,
        metavar="SECONDS",
        help="列表页之间的间隔秒数，至少 10 秒（默认：10）",
    )
    parser.add_argument(
        "--detail-interval-seconds",
        type=_slow_interval_seconds,
        default=10.0,
        metavar="SECONDS",
        help="详情完成验收并离开页面后的间隔秒数，至少 10 秒（默认：10）",
    )
    parser.add_argument(
        "--browser-profile",
        choices=("auto", *APPROVED_PROFILE_IDS),
        default="auto",
        help="每轮从已审阅配置中随机选择一次；也可指定配置，运行中不会切换",
    )
    parser.add_argument(
        "--chrome-executable",
        type=Path,
        default=DEFAULT_CHROME,
        help=f"Google Chrome 可执行文件（默认：{DEFAULT_CHROME}）",
    )
    return parser


def _progress(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", file=sys.stderr, flush=True)


def _bound_project_root(value: Path) -> Path:
    """Bind publication to this skill's primary Git repository."""

    provided = value.expanduser().resolve()
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(Path(__file__).resolve().parent),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"无法确定 Skill 所属主项目：{detail}")
    common_dir = Path(completed.stdout.strip()).resolve()
    expected = common_dir.parent
    if common_dir.name != ".git" or not (expected / ".git").is_dir():
        raise ValueError(f"不支持的 Git 主项目布局：{common_dir}")
    if provided != expected:
        raise ValueError(
            f"--project-root 必须是当前 Skill 的主项目：{expected}"
        )
    return expected


def _git_read(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"Git 只读检查失败（{' '.join(args)}）：{detail}")
    return completed.stdout.strip()


def _validate_daily_run(project_root: Path, run_date: date | None = None) -> None:
    """Only publish from today's clean, reviewed worktree; never change Git state."""

    run_date = run_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    compact = run_date.strftime("%Y%m%d")
    worktrees = project_root / "worktrees"
    worktree = worktrees / f"{compact}_ugreen_topsales"
    if worktrees.is_symlink() or worktree.is_symlink():
        raise ValueError("每日 worktree 路径不能是符号链接")
    expected_runner = worktree / "skills/shopee-ugreen-topsales/scripts/run_scrape.py"
    if Path(__file__).resolve() != expected_runner.resolve():
        raise ValueError(
            f"完整抓取必须从上海当天的每日 worktree 运行：{expected_runner}；"
            "当前开发代码只能使用 --verify-access 验证，不可发布"
        )
    if Path(_git_read(worktree, "rev-parse", "--show-toplevel")).resolve() != worktree.resolve():
        raise ValueError("每日目录不是预期 Git worktree")
    expected_branch = f"daily/{compact}-ugreen-topsales"
    actual_branch = _git_read(worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
    if actual_branch != expected_branch:
        raise ValueError(f"每日 worktree 分支不符；预期 {expected_branch}")
    for label, root in (("主项目", project_root), ("每日 worktree", worktree)):
        if _git_read(root, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError(f"{label}存在未提交改动；请先人工审阅处理，程序不会修改 Git 状态")
    if _git_read(project_root, "rev-parse", "HEAD") != _git_read(worktree, "rev-parse", "HEAD"):
        raise ValueError("主项目与每日 worktree 的 HEAD 不一致；请人工处理")


@contextmanager
def _exclusive_run_lock(path: Path):
    """Hold a project-wide lock for the whole crawl and publication."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("已有另一个抓取或访问验证任务正在运行") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _check_output_directory(output: Path) -> None:
    output_dir = output.parent
    if output_dir.is_symlink() or output.is_symlink():
        raise ValueError("每日 result 目录和目标 Excel 不能是符号链接")
    if output_dir.exists():
        unexpected = [path for path in output_dir.iterdir() if path != output]
        if unexpected:
            names = ", ".join(sorted(path.name for path in unexpected))
            raise ValueError(f"result/ 包含非目标文件，请先处理：{names}")


def _default_reference(project_root: Path, run_date: date) -> Path:
    """只读选择最近已有的每日表；旧主目录表仅作迁移期链接参考。"""
    worktrees = project_root / "worktrees"
    if worktrees.is_symlink():
        raise ValueError("worktrees 目录不能是符号链接")
    candidates: list[tuple[date, Path]] = []
    if worktrees.is_dir():
        for directory in worktrees.iterdir():
            match = re.fullmatch(r"(\d{8})_ugreen_topsales", directory.name)
            if not match or directory.is_symlink() or not directory.is_dir():
                continue
            compact = match[1]
            try:
                candidate_date = date.fromisoformat(
                    f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"
                )
            except ValueError:
                continue
            target = directory / "result/ugreen_topsales.xlsx"
            if (candidate_date <= run_date and target.is_file()
                    and not target.parent.is_symlink() and not target.is_symlink()):
                candidates.append((candidate_date, target))
    if candidates:
        return max(candidates, key=lambda value: value[0])[1]
    legacy = project_root / "result/ugreen_topsales.xlsx"
    if legacy.is_file() and not legacy.parent.is_symlink() and not legacy.is_symlink():
        return legacy
    raise FileNotFoundError(
        "未找到可用历史工作簿；请用 --reference-workbook 显式指定用于复测的已有表，"
        "不会创建或复制旧表充当当天结果"
    )


def _validate_mode_args(args: argparse.Namespace) -> None:
    if args.manual_list_handoff:
        if args.headless or args.detail_shards != 1 or args.historical_list_preflight:
            raise ValueError("--manual-access 需要可见窗口、单路采集，不能同时启用历史预访问")
        if not sys.stdin.isatty():
            raise ValueError("人工接管必须在可交互终端运行，等待用户确认后输入 resume")
    if args.reference_workbook is not None and not (args.verify_access or args.refresh_known_products):
        raise ValueError("--reference-workbook 只能与 --verify-access 或 --refresh-known-products 一起使用")
    if args.confirm_no_new_products and not args.refresh_known_products:
        raise ValueError("--confirm-no-new-products 只能与 --refresh-known-products 一起使用")
    if args.refresh_known_products:
        if args.reference_workbook is None:
            raise ValueError("已知商品详情刷新必须用 --reference-workbook 指定完整清单来源")
        if args.historical_list_preflight:
            raise ValueError("已知商品详情刷新不访问列表，不能同时启用 --historical-list-preflight")
        if args.detail_shards != 1:
            raise ValueError("已知商品详情刷新只允许单路慢速访问")
        if not args.verify_access and not args.confirm_no_new_products:
            raise ValueError("发布已知商品详情前必须有用户无新增确认，并显式传入 --confirm-no-new-products")


async def _run(args: argparse.Namespace) -> Path | dict:
    _validate_mode_args(args)
    run_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    project_root = args.project_root
    worktree = project_root / "worktrees" / f"{run_date:%Y%m%d}_ugreen_topsales"
    output_dir = worktree / "result"
    output = output_dir / "ugreen_topsales.xlsx"
    config = BrowserConfig(
        headless=bool(args.headless),
        detail_shards=args.detail_shards,
        chrome_executable=args.chrome_executable.expanduser(),
        browser_profile=args.browser_profile,
        list_interval_ms=round(args.list_interval_seconds * 1_000),
        detail_interval_ms=round(args.detail_interval_seconds * 1_000),
        historical_list_preflight=args.historical_list_preflight,
        manual_list_handoff=args.manual_list_handoff,
    )
    if args.verify_access:
        reference = (args.reference_workbook or _default_reference(project_root, run_date)).expanduser().resolve()
        if args.refresh_known_products:
            return await verify_access(config, reference, progress=_progress, details_only=True)
        return await verify_access(config, reference, progress=_progress)

    _validate_daily_run(project_root, run_date)
    _check_output_directory(output)
    if args.refresh_known_products:
        reference = args.reference_workbook.expanduser().resolve()
        if reference == output.resolve():
            raise ValueError("参考清单不能是本次将覆盖的目标工作簿；请选择保留不变的历史文件")
        result = await scrape_known_details(
            config, reference, no_new_products_confirmed=args.confirm_no_new_products,
            progress=_progress,
        )
        _progress(f"已知清单详情校验通过：{len(result.products)} 个商品；未重新采集列表，开始写 Excel")
    else:
        result = await scrape_all(config, progress=_progress)
        _progress(
            f"抓取校验通过：{result.audit.list_page_count} 页、"
            f"{len(result.products)} 个商品；开始写 Excel"
        )
    _validate_daily_run(project_root, run_date)
    _check_output_directory(output)
    published = write_excel(result, output)
    if sorted(path.name for path in output_dir.iterdir()) != [output.name]:
        raise ValueError("发布后 result/ 未保持为单一 Excel 文件")
    return published


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _validate_mode_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        project_root = _bound_project_root(args.project_root)
        args.project_root = project_root
        with _exclusive_run_lock(project_root / ".git/ugreen_daily_run.lock"):
            output = asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("已中止；未覆盖已有 Excel。", file=sys.stderr)
        return 130
    except (ScrapeError, ValueError, FileNotFoundError, OSError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.verify_access:
        if not isinstance(output, dict):
            print("失败：访问验证未返回有效摘要", file=sys.stderr)
            return 1
        if (
            output.get("mode") != "verify_access"
            or output.get("full_crawl_completed") is not False
            or output.get("workbook_written") is not False
        ):
            print("失败：访问验证摘要违反不发布边界", file=sys.stderr)
            return 1
        print(json.dumps(output, ensure_ascii=False))
        print("访问验证结束：这不是完整抓取，本次未生成或覆盖 Excel。", file=sys.stderr)
        attempted = output.get("detail_attempted_count")
        success = output.get("detail_success_count")
        target = output.get("detail_target_count")
        listing_requirement_met = (
            output.get("details_only") is True
            and output.get("list_skipped") is True
            and output.get("list_pass") is None
            and output.get("list_pages_checked") == 0
        ) if args.refresh_known_products else (
            output.get("list_pass") is True and output.get("list_skipped") is not True
        )
        passed = (
            listing_requirement_met
            and all(isinstance(value, int) and not isinstance(value, bool) for value in (attempted, success, target))
            and attempted > 0
            and success == attempted == target
        )
        return 0 if passed else 2
    label = "已知清单详情刷新完成" if args.refresh_known_products else "完成"
    print(f"{label}：{output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
