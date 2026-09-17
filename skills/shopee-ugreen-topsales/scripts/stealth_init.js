Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined,
  configurable: false
});

const injectedUserAgent =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' +
  'AppleWebKit/537.36 (KHTML, like Gecko) ' +
  'Chrome/122.0.0.0 Safari/537.36';
const injectedAppVersion = injectedUserAgent.replace(/^Mozilla\//, '');
const injectedUserAgentData = {
  brands: [
    { brand: 'Not(A:Brand', version: '99' },
    { brand: 'Google Chrome', version: '122' },
    { brand: 'Chromium', version: '122' }
  ],
  mobile: false,
  platform: 'Windows',
  getHighEntropyValues: async (hints) => {
    const values = {
      architecture: 'x86',
      bitness: '64',
      brands: injectedUserAgentData.brands,
      fullVersionList: [
        { brand: 'Not(A:Brand', version: '99.0.0.0' },
        { brand: 'Google Chrome', version: '122.0.0.0' },
        { brand: 'Chromium', version: '122.0.0.0' }
      ],
      mobile: false,
      model: '',
      platform: 'Windows',
      platformVersion: '10.0.0',
      uaFullVersion: '122.0.0.0',
      wow64: false
    };
    const selected = {};
    for (const hint of Array.isArray(hints) ? hints : []) {
      if (Object.prototype.hasOwnProperty.call(values, hint)) selected[hint] = values[hint];
    }
    return Object.assign({
      brands: values.brands,
      mobile: values.mobile,
      platform: values.platform
    }, selected);
  },
  toJSON: () => ({
    brands: injectedUserAgentData.brands,
    mobile: false,
    platform: 'Windows'
  })
};

Object.defineProperty(navigator, 'userAgent', {
  get: () => injectedUserAgent,
  configurable: false
});
Object.defineProperty(navigator, 'appVersion', {
  get: () => injectedAppVersion,
  configurable: false
});
Object.defineProperty(navigator, 'oscpu', {
  get: () => 'Windows NT 10.0; Win64; x64',
  configurable: false
});
Object.defineProperty(navigator, 'userAgentData', {
  get: () => injectedUserAgentData,
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

const OriginalDateTimeFormat = Intl.DateTimeFormat;
const InjectedDateTimeFormat = function(locales, options) {
  const injectedOptions = Object.assign({}, options || {});
  if (!Object.prototype.hasOwnProperty.call(injectedOptions, 'timeZone')) {
    injectedOptions.timeZone = 'Asia/Manila';
  }
  return new OriginalDateTimeFormat(locales || 'en-US', injectedOptions);
};
Object.setPrototypeOf(InjectedDateTimeFormat, OriginalDateTimeFormat);
InjectedDateTimeFormat.prototype = OriginalDateTimeFormat.prototype;
InjectedDateTimeFormat.supportedLocalesOf = OriginalDateTimeFormat.supportedLocalesOf.bind(
  OriginalDateTimeFormat
);
Intl.DateTimeFormat = InjectedDateTimeFormat;
Object.defineProperty(Date.prototype, 'getTimezoneOffset', {
  value: () => -480,
  configurable: false,
  writable: false
});

Object.defineProperty(window.screen, 'availWidth', { get: () => window.innerWidth });
Object.defineProperty(window.screen, 'availHeight', { get: () => window.innerHeight });
Object.defineProperty(window.screen, 'width', { get: () => 1366 });
Object.defineProperty(window.screen, 'height', { get: () => 768 });
Object.defineProperty(window, 'outerWidth', { get: () => 1366 });
Object.defineProperty(window, 'outerHeight', { get: () => 768 });

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
