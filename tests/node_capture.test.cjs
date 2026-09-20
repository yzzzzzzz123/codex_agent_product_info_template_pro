'use strict';

// Every browser object is fake. These tests do not access real Chrome/profile/network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const {EventEmitter} = require('node:events');
const {spawnSync} = require('node:child_process');
const {test} = require('node:test');

const SCRIPTS = path.join(__dirname, '..', 'skills', 'shopee-ugreen-topsales', 'scripts');
const HELPER = path.join(SCRIPTS, 'capture_list_page.cjs');
const INIT_TEMPLATE = fs.readFileSync(path.join(SCRIPTS, 'proxy-access.js'), 'utf8');
const PROFILE_CATALOG = JSON.parse(fs.readFileSync(path.join(SCRIPTS, 'browser-profiles.json'), 'utf8'));
const {capture, createManualHandoff, installPersistentLaunchShim, AccessWatch, STEALTH_PROBE} = require(HELPER);
const LIST_URL = 'https://shopee.ph/ugreen.ph?page=0&shop=64922227&sortBy=sales&tab=0';
const USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36';
const HTML = '<!doctype html><html><title>离线列表</title><body>单次 HTML</body></html>';
const US_REGION = {country_code: 'US', locale: 'en-US', languages: ['en-US', 'en'], timezone_id: 'America/New_York'};
const SG_REGION = {country_code: 'SG', locale: 'en-SG', languages: ['en-SG', 'en'], timezone_id: 'Asia/Singapore'};
const PH_REGION = {country_code: 'PH', locale: 'en-PH', languages: ['en-PH', 'en'], timezone_id: 'Asia/Manila'};
const CHROME_VERSION = '153.0.8010.50';
function fingerprintFixture(region = US_REGION, profileId = 'windows-intel', version = CHROME_VERSION) {
  const {id, ua_platform, ...fields} = PROFILE_CATALOG.profiles.find(profile => profile.id === profileId);
  return {
    profile_id: id, chrome_version: version,
    user_agent: `Mozilla/5.0 (${ua_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${version.split('.')[0]}.0.0.0 Safari/537.36`,
    ...fields, region: {...region, languages: [...region.languages]},
  };
}
function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort()
    .map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}
function renderInitScript(fingerprint) {
  return INIT_TEMPLATE.replace('__UGREEN_FINGERPRINT__', () => canonicalJson(fingerprint));
}
const INIT_SCRIPT = renderInitScript(fingerprintFixture());

function configFixture(t, region = US_REGION, profileId = 'windows-intel', version = CHROME_VERSION) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'shopees-ugreen-profile-node-test-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const profile = path.join(root, 'base');
  fs.mkdirSync(path.join(profile, 'Default'), {recursive: true});
  fs.writeFileSync(path.join(profile, 'Local State'), '{}');
  fs.writeFileSync(path.join(profile, 'Default', 'Cookies'), 'offline fixture only');
  const fingerprint = fingerprintFixture(region, profileId, version);
  return {
    playwright_module: path.join(root, 'fake-playwright'),
    user_data_dir: profile,
    chrome_executable: '/offline-fixture/Google Chrome',
    region: {...region, languages: [...region.languages]},
    fingerprint,
    init_script: renderInitScript(fingerprint),
    url: LIST_URL,
  };
}

function responseFixture(url, status = 200, payload = {}) {
  return {url: () => url, status: () => status, json: async () => payload};
}

function browserFixture(options = {}) {
  const calls = [];
  const startup = Array.from({length: options.startupPages ?? 1}, () => ({close() {
    assert.fail('persistent startup page must not be closed individually');
  }}));
  const created = [];
  const probe = {offline_probe: true};
  const context = {
    async addInitScript(script) {
      calls.push(['init', script]);
      if (options.initError) throw options.initError;
    },
    pages() { calls.push(['pages']); return [...startup, ...created]; },
    async newPage() {
      calls.push(['newPage']);
      const page = new EventEmitter();
      page.goto = async (url, args) => {
        calls.push(['goto', url, args]);
        for (const response of options.responses || []) page.emit('response', response);
        if (options.navigationError) throw options.navigationError;
        return options.noNavigationResponse ? null : {status: () => options.httpStatus ?? 200};
      };
      page.waitForTimeout = async duration => { calls.push(['wait', duration]); };
      page.title = async () => { calls.push(['title']); return '离线列表'; };
      page.content = async () => {
        calls.push(['content']);
        if (options.contentError) throw options.contentError;
        return HTML;
      };
      page.evaluate = async script => { calls.push(['probe', script]); return probe; };
      page.url = () => options.finalUrl || LIST_URL;
      created.push(page);
      return page;
    },
    async close() {
      calls.push(['close']);
      for (const page of created) page.emit('close');
      if (options.closeError) throw options.closeError;
    },
  };
  const originalLaunch = async () => assert.fail('original nonpersistent launch must not run');
  const chromium = {
    launch: originalLaunch,
    async launchPersistentContext(directory, args) {
      calls.push(['persistent', directory, args]);
      if (options.launchError) throw options.launchError;
      return context;
    },
  };
  return {calls, context, chromium, originalLaunch, created, probe,
    dependencies: {chromium, playwright_version: '1.63.0', env: {PATH: '/offline/path'}}};
}

test('historical lifecycle keeps startup page, waits in full, and reads raw HTML once', async t => {
  const config = configFixture(t);
  const fake = browserFixture();
  const result = await capture(config, fake.dependencies);
  assert.deepEqual(fake.calls.map(call => call[0]), [
    'persistent', 'init', 'pages', 'newPage', 'goto', 'wait', 'title', 'content', 'probe', 'close',
  ]);
  const launch = fake.calls[0];
  assert.equal(launch[1], fs.realpathSync(config.user_data_dir));
  assert.deepEqual(launch[2], {
    headless: false,
    args: ['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage', '--no-sandbox'],
    ignoreHTTPSErrors: true,
    userAgent: USER_AGENT,
    locale: 'en-US',
    timezoneId: 'America/New_York',
    viewport: {width: 1366, height: 768},
    screen: {width: 1366, height: 768},
    executablePath: config.chrome_executable,
    ignoreDefaultArgs: ['--use-mock-keychain', '--password-store=basic'],
    env: {PATH: '/offline/path'},
  });
  assert.equal(fake.calls[1][1], INIT_SCRIPT);
  assert.deepEqual(fake.calls[4], ['goto', LIST_URL, {waitUntil: 'domcontentloaded', timeout: 120000}]);
  assert.deepEqual(fake.calls[5], ['wait', 15000]);
  assert.equal(fake.calls[8][1], STEALTH_PROBE);
  assert.deepEqual(result, {
    html: HTML, final_url: LIST_URL, title: '离线列表', http_status: 200,
    stealth_probe: fake.probe, access_error: null, node_version: process.versions.node,
    playwright_version: '1.63.0', startup_page_count: 1,
  });
  assert.equal(fake.chromium.launch, fake.originalLaunch);
  assert.equal(fake.created[0].listenerCount('response'), 0);
  assert.equal(fake.created[0].listenerCount('close'), 0);
});

