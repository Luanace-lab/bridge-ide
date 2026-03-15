const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

test('project config surfaces runtime configure feedback from the live backend', async ({ page }) => {
  await page.goto(`${BASE_URL}/project_config.html`, { waitUntil: 'domcontentloaded' });

  await page.locator('#projName').fill('BRIDGE');
  await page.locator('#projPath').fill('/home/user/bridge/BRIDGE');

  const configurePromise = page.waitForResponse(
    (resp) => resp.url() === `${BASE_URL}/runtime/configure` && resp.request().method() === 'POST'
  );
  await page.locator('#startTeamBtn').click();
  const configureResponse = await configurePromise;
  const body = await configureResponse.json();

  if (body.ok) {
    await expect(page.locator('.feedback--ok').last()).toContainText('Team gestartet');
    return;
  }

  const firstFailure = Array.isArray(body.failed) ? body.failed.find(item => item && (item.error_detail || item.error_reason)) : null;
  const expectedDetail = firstFailure?.error_detail || firstFailure?.error_reason || body.error || 'Konfiguration fehlgeschlagen';
  await expect(page.locator('.feedback--error').last()).toContainText(expectedDetail);
});
