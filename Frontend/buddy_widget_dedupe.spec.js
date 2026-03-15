const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';
const HARNESS_URL = `${BASE_URL}/buddy_widget_harness.html`;
const JSON_HEADERS = {
  'content-type': 'application/json',
};

async function installBuddyHarness(page) {
  await page.addInitScript(() => {
    localStorage.setItem('buddyWidgetFirstSeen', '1');
    window.WebSocket = class MockWebSocket {
      constructor() {
        setTimeout(() => {
          if (typeof this.onopen === 'function') this.onopen();
        }, 0);
      }
      send() {}
      close() {
        if (typeof this.onclose === 'function') this.onclose();
      }
    };
  });
}

test('buddy widget reloads history on first websocket connect for ui-role recovery', async ({ page }) => {
  let historyCalls = 0;

  await installBuddyHarness(page);

  await page.route(`${BASE_URL}/history*`, async (route) => {
    historyCalls += 1;
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ messages: [] }),
    });
  });

  await page.route(`${BASE_URL}/cli/detect*`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ cli: { available: [] }, tools: {} }),
    });
  });

  await page.route(`${BASE_URL}/agents/buddy`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ agent_id: 'buddy', active: true, online: true, tmux_alive: true, status: 'running' }),
    });
  });

  await page.goto(HARNESS_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(300);

  expect(historyCalls).toBeGreaterThanOrEqual(2);
});

test('buddy widget keeps user messages deduplicated and ordered after history merge', async ({ page }) => {
  const historyMessages = [];
  let nextId = 1000;

  await installBuddyHarness(page);

  await page.route(`${BASE_URL}/history*`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ messages: historyMessages }),
    });
  });

  await page.route(`${BASE_URL}/cli/detect*`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ cli: { available: [] }, tools: {} }),
    });
  });

  await page.route(`${BASE_URL}/agents/buddy`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ agent_id: 'buddy', active: false, online: false, tmux_alive: false, status: 'offline' }),
    });
  });

  await page.route(`${BASE_URL}/send`, async (route) => {
    const payload = route.request().postDataJSON();
    const now = new Date();
    historyMessages.push({
      id: ++nextId,
      from: 'user',
      to: 'buddy',
      content: payload.content,
      timestamp: now.toISOString(),
      meta: payload.meta || null,
    });
    historyMessages.push({
      id: ++nextId,
      from: 'buddy',
      to: 'user',
      content: `Reply to ${payload.content}`,
      timestamp: new Date(now.getTime() + 1000).toISOString(),
      meta: { reply_to_client_nonce: payload?.meta?.client_nonce || '' },
    });
    await route.fulfill({
      status: 201,
      headers: JSON_HEADERS,
      body: JSON.stringify({ ok: true }),
    });
  });

  await page.goto(HARNESS_URL, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    document.getElementById('buddyWidgetBubble').classList.add('open');
  });
  await expect(page.locator('#bwInput')).toBeVisible();

  await page.locator('#bwInput').fill('Hallo Buddy');
  await page.evaluate(() => document.getElementById('bwSend').click());
  await page.waitForTimeout(2300);

  await page.locator('#bwInput').fill('Test an Buddy');
  await page.evaluate(() => document.getElementById('bwSend').click());
  await page.waitForTimeout(2300);

  const renderedTexts = await page.locator('.bwMsg > span:first-child').evaluateAll((nodes) =>
    nodes.map((node) => node.textContent.trim())
  );

  expect(renderedTexts).toEqual([
    'Hallo Buddy',
    'Reply to Hallo Buddy',
    'Test an Buddy',
    'Reply to Test an Buddy',
  ]);
});

test('buddy widget reflects offline buddy state instead of a static green indicator', async ({ page }) => {
  await installBuddyHarness(page);

  await page.route(`${BASE_URL}/history*`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ messages: [] }),
    });
  });

  await page.route(`${BASE_URL}/cli/detect*`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ cli: { available: [] }, tools: {} }),
    });
  });

  await page.route(`${BASE_URL}/agents/buddy`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ agent_id: 'buddy', active: false, online: false, tmux_alive: false, status: 'offline' }),
    });
  });

  await page.goto(HARNESS_URL, { waitUntil: 'domcontentloaded' });

  await expect(page.locator('.bwHeader__dot')).toHaveAttribute('data-state', 'offline');
  await expect(page.locator('.bwHeader__name')).toHaveAttribute('title', /Buddy: offline/);
});

