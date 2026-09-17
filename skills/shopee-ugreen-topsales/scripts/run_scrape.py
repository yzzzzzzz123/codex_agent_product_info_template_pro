"""Run the deterministic crawl phase for the AI-driven daily skill."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Sequence

from excel import write_excel
from scraper import (
    DEFAULT_CHROME,
    BrowserConfig,
    ScrapeError,
    scrape_all,
)


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
        help="主项目根目录；结果固定发布到 result/ugreen_topsales.xlsx",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无界面运行 Chrome；默认使用已验证的可见窗口模式",
    )
    parser.add_argument(
        "--detail-workers",
        type=int,
        default=4,
        metavar="N",
        help="同时访问详情页的 Page 数（默认：4）",
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
    print(f"[{stamp}] {message}", flush=True)


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


@contextmanager
def _exclusive_run_lock(path: Path):
    """Hold a project-wide lock for the whole crawl and publication."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("已有另一个每日抓取任务正在运行") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


async def _run(args: argparse.Namespace) -> Path:
    project_root = args.project_root
    output_dir = project_root / "result"
    output = output_dir / "ugreen_topsales.xlsx"
    if output_dir.exists():
        unexpected = [path for path in output_dir.iterdir() if path != output]
        if unexpected:
            names = ", ".join(sorted(path.name for path in unexpected))
            raise ValueError(f"result/ 包含非目标文件，请先处理：{names}")
    config = BrowserConfig(
        headless=bool(args.headless),
        detail_workers=args.detail_workers,
        chrome_executable=args.chrome_executable.expanduser(),
    )
    result = await scrape_all(config, progress=_progress)
    _progress(
        f"抓取校验通过：{result.audit.list_page_count} 页、"
        f"{len(result.products)} 个商品；开始写 Excel"
    )
    published = write_excel(result, output)
    if sorted(path.name for path in output_dir.iterdir()) != [output.name]:
        raise ValueError("发布后 result/ 未保持为单一 Excel 文件")
    return published


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
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
    print(f"完成：{output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
