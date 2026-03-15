const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

async function hideWelcomeOverlay(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_welcome_seen', '1');
  });
}

test('chat approval panel opens and closes from its own close button', async ({ page }) => {
  await hideWelcomeOverlay(page);
  await page.goto(`${BASE_URL}/chat.html`, { waitUntil: 'domcontentloaded' });

  await page.locator('#approvalBadge').click();
  await expect(page.locator('#approvalPanel')).toHaveClass(/approvalPanel--open/);

  await page.locator('#panelClose').click();
  await expect(page.locator('#approvalPanel')).not.toHaveClass(/approvalPanel--open/);
});
