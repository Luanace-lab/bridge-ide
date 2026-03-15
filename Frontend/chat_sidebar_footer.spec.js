const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

async function hideWelcomeOverlay(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_welcome_seen', '1');
  });
}

test('chat sidebar footer keeps approval badge separate at narrow sidebar width', async ({ page }) => {
  await hideWelcomeOverlay(page);
  await page.goto(`${BASE_URL}/chat.html`, { waitUntil: 'domcontentloaded' });

  await page.evaluate(() => {
    document.documentElement.style.setProperty('--sw', '88px');
  });
  await page.waitForTimeout(500);

  const layout = await page.evaluate(() => {
    const badge = document.getElementById('approvalBadge');
    const name = document.querySelector('.sidebarUserName');
    const bottom = document.querySelector('.sidebarBottom');
    if (!badge || !name || !bottom) {
      return { missing: true };
    }
    const br = badge.getBoundingClientRect();
    const nr = name.getBoundingClientRect();
    const pr = bottom.getBoundingClientRect();
    const overlap = !(
      br.right <= nr.left ||
      nr.right <= br.left ||
      br.bottom <= nr.top ||
      nr.bottom <= br.top
    );
    return {
      missing: false,
      overlap,
      bottom: { x: pr.x, y: pr.y, width: pr.width, height: pr.height },
      badge: { x: br.x, y: br.y, width: br.width, height: br.height },
      name: { x: nr.x, y: nr.y, width: nr.width, height: nr.height },
    };
  });

  expect(layout.missing, JSON.stringify(layout)).toBe(false);
  expect(layout.overlap, JSON.stringify(layout)).toBe(false);
});
