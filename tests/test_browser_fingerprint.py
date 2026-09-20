"""指纹目录及完整模板的离线测试；不启动浏览器、不联网、不读取会话。"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/shopee-ugreen-topsales/scripts"
sys.path.insert(0, str(SCRIPTS))
import browser_fingerprint  # noqa: E402
from browser_region import BrowserRegion  # noqa: E402


REGION = BrowserRegion("SG", "en-SG", ("en-SG", "en"), "Asia/Singapore")
VERSION = "153.0.8010.50"
EXPECTED_IDS = (
    "windows-intel", "windows-nvidia", "windows-amd", "macos-intel", "macos-amd",
    "linux-intel", "linux-nvidia", "linux-amd",
)
EXPECTED_KEYS = {
    "profile_id", "chrome_version", "user_agent", "platform", "vendor",
    "hardware_concurrency", "device_memory", "max_touch_points", "pdf_viewer_enabled",
    "screen_width", "screen_height", "webgl_vendor", "webgl_renderer", "region",
}


class BrowserFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = json.loads((SCRIPTS / "browser-profiles.json").read_text(encoding="utf-8"))

    def mocked_catalog(self, value=None, *, raw=None):
        catalog_path = Mock(spec=Path)
        body = raw if raw is not None else json.dumps(self.catalog if value is None else value).encode()
        catalog_path.open.side_effect = lambda *_: io.BytesIO(body)
        return patch.object(browser_fingerprint, "CATALOG_PATH", catalog_path)

    def load(self, profile_id="windows-intel", version=VERSION, region=REGION):
        return browser_fingerprint.load_fingerprint(profile_id, version, region)

    def test_eight_approved_profiles_have_exact_output_shape_and_distinct_devices(self) -> None:
        self.assertEqual(browser_fingerprint.APPROVED_PROFILE_IDS, EXPECTED_IDS)
        configurations = []
        for profile_id in EXPECTED_IDS:
            with self.subTest(profile_id=profile_id):
                value = self.load(profile_id)
                self.assertEqual(set(value), EXPECTED_KEYS)
                self.assertEqual(value["profile_id"], profile_id)
                self.assertEqual(value["chrome_version"], VERSION)
                self.assertEqual(value["region"], REGION.to_dict())
                self.assertIn("Chrome/153.0.0.0", value["user_agent"])
                self.assertNotIn("Mobile", value["user_agent"])
                self.assertNotIn("Firefox", value["user_agent"])
                configurations.append(tuple(value[key] for key in (
                    "platform", "webgl_vendor", "webgl_renderer", "screen_width", "screen_height",
                )))
        self.assertEqual(len(set(configurations)), 8)

    def test_os_ua_platform_and_gpu_families_match(self) -> None:
        for profile_id in EXPECTED_IDS:
            with self.subTest(profile_id=profile_id):
                value = self.load(profile_id)
                if profile_id.startswith("windows-"):
                    self.assertEqual(value["platform"], "Win32")
                    self.assertIn("(Windows NT 10.0; Win64; x64)", value["user_agent"])
                    self.assertIn("Direct3D11", value["webgl_renderer"])
                elif profile_id.startswith("macos-"):
                    self.assertEqual(value["platform"], "MacIntel")
                    self.assertIn("(Macintosh; Intel Mac OS X 10_15_7)", value["user_agent"])
                    self.assertIn("OpenGL Engine", value["webgl_renderer"])
                    self.assertNotIn("Apple", value["webgl_renderer"])
                else:
                    self.assertEqual(value["platform"], "Linux x86_64")
                    self.assertIn("(X11; Linux x86_64)", value["user_agent"])
                    self.assertNotIn("Direct3D", value["webgl_renderer"])
                self.assertIn(profile_id.split("-")[1].lower(), value["webgl_renderer"].lower())

    def test_supplied_real_version_kept_and_reduced_ua_tracks_major(self) -> None:
        for version in ("122.0.6261.94", VERSION, "154.1.2.3"):
            with self.subTest(version=version):
                value = self.load(version=version)
                self.assertEqual(value["chrome_version"], version)
                self.assertIn(f"Chrome/{version.split('.')[0]}.0.0.0", value["user_agent"])

    def test_region_is_not_inferred_from_os_and_never_changed(self) -> None:
        for region in (
            REGION, BrowserRegion("PH", "en-PH", ("en-PH", "en"), "Asia/Manila"),
            BrowserRegion("US", "en-US", ("en-US", "en"), "America/New_York"),
            BrowserRegion("JP", "ja-JP", ("ja-JP", "ja"), "Asia/Tokyo"),
        ):
            for profile_id in EXPECTED_IDS:
                with self.subTest(region=region.country_code, profile_id=profile_id):
                    self.assertEqual(self.load(profile_id, region=region)["region"], region.to_dict())

    def test_each_load_returns_an_independent_snapshot(self) -> None:
        first = self.load()
        first["platform"] = "changed"
        first["region"]["languages"].append("changed")
        second = self.load()
        self.assertEqual(second["platform"], "Win32")
        self.assertEqual(second["region"], REGION.to_dict())

    def test_choose_uses_secrets_once_per_call_without_persistent_state(self) -> None:
        with self.mocked_catalog() as path, patch.object(
            browser_fingerprint.secrets, "choice", side_effect=["linux-amd", "linux-amd", "macos-intel"],
        ) as choice:
            self.assertEqual([browser_fingerprint.choose_profile_id() for _ in range(3)],
                             ["linux-amd", "linux-amd", "macos-intel"])
        self.assertEqual(choice.call_count, 3)
        self.assertTrue(all(call.args == (EXPECTED_IDS,) for call in choice.call_args_list))
        self.assertEqual(path.open.call_count, 3)
        self.assertTrue(all(call.args == ("rb",) for call in path.open.call_args_list))

    def test_unknown_profile_and_invalid_versions_rejected_without_fallback(self) -> None:
        for profile_id in (None, "", [], "auto", "macos-apple", "windows-unknown"):
            with self.subTest(profile_id=profile_id), self.assertRaises(ValueError):
                self.load(profile_id)
        for version in (None, True, 153, [], "", "153", "153.0.0", "153.0.0.0.0",
                        "Chrome 153.0.8010.50", "153.0.8010.50\n", " 153.0.0.0",
                        "153.0.0.0;alert(1)", "0.0.0.0", "0153.0.0.0", "153.00.0.0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.load(version=version)

    def test_invalid_regions_rejected(self) -> None:
        for region in (None, REGION.to_dict(), replace(REGION, locale="en-US"),
                       replace(REGION, timezone_id="invalid/timezone"),
                       replace(REGION, languages=("en-SG", "zh"))):
            with self.subTest(region=region), self.assertRaises(ValueError):
                self.load(region=region)

    def test_catalog_top_level_keys_and_schema_are_strict(self) -> None:
        values = [[], {}, {**self.catalog, "extra": 1}, {"profiles": self.catalog["profiles"]}]
        values += [{**self.catalog, "schema_version": version} for version in (True, "1", 1.0, 2, None)]
        for value in values:
            with self.subTest(value_type=type(value)), self.mocked_catalog(value), self.assertRaises(ValueError):
                self.load()

    def test_catalog_requires_exact_complete_profile_set_and_unique_ids(self) -> None:
        duplicate = copy.deepcopy(self.catalog)
        duplicate["profiles"][-1] = copy.deepcopy(duplicate["profiles"][0])
        unknown = copy.deepcopy(self.catalog)
        unknown["profiles"][-1]["id"] = "linux-unknown"
        for value in (
            {**self.catalog, "profiles": []}, {**self.catalog, "profiles": {}},
            {**self.catalog, "profiles": self.catalog["profiles"][:-1]},
            {**self.catalog, "profiles": self.catalog["profiles"] + [self.catalog["profiles"][0]]},
            duplicate, unknown,
        ):
            with self.subTest(value=value), self.mocked_catalog(value), self.assertRaises(ValueError):
                self.load()

    def test_all_profiles_validated_even_when_unselected(self) -> None:
        self.catalog["profiles"][-1]["platform"] = "Win32"
        with self.mocked_catalog(), self.assertRaisesRegex(ValueError, "不匹配"):
            self.load("windows-intel")
        with self.mocked_catalog(), patch.object(browser_fingerprint.secrets, "choice") as choice:
            with self.assertRaises(ValueError):
                browser_fingerprint.choose_profile_id()
            choice.assert_not_called()

    def test_profile_fields_are_exact_not_extensible_runtime_payloads(self) -> None:
        for key in tuple(self.catalog["profiles"][0]):
            value = copy.deepcopy(self.catalog)
            del value["profiles"][0][key]
            with self.subTest(missing=key), self.mocked_catalog(value), self.assertRaises(ValueError):
                self.load()
        for item in (None, [], {**self.catalog["profiles"][0], "user_agent": "custom"},
                     {**self.catalog["profiles"][0], "region": REGION.to_dict()}):
            value = copy.deepcopy(self.catalog)
            value["profiles"][0] = item
            with self.subTest(item=item), self.mocked_catalog(value), self.assertRaises(ValueError):
                self.load()

    def test_numeric_fields_reject_bool_wrong_types_and_out_of_range_values(self) -> None:
        invalid = {
            "hardware_concurrency": (True, "8", 8.0, 0, 3, 64),
            "device_memory": (True, "8", 8.0, 0, 3, 16),
            "max_touch_points": (True, "0", 0.0, -1, 1),
            "screen_width": (True, "1366", 1366.0, 1023, 7681),
            "screen_height": (True, "768", 768.0, 599, 4321),
            "pdf_viewer_enabled": (1, 0, "true", None),
        }
        for key, cases in invalid.items():
            for bad in cases:
                value = copy.deepcopy(self.catalog)
                value["profiles"][0][key] = bad
                with self.subTest(key=key, bad=bad), self.mocked_catalog(value), self.assertRaises(ValueError):
                    self.load()

    def test_unreasonable_screen_aspect_ratio_rejected(self) -> None:
        for width, height in ((1024, 4320), (7680, 600)):
            value = copy.deepcopy(self.catalog)
            value["profiles"][0].update(screen_width=width, screen_height=height)
            with self.mocked_catalog(value), self.assertRaisesRegex(ValueError, "比例"):
                self.load()

    def test_os_gpu_and_vendor_mismatches_rejected(self) -> None:
        for index, key, bad in (
            (0, "ua_platform", "X11; Linux x86_64"), (0, "platform", "MacIntel"),
            (0, "vendor", "Apple Computer, Inc."), (0, "webgl_vendor", "Intel Inc."),
            (0, "webgl_renderer", "Intel Iris OpenGL Engine"),
            (1, "webgl_renderer", self.catalog["profiles"][0]["webgl_renderer"]),
            (2, "webgl_renderer", self.catalog["profiles"][1]["webgl_renderer"]),
            (3, "webgl_renderer", "ANGLE (Apple, ANGLE Metal Renderer: Apple M1)"),
            (4, "webgl_vendor", "Intel Inc."),
            (5, "webgl_renderer", self.catalog["profiles"][0]["webgl_renderer"]),
            (6, "webgl_vendor", "Google Inc. (NVIDIA)"),
            (7, "webgl_renderer", "AMD Radeon Pro 560X OpenGL Engine"),
        ):
            value = copy.deepcopy(self.catalog)
            value["profiles"][index][key] = bad
            with self.subTest(index=index, key=key), self.mocked_catalog(value), self.assertRaises(ValueError):
                self.load()

    def test_text_fields_reject_non_strings_whitespace_controls_and_oversized_values(self) -> None:
        for key in ("id", "ua_platform", "platform", "vendor", "webgl_vendor", "webgl_renderer"):
            for bad in (None, [], 1, "", " leading", "trailing ", "line\nbreak", "\x7f", "x" * 513):
                value = copy.deepcopy(self.catalog)
                value["profiles"][0][key] = bad
                with self.subTest(key=key, bad=bad), self.mocked_catalog(value), self.assertRaises(ValueError):
                    self.load()

    def test_catalog_duplicate_json_fields_invalid_encoding_and_size_rejected(self) -> None:
        encoded = json.dumps(self.catalog).encode()
        duplicate = encoded.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1', 1)
        for raw in (duplicate, b"not json", b"\xff", b" " * (browser_fingerprint.MAX_CATALOG_BYTES + 1)):
            with self.subTest(size=len(raw)), self.mocked_catalog(raw=raw), self.assertRaises(ValueError):
                self.load()

    def test_catalog_read_error_is_a_clear_value_error(self) -> None:
        path = Mock(spec=Path)
        path.open.side_effect = FileNotFoundError("private path")
        with patch.object(browser_fingerprint, "CATALOG_PATH", path), self.assertRaises(ValueError) as raised:
            self.load()
        self.assertNotIn("private path", str(raised.exception))

    def test_template_only_parameterizes_values_and_preserves_all_original_blocks(self) -> None:
        template = (SCRIPTS / "proxy-access.js").read_text(encoding="utf-8")
        self.assertEqual(template.count("__UGREEN_FINGERPRINT__"), 1)
        self.assertNotIn("__UGREEN_LANGUAGE", template)
        original = template.replace("  const fingerprint = __UGREEN_FINGERPRINT__;\n", "", 1)
        replacements = {
            "fingerprint.chrome_version": "'153.0.0.0'",
            "[...fingerprint.region.languages]": "__UGREEN_LANGUAGES__",
            "fingerprint.region.locale": "__UGREEN_LANGUAGE__",
            "fingerprint.vendor": "'Google Inc.'", "fingerprint.platform": "'Win32'",
            "fingerprint.max_touch_points": "0", "fingerprint.hardware_concurrency": "8",
            "fingerprint.device_memory": "8", "fingerprint.pdf_viewer_enabled": "true",
            "fingerprint.screen_width": "1366", "fingerprint.screen_height": "768",
            "fingerprint.webgl_vendor": "'Intel Inc.'",
            "fingerprint.webgl_renderer": "'Intel Iris OpenGL Engine'",
        }
        for value, previous in replacements.items():
            self.assertIn(value, original)
            original = original.replace(value, previous)
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         "40a7fd2e5ddfe7c89194879119fe00db6f0a14dc68adb44494058738762a8080")


if __name__ == "__main__":
    unittest.main()
