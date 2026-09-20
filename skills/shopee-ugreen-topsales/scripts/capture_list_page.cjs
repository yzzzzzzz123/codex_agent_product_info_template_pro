'use strict';

// Internal stdin/stdout bridge. HTML stays in the parent process's memory.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {createHash} = require('node:crypto');
const readline = require('node:readline');

const STEALTH_SHA256 = '670a595ce5f75286ea1d5af02c5c1aae3433745a2bc15ae744f926a80fbb215c';
const PROFILE_IDS = ['windows-intel', 'windows-nvidia', 'windows-amd', 'macos-intel', 'macos-amd',
  'linux-intel', 'linux-nvidia', 'linux-amd'];
const PROFILE_FIELDS = ['id', 'ua_platform', 'platform', 'vendor', 'hardware_concurrency', 'device_memory',
  'max_touch_points', 'pdf_viewer_enabled', 'screen_width', 'screen_height', 'webgl_vendor', 'webgl_renderer'];
const OS_PLATFORMS = {
  windows: {ua_platform: 'Windows NT 10.0; Win64; x64', platform: 'Win32'},
  macos: {ua_platform: 'Macintosh; Intel Mac OS X 10_15_7', platform: 'MacIntel'},
  linux: {ua_platform: 'X11; Linux x86_64', platform: 'Linux x86_64'},
};
const BLOCKED_STATUSES = new Set([403, 418, 429, 503]);
const PROXY_ENV_NAMES = new Set(['http_proxy', 'https_proxy', 'all_proxy']);

const STEALTH_PROBE = () => {
  let webglVendor = null;
  let webglRenderer = null;
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    if (gl) {
      webglVendor = gl.getParameter(37445);
      webglRenderer = gl.getParameter(37446);
    }
  } catch (_) { /* Missing WebGL is represented explicitly, never guessed. */ }
  return {
  webdriver_is_undefined: navigator.webdriver === undefined,
  user_agent: navigator.userAgent,
  user_agent_data: navigator.userAgentData ? navigator.userAgentData.toJSON() : null,
  language: navigator.language,
  languages: Array.from(navigator.languages || []),
  platform: navigator.platform,
  vendor: navigator.vendor,
  plugin_count: navigator.plugins ? navigator.plugins.length : null,
  hardware_concurrency: navigator.hardwareConcurrency,
  device_memory: navigator.deviceMemory === undefined ? null : navigator.deviceMemory,
  max_touch_points: navigator.maxTouchPoints,
  pdf_viewer_enabled: navigator.pdfViewerEnabled,
  chrome_runtime_present: Boolean(window.chrome && window.chrome.runtime),
  chrome_version: window.chrome && window.chrome.runtime
    && typeof window.chrome.runtime.getManifest === 'function'
    ? window.chrome.runtime.getManifest().version : null,
  webgl_vendor: webglVendor,
  webgl_renderer: webglRenderer,
  time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  screen_width: window.screen.width,
  screen_height: window.screen.height,
  };
};

class CaptureError extends Error {
  constructor(kind, message) {
    super(message);
    this.kind = kind;
  }
}

function configError(message) {
  throw new CaptureError('config', message);
}

function inside(parent, child) {
  const relative = path.relative(parent, child);
  return relative !== '' && !relative.startsWith(`..${path.sep}`)
    && relative !== '..' && !path.isAbsolute(relative);
}

function validateProfile(rawDirectory) {
  if (typeof rawDirectory !== 'string' || !rawDirectory.trim() || !path.isAbsolute(rawDirectory)) {
    configError('列表采集需要已有的独立临时 Chrome 会话目录');
  }
  try {
    const directory = fs.realpathSync(rawDirectory);
    const roots = [os.tmpdir(), '/private/tmp'].filter(value => fs.existsSync(value));
    const permitted = roots.some(root => {
      const tempRoot = fs.realpathSync(root);
      if (!inside(tempRoot, directory)) return false;
      const firstPart = path.relative(tempRoot, directory).split(path.sep)[0];
      return firstPart.startsWith('shopees-ugreen-profile-')
        && firstPart.length > 'shopees-ugreen-profile-'.length;
    });
    if (!permitted || !fs.statSync(directory).isDirectory()) {
      configError('只允许使用任务建立的独立临时 Chrome 会话副本');
    }
    for (const relative of ['Local State', path.join('Default', 'Cookies')]) {
      const candidate = fs.realpathSync(path.join(directory, relative));
      if (!inside(directory, candidate) || !fs.statSync(candidate).isFile()) {
        configError('临时 Chrome 会话缺少必要状态副本');
      }
    }
    return directory;
  } catch (error) {
    if (error instanceof CaptureError) throw error;
    configError('临时 Chrome 会话缺少必要状态副本');
  }
}

