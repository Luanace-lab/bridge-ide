const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

async function hideWelcomeOverlay(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_welcome_seen', '1');
  });
}

test('chat routes live buddy messages into an open Buddy DM panel without leaking them into the main boards', async ({ page }) => {
  await hideWelcomeOverlay(page);
  await page.goto(`${BASE_URL}/chat.html?agent=buddy`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);

  await page.evaluate(() => {
    const leftInner = document.querySelector('#chatMessagesLeft .chatMessagesInner');
    const rightInner = document.querySelector('#chatMessagesRight .chatMessagesInner');
    if (leftInner) leftInner.innerHTML = '';
    if (rightInner) rightInner.innerHTML = '';

    const dmEntry = window.wsCreateDMPanel('buddy');
    if (dmEntry && dmEntry.messagesEl) dmEntry.messagesEl.innerHTML = '';

    window.renderMessage({
      id: 93001,
      from: 'user',
      to: 'buddy',
      content: 'Hallo Buddy aus dem DM-Test',
      timestamp: new Date(Date.UTC(2026, 2, 15, 15, 1, 0)).toISOString(),
    });
    window.renderMessage({
      id: 93002,
      from: 'buddy',
      to: 'user',
      content: 'Hallo Leo aus dem DM-Test',
      timestamp: new Date(Date.UTC(2026, 2, 15, 15, 1, 5)).toISOString(),
    });
  });

  const dmPanel = page.locator('.wsPanel--dm[data-dm-agent="buddy"]');
  await expect(dmPanel.locator('.chatMsg')).toHaveCount(2);
  await expect(dmPanel).toContainText('Hallo Buddy aus dem DM-Test');
  await expect(dmPanel).toContainText('Hallo Leo aus dem DM-Test');

  await expect(page.locator('#chatMessagesLeft .chatMsg')).toHaveCount(0);
  await expect(page.locator('#chatMessagesRight .chatMsg')).toHaveCount(0);
});
