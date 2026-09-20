const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');

const collectRepoRootCandidates = () => {
  const candidates = [];
  const pushCandidate = (candidatePath) => {
    if (!candidatePath) return;
    const normalized = path.resolve(candidatePath);
    if (!candidates.includes(normalized)) candidates.push(normalized);
  };

  pushCandidate(path.resolve(__dirname, '..', '..', '..'));
  pushCandidate(path.resolve(fs.realpathSync(__dirname), '..', '..', '..'));
  pushCandidate(process.cwd());

  return candidates;
};

const resolveEnvNodePackage = () => {
  for (const repoRoot of collectRepoRootCandidates()) {
    const envPackage = path.join(repoRoot, 'env', 'node', 'package.json');
    if (fs.existsSync(envPackage)) return { repoRoot, envPackage };
  }
  throw new Error(
    'Cannot locate env/node/package.json. Prepare repo-local Node dependencies under env/node first.'
  );
};

const { repoRoot, envPackage: ENV_NODE_PACKAGE } = resolveEnvNodePackage();
const envRequire = createRequire(ENV_NODE_PACKAGE);
const { chromium } = envRequire('playwright');

if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(repoRoot, 'env', 'ms-playwright');
}

const DEFAULT_PROXY_ENV = {
  GOLDRUSH_PROXY_SERVER: 'http://goldrush-proxy.byteintl.net:1935',
  GOLDRUSH_PROXY_USERNAME: 'browserAmazon',
  GOLDRUSH_PROXY_PASSWORD:
    'amazon-X-RID-z-test-yf-AP-z-x435gctttmini-zone-custom-region-us-W-MPwPSLXe54-W-19p7v718r8e2-ne.bytefrontica.com-W-2333-Y-APPC-Z-1',
};

const collectConfigCandidates = (outputDir, filename) => {
  const candidates = [];
  const pushCandidate = (p) => {
    if (!p) return;
    const normalized = path.resolve(p);
    if (!candidates.includes(normalized)) candidates.push(normalized);
  };

  pushCandidate(path.resolve(process.cwd(), filename));
  pushCandidate(path.resolve(__dirname, filename));
  pushCandidate(path.resolve(__dirname, '..', filename));

  if (outputDir) {
    let dir = path.resolve(outputDir);
    for (let hop = 0; hop < 12; hop++) {
      pushCandidate(path.join(dir, filename));
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }

  return candidates;
};

const parseKeyValueLines = (content, matcher) => {
  const loadedKeys = [];
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const match = line.match(matcher);
    if (!match) continue;
    const [, key, rawValue] = match;
    if (process.env[key]) continue;
    let value = rawValue.trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
    loadedKeys.push(key);
  }
  return loadedKeys;
};

const loadConfigFile = (candidatePaths, matcher) => {
  for (const envPath of candidatePaths) {
    if (!fs.existsSync(envPath)) continue;
    const content = fs.readFileSync(envPath, 'utf8');
    const loadedKeys = parseKeyValueLines(content, matcher);
    if (loadedKeys.length > 0) return envPath;
  }
  return null;
};

const loadDotEnv = (candidatePaths) => loadConfigFile(candidatePaths, /^([^=]+)=(.*)$/);

const loadBashExports = (candidatePaths) =>
  loadConfigFile(candidatePaths, /^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)[\s=]*\s*(.*)$/);

const bootstrapProxyEnv = (outputDir) => {
  const envLoaded = loadDotEnv(collectConfigCandidates(outputDir, '.env'));
  const bashLoaded = loadBashExports(collectConfigCandidates(outputDir, '.bashrc'));
  for (const [key, value] of Object.entries(DEFAULT_PROXY_ENV)) {
    if (!process.env[key]) process.env[key] = value;
  }
  return envLoaded || bashLoaded || 'built-in-defaults';
};