test('missing startup page gets a blank companion before the capture tab', async t => {
  const fake = browserFixture({startupPages: 0, noNavigationResponse: true});
  const result = await capture(configFixture(t), fake.dependencies);
  assert.equal(result.startup_page_count, 0);
  assert.equal(result.http_status, null);
  assert.equal(fake.created.length, 2);
  assert.deepEqual(fake.calls.map(call => call[0]).slice(0, 6), [
    'persistent', 'init', 'pages', 'newPage', 'newPage', 'goto',
  ]);
});

test('challenge navigation still waits and captures exactly once for Python validation', async t => {
  const fake = browserFixture({finalUrl: 'https://shopee.ph/verify/captcha', httpStatus: 403});
  const result = await capture(configFixture(t), fake.dependencies);
  assert.equal(result.final_url, 'https://shopee.ph/verify/captcha');
  assert.equal(result.http_status, 403);
  assert.equal(fake.calls.filter(call => call[0] === 'content').length, 1);
  assert.deepEqual(fake.calls.find(call => call[0] === 'wait'), ['wait', 15000]);
});

test('preload shim removes proxy and extra headers from both option sources and environment', async () => {
  const fake = browserFixture();
  const config = {user_data_dir: '/offline/profile', chrome_executable: '/offline/chrome'};
  const environment = {PATH: '/offline/path', HTTP_PROXY: 'fixture', https_proxy: 'fixture', ALL_PROXY: 'fixture', NO_PROXY: 'keep'};
  const originalEnvironment = {...environment};
  const shim = installPersistentLaunchShim(fake.chromium, config, environment);
  try {
    const browser = await fake.chromium.launch({proxy: {server: 'fixture'}, extraHTTPHeaders: {DNT: '1'}, headless: false});
    await browser.newContext({proxy: {server: 'second-fixture'}, extraHTTPHeaders: {Upgrade: 'fixture'}, locale: 'en-US'});
    const args = fake.calls[0][2];
    assert.equal(Object.hasOwn(args, 'proxy'), false);
    assert.equal(Object.hasOwn(args, 'extraHTTPHeaders'), false);
    assert.deepEqual(args.env, {PATH: '/offline/path', NO_PROXY: 'keep'});
    assert.deepEqual(environment, originalEnvironment);
    assert.deepEqual(args.ignoreDefaultArgs, ['--use-mock-keychain', '--password-store=basic']);
    await assert.rejects(browser.newContext({}), {kind: 'runtime'});
    await browser.close();
    await browser.close();
    assert.equal(fake.calls.filter(call => call[0] === 'close').length, 1);
  } finally {
    await shim.close();
    shim.restore();
  }
  assert.equal(fake.chromium.launch, fake.originalLaunch);
});

test('shim removes an override of inherited launch when restored, including failed close', async () => {
  const fake = browserFixture({closeError: new Error('private failure must not escape')});
  const inherited = Object.create({launch: fake.originalLaunch});
  inherited.launchPersistentContext = fake.chromium.launchPersistentContext;
  const shim = installPersistentLaunchShim(inherited, {user_data_dir: '/offline', chrome_executable: '/offline'});
  try {
    const browser = await inherited.launch({});
    await browser.newContext({});
    await assert.rejects(shim.close(), {kind: 'cleanup', message: '列表浏览器会话关闭失败'});
  } finally {
    shim.restore();
  }
  assert.equal(Object.hasOwn(inherited, 'launch'), false);
  assert.equal(inherited.launch, fake.originalLaunch);
});

test('failures close available context and restore launch without exposing underlying messages', async t => {
  for (const [field, kind, closeCount] of [
    ['navigationError', 'navigation', 1], ['contentError', 'runtime', 1],
    ['initError', 'runtime', 1], ['launchError', 'runtime', 0], ['closeError', 'cleanup', 1],
  ]) {
    await t.test(field, async sub => {
      const fake = browserFixture({[field]: new Error('PRIVATE_VALUE https://example.invalid/?token=PRIVATE_VALUE <html>')});
      await assert.rejects(capture(configFixture(sub), fake.dependencies), error => {
        assert.equal(error.kind, kind);
        assert.equal(error.message.includes('PRIVATE_VALUE'), false);
        return true;
      });
      assert.equal(fake.calls.filter(call => call[0] === 'close').length, closeCount);
      assert.equal(fake.chromium.launch, fake.originalLaunch);
      for (const page of fake.created) assert.equal(page.listenerCount('response'), 0);
    });
  }
});

test('navigation timeout stays a short categorized failure even when close also fails', async t => {
  const timeout = new Error('PRIVATE_NAVIGATION_DETAILS');
  timeout.name = 'TimeoutError';
  const fake = browserFixture({navigationError: timeout, closeError: new Error('PRIVATE_CLOSE_DETAILS')});
  await assert.rejects(capture(configFixture(t), fake.dependencies), {kind: 'timeout', message: '列表浏览器操作超时'});
  assert.equal(fake.chromium.launch, fake.originalLaunch);
});

test('configuration rejects empty, original, root, unrelated, incomplete or symlinked profiles', async t => {
  const config = configFixture(t);
  const fake = browserFixture();
  for (const profile of ['', 'relative/profile', os.tmpdir(), '/',
    path.join(os.homedir(), 'Library/Application Support/Google/Chrome')]) {
    await assert.rejects(capture({...config, user_data_dir: profile}, fake.dependencies), {kind: 'config'});
  }
  const unrelated = fs.mkdtempSync(path.join(os.tmpdir(), 'unrelated-node-capture-'));
  t.after(() => fs.rmSync(unrelated, {recursive: true, force: true}));
  await assert.rejects(capture({...config, user_data_dir: unrelated}, fake.dependencies), {kind: 'config'});
  const cookie = path.join(config.user_data_dir, 'Default', 'Cookies');
  fs.unlinkSync(cookie);
  await assert.rejects(capture(config, fake.dependencies), {kind: 'config'});
  const external = path.join(unrelated, 'external-cookie-fixture');
  fs.writeFileSync(external, 'offline fixture');
  fs.symlinkSync(external, cookie);
  await assert.rejects(capture(config, fake.dependencies), {kind: 'config'});
  assert.equal(fake.calls.length, 0);
});

