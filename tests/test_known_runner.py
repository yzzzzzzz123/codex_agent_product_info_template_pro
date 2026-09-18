"""已知清单模式的入口/发布隔离；所有采集和发布均 mock。"""

import asyncio
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/shopee-ugreen-topsales/scripts"))
import run_scrape as runner


class KnownRunnerTests(unittest.TestCase):
    def args(self, root, *extra):
        return runner._parser().parse_args(["--project-root", str(root), *extra])

    def test_known_mode_requires_explicit_reference_and_publication_confirmation(self):
        invalid = (
            ["--refresh-known-products"],
            ["--refresh-known-products", "--reference-workbook", "/old.xlsx"],
            ["--confirm-no-new-products"],
            ["--refresh-known-products", "--verify-access", "--reference-workbook", "/old.xlsx", "--historical-list-preflight"],
            ["--refresh-known-products", "--verify-access", "--reference-workbook", "/old.xlsx", "--detail-shards", "2"],
        )
        for options in invalid:
            with self.subTest(options=options), patch.object(runner, "_bound_project_root") as bind, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    runner.main(["--project-root", "/fixture", *options])
                bind.assert_not_called()

    def test_known_verify_only_calls_details_only_and_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.xlsx"
            with (
                patch.object(runner, "verify_access", new=AsyncMock(return_value={"mode": "verify_access"})) as verify,
                patch.object(runner, "scrape_all", new_callable=AsyncMock) as listing,
                patch.object(runner, "scrape_known_details", new_callable=AsyncMock) as full,
                patch.object(runner, "write_excel") as publish,
                patch.object(runner, "_validate_daily_run") as daily,
            ):
                asyncio.run(runner._run(self.args(root, "--verify-access", "--refresh-known-products", "--reference-workbook", str(reference))))
            self.assertTrue(verify.await_args.kwargs["details_only"])
            self.assertEqual(verify.await_args.args[1], reference.resolve())
            listing.assert_not_called()
            full.assert_not_called()
            publish.assert_not_called()
            daily.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_known_full_preserves_daily_publication_gates_and_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.xlsx"
            reference.write_bytes(b"unchanged historical input")
            result = SimpleNamespace(products=[object(), object()])
            events = []

            async def collect(config, source, **kwargs):
                events.append("collect")
                self.assertEqual(source, reference.resolve())
                self.assertIs(kwargs["no_new_products_confirmed"], True)
                self.assertEqual(config.detail_shards, 1)
                self.assertEqual(config.detail_interval_ms, 10_000)
                return result

            def publish(data, target):
                events.append("publish")
                self.assertIs(data, result)
                target.parent.mkdir(parents=True)
                target.write_bytes(b"fake test output, not production")
                return target

            with (
                patch.object(runner, "datetime") as clock,
                patch.object(runner, "_validate_daily_run", side_effect=lambda *args: events.append("daily")),
                patch.object(runner, "scrape_known_details", new=collect),
                patch.object(runner, "scrape_all", new_callable=AsyncMock) as listing,
                patch.object(runner, "write_excel", side_effect=publish),
                patch.object(runner, "_progress"),
            ):
                clock.now.side_effect = lambda zone: datetime(2026, 9, 18, 12, tzinfo=zone)
                output = asyncio.run(runner._run(self.args(root, "--refresh-known-products", "--reference-workbook", str(reference), "--confirm-no-new-products")))
            self.assertEqual(events, ["daily", "collect", "daily", "publish"])
            listing.assert_not_called()
            self.assertEqual(output, root / "worktrees/20260918_ugreen_topsales/result/ugreen_topsales.xlsx")
            self.assertEqual(reference.read_bytes(), b"unchanged historical input")

    def test_missing_confirmation_is_rejected_even_by_internal_run(self):
        with patch.object(runner, "scrape_known_details", new_callable=AsyncMock) as full:
            with self.assertRaises(ValueError):
                asyncio.run(runner._run(self.args(Path("/fixture"), "--refresh-known-products", "--reference-workbook", "/old.xlsx")))
        full.assert_not_called()

    def test_failed_known_collection_does_not_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(runner, "_validate_daily_run"),
                patch.object(runner, "scrape_known_details", new=AsyncMock(side_effect=runner.ScrapeError("one PDP missing"))),
                patch.object(runner, "write_excel") as publish,
            ):
                with self.assertRaises(runner.ScrapeError):
                    asyncio.run(runner._run(self.args(Path(directory), "--refresh-known-products", "--reference-workbook", "/old.xlsx", "--confirm-no-new-products")))
            publish.assert_not_called()

    def test_known_verify_pass_does_not_claim_listing_or_full_crawl(self):
        baseline = {
            "mode": "verify_access", "details_only": True, "list_skipped": True,
            "list_pass": None, "list_pages_checked": 0,
            "detail_attempted_count": 3, "detail_success_count": 3, "detail_target_count": 3,
            "full_crawl_completed": False, "workbook_written": False,
        }
        cases = (({}, 0), ({"list_pass": True}, 2), ({"list_skipped": False}, 2),
                 ({"list_pages_checked": 1}, 2), ({"details_only": False}, 2),
                 ({"detail_success_count": 2}, 2), ({"full_crawl_completed": True}, 1))
        for changes, expected in cases:
            payload = {**baseline, **changes}
            with (
                self.subTest(changes=changes),
                patch.object(runner, "_bound_project_root", return_value=Path("/fixture")),
                patch.object(runner, "_exclusive_run_lock", return_value=nullcontext()),
                patch.object(runner, "_run", new=AsyncMock(return_value=payload)),
                redirect_stdout(io.StringIO()) as output,
                redirect_stderr(io.StringIO()),
            ):
                code = runner.main(["--project-root", "/fixture", "--verify-access", "--refresh-known-products", "--reference-workbook", "/old.xlsx"])
            self.assertEqual(code, expected)
            if expected != 1:
                self.assertEqual(json.loads(output.getvalue())["full_crawl_completed"], False)


if __name__ == "__main__":
    unittest.main()
