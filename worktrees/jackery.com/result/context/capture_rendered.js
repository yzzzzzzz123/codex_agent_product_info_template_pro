const fs = require('fs');
const path = require('path');
const { chromium } = require('/Users/yuzhizheng/Desktop/codex/codex_agent_product_info_template_pro/env/node/node_modules/playwright');

const url = 'https://www.jackery.com/products/jackery-solar-generator-5000-plus';
const rawDir = path.resolve(__dirname, '../raw_html');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  });
  const context = await browser.newContext({
    locale: 'en-US',
    timezoneId: 'America/Los_Angeles',
    viewport: { width: 1440, height: 1000 },
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
  });
  const page = await context.newPage();
  const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForSelector('h1', { timeout: 20000 });
  await page.waitForTimeout(4000);
  await page.evaluate(async () => {
    const height = document.documentElement.scrollHeight;
    for (let y = 0; y < height; y += 1000) {
      window.scrollTo(0, y);
      await new Promise(resolve => setTimeout(resolve, 80));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(1500);

  const snapshot = await page.evaluate(() => {
    const text = el => el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : null;
    const checked = document.querySelector('input[type="radio"][name="Select Options"]:checked');
    const hiddenVariant = document.querySelector('input.product-variant-id[name="id"]');
    const options = Array.from(document.querySelectorAll('input[type="radio"][name="Select Options"]')).map(input => {
      const label = input.id ? document.querySelector(`label[for="${CSS.escape(input.id)}"]`) : input.closest('label');
      return {
        id: input.getAttribute('data-id') || input.value || input.id,
        checked: input.checked,
        disabled: input.disabled,
        label_text: text(label),
      };
    });
    const buttons = Array.from(document.querySelectorAll('button')).map(button => ({
      text: text(button),
      disabled: button.disabled,
    })).filter(item => item.text && /add to cart|sold out|unavailable/i.test(item.text));
    return {
      title: document.title,
      url: location.href,
      h1: Array.from(document.querySelectorAll('h1')).map(text).filter(Boolean),
      checked_variant_id: checked ? (checked.getAttribute('data-id') || checked.value || checked.id) : null,
      hidden_variant_id: hiddenVariant ? hiddenVariant.value : null,
      options,
      commerce_buttons: buttons,
      visible_body_excerpt: text(document.body).slice(0, 12000),
    };
  });

  snapshot.http_status = response ? response.status() : null;
  snapshot.captured_at = new Date().toISOString();
  fs.writeFileSync(path.join(rawDir, 'rendered_page.html'), await page.content(), 'utf8');
  fs.writeFileSync(path.join(rawDir, 'jackery_5000_plus_snapshot.json'), JSON.stringify(snapshot, null, 2), 'utf8');
  await page.screenshot({ path: path.join(rawDir, 'jackery_5000_plus_screenshot.png'), fullPage: true });
  await browser.close();
})().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