test('URL validation accepts only the requested UGREEN Top Sales list', async t => {
  const config = configFixture(t);
  for (const url of [
    'https://shopee.ph/other-shop?page=0&sortBy=sales&tab=0',
    'http://shopee.ph/ugreen.ph?page=0&sortBy=sales&tab=0',
    'https://evil.invalid/ugreen.ph?page=0&sortBy=sales&tab=0',
    'https://shopee.ph/ugreen.ph?page=-1&sortBy=sales&tab=0',
    'https://shopee.ph/ugreen.ph?page=0&page=1&sortBy=sales&tab=0',
    'https://shopee.ph/ugreen.ph?page=0&shop=123&sortBy=sales&tab=0',
    'https://shopee.ph/ugreen.ph?page=0&sortBy=price&tab=0',
    'https://shopee.ph/ugreen.ph?page=0&sortBy=sales&tab=1',
    'https://name:private@shopee.ph/ugreen.ph?page=0&sortBy=sales&tab=0',
    `${LIST_URL}&token=private`, `${LIST_URL}#private`,
  ]) {
    const fake = browserFixture();
    await assert.rejects(capture({...config, url}, fake.dependencies), {kind: 'config'});
    assert.equal(fake.calls.length, 0);
  }
  const fake = browserFixture();
  await capture({...config, url: 'https://shopee.ph/ugreen.ph?page=27&sortBy=sales&tab=0'}, fake.dependencies);
  assert.equal(fake.calls.filter(call => call[0] === 'content').length, 1);
});

test('selected init script and full wait/identity cannot be silently weakened', async t => {
  const config = configFixture(t);
  for (const patch of [
    {init_script: ''}, {init_script: `${INIT_SCRIPT}\n`}, {post_load_wait_ms: 14999},
    {post_load_wait_ms: -1}, {navigation_timeout_ms: 0}, {headless: 'false'},
    {user_agent: 'changed'}, {locale: 'en-PH'}, {timezone_id: 'Asia/Manila'},
    {user_agent: USER_AGENT.replace('Chrome/153.', 'Chrome/122.')},
    {user_agent: USER_AGENT.replace('Chrome/153.', 'Chrome/154.')},
  ]) {
    await assert.rejects(capture({...config, ...patch}, browserFixture().dependencies), {kind: 'config'});
  }
});

test('US, SG and PH regions consistently drive context and template without changing selected hardware', async t => {
  for (const region of [US_REGION, SG_REGION, PH_REGION]) {
    const config = configFixture(t, region);
    const fake = browserFixture();
    await capture(config, fake.dependencies);
    const options = fake.calls.find(call => call[0] === 'persistent')[2];
    assert.equal(options.locale, region.locale);
    assert.equal(options.timezoneId, region.timezone_id);
    assert.equal(options.userAgent, USER_AGENT);
    assert.deepEqual(options.viewport, {width: 1366, height: 768});
    assert.deepEqual(options.screen, {width: 1366, height: 768});
    assert.equal(Object.hasOwn(options, 'proxy'), false);
    const rendered = fake.calls.find(call => call[0] === 'init')[1];
    assert.equal(rendered, renderInitScript(config.fingerprint));
    assert.equal(rendered.includes('__UGREEN_'), false);
    assert.equal(rendered.replace(canonicalJson(config.fingerprint), '__UGREEN_FINGERPRINT__'), INIT_TEMPLATE);
  }
});

test('region is mandatory and rejects incomplete, mixed, unsupported or unsafe configuration before launch', async t => {
  const config = configFixture(t);
  const malformed = [
    undefined, null, [], {}, {locale: 'en-US'}, {...US_REGION, unexpected: 'PRIVATE'},
    {...US_REGION, country_code: 'us'}, {...US_REGION, country_code: 'USA'},
    {...US_REGION, country_code: 'SG'}, {...US_REGION, locale: 'en'},
    {...US_REGION, locale: 'en_US'}, {...US_REGION, locale: 'en-us'},
    {...US_REGION, locale: 'zz-US', languages: ['zz-US', 'zz']},
    {...US_REGION, languages: ['en-US', 'en', 'zh-CN']},
    {...US_REGION, languages: ['en-SG', 'en']}, {...US_REGION, languages: ['en-US', 'fr']},
    {...US_REGION, languages: 'en-US,en'}, {...US_REGION, timezone_id: 'Not/AZone'},
    {...US_REGION, timezone_id: '+08:00'}, {...US_REGION, timezone_id: ''},
    {...US_REGION, timezone_id: null}, {...US_REGION, locale: 'en-US\";PRIVATE'},
  ];
  for (const region of malformed) {
    const fake = browserFixture();
    await assert.rejects(capture({...config, region}, fake.dependencies), error => {
      assert.equal(error.kind, 'config');
      assert.equal(error.message.includes('PRIVATE'), false);
      return true;
    });
    assert.equal(fake.calls.length, 0);
  }
  const {region, ...missing} = config;
  await assert.rejects(capture(missing, browserFixture().dependencies), {kind: 'config'});
});

test('region accepts UTC and matching legacy fields but never mixes scripts or trusts caller hashes', async t => {
  const config = configFixture(t, SG_REGION);
  const utcRegion = {...SG_REGION, timezone_id: 'UTC'};
  const utc = browserFixture();
  await capture(configFixture(t, utcRegion), utc.dependencies);
  assert.equal(utc.calls[0][2].timezoneId, 'UTC');
  const matching = browserFixture();
  await capture({...config, locale: SG_REGION.locale, timezone_id: SG_REGION.timezone_id}, matching.dependencies);
  assert.equal(matching.calls[0][2].locale, SG_REGION.locale);
  for (const patch of [
    {init_script: INIT_SCRIPT}, {init_script: INIT_TEMPLATE}, {init_script: `${config.init_script}\n`},
    {init_script: 'PRIVATE_SCRIPT', stealth_sha256: 'caller supplied'},
    {init_script: config.init_script.replace('Win32', 'Linux x86_64')},
    {init_script: config.init_script.replace('"webgl_vendor":', '"webgl_vendor_tampered":')},
    {locale: 'en-US'}, {timezone_id: 'America/New_York'}, {locale: null}, {timezone_id: null},
  ]) {
    const fake = browserFixture();
    await assert.rejects(capture({...config, ...patch}, fake.dependencies), {kind: 'config'});
    assert.equal(fake.calls.length, 0);
  }
});

