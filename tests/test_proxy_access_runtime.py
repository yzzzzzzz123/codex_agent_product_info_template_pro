"""可选本地 Chrome 原始注入基线测试；不读取真实档案、不访问 Shopee。

运行：RUN_CHROME_RUNTIME_TESTS=1 .venv/bin/python -m unittest discover \
    -s tests -p test_proxy_access_runtime.py -v

页面请求全部由内存 HTML 响应；唯一临时文件是空白私有 Chrome profile，结束后清理。
用户指定保留的原始 API 不兼容行为以 expectedFailure 单独记录，不代表这些问题已修好。
默认跳过，不要求普通单元测试环境安装或下载浏览器。
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/shopee-ugreen-topsales/scripts"
sys.path.insert(0, str(SCRIPTS))
import scraper  # noqa: E402


NATIVE_SNAPSHOT = """
(() => {
    Object.defineProperty(window, '__ugreen_test_native_api__', {
        value: {
            chrome: window.chrome,
            ownPropertyNames: Object.getOwnPropertyNames,
            plugins: navigator.plugins,
            userAgentData: navigator.userAgentData,
        },
        configurable: true,
    });
    for (const key of ['cdc_ugreen_seed', '__playwright_ugreen_seed', '__pw_ugreen_seed']) {
        window[key] = 'local test only';
    }
    window.__ugreen_test_regular_seed__ = 'local test only';
})();
"""

PLUGIN_NAMES = [
    "Chrome PDF Plugin",
    "Chrome PDF Viewer",
    "Native Client",
    "Widevine Content Decryption Module",
    "WebRTC Desktop Sharing",
]

SCREEN_SCRIPT = """() => ({
    width: screen.width, height: screen.height,
    availWidth: screen.availWidth, availHeight: screen.availHeight,
    innerWidth, innerHeight, outerWidth, outerHeight,
})"""


@unittest.skipUnless(
    os.environ.get("RUN_CHROME_RUNTIME_TESTS") == "1",
    "仅在 RUN_CHROME_RUNTIME_TESTS=1 时运行本地 Chrome 注入基线测试",
)
class ProxyAccessRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.assertTrue(scraper.DEFAULT_CHROME.is_file(), "本机 Google Chrome 不存在")
        self.script = scraper._stealth_script()
        self.page_errors: list[str] = []
        self.routed_urls: list[str] = []
        self.observed_headers: list[dict[str, str]] = []
        self.temporary = tempfile.TemporaryDirectory(prefix="ugreen-runtime-test-")
        self.addCleanup(self.temporary.cleanup)
        profile = Path(self.temporary.name) / "profile"
        profile.mkdir(mode=0o700)
        # 同一 init 内先快照、再运行真正脚本，避免多个 init 的顺序未定义。
        with patch.object(scraper, "_stealth_script", return_value=NATIVE_SNAPSHOT + self.script):
            self.context = await scraper._launch_context(scraper.BrowserConfig(), profile)
        self.addAsyncCleanup(scraper._close_context, self.context)

        async def fulfill_locally(route) -> None:
            self.routed_urls.append(route.request.url)
            headers = await route.request.all_headers()
            self.observed_headers.append({
                key: headers[key]
                for key in (
                    "user-agent", "accept-language", "sec-ch-ua",
                    "sec-ch-ua-platform", "sec-ch-ua-mobile",
                )
                if key in headers
            })
            await route.fulfill(
                status=200,
                content_type="text/html",
                body="<!doctype html><html lang=en><title>Local runtime test</title></html>",
            )

        await self.context.route("**/*", fulfill_locally)
        self.page = await self.context.new_page()
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        await self.page.goto("https://ugreen-runtime.invalid/", wait_until="load")
        # Setup failures remain real errors, never hidden by expectedFailure decorators.
        self.assertEqual(self.page_errors, [])

    async def _smaller_viewport_same_screen(self) -> dict:
        # set_viewport_size 重置 screen，不能模拟物理屏幕不变的窗口缩放。
        session = await self.context.new_cdp_session(self.page)
        try:
            await session.send("Emulation.setDeviceMetricsOverride", {
                "width": 1024, "height": 600, "screenWidth": 1366, "screenHeight": 768,
                "deviceScaleFactor": 1, "mobile": False,
            })
            return await self.page.evaluate(SCREEN_SCRIPT)
        finally:
            await session.detach()

    async def test_original_injection_blocks_and_historical_configuration(self) -> None:
        with self.subTest("真实列表脚本的页面探针"):
            payload = await self.page.evaluate(
                scraper.LIST_PAGE_SCRIPT, {"expected_shop_id": scraper.SHOP_ID},
            )
            self.assertTrue(
                scraper._valid_stealth_probe(payload.get("stealth_probe")),
                payload.get("stealth_probe"),
            )

        with self.subTest("历史语言、马尼拉时区、Win32 和全部 navigator 注入值"):
            values = await self.page.evaluate("""() => ({
                language: navigator.language,
                languages: Array.from(navigator.languages),
                platform: navigator.platform,
                vendor: navigator.vendor,
                webdriverUndefined: navigator.webdriver === undefined,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemory: navigator.deviceMemory,
                maxTouchPoints: navigator.maxTouchPoints,
                pdfViewerEnabled: navigator.pdfViewerEnabled,
                timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                locale: Intl.DateTimeFormat().resolvedOptions().locale,
                winterOffset: new Date('2026-01-15T12:00:00Z').getTimezoneOffset(),
                summerOffset: new Date('2026-07-15T12:00:00Z').getTimezoneOffset(),
            })""")
            self.assertEqual(values, {
                "language": "en-US", "languages": ["en-US", "en", "zh-CN"], "platform": "Win32",
                "vendor": "Google Inc.", "webdriverUndefined": True,
                "hardwareConcurrency": 8, "deviceMemory": 8, "maxTouchPoints": 0,
                "pdfViewerEnabled": True, "timeZone": "Asia/Manila", "locale": "en-PH",
                "winterOffset": -480, "summerOffset": -480,
            })

        with self.subTest("历史固定 UA 与请求一致；原生 Client Hints 保留实际 Chrome 版本"):
            values = await self.page.evaluate("""async () => ({
                userAgent: navigator.userAgent,
                originalUserAgentData: navigator.userAgentData ===
                    window.__ugreen_test_native_api__.userAgentData,
                brands: navigator.userAgentData.brands,
                platform: navigator.userAgentData.platform,
                mobile: navigator.userAgentData.mobile,
                highEntropy: await navigator.userAgentData.getHighEntropyValues([
                    'architecture', 'bitness', 'platform', 'platformVersion', 'fullVersionList',
                ]),
            })""")
            session = await self.context.new_cdp_session(self.page)
            try:
                browser_version = await session.send("Browser.getVersion")
            finally:
                await session.detach()
            headers = self.observed_headers[0]
            self.assertEqual(values["userAgent"], scraper.CHROME_USER_AGENT)
            self.assertEqual(headers["user-agent"], values["userAgent"])
            self.assertTrue(values["originalUserAgentData"])
            match = re.search(r"(?:Chrome|Chromium)/(\d+)\.", browser_version["product"])
            self.assertIsNotNone(match, browser_version["product"])
            native_major = match.group(1)
            self.assertIn("Windows NT 10.0; Win64; x64", values["userAgent"])
            self.assertEqual(values["platform"], "Windows")
            self.assertFalse(values["mobile"])
            self.assertEqual(headers["sec-ch-ua-platform"], '"Windows"')
            self.assertEqual(headers["sec-ch-ua-mobile"], "?0")
            self.assertTrue(headers["accept-language"].startswith("en-PH"))
            chromium_brands = [
                brand for brand in values["brands"]
                if brand["brand"] in {"Chromium", "Google Chrome"}
            ]
            self.assertTrue(chromium_brands)
            for brand in chromium_brands:
                self.assertEqual(brand["version"], native_major)
                self.assertIn(f'"{brand["brand"]}";v="{native_major}"', headers["sec-ch-ua"])
            self.assertEqual(values["highEntropy"]["platform"], "Windows")
            for brand in values["highEntropy"].get("fullVersionList", []):
                if brand["brand"] in {"Chromium", "Google Chrome"}:
                    self.assertEqual(brand["version"].split(".")[0], native_major)
            print("本地 Chrome 高熵观察（无站点访问）：", {
                key: values["highEntropy"].get(key)
                for key in ("architecture", "bitness", "platform", "platformVersion")
            })

        with self.subTest("完整 chrome runtime/app/webstore/loadTimes/csi"):
            values = await self.page.evaluate("""() => {
                const c = window.chrome;
                return {
                    originalReplaced: c !== window.__ugreen_test_native_api__.chrome,
                    manifest: c.runtime.getManifest(),
                    installedListener: typeof c.runtime.onInstalled.addListener,
                    removedListener: typeof c.runtime.onInstalled.removeListener,
                    sendNoop: c.runtime.sendMessage() === undefined,
                    connect: c.runtime.connect(),
                    appInstalled: c.app.isInstalled,
                    appIsInstalled: c.app.getIsInstalled(),
                    appDetailsNoop: c.app.getDetails() === undefined,
                    installListener: typeof c.webstore.onInstallStageChanged.addListener,
                    downloadListener: typeof c.webstore.onDownloadProgress.addListener,
                    loadTimes: c.loadTimes(),
                    csi: c.csi(),
                };
            }""")
            self.assertTrue(values["originalReplaced"])
            # 原始 fake manifest 的 122 按用户要求原样保留，并非当前 Chrome 版本。
            self.assertEqual(values["manifest"], {"version": "122.0.0.0"})
            for key in ("installedListener", "removedListener", "installListener", "downloadListener"):
                self.assertEqual(values[key], "function")
            self.assertTrue(values["sendNoop"])
            self.assertEqual(values["connect"], {})
            self.assertFalse(values["appInstalled"])
            self.assertFalse(values["appIsInstalled"])
            self.assertTrue(values["appDetailsNoop"])
            load_times = values["loadTimes"]
            self.assertEqual(set(load_times), {
                "requestTime", "startLoadTime", "commitLoadTime", "finishDocumentLoadTime",
                "finishLoadTime", "firstPaintTime", "firstContentfulPaintTime",
                "domContentLoadedEventEnd", "loadEventEnd",
            })
            self.assertTrue(all(isinstance(value, (int, float)) for value in load_times.values()))
            csi = values["csi"]
            self.assertEqual({key: csi[key] for key in ("pageT", "tran", "dns", "conn", "resp")}, {
                "pageT": 300, "tran": 150, "dns": 20, "conn": 50, "resp": 80,
            })
            self.assertEqual(csi["onloadT"] - csi["startE"], 300)

        with self.subTest("完整五项插件数组和原始权限返回值"):
            values = await self.page.evaluate("""async () => {
                const plugins = navigator.plugins;
                const permission = await navigator.permissions.query({ name: 'notifications' });
                const other = await navigator.permissions.query({ name: 'geolocation' });
                return {
                    names: plugins.map(plugin => plugin.name),
                    filenames: plugins.map(plugin => plugin.filename),
                    descriptionsPresent: plugins.every(plugin => Boolean(plugin.description)),
                    array: Array.isArray(plugins),
                    permissionState: permission.state,
                    notificationPermission: Notification.permission,
                    permissionKeys: Object.keys(permission),
                    permissionPlainObject: Object.getPrototypeOf(permission) === Object.prototype,
                    otherPermissionNative: other instanceof PermissionStatus,
                };
            }""")
            self.assertEqual(values["names"], PLUGIN_NAMES)
            self.assertEqual(values["filenames"], [
                "internal-pdf-viewer", "mhjfbmdgcfjbbpaeojofohoefghlsjai", "internal-nacl-plugin",
                "widevinecdm", "webrtc-desktop-sharing",
            ])
            self.assertTrue(values["descriptionsPresent"])
            self.assertTrue(values["array"])
            self.assertEqual(values["permissionState"], values["notificationPermission"])
            self.assertEqual(values["permissionKeys"], ["state"])
            self.assertTrue(values["permissionPlainObject"])
            self.assertTrue(values["otherPermissionNative"])

        with self.subTest("自动化标记清除和原始全局属性名过滤"):
            values = await self.page.evaluate("""() => {
                const seeded = ['cdc_ugreen_seed', '__playwright_ugreen_seed', '__pw_ugreen_seed'];
                const ordinary = { cdc_example: 1, __playwright_example: 2, __pw_example: 3,
                    regular: 4 };
                return {
                    deleted: seeded.every(key => !Object.prototype.hasOwnProperty.call(window, key)),
                    regularKept: window.__ugreen_test_regular_seed__ === 'local test only',
                    filteredNames: Object.getOwnPropertyNames(ordinary),
                    nativeNames: window.__ugreen_test_native_api__.ownPropertyNames(ordinary),
                };
            }""")
            self.assertTrue(values["deleted"])
            self.assertTrue(values["regularKept"])
            self.assertEqual(values["filteredNames"], ["regular"])
            self.assertEqual(values["nativeNames"], [
                "cdc_example", "__playwright_example", "__pw_example", "regular",
            ])

        with self.subTest("原始 screen/outer 覆写和 avail 跟随 viewport"):
            before = await self.page.evaluate(SCREEN_SCRIPT)
            self.assertEqual(before, {
                "width": 1366, "height": 768, "availWidth": 1366, "availHeight": 768,
                "innerWidth": 1366, "innerHeight": 768, "outerWidth": 1366, "outerHeight": 768,
            })
            after = await self._smaller_viewport_same_screen()
            self.assertEqual(after, {
                "width": 1366, "height": 768, "availWidth": 1024, "availHeight": 600,
                "innerWidth": 1024, "innerHeight": 600, "outerWidth": 1366, "outerHeight": 768,
            })

        with self.subTest("原始 WebGL 1/2 厂商和 GPU 字符串"):
            values = await self.page.evaluate("""() => {
                return ['webgl', 'webgl2'].map(kind => {
                    const canvas = document.createElement('canvas');
                    const gl = canvas.getContext(kind);
                    if (!gl) return { kind, available: false };
                    return { kind, available: true,
                        vendor: gl.getParameter(37445), renderer: gl.getParameter(37446),
                        regularVendor: gl.getParameter(gl.VENDOR),
                    };
                });
            }""")
            for value in values:
                self.assertTrue(value["available"], value)
                self.assertEqual(value["vendor"], "Intel Inc.")
                self.assertEqual(value["renderer"], "Intel Iris OpenGL Engine")
                self.assertTrue(value["regularVendor"])

        with self.subTest("新 iframe document 继承完整注入"):
            await self.page.evaluate("""async () => {
                const frame = document.createElement('iframe');
                const loaded = new Promise(resolve => frame.onload = resolve);
                frame.src = '/frame';
                document.body.appendChild(frame);
                await loaded;
            }""")
            frame = next(frame for frame in self.page.frames if frame != self.page.main_frame)
            values = await frame.evaluate("""() => ({
                language: navigator.language,
                languages: Array.from(navigator.languages),
                platform: navigator.platform,
                timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                webdriverUndefined: navigator.webdriver === undefined,
                pluginNames: navigator.plugins.map(plugin => plugin.name),
                runtimeManifest: window.chrome.runtime.getManifest(),
            })""")
            self.assertEqual(values, {
                "language": "en-US", "languages": ["en-US", "en", "zh-CN"], "platform": "Win32",
                "timeZone": "Asia/Manila", "webdriverUndefined": True,
                "pluginNames": PLUGIN_NAMES, "runtimeManifest": {"version": "122.0.0.0"},
            })

        with self.subTest("没有脚本错误，页面全部在本地响应"):
            self.assertEqual(self.page_errors, [])
            self.assertTrue(self.routed_urls)
            self.assertTrue(
                all(url.startswith("https://ugreen-runtime.invalid/") for url in self.routed_urls),
                self.routed_urls,
            )

    @unittest.expectedFailure
    async def test_known_limitation_repeated_classic_script_is_not_idempotent(self) -> None:
        """原脚本的顶层 const/不可重定义 getter 导致重复注入失败，未修复。"""
        await self.page.add_script_tag(content=self.script)
        await self.page.evaluate("() => true")
        self.assertEqual(self.page_errors, [])

    @unittest.expectedFailure
    async def test_known_limitation_plugins_are_not_native_plugin_array(self) -> None:
        """原脚本每次返回普通数组，不具备原生 PluginArray 合约，未修复。"""
        valid = await self.page.evaluate("""() => {
            const plugins = navigator.plugins;
            return plugins instanceof PluginArray && plugins === navigator.plugins &&
                typeof plugins.item === 'function' && typeof plugins.namedItem === 'function';
        }""")
        self.assertTrue(valid)

    @unittest.expectedFailure
    async def test_known_limitation_notifications_are_not_permission_status(self) -> None:
        """原脚本的 notification 查询返回普通对象，无 EventTarget，未修复。"""
        valid = await self.page.evaluate("""async () => {
            const status = await navigator.permissions.query({ name: 'notifications' });
            return status instanceof PermissionStatus && status instanceof EventTarget &&
                'onchange' in status;
        }""")
        self.assertTrue(valid)

    @unittest.expectedFailure
    async def test_known_limitation_webgl_spoof_bypasses_receiver_validation(self) -> None:
        """原脚本对两个伪装参数提前 return，非法 receiver 不再抛 TypeError，未修复。"""
        values = await self.page.evaluate("""() => {
            const results = [];
            for (const kind of ['WebGLRenderingContext', 'WebGL2RenderingContext']) {
                for (const receiver of [null, {}]) {
                    for (const parameter of [37445, 37446, 7936]) {
                        let typeError = false;
                        try { window[kind].prototype.getParameter.call(receiver, parameter); }
                        catch (error) { typeError = error instanceof TypeError; }
                        results.push({ kind, parameter, nullReceiver: receiver === null, typeError });
                    }
                }
            }
            return results;
        }""")
        self.assertTrue(all(value["typeError"] for value in values), values)

    @unittest.expectedFailure
    async def test_known_limitation_global_reflection_filters_ordinary_objects(self) -> None:
        """原始 Object.getOwnPropertyNames Proxy 也过滤普通对象，未修复。"""
        names = await self.page.evaluate("""() =>
            Object.getOwnPropertyNames({ cdc_example: 1, __playwright_example: 2,
                __pw_example: 3, regular: 4 })""")
        self.assertEqual(names, ["cdc_example", "__playwright_example", "__pw_example", "regular"])

    @unittest.expectedFailure
    async def test_known_limitation_chrome_object_replaces_native_apis(self) -> None:
        """原脚本整体替换 window.chrome，原生对象身份不保留，未修复。"""
        identity = await self.page.evaluate(
            "() => window.chrome === window.__ugreen_test_native_api__.chrome",
        )
        self.assertTrue(identity)

    @unittest.expectedFailure
    async def test_known_limitation_screen_available_size_tracks_viewport(self) -> None:
        """原脚本 availWidth/availHeight 读取 innerWidth/innerHeight，未修复。"""
        before = await self.page.evaluate(SCREEN_SCRIPT)
        after = await self._smaller_viewport_same_screen()
        self.assertEqual(after["availWidth"], before["availWidth"])
        self.assertEqual(after["availHeight"], before["availHeight"])

    @unittest.expectedFailure
    async def test_known_limitation_injected_getter_accepts_invalid_receiver(self) -> None:
        """原 navigator 实例的 getter 不再校验原生 receiver，未修复。"""
        type_error = await self.page.evaluate("""() => {
            const getter = Object.getOwnPropertyDescriptor(navigator, 'platform').get;
            try { getter.call({}); } catch (error) { return error instanceof TypeError; }
            return false;
        }""")
        self.assertTrue(type_error)


if __name__ == "__main__":
    unittest.main()
