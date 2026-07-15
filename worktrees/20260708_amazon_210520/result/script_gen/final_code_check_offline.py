"""Offline checker for final_code.py.

Replays Stage1 captured evidence instead of making live requests.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

import final_code_check as LIVE_CHECKER


class OfflineResponse:
    """Mimics a requests.Response using captured bytes."""

    def __init__(self, url: str, content: bytes, status_code: int = 200, headers: Optional[Dict[str, str]] = None):
        self.url = url
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self._text: Optional[str] = None

    @property
    def text(self) -> str:
        if self._text is None:
            try:
                self._text = self.content.decode("utf-8", errors="ignore")
            except Exception:
                self._text = ""
        return self._text

    def json(self) -> Any:
        return json.loads(self.text)


class OfflineFixtureRouter:
    """Routes a request URL to a captured fixture file."""

    def __init__(self, detail_url: str, case_dir: Path):
        self.detail_url = detail_url
        self.case_dir = case_dir

    def resolve(self, url: str) -> OfflineResponse:
        # 1. exact detail_url -> static_page.html
        if url == self.detail_url or url.rstrip("/") == self.detail_url.rstrip("/"):
            static = self.case_dir / "raw_html" / "static_page.html"
            if static.exists():
                return OfflineResponse(url, static.read_bytes())
        # 2. any URL -> try fixtures/<host>.html
        from urllib.parse import urlsplit
        host = (urlsplit(url).hostname or "").lower()
        if host:
            fixture = self.case_dir / "fixtures" / (host + ".html")
            if fixture.exists():
                return OfflineResponse(url, fixture.read_bytes())
        # 3. fallback empty
        return OfflineResponse(url, b"", status_code=404)


def _build_requests_module(router: OfflineFixtureRouter):
    class _OfflineRequests:
        @staticmethod
        def get(url, **kwargs):
            return router.resolve(url)

        @staticmethod
        def post(url, **kwargs):
            return router.resolve(url)

        @staticmethod
        def Session():
            raise RuntimeError("Session is not supported in offline mode")

    return _OfflineRequests


def _build_curl_cffi_module(fake_requests):
    class _OfflineCurlRequests:
        @staticmethod
        def get(url, **kwargs):
            return fake_requests.get(url, **kwargs)

        @staticmethod
        def post(url, **kwargs):
            return fake_requests.post(url, **kwargs)

    return _OfflineCurlRequests


def offline_common_request(router: OfflineFixtureRouter):
    def _common_request(method, url, **kwargs):
        method = (method or "get").lower()
        if method == "get":
            return router.resolve(url)
        if method == "post":
            return router.resolve(url)
        raise ValueError("unsupported method: %s" % method)
    return _common_request


def handle_spu_url_with_custom_code_offline(
    *,
    detail_url: str,
    final_code_path: Path,
    site_result_dir: Path,
    case_dir: Path,
    clear_rendered_html: bool,
) -> None:
    router = OfflineFixtureRouter(detail_url, case_dir)
    fake_requests_module = _build_requests_module(router)
    fake_curl_cffi = _build_curl_cffi_module(fake_requests_module)

    original_requests = sys.modules.get("requests")
    original_curl_cffi = sys.modules.get("curl_cffi")
    original_curl_cffi_requests = sys.modules.get("curl_cffi.requests")

    sys.modules["requests"] = fake_requests_module
    sys.modules["curl_cffi"] = fake_curl_cffi
    sys.modules["curl_cffi.requests"] = fake_requests_module

    try:
        namespace = LIVE_CHECKER.basic_runtime_namespace()
        namespace.update({
            "detail_url": detail_url,
            "common_request": offline_common_request(router),
        })

        code = final_code_path.read_text(encoding="utf-8")
        sub_rule = "\n".join([f"    {line}" for line in code.split("\n")])
        sub_rule = f"if True:\n{sub_rule}"
        exec(compile(sub_rule, str(final_code_path), "exec"), namespace)
        script_res = namespace.get("script_res", {})
        formatted_spu = check_and_reformat_spu_offline(script_res, detail_url)
    finally:
        if original_requests is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = original_requests
        if original_curl_cffi is None:
            sys.modules.pop("curl_cffi", None)
        else:
            sys.modules["curl_cffi"] = original_curl_cffi
        if original_curl_cffi_requests is None:
            sys.modules.pop("curl_cffi.requests", None)
        else:
            sys.modules["curl_cffi.requests"] = original_curl_cffi_requests


def check_and_reformat_spu_offline(script_res: Dict[str, Any], detail_url: str) -> Dict[str, Any]:
    error = LIVE_CHECKER.validate_script_res(script_res, detail_url)
    if error:
        raise ValueError("offline validation failed: %s" % error)
    return script_res


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline checker for final_code.py")
    parser.add_argument("--final-code", required=True, help="Path to final_code.py")
    parser.add_argument("--detail-url", required=True, help="PDP URL to check against")
    parser.add_argument("--case-dir", required=True, help="Directory with captured evidence")
    parser.add_argument("--output", help="Optional path to write script_res JSON")
    args = parser.parse_args()

    final_code_path = Path(args.final_code).resolve()
    if not final_code_path.exists():
        print("final_code.py not found: %s" % final_code_path, file=sys.stderr)
        return 2

    case_dir = Path(args.case_dir).resolve()
    if not case_dir.exists():
        print("case_dir not found: %s" % case_dir, file=sys.stderr)
        return 2

    try:
        handle_spu_url_with_custom_code_offline(
            detail_url=args.detail_url,
            final_code_path=final_code_path,
            site_result_dir=case_dir,
            case_dir=case_dir,
            clear_rendered_html=False,
        )
        script_res = check_and_reformat_spu_offline({}, args.detail_url)
    except Exception:
        traceback.print_exc()
        return 1

    print("OFFLINE VALIDATION OK")
    print(json.dumps(script_res, indent=2, ensure_ascii=False))

    if args.output:
        Path(args.output).write_text(
            json.dumps(script_res, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