const requiredEnv = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var: ${name}`);
  return value;
};

const parseBoolEnv = (name, defaultValue) => {
  const raw = process.env[name];
  if (raw === null || raw === undefined || raw === '') return defaultValue;
  return raw === '1' || raw.toLowerCase() === 'true';
};

const defaultHeadless = () => {
  if (process.platform === 'win32' || process.platform === 'darwin') return false;
  return !process.env.DISPLAY;
};

const ensureDir = (dirPath) => {
  fs.mkdirSync(dirPath, { recursive: true });
};

const parseViewport = () => {
  const raw = process.env.PLAYWRIGHT_PROXY_VIEWPORT || '1366x768';
  const match = raw.match(/^(\d+)x(\d+)$/);
  if (!match) return { width: 1366, height: 768 };
  return { width: Number(match[1]), height: Number(match[2]) };
};

const normalizeLanguageTag = (value) => String(value || 'en-US').replace('_', '-');

const buildExtraHeaders = (locale) => ({
  'Accept-Language': normalizeLanguageTag(locale),
  'DNT': '1',
  'Upgrade-Insecure-Requests': '1',
});

const buildStealthScript = (viewport) => `
  Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: false
  });

  const originalGetOwnPropertyNames = Object.getOwnPropertyNames;
  Object.getOwnPropertyNames = new Proxy(originalGetOwnPropertyNames, {
    apply: (target, thisArg, args) => {
      const result = target.apply(thisArg, args);
      return result.filter(
        (name) => !name.startsWith('cdc_') && !name.startsWith('__playwright') && !name.startsWith('__pw')
      );
    }
  });

  for (const key of Object.keys(window)) {
    if (key.startsWith('__playwright') || key.startsWith('__pw') || key.startsWith('cdc_')) {
      try { delete window[key]; } catch (e) {}
    }
  }

  window.chrome = {
    runtime: {
      onInstalled: { addListener: () => {}, removeListener: () => {} },
      sendMessage: () => {},
      connect: () => ({}),
      getManifest: () => ({ version: '122.0.0.0' })
    },
    loadTimes: () => ({
      requestTime: Date.now() / 1000,
      startLoadTime: Date.now() / 1000,
      commitLoadTime: Date.now() / 1000,
      finishDocumentLoadTime: Date.now() / 1000,
      finishLoadTime: Date.now() / 1000,
      firstPaintTime: Date.now() / 1000 + 0.1,
      firstContentfulPaintTime: Date.now() / 1000 + 0.12,
      domContentLoadedEventEnd: Date.now() / 1000 + 0.2,
      loadEventEnd: Date.now() / 1000 + 0.3
    }),
    csi: () => ({
      startE: Date.now(),
      onloadT: Date.now() + 300,
      pageT: 300,
      tran: 150,
      dns: 20,
      conn: 50,
      resp: 80
    }),
    app: {
      isInstalled: false,
      getDetails: () => {},
      getIsInstalled: () => false
    },
    webstore: {
      onInstallStageChanged: { addListener: () => {} },
      onDownloadProgress: { addListener: () => {} }
    }
  };

  const originalPermissionQuery = window.navigator.permissions &&
    typeof window.navigator.permissions.query === 'function'
    ? window.navigator.permissions.query.bind(window.navigator.permissions)
    : null;

  if (originalPermissionQuery) {
    window.navigator.permissions.query = (parameters) => {
      return parameters && parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalPermissionQuery(parameters);
    };
  }

  Object.defineProperty(navigator, 'plugins', {
    get: () => [
      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefghlsjai', description: 'Portable Document Format' },
      { name: 'Native Client', filename: 'internal-nacl-plugin', description: 'Native Client' },
      { name: 'Widevine Content Decryption Module', filename: 'widevinecdm', description: 'Enables Widevine licenses for playback of HTML audio/video content.' },
      { name: 'WebRTC Desktop Sharing', filename: 'webrtc-desktop-sharing', description: 'WebRTC Desktop Sharing' }
    ]
  });

  Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en', 'zh-CN'],
    configurable: false
  });

  Object.defineProperty(navigator, 'language', {
    get: () => 'en-US',
    configurable: false
  });

  Object.defineProperty(navigator, 'vendor', {
    get: () => 'Google Inc.',
    configurable: false
  });

  Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
    configurable: false
  });

  Object.defineProperty(navigator, 'maxTouchPoints', {
    get: () => 0,
    configurable: false
  });

  Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
    configurable: false
  });

  Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
    configurable: false
  });

  Object.defineProperty(navigator, 'pdfViewerEnabled', {
    get: () => true,
    configurable: false
  });

  Object.defineProperty(window.screen, 'availWidth', { get: () => window.innerWidth });
  Object.defineProperty(window.screen, 'availHeight', { get: () => window.innerHeight });
  Object.defineProperty(window.screen, 'width', { get: () => ${viewport.width} });
  Object.defineProperty(window.screen, 'height', { get: () => ${viewport.height} });
  Object.defineProperty(window, 'outerWidth', { get: () => ${viewport.width} });
  Object.defineProperty(window, 'outerHeight', { get: () => ${viewport.height} });

  const patchWebGL = (prototype) => {
    if (!prototype || typeof prototype.getParameter !== 'function') return;
    const originalGetParameter = prototype.getParameter;
    prototype.getParameter = function(parameter) {
      if (parameter === 37445) return 'Intel Inc.';
      if (parameter === 37446) return 'Intel Iris OpenGL Engine';
      return originalGetParameter.call(this, parameter);
    };
  };

  patchWebGL(window.WebGLRenderingContext && window.WebGLRenderingContext.prototype);
  patchWebGL(window.WebGL2RenderingContext && window.WebGL2RenderingContext.prototype);