function validateRegion(input) {
  const keys = ['country_code', 'languages', 'locale', 'timezone_id'];
  if (!input || typeof input !== 'object' || Array.isArray(input)
      || JSON.stringify(Object.keys(input).sort()) !== JSON.stringify(keys)
      || typeof input.country_code !== 'string' || !/^[A-Z]{2}$/.test(input.country_code)
      || typeof input.locale !== 'string' || !/^[a-z]{2,3}(?:-[A-Z][a-z]{3})?-[A-Z]{2}$/.test(input.locale)
      || !Array.isArray(input.languages) || input.languages.length !== 2
      || input.languages[0] !== input.locale || input.languages[1] !== input.locale.split('-')[0]
      || typeof input.timezone_id !== 'string'
      || !/^(?:[A-Za-z_]+\/[A-Za-z_+\d-]+(?:\/[A-Za-z_+\d-]+)?|UTC)$/.test(input.timezone_id)) {
    configError('列表采集需要完整且一致的本轮出口地区配置');
  }
  try {
    const locale = new Intl.Locale(input.locale);
    if (locale.toString() !== input.locale || locale.region !== input.country_code
        || Intl.DateTimeFormat.supportedLocalesOf([input.locale]).length !== 1) {
      configError('列表采集地区语言与出口国家不一致或不受支持');
    }
    new Intl.DateTimeFormat(input.locale, {timeZone: input.timezone_id}).resolvedOptions();
  } catch (error) {
    if (error instanceof CaptureError) throw error;
    configError('列表采集地区语言或 IANA 时区无效');
  }
  return Object.freeze({...input, languages: Object.freeze([...input.languages])});
}

function exactKeys(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort());
}

function canonicalJson(value) {
  const sort = item => {
    if (Array.isArray(item)) return item.map(sort);
    if (item && typeof item === 'object') {
      return Object.fromEntries(Object.keys(item).sort().map(key => [key, sort(item[key])]));
    }
    return item;
  };
  return JSON.stringify(sort(value));
}

function uniqueJson(raw) {
  const result = JSON.parse(raw);
  // JSON.parse alone silently accepts duplicate keys; scan the already-valid
  // JSON token stream so it cannot disagree with Python's strict catalog reader.
  const tokens = raw.match(/"(?:\\[\s\S]|[^"\\])*"|[{}\[\]:,]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/g);
  let index = 0;
  const visit = () => {
    const token = tokens[index++];
    if (token === '{') {
      const keys = new Set();
      if (tokens[index] === '}') { index++; return; }
      while (true) {
        const key = JSON.parse(tokens[index++]);
        if (keys.has(key)) throw new Error('duplicate JSON key');
        keys.add(key);
        index++; // colon; syntax was checked by JSON.parse above.
        visit();
        if (tokens[index++] === '}') return;
      }
    }
    if (token === '[') {
      if (tokens[index] === ']') { index++; return; }
      while (true) {
        visit();
        if (tokens[index++] === ']') return;
      }
    }
  };
  visit();
  return result;
}

function compatibleGraphics(profile) {
  const [osName, gpuName] = profile.id.split('-');
  const vendor = profile.webgl_vendor;
  const renderer = profile.webgl_renderer;
  if (osName === 'windows') {
    const token = {intel: 'Intel', nvidia: 'NVIDIA', amd: 'AMD'}[gpuName];
    return vendor === `Google Inc. (${token})` && renderer.startsWith('ANGLE (')
      && renderer.includes(token) && renderer.includes('Direct3D11') && renderer.includes('D3D11')
      && !['OpenGL Engine', 'Mesa', 'Metal'].some(value => renderer.includes(value));
  }
  if (osName === 'macos') {
    const [expectedVendor, prefix] = gpuName === 'intel' ? ['Intel Inc.', 'Intel ']
      : ['ATI Technologies Inc.', 'AMD Radeon '];
    return vendor === expectedVendor && renderer.startsWith(prefix) && renderer.endsWith(' OpenGL Engine')
      && !renderer.includes('Direct3D') && !renderer.includes('Apple');
  }
  if (gpuName === 'intel') return vendor === 'Intel' && renderer.startsWith('Mesa Intel(')
    && !renderer.includes('Direct3D') && !renderer.includes('OpenGL Engine');
  if (gpuName === 'nvidia') return vendor === 'NVIDIA Corporation' && renderer.startsWith('NVIDIA ')
    && renderer.endsWith('/PCIe/SSE2') && !renderer.includes('Direct3D');
  return vendor === 'AMD' && renderer.startsWith('AMD Radeon ') && renderer.includes('radeonsi')
    && !renderer.includes('Direct3D') && !renderer.includes('OpenGL Engine');
}