test('buddy widget hides operational chatter and waits for a real buddy reply', async ({ page }) => {
  let historyCall = 0;
  const historyMessages = [];
  let nextId = 2000;

  await installBuddyHarness(page);

  await page.route(`${BASE_URL}/history*`, async (route) => {
    historyCall += 1;
    if (historyCall >= 2 && historyMessages.length === 1) {
      historyMessages.push({
        id: ++nextId,
        from: 'buddy',
        to: 'user',
        content: 'HEARTBEAT_CHECK verarbeitet. Status: keine aktive Buddy-Aufgabe in acked.',
        timestamp: new Date(Date.UTC(2026, 2, 14, 21, 10, 5)).toISOString(),
        meta: null,
      });
    }
    if (historyCall >= 3 && historyMessages.length === 2) {
      historyMessages.push({
        id: ++nextId,
        from: 'buddy',
        to: 'user',
        content: 'SLICE47_OK',
        timestamp: new Date(Date.UTC(2026, 2, 14, 21, 10, 9)).toISOString(),
        meta: null,
      });
    }
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ messages: historyMessages }),
    });
  });

  await page.route(`${BASE_URL}/cli/detect*`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ cli: { available: [] }, tools: {} }),
    });
  });

  await page.route(`${BASE_URL}/agents/buddy`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ agent_id: 'buddy', active: true, online: true, tmux_alive: true, status: 'running' }),
    });
  });

  await page.route(`${BASE_URL}/send`, async (route) => {
    const payload = route.request().postDataJSON();
    historyMessages.length = 0;
    historyCall = 0;
    historyMessages.push({
      id: ++nextId,
      from: 'user',
      to: 'buddy',
      content: payload.content,
      timestamp: new Date(Date.UTC(2026, 2, 14, 21, 10, 0)).toISOString(),
      meta: payload.meta || null,
    });
    await route.fulfill({
      status: 201,
      headers: JSON_HEADERS,
      body: JSON.stringify({ ok: true }),
    });
  });

  await page.goto(HARNESS_URL, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    document.getElementById('buddyWidgetBubble').classList.add('open');
  });

  await page.locator('#bwInput').fill('Bitte antworte mit SLICE47_OK');
  await page.evaluate(() => document.getElementById('bwSend').click());
  await page.waitForTimeout(6500);

  const renderedTexts = await page.locator('.bwMsg > span:first-child').evaluateAll((nodes) =>
    nodes.map((node) => node.textContent.trim())
  );

  expect(renderedTexts).toEqual([
    'Bitte antworte mit SLICE47_OK',
    'SLICE47_OK',
  ]);
});

test('buddy widget history stays scrollable across all supported themes', async ({ page }) => {
  const historyMessages = Array.from({ length: 80 }, (_, index) => ({
    id: index + 1,
    from: index % 2 === 0 ? 'buddy' : 'user',
    to: index % 2 === 0 ? 'user' : 'buddy',
    content: `History message ${index + 1}`,
    timestamp: new Date(Date.UTC(2026, 2, 14, 20, Math.floor(index / 2), index % 60)).toISOString(),
    meta: null,
  }));

  await installBuddyHarness(page);

  await page.route(`${BASE_URL}/history*`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ messages: historyMessages }),
    });
  });

  await page.route(`${BASE_URL}/cli/detect*`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ cli: { available: [] }, tools: {} }),
    });
  });

  await page.route(`${BASE_URL}/agents/buddy`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ agent_id: 'buddy', active: true, online: true, tmux_alive: true, status: 'waiting' }),
    });
  });

  await page.goto(HARNESS_URL, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    document.getElementById('buddyWidgetBubble').classList.add('open');
  });
  await expect(page.locator('.bwMsg')).toHaveCount(80);

  for (const theme of ['warm', 'light', 'rose', 'dark', 'black']) {
    await page.evaluate((value) => {
      document.documentElement.setAttribute('data-theme', value);
    }, theme);
    await page.waitForTimeout(100);

    const probe = await page.evaluate(() => {
      const el = document.getElementById('bwMessages');
      el.scrollTop = 0;
      const top = el.scrollTop;
      el.scrollTop = el.scrollHeight;
      const bottom = el.scrollTop;
      return {
        clientHeight: el.clientHeight,
        scrollHeight: el.scrollHeight,
        top,
        bottom,
        background: getComputedStyle(el).backgroundColor,
      };
    });

    expect(probe.scrollHeight).toBeGreaterThan(probe.clientHeight);
    expect(probe.bottom).toBeGreaterThan(probe.top);
    if (theme === 'dark' || theme === 'black') {
      expect(probe.background).not.toBe('rgb(255, 255, 255)');
    }
  }
});
