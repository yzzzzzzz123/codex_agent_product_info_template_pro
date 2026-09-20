"""从已审阅桌面配置中为每轮选择一次参数；不执行浏览器或网络操作。

地区只来自调用者提供的 BrowserRegion，不由设备配置推断或覆盖。配置值不是
真实硬件证明，也不保证 Worker、Client Hints、网络层或网站的识别结果一致。
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

from browser_region import BrowserRegion


CATALOG_PATH = Path(__file__).with_name("browser-profiles.json")
MAX_CATALOG_BYTES = 64 * 1024
APPROVED_PROFILE_IDS = (
    "windows-intel", "windows-nvidia", "windows-amd", "macos-intel", "macos-amd",
    "linux-intel", "linux-nvidia", "linux-amd",
)
_PROFILE_KEYS = {
    "id", "ua_platform", "platform", "vendor", "hardware_concurrency", "device_memory",
    "max_touch_points", "pdf_viewer_enabled", "screen_width", "screen_height",
    "webgl_vendor", "webgl_renderer",
}
_PLATFORMS = {
    "windows": ("Windows NT 10.0; Win64; x64", "Win32"),
    "macos": ("Macintosh; Intel Mac OS X 10_15_7", "MacIntel"),
    "linux": ("X11; Linux x86_64", "Linux x86_64"),
}
_CHROME_VERSION = re.compile(r"([1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("指纹目录包含重复 JSON 字段")
        result[key] = value
    return result


def _validate_profile(profile: object) -> dict[str, object]:
    if not isinstance(profile, dict) or set(profile) != _PROFILE_KEYS:
        raise ValueError("指纹套装字段缺失或包含未知字段")
    profile_id = profile["id"]
    if type(profile_id) is not str or profile_id not in APPROVED_PROFILE_IDS:
        raise ValueError("指纹套装 ID 未获批准")
    for key in ("ua_platform", "platform", "vendor", "webgl_vendor", "webgl_renderer"):
        value = profile[key]
        if (type(value) is not str or not 1 <= len(value) <= 512
                or value.strip() != value or any(ord(char) < 32 or ord(char) > 126 for char in value)):
            raise ValueError("指纹套装文本字段无效")
    os_name, gpu_name = profile_id.split("-", 1)
    if (profile["ua_platform"], profile["platform"]) != _PLATFORMS[os_name]:
        raise ValueError("指纹 UA 操作系统与 navigator.platform 不匹配")
    if profile["vendor"] != "Google Inc.":
        raise ValueError("指纹 vendor 必须匹配 Chrome")
    for key, lower, upper in (
        ("hardware_concurrency", 2, 32), ("device_memory", 1, 8),
        ("max_touch_points", 0, 0), ("screen_width", 1024, 7680),
        ("screen_height", 600, 4320),
    ):
        value = profile[key]
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError("指纹套装数值字段类型或范围无效")
    if profile["hardware_concurrency"] not in {2, 4, 8, 12, 16, 24, 32}:
        raise ValueError("指纹 CPU 线程数不在已审阅范围")
    if profile["device_memory"] not in {1, 2, 4, 8}:
        raise ValueError("指纹内存值不符合 Chrome 离散取值")
    ratio = profile["screen_width"] / profile["screen_height"]
    if not 1.2 <= ratio <= 2.5:
        raise ValueError("指纹屏幕比例不在已审阅桌面范围")
    if type(profile["pdf_viewer_enabled"]) is not bool:
        raise ValueError("指纹 PDF 字段必须为布尔值")
    vendor = profile["webgl_vendor"]
    renderer = profile["webgl_renderer"]
    if os_name == "windows":
        gpu_token = {"intel": "Intel", "nvidia": "NVIDIA", "amd": "AMD"}[gpu_name]
        compatible = (vendor == f"Google Inc. ({gpu_token})" and renderer.startswith("ANGLE (")
                      and gpu_token in renderer and "Direct3D11" in renderer
                      and "D3D11" in renderer and "OpenGL Engine" not in renderer
                      and "Mesa" not in renderer and "Metal" not in renderer)
    elif os_name == "macos":
        expected_vendor, prefix = (("Intel Inc.", "Intel ") if gpu_name == "intel"
                                   else ("ATI Technologies Inc.", "AMD Radeon "))
        compatible = (vendor == expected_vendor and renderer.startswith(prefix)
                      and renderer.endswith(" OpenGL Engine") and "Direct3D" not in renderer
                      and "Apple" not in renderer)
    elif gpu_name == "intel":
        compatible = (vendor == "Intel" and renderer.startswith("Mesa Intel(")
                      and "Direct3D" not in renderer and "OpenGL Engine" not in renderer)
    elif gpu_name == "nvidia":
        compatible = (vendor == "NVIDIA Corporation" and renderer.startswith("NVIDIA ")
                      and renderer.endswith("/PCIe/SSE2") and "Direct3D" not in renderer)
    else:
        compatible = (vendor == "AMD" and renderer.startswith("AMD Radeon ")
                      and "radeonsi" in renderer and "Direct3D" not in renderer
                      and "OpenGL Engine" not in renderer)
    if not compatible:
        raise ValueError("指纹 WebGL 配置与操作系统/GPU 套装不匹配")
    return dict(profile)


def _read_catalog() -> dict[str, dict[str, object]]:
    try:
        with CATALOG_PATH.open("rb") as stream:
            raw = stream.read(MAX_CATALOG_BYTES + 1)
    except OSError:
        raise ValueError("无法读取指纹目录") from None
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("指纹目录超过大小上限")
    try:
        catalog = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("指纹目录不是有效 UTF-8 JSON") from None
    if not isinstance(catalog, dict) or set(catalog) != {"schema_version", "profiles"}:
        raise ValueError("指纹目录顶层字段无效")
    if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1:
        raise ValueError("指纹目录 schema_version 必须为 1")
    profiles = catalog["profiles"]
    if not isinstance(profiles, list) or len(profiles) != len(APPROVED_PROFILE_IDS):
        raise ValueError("指纹目录必须包含全部已批准套装")
    validated = {}
    for item in profiles:
        profile = _validate_profile(item)
        if profile["id"] in validated:
            raise ValueError("指纹目录包含重复套装 ID")
        validated[profile["id"]] = profile
    if set(validated) != set(APPROVED_PROFILE_IDS):
        raise ValueError("指纹目录缺少已批准套装")
    return validated


def choose_profile_id() -> str:
    """每次调用独立选择一个批准 ID；调用者须每轮仅调用一次并固定结果。"""
    profiles = _read_catalog()
    return secrets.choice(tuple(profile_id for profile_id in APPROVED_PROFILE_IDS if profile_id in profiles))


def load_fingerprint(profile_id: str, chrome_version: str, region: BrowserRegion) -> dict:
    """构建一轮完整参数快照；Chrome 完整版本由调用者实测提供，不静默猜测。"""
    if type(profile_id) is not str or profile_id not in APPROVED_PROFILE_IDS:
        raise ValueError("未知指纹套装 ID")
    if type(chrome_version) is not str or _CHROME_VERSION.fullmatch(chrome_version) is None:
        raise ValueError("Chrome 版本必须为完整四段数字版本")
    if not isinstance(region, BrowserRegion):
        raise ValueError("指纹地区必须为已验证 BrowserRegion")
    region_dict = region.to_dict()
    profile = _read_catalog()[profile_id]
    major = chrome_version.split(".", 1)[0]
    return {
        "profile_id": profile_id,
        "chrome_version": chrome_version,
        "user_agent": (
            f"Mozilla/5.0 ({profile['ua_platform']}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
        ),
        **{key: profile[key] for key in (
            "platform", "vendor", "hardware_concurrency", "device_memory", "max_touch_points",
            "pdf_viewer_enabled", "screen_width", "screen_height", "webgl_vendor", "webgl_renderer",
        )},
        "region": region_dict,
    }