function loadFingerprintProfiles() {
  let catalog;
  try {
    const raw = fs.readFileSync(path.join(__dirname, 'browser-profiles.json'), 'utf8');
    if (Buffer.byteLength(raw, 'utf8') > 64 * 1024) configError('浏览器配置目录超过大小上限');
    catalog = uniqueJson(raw);
  } catch (_) {
    configError('无法读取受控浏览器配置目录');
  }
  if (!exactKeys(catalog, ['schema_version', 'profiles']) || catalog.schema_version !== 1
      || !Array.isArray(catalog.profiles) || catalog.profiles.length !== PROFILE_IDS.length) {
    configError('浏览器配置目录结构无效');
  }
  const profiles = new Map();
  for (const profile of catalog.profiles) {
    if (!exactKeys(profile, PROFILE_FIELDS) || !PROFILE_IDS.includes(profile.id) || profiles.has(profile.id)) {
      configError('浏览器配置目录包含缺失、重复或非批准套件');
    }
    const expectedOS = OS_PLATFORMS[profile.id.split('-')[0]];
    if (profile.ua_platform !== expectedOS.ua_platform || profile.platform !== expectedOS.platform
        || profile.vendor !== 'Google Inc.' || typeof profile.pdf_viewer_enabled !== 'boolean'
        || !Number.isSafeInteger(profile.hardware_concurrency)
        || ![2, 4, 8, 12, 16, 24, 32].includes(profile.hardware_concurrency)
        || ![1, 2, 4, 8].includes(profile.device_memory)
        || profile.max_touch_points !== 0
        || !Number.isSafeInteger(profile.screen_width) || profile.screen_width < 1024 || profile.screen_width > 7680
        || !Number.isSafeInteger(profile.screen_height) || profile.screen_height < 600 || profile.screen_height > 4320
        || profile.screen_width / profile.screen_height < 1.2 || profile.screen_width / profile.screen_height > 2.5
        || !['webgl_vendor', 'webgl_renderer'].every(key => typeof profile[key] === 'string'
          && /^[\x20-\x7e]{1,512}$/.test(profile[key]) && profile[key].trim() === profile[key])
        || !compatibleGraphics(profile)) {
      configError('浏览器配置目录存在无效或不成套的字段');
    }
    profiles.set(profile.id, profile);
  }
  return profiles;
}

function validateFingerprint(input, region) {
  const fields = ['profile_id', 'chrome_version', 'user_agent', 'region',
    ...PROFILE_FIELDS.filter(key => !['id', 'ua_platform'].includes(key))];
  if (!exactKeys(input, fields) || typeof input.profile_id !== 'string'
      || typeof input.chrome_version !== 'string'
      || !/^[1-9]\d{0,3}\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$/.test(input.chrome_version)) {
    configError('列表采集需要完整且有效的本轮浏览器套件');
  }
  const profile = loadFingerprintProfiles().get(input.profile_id);
  if (!profile) configError('列表采集浏览器套件不在批准目录中');
  const {id, ua_platform, ...details} = profile;
  const expected = {
    profile_id: id,
    chrome_version: input.chrome_version,
    user_agent: `Mozilla/5.0 (${ua_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${input.chrome_version.split('.')[0]}.0.0.0 Safari/537.36`,
    ...details,
    region,
  };
  if (canonicalJson(input) !== canonicalJson(expected)) {
    configError('列表采集浏览器字段与本轮套件、版本或地区不一致');
  }
  return Object.freeze(expected);
}

