  const fingerprint = __UGREEN_FINGERPRINT__;

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
      getManifest: () => ({ version: fingerprint.chrome_version })
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
    get: () => [...fingerprint.region.languages],
    configurable: false
  });

  Object.defineProperty(navigator, 'language', {
    get: () => fingerprint.region.locale,
    configurable: false
  });

  Object.defineProperty(navigator, 'vendor', {
    get: () => fingerprint.vendor,
    configurable: false
  });

  Object.defineProperty(navigator, 'platform', {
    get: () => fingerprint.platform,
    configurable: false
  });

  Object.defineProperty(navigator, 'maxTouchPoints', {
    get: () => fingerprint.max_touch_points,
    configurable: false
  });

  Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => fingerprint.hardware_concurrency,
    configurable: false
  });

  Object.defineProperty(navigator, 'deviceMemory', {
    get: () => fingerprint.device_memory,
    configurable: false
  });

  Object.defineProperty(navigator, 'pdfViewerEnabled', {
    get: () => fingerprint.pdf_viewer_enabled,
    configurable: false
  });

  Object.defineProperty(window.screen, 'availWidth', { get: () => window.innerWidth });
  Object.defineProperty(window.screen, 'availHeight', { get: () => window.innerHeight });
  Object.defineProperty(window.screen, 'width', { get: () => fingerprint.screen_width });
  Object.defineProperty(window.screen, 'height', { get: () => fingerprint.screen_height });
  Object.defineProperty(window, 'outerWidth', { get: () => fingerprint.screen_width });
  Object.defineProperty(window, 'outerHeight', { get: () => fingerprint.screen_height });

  const patchWebGL = (prototype) => {
    if (!prototype || typeof prototype.getParameter !== 'function') return;
    const originalGetParameter = prototype.getParameter;
    prototype.getParameter = function(parameter) {
      if (parameter === 37445) return fingerprint.webgl_vendor;
      if (parameter === 37446) return fingerprint.webgl_renderer;
      return originalGetParameter.call(this, parameter);
    };
  };

  patchWebGL(window.WebGLRenderingContext && window.WebGLRenderingContext.prototype);
  patchWebGL(window.WebGL2RenderingContext && window.WebGL2RenderingContext.prototype);