test('local template changes and unreadable templates fail closed without trusting caller content', async t => {
  const config = configFixture(t);
  const originalRead = fs.readFileSync;
  for (const tampered of [`${INIT_TEMPLATE}\n`, null]) {
    const fake = browserFixture();
    const read = t.mock.method(fs, 'readFileSync', function (filename, ...args) {
      if (filename === path.join(SCRIPTS, 'proxy-access.js')) {
        if (tampered === null) throw new Error('PRIVATE_TEMPLATE_PATH');
        return tampered;
      }
      return originalRead.call(this, filename, ...args);
    });
    try {
      await assert.rejects(capture(config, fake.dependencies), error => {
        assert.equal(error.kind, 'config');
        assert.equal(error.message.includes('PRIVATE'), false);
        return true;
      });
      assert.equal(fake.calls.length, 0);
    } finally {
      read.mock.restore();
    }
  }
});

test('all eight selected profiles remain coherent across US SG PH and follow the supplied Chrome major', async t => {
  assert.deepEqual(PROFILE_CATALOG.profiles.map(profile => profile.id), [
    'windows-intel', 'windows-nvidia', 'windows-amd', 'macos-intel', 'macos-amd',
    'linux-intel', 'linux-nvidia', 'linux-amd',
  ]);
  for (const profile of PROFILE_CATALOG.profiles) {
    for (const region of [US_REGION, SG_REGION, PH_REGION]) {
      const config = configFixture(t, region, profile.id, '154.1.9000.7');
      const before = JSON.stringify(config);
      const fake = browserFixture();
      await capture(config, fake.dependencies);
      const options = fake.calls.find(call => call[0] === 'persistent')[2];
      assert.equal(options.locale, region.locale);
      assert.equal(options.timezoneId, region.timezone_id);
      assert.equal(options.userAgent, config.fingerprint.user_agent);
      assert.ok(options.userAgent.includes(`(${profile.ua_platform})`));
      assert.ok(options.userAgent.includes('Chrome/154.0.0.0'));
      assert.deepEqual(options.viewport, {width: profile.screen_width, height: profile.screen_height});
      assert.deepEqual(options.screen, options.viewport);
      assert.equal(fake.calls.find(call => call[0] === 'init')[1], renderInitScript(config.fingerprint));
      assert.equal(Object.hasOwn(options, 'proxy'), false);
      assert.equal(JSON.stringify(config), before);
      const second = browserFixture();
      await capture(config, second.dependencies);
      assert.equal(second.calls.find(call => call[0] === 'init')[1], fake.calls.find(call => call[0] === 'init')[1]);
    }
  }
});

test('missing, forged, mixed or incomplete fingerprint configuration never starts the browser', async t => {
  const config = configFixture(t);
  const fingerprint = config.fingerprint;
  const mismatches = [
    undefined, null, [], {}, {...fingerprint, unexpected: 'PRIVATE'},
    {...fingerprint, profile_id: 'unknown'}, {...fingerprint, profile_id: 'macos-intel'},
    {...fingerprint, platform: 'MacIntel'}, {...fingerprint, vendor: 'Other'},
    {...fingerprint, hardware_concurrency: 16}, {...fingerprint, device_memory: 4},
    {...fingerprint, max_touch_points: 1}, {...fingerprint, pdf_viewer_enabled: false},
    {...fingerprint, screen_width: 1920}, {...fingerprint, screen_height: 1080},
    {...fingerprint, webgl_vendor: 'Intel Inc.'}, {...fingerprint, webgl_renderer: 'PRIVATE'},
    {...fingerprint, region: SG_REGION}, {...fingerprint, user_agent: USER_AGENT.replace('153.', '122.')},
    ...['', '153', '153.0.0', '0153.0.0.0', '153.00.0.0', '153.0.0001.0', '153.0.1.0\n',
      '99999.0.0.0', '153.1234567.0.0', '153.0.0.0;PRIVATE'].map(chrome_version => ({...fingerprint, chrome_version})),
  ];
  for (const key of Object.keys(fingerprint)) {
    const copy = {...fingerprint};
    delete copy[key];
    mismatches.push(copy);
  }
  for (const value of mismatches) {
    const fake = browserFixture();
    await assert.rejects(capture({...config, fingerprint: value}, fake.dependencies), error => {
      assert.equal(error.kind, 'config');
      assert.equal(error.message.includes('PRIVATE'), false);
      return true;
    });
    assert.equal(fake.calls.length, 0);
  }
});

test('redundant launch dimensions must equal the selected profile and scripts cannot mix selected profiles', async t => {
  const config = configFixture(t, SG_REGION, 'linux-nvidia');
  const dimensions = {width: config.fingerprint.screen_width, height: config.fingerprint.screen_height};
  const matching = browserFixture();
  await capture({...config, viewport: dimensions, screen: dimensions, user_agent: config.fingerprint.user_agent}, matching.dependencies);
  assert.deepEqual(matching.calls[0][2].viewport, dimensions);
  for (const patch of [
    {viewport: null}, {screen: null}, {viewport: {width: 1366, height: 768}},
    {screen: {...dimensions, extra: true}}, {screen: {width: String(dimensions.width), height: dimensions.height}},
    {user_agent: USER_AGENT}, {user_agent: null},
    {init_script: renderInitScript(fingerprintFixture(SG_REGION, 'windows-nvidia'))},
    {init_script: config.init_script.replace('fingerprint.webgl_vendor', '"PRIVATE_GPU"')},
  ]) {
    const fake = browserFixture();
    await assert.rejects(capture({...config, ...patch}, fake.dependencies), {kind: 'config'});
    assert.equal(fake.calls.length, 0);
  }
});