`;

(async () => {
  let browser;
  try {
    const targetUrl = process.argv[2] || process.env.TARGET_URL;
    if (!targetUrl) throw new Error('Missing target URL (pass as argv[2] or set TARGET_URL)');

    const outputDir = process.argv[3] || process.env.OUTPUT_DIR || process.cwd();
    ensureDir(outputDir);

    bootstrapProxyEnv(outputDir);

    const proxyServer = process.env.GOLDRUSH_PROXY_SERVER || 'http://goldrush-proxy.byteintl.net:1935';
    const proxyUsername = requiredEnv('GOLDRUSH_PROXY_USERNAME');
    const proxyPassword = requiredEnv('GOLDRUSH_PROXY_PASSWORD');
    const headlessDefault = defaultHeadless();
    const headless = parseBoolEnv('HEADLESS', headlessDefault);
    const viewport = parseViewport();
    const postLoadWaitMs = Number(process.env.PLAYWRIGHT_PROXY_POST_LOAD_WAIT_MS || '6000');
    const userAgent =
      process.env.PLAYWRIGHT_PROXY_USER_AGENT ||
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36';
    const locale = process.env.PLAYWRIGHT_PROXY_LOCALE || 'en-US';
    const timezoneId = process.env.PLAYWRIGHT_PROXY_TIMEZONE || 'America/New_York';

    browser = await chromium.launch({
      headless,
      proxy: {
        server: proxyServer,
        username: proxyUsername,
        password: proxyPassword,
      },
      args: [
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
        '--no-sandbox',
      ],
    });

    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      userAgent,
      locale,
      timezoneId,
      viewport,
      screen: viewport,
      extraHTTPHeaders: buildExtraHeaders(locale),
    });

    await context.addInitScript(buildStealthScript(viewport));
    const page = await context.newPage();

    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
    if (postLoadWaitMs > 0) {
      await page.waitForTimeout(postLoadWaitMs);
    }

    const title = await page.title();
    const renderedHtml = await page.content();

    const renderedPath = path.join(outputDir, 'rendered_page.html');
    const screenshotPath = path.join(outputDir, 'screenshot.png');
    const metaPath = path.join(outputDir, 'meta.json');

    fs.writeFileSync(renderedPath, renderedHtml, 'utf8');
    await page.screenshot({ path: screenshotPath, fullPage: true });
    fs.writeFileSync(
      metaPath,
      JSON.stringify(
        {
          title,
          url: targetUrl,
          saved_at: new Date().toISOString(),
          stealth_enabled: true,
          user_agent: userAgent,
          locale,
          timezone_id: timezoneId,
          viewport,
        },
        null,
        2
      ),
      'utf8'
    );

    process.stdout.write(`Saved rendered HTML: ${renderedPath}\n`);
    process.stdout.write(`Saved screenshot: ${screenshotPath}\n`);
    process.stdout.write(`Saved meta: ${metaPath}\n`);
  } catch (error) {
    process.stderr.write(`Runtime error: ${error.message}\n`);
    process.stderr.write(`${String(error.stack || error)}\n`);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
  }
})();