function validatedInitScript(fingerprint) {
  let template;
  try {
    template = fs.readFileSync(path.join(__dirname, 'proxy-access.js'), 'utf8');
  } catch (_) {
    configError('无法读取列表采集初始化模板');
  }
  if (createHash('sha256').update(template, 'utf8').digest('hex') !== STEALTH_SHA256
      || template.split('__UGREEN_FINGERPRINT__').length !== 2) {
    configError('列表采集初始化模板与批准版本不一致');
  }
  return template.replace('__UGREEN_FINGERPRINT__', () => canonicalJson(fingerprint));
}

function validateConfig(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    configError('列表采集配置必须是单个 JSON 对象');
  }
  const config = {...input};
  config.user_data_dir = validateProfile(config.user_data_dir);
  for (const key of ['playwright_module', 'chrome_executable']) {
    if (typeof config[key] !== 'string' || !path.isAbsolute(config[key])) {
      configError('列表采集需要现有 Playwright 模块与系统 Chrome 的绝对路径');
    }
  }
  config.region = validateRegion(config.region);
  config.fingerprint = validateFingerprint(config.fingerprint, config.region);
  if (typeof config.init_script !== 'string' || config.init_script !== validatedInitScript(config.fingerprint)) {
    configError('列表采集初始化脚本与本轮浏览器套件及地区模板不一致');
  }
  try {
    const url = new URL(config.url);
    const keys = Array.from(url.searchParams.keys());
    if (url.protocol !== 'https:' || url.hostname !== 'shopee.ph' || url.port
        || url.username || url.password || url.hash || url.pathname !== '/ugreen.ph'
        || !/^(0|[1-9]\d*)$/.test(url.searchParams.get('page') || '')
        || url.searchParams.get('sortBy') !== 'sales' || url.searchParams.get('tab') !== '0'
        || (url.searchParams.has('shop') && url.searchParams.get('shop') !== '64922227')
        || keys.some(key => !['page', 'shop', 'sortBy', 'tab'].includes(key))
        || new Set(keys).size !== keys.length) {
      configError('列表采集 URL 必须属于指定 UGREEN Top Sales 范围');
    }
  } catch (error) {
    if (error instanceof CaptureError) throw error;
    configError('列表采集 URL 无效');
  }
  config.headless = config.headless ?? false;
  config.navigation_timeout_ms = config.navigation_timeout_ms ?? 120000;
  config.post_load_wait_ms = config.post_load_wait_ms ?? 15000;
  if (typeof config.headless !== 'boolean'
      || !Number.isSafeInteger(config.navigation_timeout_ms) || config.navigation_timeout_ms <= 0
      || !Number.isSafeInteger(config.post_load_wait_ms) || config.post_load_wait_ms < 15000) {
    configError('列表采集参数无效；导航后必须完整等待至少 15 秒');
  }
  if ((Object.hasOwn(config, 'user_agent') && config.user_agent !== config.fingerprint.user_agent)
      || (Object.hasOwn(config, 'locale') && config.locale !== config.region.locale)
      || (Object.hasOwn(config, 'timezone_id') && config.timezone_id !== config.region.timezone_id)) {
    configError('列表采集参数必须与本轮浏览器套件及地区一致');
  }
  config.user_agent = config.fingerprint.user_agent;
  config.locale = config.region.locale;
  config.timezone_id = config.region.timezone_id;
  const dimensions = {width: config.fingerprint.screen_width, height: config.fingerprint.screen_height};
  for (const field of ['viewport', 'screen']) {
    if (Object.hasOwn(config, field) && canonicalJson(config[field]) !== canonicalJson(dimensions)) {
      configError('列表采集窗口尺寸与本轮浏览器套件不一致');
    }
    config[field] = dimensions;
  }
  return config;
}

function cleanEnvironment(environment) {
  return Object.fromEntries(Object.entries(environment)
    .filter(([key]) => !PROXY_ENV_NAMES.has(key.toLowerCase())));
}