test('shared catalog validates exact schema unique fields complete profile IDs and coherent OS GPU values', async t => {
  const config = configFixture(t);
  const originalRead = fs.readFileSync;
  const encodeChangedProfile = patch => JSON.stringify({...PROFILE_CATALOG,
    profiles: PROFILE_CATALOG.profiles.map((profile, index) => index === 0 ? {...profile, ...patch} : profile)});
  const invalid = [
    null, 'PRIVATE_BAD_JSON', ' '.repeat(64 * 1024 + 1),
    JSON.stringify({...PROFILE_CATALOG, schema_version: true}),
    JSON.stringify({...PROFILE_CATALOG, unexpected: true}),
    JSON.stringify({...PROFILE_CATALOG, profiles: PROFILE_CATALOG.profiles.slice(1)}),
    JSON.stringify({...PROFILE_CATALOG, profiles: [PROFILE_CATALOG.profiles[1], ...PROFILE_CATALOG.profiles.slice(1)]}),
    JSON.stringify(PROFILE_CATALOG).replace('"schema_version":1', '"schema_version":1,"schema_version":1'),
    JSON.stringify(PROFILE_CATALOG).replace('"id":"windows-intel"', '"id":"windows-intel","id":"windows-intel"'),
    ...[
      {id: 'unknown'}, {extra: true}, {ua_platform: 'X11; Linux x86_64'}, {platform: 'MacIntel'},
      {vendor: 'Other'}, {hardware_concurrency: true}, {hardware_concurrency: 3}, {device_memory: 16},
      {max_touch_points: 1}, {pdf_viewer_enabled: 1}, {screen_width: 900}, {screen_height: 0},
      {screen_width: 7680}, {webgl_vendor: 'Intel Inc.'}, {webgl_renderer: 'Intel Iris OpenGL Engine'},
      {webgl_renderer: 'ANGLE (Intel, Direct3D11 D3D11 Metal)'},
      {webgl_vendor: 'Google Inc. (Intel)\n'},
    ].map(encodeChangedProfile),
  ];
  for (const raw of invalid) {
    const read = t.mock.method(fs, 'readFileSync', function (filename, ...args) {
      if (filename === path.join(SCRIPTS, 'browser-profiles.json')) {
        if (raw === null) throw new Error('PRIVATE_CATALOG_PATH');
        return raw;
      }
      return originalRead.call(this, filename, ...args);
    });
    const fake = browserFixture();
    try {
      await assert.rejects(capture(config, fake.dependencies), error => {
        assert.equal(error.kind, 'config');
        assert.equal(error.message.includes('PRIVATE'), false);
        return true;
      });
      assert.equal(fake.calls.length, 0);
    } finally {
      read.mock.restore();
    }
  }
});

test('access watch ignores only shop-tab business code, never HTTP refusal or other endpoint code', async t => {
  const config = configFixture(t);
  for (const [endpoint, status, payload, expected] of [
    ['/api/v4/shop/get_shop_tab', 200, {error: 90309999}, null],
    ['/api/v4/shop/get_shop_tab', 403, {error: 90309999}, 'HTTP 403'],
    ['/api/v4/shop/get_shop_base', 200, {error_code: '90309999'}, '业务错误码 90309999'],
    ['/api/v4/pdp/get', 418, {}, 'HTTP 418'],
    ['/api/v4/search/search_items', 429, {}, 'HTTP 429'],
    ['/api/v4/shop/get', 503, {}, 'HTTP 503'],
    ['/api/v4/other/get', 403, {code: 90309999}, null],
  ]) {
    const fake = browserFixture({responses: [responseFixture(`https://shopee.ph${endpoint}?token=PRIVATE`, status, payload)]});
    const result = await capture(config, fake.dependencies);
    if (expected === null) assert.equal(result.access_error, null);
    else {
      assert.ok(result.access_error.includes(expected));
      assert.ok(result.access_error.includes(endpoint));
      assert.equal(result.access_error.includes('PRIVATE'), false);
      assert.equal(result.access_error.includes('?'), false);
    }
    assert.equal(fake.calls.filter(call => call[0] === 'content').length, 1);
  }
  const external = browserFixture({responses: [responseFixture('https://external.invalid/api/v4/shop/get', 403, {error: 90309999})]});
  assert.equal((await capture(config, external.dependencies)).access_error, null);
});

test('access watch checks received body tasks for at most two seconds and detaches on close', async () => {
  const page = new EventEmitter();
  let scheduled;
  let cleared = false;
  const watch = new AccessWatch(page, {
    setTimeout(callback, ms) { scheduled = ms; queueMicrotask(callback); return 17; },
    clearTimeout(timer) { assert.equal(timer, 17); cleared = true; },
  });
  let resolveBody;
  page.emit('response', {
    url: () => 'https://shopee.ph/api/v4/shop/get?private=yes', status: () => 200,
    json: () => new Promise(resolve => { resolveBody = resolve; }),
  });
  assert.equal(await watch.check(), '已收到的商品接口响应仍无法核对，停止接受本次快照');
  assert.equal(scheduled, 2000);
  assert.equal(cleared, true);
  page.emit('close');
  resolveBody({error: 90309999});
  await Promise.allSettled(Array.from(watch.tasks));
  assert.equal(watch.error, null);
  assert.equal(page.listenerCount('response'), 0);
  assert.equal(page.listenerCount('close'), 0);
});

test('probe is limited to the same public fingerprint fields used by Python verification', () => {
  const fingerprint = fingerprintFixture();
  const navigator = {
    webdriver: undefined, userAgent: USER_AGENT, userAgentData: {toJSON: () => ({mobile: false})},
    language: 'en-US', languages: ['en-US', 'en'], platform: 'Win32', vendor: 'Google Inc.',
    plugins: Array(5), hardwareConcurrency: 8, deviceMemory: 8, maxTouchPoints: 0, pdfViewerEnabled: true,
  };
  const result = vm.runInNewContext(`(${STEALTH_PROBE.toString()})()`, {
    navigator,
    document: {createElement: () => ({getContext: () => ({getParameter: code =>
      code === 37445 ? fingerprint.webgl_vendor : fingerprint.webgl_renderer})})},
    window: {chrome: {runtime: {getManifest: () => ({version: CHROME_VERSION})}}, screen: {width: 1366, height: 768}},
    Intl: {DateTimeFormat: () => ({resolvedOptions: () => ({timeZone: 'America/New_York'})})},
  });
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    webdriver_is_undefined: true, user_agent: USER_AGENT, user_agent_data: {mobile: false},
    language: 'en-US', languages: ['en-US', 'en'], platform: 'Win32', vendor: 'Google Inc.',
    plugin_count: 5, hardware_concurrency: 8, device_memory: 8,
    max_touch_points: 0, pdf_viewer_enabled: true, chrome_version: CHROME_VERSION,
    webgl_vendor: fingerprint.webgl_vendor, webgl_renderer: fingerprint.webgl_renderer,
    chrome_runtime_present: true, time_zone: 'America/New_York', screen_width: 1366, screen_height: 768,
  });
});

