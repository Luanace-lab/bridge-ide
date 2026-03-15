const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

async function verifyUnauthorizedWsTriggersRefresh(page, pagePath) {
  let tampered = false;

  await page.route(`${BASE_URL}/${pagePath}*`, async (route) => {
    if (tampered) {
      await route.continue();
      return;
    }
    tampered = true;
    const response = await route.fetch();
    let body = await response.text();
    body = body.replace(
      /window\.__BRIDGE_UI_TOKEN="[^"]*"/,
      'window.__BRIDGE_UI_TOKEN="stale-ui-token-for-ws-refresh-test"',
    );
    await route.fulfill({
      response,
      body,
      headers: {
        ...response.headers(),
        'content-type': 'text/html; charset=utf-8',
      },
    });
  });

  await page.goto(`${BASE_URL}/${pagePath}`, { waitUntil: 'domcontentloaded' });
  await page.waitForURL(new RegExp(`${pagePath.replace('.', '\\.')}.+_bridge_token_refresh=`), { timeout: 10000 });
  await expect(page).toHaveURL(/_bridge_token_refresh=/);
}

test('chat refreshes after websocket unauthorized close', async ({ page }) => {
  await verifyUnauthorizedWsTriggersRefresh(page, 'chat.html');
});

async function verifyUnauthorizedHttpTriggersRefresh(page, pagePath) {
  let tampered = false;

  await page.route(`${BASE_URL}/${pagePath}*`, async (route) => {
    if (tampered) {
      await route.continue();
      return;
    }
    tampered = true;
    const response = await route.fetch();
    let body = await response.text();
    body = body.replace(
      /window\.__BRIDGE_UI_TOKEN="[^"]*"/,
      'window.__BRIDGE_UI_TOKEN=""',
    );
    await route.fulfill({
      response,
      body,
      headers: {
        ...response.headers(),
        'content-type': 'text/html; charset=utf-8',
      },
    });
  });

  await page.route(`${BASE_URL}/n8n/executions*`, async (route) => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'authentication required' }),
    });
  });

  const startUrl = pagePath === 'control_center.html'
    ? `${BASE_URL}/${pagePath}#workflows`
    : `${BASE_URL}/${pagePath}`;
  await page.goto(startUrl, { waitUntil: 'domcontentloaded' });
  try {
    await page.evaluate((baseUrl) => {
      void fetch(`${baseUrl}/n8n/executions?limit=5`, {
        headers: { Accept: 'application/json' },
      }).catch(() => null);
    }, BASE_URL);
  } catch (error) {
    if (!String(error && error.message || '').includes('Execution context was destroyed')) {
      throw error;
    }
  }
  await page.waitForURL(new RegExp(`${pagePath.replace('.', '\\.')}.+_bridge_token_refresh=`), { timeout: 10000 });
}

test('chat refreshes after HTTP auth failure on n8n executions', async ({ page }) => {
  await verifyUnauthorizedHttpTriggersRefresh(page, 'chat.html');
});

test('control center refreshes after HTTP auth failure on n8n executions', async ({ page }) => {
  await verifyUnauthorizedHttpTriggersRefresh(page, 'control_center.html');
});
