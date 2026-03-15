const path = require('path');
const { test, expect } = require('playwright/test');

const STATIC_UI_BASE_127 = 'http://127.0.0.1:9787/Frontend';
const STATIC_UI_BASE_LOCALHOST = 'http://localhost:9787/Frontend';

function routeTrackerEndpoint(page, expectedBase, seenUrls) {
  return Promise.all([
    page.route(`${expectedBase}/task/tracker*`, async (route) => {
      seenUrls.push(route.request().url());
      await route.fulfill({
        status: 200,
        headers: {
          'access-control-allow-origin': '*',
          'content-type': 'application/json',
        },
        body: JSON.stringify({ tasks: [] }),
      });
    }),
    page.route(`${expectedBase}/task/queue*`, async (route) => {
      seenUrls.push(route.request().url());
      await route.fulfill({
        status: 200,
        headers: {
          'access-control-allow-origin': '*',
          'content-type': 'application/json',
        },
        body: JSON.stringify({ tasks: [] }),
      });
    }),
  ]);
}

test('shared runtime url helper resolves local and proxied hosts deterministically', async ({ page }) => {
  await page.goto('about:blank');
  await page.addScriptTag({ path: path.join(__dirname, 'bridge_runtime_urls.js') });

  const data = await page.evaluate(() => ({
    local127: window.BridgeRuntimeUrls.resolveConfig({ href: 'http://127.0.0.1:8787/Frontend/chat.html' }),
    localhost: window.BridgeRuntimeUrls.resolveConfig({ href: 'http://localhost:8787/Frontend/chat.html' }),
    proxy: window.BridgeRuntimeUrls.resolveConfig({ href: 'https://bridge.example.com/chat.html' }),
  }));

  expect(data.local127.apiBase).toBe('http://127.0.0.1:9111');
  expect(data.local127.wsUrl).toBe('ws://127.0.0.1:9112');
  expect(data.localhost.apiBase).toBe('http://localhost:9111');
  expect(data.localhost.wsUrl).toBe('ws://localhost:9112');
  expect(data.proxy.apiBase).toBe('https://bridge.example.com');
  expect(data.proxy.wsUrl).toBe('wss://bridge.example.com');
});

test('task tracker resolves API to 127.0.0.1 bridge port when served from a non-canonical UI port', async ({ page }) => {
  const seenUrls = [];
  await routeTrackerEndpoint(page, 'http://127.0.0.1:9111', seenUrls);

  await page.goto(`${STATIC_UI_BASE_127}/task_tracker.html`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#footerCount')).toContainText('0 Tasks gefunden');
  expect(seenUrls.some((url) => url.startsWith('http://127.0.0.1:9111/task/tracker'))).toBeTruthy();
});

test('task tracker preserves the current hostname when served as localhost on a non-canonical UI port', async ({ page }) => {
  const seenUrls = [];
  await routeTrackerEndpoint(page, 'http://localhost:9111', seenUrls);

  await page.goto(`${STATIC_UI_BASE_LOCALHOST}/task_tracker.html`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#footerCount')).toContainText('0 Tasks gefunden');
  expect(seenUrls.some((url) => url.startsWith('http://localhost:9111/task/tracker'))).toBeTruthy();
});