function writeFakeModule(config, navigationFails = false) {
  fs.mkdirSync(config.playwright_module);
  fs.writeFileSync(path.join(config.playwright_module, 'package.json'), JSON.stringify({
    name: 'playwright-core', version: '1.63.0', main: 'index.cjs',
  }));
  fs.writeFileSync(path.join(config.playwright_module, 'index.cjs'), `
    const {EventEmitter} = require('node:events');
    module.exports.chromium = {
      async launch() { throw new Error('nonpersistent launch forbidden'); },
      async launchPersistentContext() {
        const page = new EventEmitter();
        page.goto = async () => {
          if (${navigationFails}) throw new Error('PRIVATE_ERROR https://example.invalid/?token=PRIVATE');
          return {status: () => 200};
        };
        page.waitForTimeout = async () => {};
        page.title = async () => '离线';
        page.content = async () => '<html>in-memory offline fixture</html>';
        page.evaluate = async () => ({offline: true});
        page.url = () => ${JSON.stringify(LIST_URL)};
        return {
          async addInitScript() {}, pages: () => [{}], async newPage() { return page; },
          async close() { page.emit('close'); },
        };
      },
    };
  `);
}

test('internal stdin/stdout protocol emits one JSON document and never runs on require', async t => {
  const config = configFixture(t);
  writeFakeModule(config);
  const success = spawnSync(process.execPath, [HELPER], {input: JSON.stringify(config), encoding: 'utf8'});
  assert.equal(success.status, 0);
  assert.equal(success.stderr, '');
  const result = JSON.parse(success.stdout);
  assert.equal(result.html, '<html>in-memory offline fixture</html>');
  assert.equal(result.playwright_version, '1.63.0');
  assert.equal(success.stdout.trim().split('\n').length, 1);
  const imported = spawnSync(process.execPath, ['-e', `require(${JSON.stringify(HELPER)})`], {encoding: 'utf8'});
  assert.equal(imported.status, 0);
  assert.equal(imported.stdout, '');
  assert.equal(imported.stderr, '');
});

test('protocol navigation and malformed-input failures expose no raw errors or stderr', async t => {
  const config = configFixture(t);
  writeFakeModule(config, true);
  for (const [input, kind] of [[JSON.stringify(config), 'navigation'], ['PRIVATE_BAD_JSON', 'config'], ['{}', 'config']]) {
    const failure = spawnSync(process.execPath, [HELPER], {input, encoding: 'utf8'});
    assert.equal(failure.status, 1);
    assert.equal(failure.stderr, '');
    const result = JSON.parse(failure.stdout);
    assert.deepEqual(Object.keys(result).sort(), ['error', 'error_kind']);
    assert.equal(result.error_kind, kind);
    assert.equal(failure.stdout.includes('PRIVATE'), false);
    assert.equal(failure.stdout.includes('<html>'), false);
    assert.equal(failure.stdout.trim().split('\n').length, 1);
  }
});

test('manual callback starts after full load wait but before any content read and keeps context open', async t => {
  const fake = browserFixture();
  const result = await capture(configFixture(t), {
    ...fake.dependencies,
    async manualHandoff({page, context, takeSnapshot}) {
      assert.equal(context, fake.context);
      assert.equal(page, fake.created[0]);
      assert.deepEqual(fake.calls.map(call => call[0]), [
        'persistent', 'init', 'pages', 'newPage', 'goto', 'wait',
      ]);
      const snapshot = await takeSnapshot();
      assert.equal(snapshot.html, HTML);
      assert.equal(fake.calls.filter(call => call[0] === 'content').length, 1);
      assert.equal(fake.calls.filter(call => call[0] === 'close').length, 0);
      assert.deepEqual(fake.calls.filter(call => call[0] === 'wait'), [['wait', 15000], ['wait', 15000]]);
      return snapshot;
    },
  });
  assert.equal(result.html, HTML);
  assert.equal(fake.calls.filter(call => call[0] === 'close').length, 1);
  assert.equal(fake.created[0].listenerCount('response'), 0);
  assert.equal(fake.created[0].listenerCount('close'), 0);
});

test('manual resume drops old API denial but records fresh denial and latest main-document status', async t => {
  const blocked = responseFixture('https://shopee.ph/api/v4/shop/rcmd_items', 403, {error: 90309999});
  const fake = browserFixture({responses: [blocked], httpStatus: 403});
  await capture(configFixture(t), {
    ...fake.dependencies,
    async manualHandoff({page, takeSnapshot}) {
      const mainFrame = {};
      page.mainFrame = () => mainFrame;
      // A user's successful navigation replaces the initial challenge's HTTP status.
      page.emit('response', {
        request: () => ({isNavigationRequest: () => true}), frame: () => mainFrame,
        status: () => 200, url: () => LIST_URL,
      });
      // Subframes and ordinary resources never replace the document status.
      page.emit('response', {
        request: () => ({isNavigationRequest: () => true}), frame: () => ({}),
        status: () => 503, url: () => 'https://shopee.ph/frame',
      });
      page.emit('response', {
        request: () => ({isNavigationRequest: () => false}), frame: () => mainFrame,
        status: () => 404, url: () => 'https://shopee.ph/image',
      });
      const passed = await takeSnapshot();
      assert.equal(passed.http_status, 200);
      assert.equal(passed.access_error, null);
      const originalWait = page.waitForTimeout;
      page.waitForTimeout = async duration => {
        await originalWait(duration);
        page.emit('response', blocked);
      };
      const denied = await takeSnapshot();
      assert.match(denied.access_error, /HTTP 403/);
      assert.equal(denied.http_status, 200);
      return denied;
    },
  });
  assert.equal(fake.calls.filter(call => call[0] === 'goto').length, 1);
  assert.equal(fake.calls.filter(call => call[0] === 'content').length, 2);
  assert.equal(fake.created[0].listenerCount('response'), 0);
});

test('manual no-navigation resume retains document HTTP refusal', async t => {
  const fake = browserFixture({httpStatus: 403});
  const result = await capture(configFixture(t), {
    ...fake.dependencies, manualHandoff: async ({takeSnapshot}) => takeSnapshot(),
  });
  assert.equal(result.http_status, 403);
});

