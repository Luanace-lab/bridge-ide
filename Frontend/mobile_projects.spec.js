const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';
const VIEWPORT = { width: 430, height: 932 };

test.setTimeout(120000);

test('mobile projects is a mobile-native replacement for project setup', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_theme', 'warm');
  });
  await page.setViewportSize(VIEWPORT);
  await page.goto(`${BASE_URL}/mobile_projects.html`, { waitUntil: 'domcontentloaded' });

  await expect(page.locator('.app')).toBeVisible();
  await expect(page.locator('#shell')).toBeVisible();
  await expect(page.locator('#backBtn img')).toBeVisible();
  await expect(page.locator('#projectsTitle')).toBeVisible();
  await expect(page.locator('#projName')).toBeVisible();
  await expect(page.locator('#projPath')).toBeVisible();
  await expect(page.locator('#scanBtn')).toBeDisabled();
  await expect(page.locator('#createBtn')).toBeDisabled();
  await expect(page.locator('#startTeamBtn')).toBeDisabled();
  await expect(page.locator('.topBar')).toHaveCount(0);

  const overflowFree = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2);
  expect(overflowFree).toBe(true);

  await expect.poll(async () => Number(await page.locator('.quickProject').count())).toBeGreaterThan(0);
  await expect(page.locator('#baseDirValue')).not.toHaveText('wird geladen');
  await expect(page.locator('#projectCountValue')).not.toHaveText('0');
  await expect(page.locator('#buddyWidget')).toBeVisible();

  await page.locator('#projName').fill('BRIDGE');
  await page.locator('#projPath').fill('/home/leo/Desktop/CC/BRIDGE');
  await expect(page.locator('#scanBtn')).toBeEnabled();
  await expect(page.locator('#createBtn')).toBeEnabled();
  await expect(page.locator('#startTeamBtn')).toBeEnabled();

  const scanPromise = page.waitForResponse(response =>
    response.url().includes('/api/context/scan?project_path=') && response.request().method() === 'GET'
  );
  await page.locator('#scanBtn').click();
  await scanPromise;
  await expect(page.locator('#scanResults')).toHaveClass(/is-visible/);
  await expect(page.locator('#scanHeadline')).toContainText(/von/);
  await expect.poll(async () => page.locator('#scanList .scanItem').count()).toBeGreaterThan(5);

  const startConfigurePromise = page.waitForResponse(
    response => response.url() === `${BASE_URL}/runtime/configure` && response.request().method() === 'POST'
  );
  await page.locator('#startTeamBtn').click();
  const configureResponse = await startConfigurePromise;
  const configureBody = await configureResponse.json();
  if (configureBody.ok) {
    await expect(page.locator('#teamFeedback')).toContainText('Team gestartet');
  } else {
    const firstFailure = Array.isArray(configureBody.failed)
      ? configureBody.failed.find(item => item && (item.error_detail || item.error_reason || item.id || item.name))
      : null;
    const expectedDetail = firstFailure
      ? `${firstFailure.id || firstFailure.name || 'runtime'}: ${firstFailure.error_detail || firstFailure.error_reason || configureBody.error || 'Konfiguration fehlgeschlagen'}`
      : (configureBody.error || 'Konfiguration fehlgeschlagen');
    await expect(page.locator('#teamFeedback')).toContainText(expectedDetail);
  }

  await expect(page.locator('.configCard[data-card-type="agent"]')).toHaveCount(2);
  await page.locator('#addAgentBtn').click();
  await expect(page.locator('.configCard[data-card-type="agent"]')).toHaveCount(3);
  await expect(page.locator('#teamCountValue')).toHaveText('4');

  const downloadPromise = page.waitForEvent('download');
  await page.locator('#exportBtn').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('BRIDGE.json');

  const baseDir = (await page.locator('#baseDirValue').textContent()).trim();
  const createName = `bridge-mobile-audit-${Date.now()}`;
  await page.locator('#projName').fill(createName);
  await page.locator('#projPath').fill(baseDir);

  const createPromise = page.waitForResponse(
    response => response.url() === `${BASE_URL}/api/projects/create` && response.request().method() === 'POST'
  );
  await page.locator('#createBtn').click();
  const createResponse = await createPromise;
  const createBody = await createResponse.json();
  expect(createBody.ok).toBe(true);
  await expect(page.locator('#projectFeedback')).toContainText(`Projekt erstellt: ${createBody.project_path}`);

  await page.goto(`${BASE_URL}/mobile_buddy.html`, { waitUntil: 'domcontentloaded' });
  await page.locator('#menuBtn').click();
  const navigationPromise = page.waitForURL(url => url.pathname.endsWith('/mobile_projects.html'));
  await page.locator('.drawerLink[data-route="mobile_projects.html"]').click({ force: true });
  await navigationPromise;
  await expect(page.locator('#projectsTitle')).toBeVisible();
});