// Reproduce the original preload's launch -> newContext call shape in process.
function installPersistentLaunchShim(chromium, config, environment = process.env) {
  const originalDescriptor = Object.getOwnPropertyDescriptor(chromium, 'launch');
  const originalLaunch = chromium.launch;
  const wrappers = new Set();
  chromium.launch = async function launch(launchOptions = {}) {
    let context;
    let requested = false;
    let closed = false;
    const wrapper = {
      async newContext(contextOptions = {}) {
        if (requested || closed) throw new CaptureError('runtime', '列表浏览器只能建立一个持久化会话');
        requested = true;
        const options = {...launchOptions, ...contextOptions};
        delete options.proxy;
        delete options.extraHTTPHeaders;
        options.executablePath = config.chrome_executable;
        options.ignoreDefaultArgs = ['--use-mock-keychain', '--password-store=basic'];
        options.env = cleanEnvironment(options.env || environment);
        context = await chromium.launchPersistentContext(config.user_data_dir, options);
        return context;
      },
      async close() {
        if (closed) return;
        closed = true;
        try {
          if (context) await context.close();
        } finally {
          wrappers.delete(wrapper);
        }
      },
    };
    wrappers.add(wrapper);
    return wrapper;
  };
  let restored = false;
  return {
    async close() {
      const results = await Promise.allSettled(Array.from(wrappers, wrapper => wrapper.close()));
      if (results.some(result => result.status === 'rejected')) {
        throw new CaptureError('cleanup', '列表浏览器会话关闭失败');
      }
    },
    restore() {
      if (restored) return;
      restored = true;
      if (originalDescriptor) Object.defineProperty(chromium, 'launch', originalDescriptor);
      else delete chromium.launch;
      // Retain the exact original function, including inherited BrowserType methods.
      if (chromium.launch !== originalLaunch) throw new CaptureError('cleanup', '列表浏览器调用恢复失败');
    },
  };
}

class AccessWatch {
  constructor(page, timers = {setTimeout, clearTimeout}) {
    this.page = page;
    this.timers = timers;
    this.error = null;
    this.tasks = new Set();
    this.closed = false;
    this.received = response => this.onResponse(response);
    this.pageClosed = () => this.dispose();
    page.on('response', this.received);
    page.on('close', this.pageClosed);
  }