test('manual protocol hold reopens user handoff without navigating and accepts only on explicit command', async t => {
  const fake = browserFixture({finalUrl: 'https://shopee.ph/verify/captcha?secret=PRIVATE#private'});
  const commands = ['resume', 'hold', 'resume', 'accept'];
  const events = [];
  const handoff = createManualHandoff(async () => ({command: commands.shift()}), async event => {
    events.push(event);
    assert.equal(fake.calls.filter(call => call[0] === 'close').length, 0);
  });
  const result = await capture(configFixture(t), {...fake.dependencies, manualHandoff: handoff});
  assert.deepEqual(events.map(event => event.event), [
    'manual_handoff_ready', 'manual_snapshot', 'manual_handoff_ready', 'manual_snapshot',
  ]);
  assert.deepEqual(events[0], {event: 'manual_handoff_ready', page_path: '/verify/captcha'});
  assert.equal(JSON.stringify(events[0]).includes('PRIVATE'), false);
  assert.equal(result, events[3].snapshot);
  assert.equal(fake.calls.filter(call => call[0] === 'goto').length, 1);
  assert.equal(fake.calls.filter(call => call[0] === 'content').length, 2);
  assert.equal(fake.calls.filter(call => call[0] === 'close').length, 1);
  assert.equal(commands.length, 0);
});

test('manual handoff is opt-in headful and rejects malformed callbacks before launch', async t => {
  for (const [configPatch, manualHandoff] of [
    [{headless: true}, async () => {}], [{}, true],
  ]) {
    const fake = browserFixture();
    await assert.rejects(capture({...configFixture(t), ...configPatch}, {
      ...fake.dependencies, manualHandoff,
    }), {kind: 'config'});
    assert.equal(fake.calls.length, 0);
  }
});

test('manual abort or illegal command closes safely without reading premature HTML', async t => {
  for (const value of [null, [], {}, {command: 'abort'}, {command: 'accept'},
    {command: 'hold'}, {command: 'resume', unexpected: 'PRIVATE'}]) {
    const fake = browserFixture();
    const handoff = createManualHandoff(async () => value, async () => {});
    await assert.rejects(capture(configFixture(t), {...fake.dependencies, manualHandoff: handoff}), error => {
      assert.equal(error.kind, 'manual');
      assert.equal(error.message.includes('PRIVATE'), false);
      return true;
    });
    assert.equal(fake.calls.filter(call => call[0] === 'content').length, 0);
    assert.equal(fake.calls.filter(call => call[0] === 'close').length, 1);
    assert.equal(fake.created[0].listenerCount('response'), 0);
  }
});

test('manual CLI exchanges line JSON and never emits duplicate final result', async t => {
  const config = configFixture(t);
  writeFakeModule(config);
  const lines = [config, {command: 'resume'}, {command: 'hold'}, {command: 'resume'}, {command: 'accept'}];
  const result = spawnSync(process.execPath, [HELPER, '--manual-handoff'], {
    input: lines.map(value => JSON.stringify(value)).join('\n') + '\n', encoding: 'utf8', timeout: 5000,
  });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  assert.equal(result.stderr, '');
  const events = result.stdout.trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(events.map(event => event.event), [
    'manual_handoff_ready', 'manual_snapshot', 'manual_handoff_ready', 'manual_snapshot',
  ]);
  assert.deepEqual(events[0], {event: 'manual_handoff_ready', page_path: '/ugreen.ph'});
  assert.equal(events[1].snapshot.html, '<html>in-memory offline fixture</html>');
  assert.equal(events[3].snapshot.playwright_version, '1.63.0');
});

test('manual CLI EOF, abort, illegal states and malformed JSON close with safe categorized errors', async t => {
  const config = configFixture(t);
  writeFakeModule(config);
  const cases = [
    [JSON.stringify(config)],
    [JSON.stringify(config), JSON.stringify({command: 'abort'})],
    [JSON.stringify(config), 'PRIVATE_BAD_JSON'],
    [JSON.stringify(config), JSON.stringify({command: 'accept'})],
    [JSON.stringify(config), JSON.stringify({command: 'resume'})],
    [JSON.stringify(config), JSON.stringify({command: 'resume'}), JSON.stringify({command: 'resume'})],
  ];
  for (const lines of cases) {
    const result = spawnSync(process.execPath, [HELPER, '--manual-handoff'], {
      input: lines.join('\n') + '\n', encoding: 'utf8', timeout: 5000,
    });
    assert.equal(result.status, 1, result.stderr || result.error?.message);
    assert.equal(result.stderr, '');
    const events = result.stdout.trim().split('\n').map(line => JSON.parse(line));
    const last = events.at(-1);
    assert.deepEqual(Object.keys(last).sort(), ['error', 'error_kind']);
    assert.equal(last.error_kind, 'manual');
    assert.equal(JSON.stringify(last).includes('PRIVATE'), false);
    assert.equal(JSON.stringify(last).includes('<html>'), false);
  }
});

test('capture-first reads immediately after the existing wait and preserves original API observations', async t => {
  const fake = browserFixture({responses: [
    responseFixture('https://shopee.ph/api/v4/shop/rcmd_items', 403, {error: 90309999}),
  ]});
  const events = [];
  const handoff = createManualHandoff(async () => ({command: 'accept'}), async event => events.push(event),
    {captureFirst: true});
  const result = await capture(configFixture(t), {...fake.dependencies, manualHandoff: handoff});
  assert.deepEqual(events.map(event => event.event), ['manual_snapshot']);
  assert.match(result.access_error, /HTTP 403/);
  assert.deepEqual(fake.calls.filter(call => call[0] === 'wait'), [['wait', 15000]]);
  assert.equal(fake.calls.filter(call => call[0] === 'content').length, 1);
  assert.equal(fake.calls.filter(call => call[0] === 'goto').length, 1);
});

test('capture-first rejected snapshot waits for user before a fresh resumed snapshot', async t => {
  const fake = browserFixture({responses: [
    responseFixture('https://shopee.ph/api/v4/shop/rcmd_items', 403, {error: 90309999}),
  ]});
  const commands = ['hold', 'resume', 'accept'];
  const events = [];
  const handoff = createManualHandoff(async () => ({command: commands.shift()}), async event => {
    events.push(event);
    if (event.event === 'manual_handoff_ready') {
      assert.equal(fake.calls.filter(call => call[0] === 'content').length, 1);
      assert.equal(fake.calls.filter(call => call[0] === 'close').length, 0);
      const page = fake.created[0];
      const mainFrame = {};
      page.mainFrame = () => mainFrame;
      page.emit('response', {request: () => ({isNavigationRequest: () => true}),
        frame: () => mainFrame, status: () => 200, url: () => LIST_URL});
    }
  }, {captureFirst: true});
  const result = await capture(configFixture(t), {...fake.dependencies, manualHandoff: handoff});
  assert.deepEqual(events.map(event => event.event), ['manual_snapshot', 'manual_handoff_ready', 'manual_snapshot']);
  assert.match(events[0].snapshot.access_error, /HTTP 403/);
  assert.equal(result.access_error, null);
  assert.deepEqual(fake.calls.filter(call => call[0] === 'wait'), [['wait', 15000], ['wait', 15000]]);
  assert.equal(fake.calls.filter(call => call[0] === 'goto').length, 1);
});

test('manual resume does not erase API refusals already received by the current document', async t => {
  const fake = browserFixture();
  const result = await capture(configFixture(t), {...fake.dependencies,
    async manualHandoff({page, takeSnapshot}) {
      const mainFrame = {};
      page.mainFrame = () => mainFrame;
      page.emit('response', {request: () => ({isNavigationRequest: () => true}),
        frame: () => mainFrame, status: () => 200, url: () => LIST_URL});
      page.emit('response', responseFixture('https://shopee.ph/api/v4/shop/rcmd_items', 200, {error: 90309999}));
      return takeSnapshot();
    },
  });
  assert.match(result.access_error, /90309999/);
});

test('manual navigation failure retains a live page for strict snapshot verification', async t => {
  const fake = browserFixture({navigationError: new Error('PRIVATE_NAVIGATION_ERROR')});
  let reached = false;
  const result = await capture(configFixture(t), {...fake.dependencies,
    async manualHandoff({takeSnapshot}) {
      reached = true;
      assert.equal(fake.calls.filter(call => call[0] === 'close').length, 0);
      return takeSnapshot({afterResume: false});
    },
  });
  assert.equal(reached, true);
  assert.equal(result.html, HTML);
  assert.equal(fake.calls.filter(call => call[0] === 'goto').length, 1);
});

test('manual snapshot read failure exposes only safe stage then holds the live page for explicit resume', async t => {
  const options = {contentError: new Error('PRIVATE_RAW_PAGE_ERROR <html>')};
  const fake = browserFixture(options);
  const commands = ['resume', 'accept'];
  const events = [];
  const handoff = createManualHandoff(async () => {
    options.contentError = null;
    return {command: commands.shift()};
  }, async event => {
    events.push(event);
    if (event.event === 'manual_handoff_ready') {
      assert.equal(fake.calls.filter(call => call[0] === 'close').length, 0);
      assert.equal(fake.calls.filter(call => call[0] === 'goto').length, 1);
      assert.equal(fake.calls.filter(call => call[0] === 'content').length, 1);
    }
  }, {captureFirst: true});
  const result = await capture(configFixture(t), {...fake.dependencies, manualHandoff: handoff});
  assert.deepEqual(events.map(event => event.event), [
    'manual_snapshot_error', 'manual_handoff_ready', 'manual_snapshot',
  ]);
  assert.deepEqual(events[0], {event: 'manual_snapshot_error', error_kind: 'runtime', stage: 'content'});
  assert.equal(JSON.stringify(events[0]).includes('PRIVATE'), false);
  assert.equal(result.html, HTML);
  assert.equal(fake.calls.filter(call => call[0] === 'close').length, 1);
  assert.equal(fake.calls.filter(call => call[0] === 'goto').length, 1);
  assert.equal(fake.created[0].listenerCount('response'), 0);
});

test('manual title and probe timeout stages are safe and remain opt-in', async t => {
  for (const [method, stage] of [['title', 'title'], ['evaluate', 'probe']]) {
    const fake = browserFixture();
    const events = [];
    await assert.rejects(capture(configFixture(t), {
      ...fake.dependencies,
      async manualHandoff(options) {
        const timeout = new Error('PRIVATE_HTML_AND_TOKENS');
        timeout.name = 'TimeoutError';
        options.page[method] = async () => { throw timeout; };
        return createManualHandoff(async () => ({command: 'abort'}), async event => events.push(event),
          {captureFirst: true})(options);
      },
    }), {kind: 'manual'});
    assert.deepEqual(events[0], {event: 'manual_snapshot_error', error_kind: 'timeout', stage});
    assert.equal(JSON.stringify(events).includes('PRIVATE'), false);
    assert.equal(fake.calls.filter(call => call[0] === 'close').length, 1);
  }
});

test('manual closed-page read failure terminates safely rather than waiting for impossible recovery', async t => {
  const fake = browserFixture({contentError: new Error('PRIVATE_CLOSED_PAGE')});
  const events = [];
  await assert.rejects(capture(configFixture(t), {
    ...fake.dependencies,
    async manualHandoff(options) {
      options.page.isClosed = () => true;
      return createManualHandoff(async () => assert.fail('closed page cannot wait for commands'),
        async event => events.push(event), {captureFirst: true})(options);
    },
  }), {kind: 'runtime', message: '人工接管页面已关闭，停止本次采集'});
  assert.deepEqual(events, []);
  assert.equal(fake.calls.filter(call => call[0] === 'close').length, 1);
  assert.equal(fake.created[0].listenerCount('response'), 0);
});

test('capture-first CLI accepts directly or holds for human and rejects standalone flag', async t => {
  const config = configFixture(t);
  writeFakeModule(config);
  for (const commands of [['accept'], ['hold', 'resume', 'accept']]) {
    const lines = [config, ...commands.map(command => ({command}))];
    const result = spawnSync(process.execPath, [HELPER, '--manual-handoff', '--capture-first'], {
      input: lines.map(value => JSON.stringify(value)).join('\n') + '\n', encoding: 'utf8', timeout: 5000,
    });
    assert.equal(result.status, 0, result.stderr || result.error?.message);
    assert.equal(result.stderr, '');
    const events = result.stdout.trim().split('\n').map(line => JSON.parse(line));
    assert.deepEqual(events.map(event => event.event), commands.length === 1 ? ['manual_snapshot']
      : ['manual_snapshot', 'manual_handoff_ready', 'manual_snapshot']);
  }
  const invalid = spawnSync(process.execPath, [HELPER, '--capture-first'], {
    input: JSON.stringify(config), encoding: 'utf8', timeout: 5000,
  });
  assert.equal(invalid.status, 1);
  assert.equal(JSON.parse(invalid.stdout).error_kind, 'config');
  assert.equal(invalid.stderr, '');
});