  onResponse(response) {
    if (this.closed) return;
    let url;
    try { url = new URL(response.url()); } catch (_) { return; }
    if (url.hostname !== 'shopee.ph'
        || !/^\/api\/v4\/(shop|pdp|search)\//.test(url.pathname)) return;
    const status = response.status();
    if (BLOCKED_STATUSES.has(status)) {
      this.error = `商品接口拒绝访问：${url.pathname}，HTTP ${status}`;
    }
    const task = Promise.resolve().then(async () => {
      let payload;
      try { payload = await response.json(); } catch (_) { return; }
      if (this.closed || !payload || typeof payload !== 'object' || Array.isArray(payload)) return;
      const denied = ['error', 'error_code', 'code'].some(key => String(payload[key]) === '90309999');
      if (denied && url.pathname !== '/api/v4/shop/get_shop_tab' && this.error === null) {
        this.error = `商品接口拒绝访问：${url.pathname}，业务错误码 90309999`;
      }
    });
    this.tasks.add(task);
    task.finally(() => this.tasks.delete(task));
  }

  async check() {
    if (this.error) return this.error;
    // Snapshot only bodies already received; do not wait for future requests/networkidle.
    const pending = Array.from(this.tasks);
    if (pending.length) {
      let timer;
      try {
        const finished = await Promise.race([
          Promise.allSettled(pending).then(() => true),
          new Promise(resolve => { timer = this.timers.setTimeout(() => resolve(false), 2000); }),
        ]);
        if (!finished) return this.error || '已收到的商品接口响应仍无法核对，停止接受本次快照';
      } finally {
        this.timers.clearTimeout(timer);
      }
    }
    return this.error;
  }

  dispose() {
    if (this.closed) return;
    this.closed = true;
    this.page.off('response', this.received);
    this.page.off('close', this.pageClosed);
  }
}

function loadPlaywright(modulePath) {
  try {
    const playwright = require(modulePath);
    const resolved = require.resolve(modulePath);
    let directory = path.dirname(resolved);
    let version;
    while (true) {
      const manifest = path.join(directory, 'package.json');
      if (fs.existsSync(manifest)) {
        const info = JSON.parse(fs.readFileSync(manifest, 'utf8'));
        if (['playwright', 'playwright-core'].includes(info.name)) {
          version = info.version;
          break;
        }
      }
      const parent = path.dirname(directory);
      if (parent === directory) break;
      directory = parent;
    }
    if (!playwright.chromium || typeof version !== 'string') {
      throw new Error('invalid module');
    }
    return {chromium: playwright.chromium, playwright_version: version};
  } catch (_) {
    throw new CaptureError('config', '无法加载指定的现有 Playwright 模块');
  }
}

async function capture(input, injectedDependencies = {}) {
  const config = validateConfig(input);
  const manualHandoff = injectedDependencies.manualHandoff;
  if (manualHandoff !== undefined && (typeof manualHandoff !== 'function' || config.headless)) {
    configError('人工接管仅允许显式启用的可见浏览器');
  }
  const dependencies = injectedDependencies.chromium ? injectedDependencies : loadPlaywright(config.playwright_module);
  const {chromium} = dependencies;
  const shim = installPersistentLaunchShim(chromium, config, injectedDependencies.env || process.env);
  let watch;
  let result;
  let failure;
  let removeNavigationWatch;
  let stage = 'runtime';
  try {
    const browser = await chromium.launch({
      headless: config.headless,
      args: ['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage', '--no-sandbox'],
    });
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      userAgent: config.user_agent,
      locale: config.locale,
      timezoneId: config.timezone_id,
      viewport: config.viewport,
      screen: config.screen,
    });
    await context.addInitScript(config.init_script);
    const startupPageCount = context.pages().length;
    if (!startupPageCount) await context.newPage();
    const page = await context.newPage();
    watch = new AccessWatch(page, injectedDependencies.timers);
    let documentResponse = null;
    if (manualHandoff) {
      const documentReceived = response => {
        try {
          if (response.request().isNavigationRequest() && response.frame() === page.mainFrame()) {
            documentResponse = response;
            // Only a new document starts a fresh access observation. A user's
            // resume command must not erase refusals already received by it.
            watch.dispose();
            watch = new AccessWatch(page, injectedDependencies.timers);
          }
        } catch (_) { /* An already detached frame is not the current document. */ }
      };
      page.on('response', documentReceived);
      removeNavigationWatch = () => page.off('response', documentReceived);
    }
    stage = 'navigation';
    try {
      const response = await page.goto(config.url, {waitUntil: 'domcontentloaded', timeout: config.navigation_timeout_ms});
      documentResponse = response;
    } catch (error) {
      if (!manualHandoff || (typeof page.isClosed === 'function' && page.isClosed())) throw error;
      // A navigation timeout need not destroy a still-live challenge window.
      // The current document must still pass the ordinary snapshot validator.
    }
    stage = 'runtime';
    await page.waitForTimeout(config.post_load_wait_ms);
    let readingSnapshot = false;
    const takeSnapshot = async ({afterResume = Boolean(manualHandoff)} = {}) => {
      if (readingSnapshot) throw new CaptureError('manual', '人工接管不能并发读取快照');
      readingSnapshot = true;
      let snapshotStage = 'settle';
      try {
        if (manualHandoff && afterResume) {
          await page.waitForTimeout(config.post_load_wait_ms);
        }
        snapshotStage = 'title';
        const title = await page.title();
        snapshotStage = 'content';
        const html = await page.content();
        snapshotStage = 'probe';
        const stealthProbe = await page.evaluate(STEALTH_PROBE);
        snapshotStage = 'access_check';
        const accessError = await watch.check();
        snapshotStage = 'metadata';
        return {
          html,
          final_url: page.url(),
          title,
          http_status: documentResponse ? documentResponse.status() : null,
          stealth_probe: stealthProbe,
          access_error: accessError,
          node_version: process.versions.node,
          playwright_version: dependencies.playwright_version,
          startup_page_count: startupPageCount,
        };
      } catch (error) {
        if (!manualHandoff) throw error;
        const failure = new CaptureError(
          error && error.name === 'TimeoutError' ? 'timeout' : 'runtime',
          '当前列表页面读取失败，未输出页面或内部错误正文',
        );
        failure.snapshotStage = snapshotStage;
        throw failure;
      } finally {
        readingSnapshot = false;
      }
    };
    result = manualHandoff ? await manualHandoff({page, context, takeSnapshot}) : await takeSnapshot();
  } catch (error) {
    if (error instanceof CaptureError) failure = error;
    else if (error && error.name === 'TimeoutError') failure = new CaptureError('timeout', '列表浏览器操作超时');
    else failure = new CaptureError(stage, stage === 'navigation' ? '列表页面导航失败' : '列表浏览器采集失败');
  } finally {
    try {
      if (watch) watch.dispose();
      if (removeNavigationWatch) removeNavigationWatch();
      await shim.close();
    } catch (_) {
      failure = failure || new CaptureError('cleanup', '列表浏览器会话关闭失败');
    } finally {
      shim.restore();
    }
  }
  if (failure) throw failure;
  return result;
}

function createManualHandoff(readCommand, emit, {captureFirst = false} = {}) {
  return async ({page, takeSnapshot}) => {
    const command = async allowed => {
      const input = await readCommand();
      if (!input || typeof input !== 'object' || Array.isArray(input)
          || Object.keys(input).length !== 1 || typeof input.command !== 'string') {
        throw new CaptureError('manual', '人工接管指令格式无效');
      }
      if (input.command === 'abort') throw new CaptureError('manual', '人工接管已取消');
      if (!allowed.includes(input.command)) throw new CaptureError('manual', '人工接管收到非预期指令');
      return input.command;
    };
    let firstSnapshot = captureFirst;
    while (true) {
      if (!firstSnapshot) {
        let pagePath;
        try { pagePath = new URL(page.url()).pathname; } catch (_) { pagePath = '/'; }
        await emit({event: 'manual_handoff_ready', page_path: pagePath});
        await command(['resume']);
      }
      let snapshot;
      try {
        snapshot = await takeSnapshot({afterResume: !firstSnapshot});
      } catch (error) {
        if (typeof page.isClosed === 'function' && page.isClosed()) {
          throw new CaptureError('runtime', '人工接管页面已关闭，停止本次采集');
        }
        const stages = new Set(['settle', 'title', 'content', 'probe', 'access_check', 'metadata']);
        await emit({
          event: 'manual_snapshot_error',
          error_kind: error instanceof CaptureError && error.kind === 'timeout' ? 'timeout' : 'runtime',
          stage: error instanceof CaptureError && stages.has(error.snapshotStage) ? error.snapshotStage : 'metadata',
        });
        firstSnapshot = false;
        continue;
      }
      firstSnapshot = false;
      await emit({event: 'manual_snapshot', snapshot});
      const decision = await command(['accept', 'hold']);
      if (decision === 'accept') return snapshot;
      // Hold leaves the current document/context untouched for the user's next action.
    }
  };
}

async function main() {
  let lines;
  try {
    const args = process.argv.slice(2);
    const manualMode = args.includes('--manual-handoff');
    const captureFirst = args.includes('--capture-first');
    if (new Set(args).size !== args.length
        || args.some(value => !['--manual-handoff', '--capture-first'].includes(value))
        || (captureFirst && !manualMode)) {
      configError('列表采集命令行参数无效');
    }
    if (manualMode) {
      // A disconnected parent must lead through capture's cleanup, not an uncaught
      // EPIPE stack on stderr. The write callback below reports the safe failure.
      process.stdout.on('error', () => {});
      lines = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
      const iterator = lines[Symbol.asyncIterator]();
      const readJson = async kind => {
        let next;
        try { next = await iterator.next(); } catch (_) {
          throw new CaptureError(kind, '人工接管输入通道读取失败');
        }
        if (next.done) throw new CaptureError(kind, '人工接管输入通道已关闭');
        try { return JSON.parse(next.value); } catch (_) {
          throw new CaptureError(kind, '人工接管输入不是有效的单行 JSON');
        }
      };
      const config = await readJson('config');
      const emit = value => new Promise((resolve, reject) => {
        process.stdout.write(`${JSON.stringify(value)}\n`, error => {
          if (error) reject(new CaptureError('manual', '人工接管输出通道已关闭'));
          else resolve();
        });
      });
      await capture(config, {
        manualHandoff: createManualHandoff(() => readJson('manual'), emit, {captureFirst}),
      });
      return;
    }
    let input = '';
    for await (const chunk of process.stdin) input += chunk;
    let config;
    try { config = JSON.parse(input); } catch (_) { configError('列表采集配置不是有效的单个 JSON'); }
    const result = await capture(config);
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } catch (error) {
    const safeError = error instanceof CaptureError ? error : new CaptureError('runtime', '列表浏览器采集失败');
    if (!process.stdout.destroyed) {
      process.stdout.write(`${JSON.stringify({error: safeError.message, error_kind: safeError.kind})}\n`);
    }
    process.exitCode = 1;
  } finally {
    if (lines) lines.close();
  }
}

module.exports = {capture, createManualHandoff, installPersistentLaunchShim, AccessWatch, STEALTH_PROBE};
if (require.main === module) main();
