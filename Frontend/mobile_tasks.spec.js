const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';
const VIEWPORT = { width: 430, height: 932 };

test.setTimeout(120000);

test('mobile tasks is a mobile-native replacement for task tracking', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_theme', 'warm');
  });
  await page.setViewportSize(VIEWPORT);
  await page.goto(`${BASE_URL}/mobile_tasks.html`, { waitUntil: 'domcontentloaded' });

  await expect(page.locator('.app')).toBeVisible();
  await expect(page.locator('#shell')).toBeVisible();
  await expect(page.locator('#backBtn img')).toBeVisible();
  await expect(page.locator('#filterAgent')).toBeVisible();
  await expect(page.locator('#filterStatus')).toBeVisible();
  await expect(page.locator('#btnFilter')).toBeVisible();
  await expect(page.locator('#autoRefreshToggle')).toBeChecked();

  const overflowFree = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2);
  expect(overflowFree).toBe(true);

  await expect.poll(async () => {
    const count = await page.locator('#taskList .taskCard').count();
    const feedback = await page.locator('#tasksFeedback').textContent();
    return { count, feedback };
  }).toEqual(expect.objectContaining({ count: expect.any(Number), feedback: expect.any(String) }));

  await expect.poll(async () => Number(await page.locator('#taskList .taskCard').count())).toBeGreaterThan(0);
  await expect(page.locator('#taskCountMetric')).not.toHaveText('0 geladen');
  await expect(page.locator('#trackerModeLabel')).not.toHaveText('laedt');
  await expect(page.locator('#buddyWidget')).toBeVisible();

  const filterPromise = page.waitForResponse(response =>
    response.url().includes('/task/tracker?') || response.url().includes('/task/queue?')
  );
  await page.locator('#filterStatus').selectOption('done');
  await page.locator('#btnFilter').click();
  await filterPromise;
  await expect(page.locator('#listSectionSub')).toContainText('Tasks');

  const detailCard = page.locator('#taskList .taskCard').first();
  await detailCard.click();
  await expect(page.locator('#detailLayer')).toBeVisible();
  await expect(page.locator('#detailTitle')).not.toHaveText('—');
  await page.locator('#detailClose').click();
  await expect(page.locator('#detailLayer')).toBeHidden();

  const csvDownloadPromise = page.waitForEvent('download');
  await page.locator('#btnExportCsv').click();
  const csvDownload = await csvDownloadPromise;
  expect(csvDownload.suggestedFilename()).toBe('mobile_tasks.csv');

  const jsonDownloadPromise = page.waitForEvent('download');
  await page.locator('#btnExportJson').click();
  const jsonDownload = await jsonDownloadPromise;
  expect(jsonDownload.suggestedFilename()).toBe('mobile_tasks.json');

  await page.locator('#autoRefreshToggle').setChecked(false, { force: true });
  await expect(page.locator('#autoRefreshToggle')).not.toBeChecked();
  await page.locator('#autoRefreshToggle').setChecked(true, { force: true });
  await expect(page.locator('#autoRefreshToggle')).toBeChecked();

  await page.goto(`${BASE_URL}/mobile_buddy.html`, { waitUntil: 'domcontentloaded' });
  await page.locator('#menuBtn').click();
  const navigationPromise = page.waitForURL(url => url.pathname.endsWith('/mobile_tasks.html'));
  await page.locator('.drawerLink[data-route="mobile_tasks.html"]').click({ force: true });
  await navigationPromise;
  await expect(page.locator('#filterAgent')).toBeVisible();

  await page.goto(`${BASE_URL}/mobile_buddy.html`, { waitUntil: 'domcontentloaded' });
  await page.locator('#menuBtn').click();
  const summaryNavigationPromise = page.waitForURL(url => url.pathname.endsWith('/mobile_tasks.html'));
  await page.locator('#tasksSummaryCard a.summaryLink[href="mobile_tasks.html"]').click({ force: true });
  await summaryNavigationPromise;
  await expect(page.locator('#filterStatus')).toBeVisible();

  await page.goto(`${BASE_URL}/mobile_buddy.html`, { waitUntil: 'domcontentloaded' });
  await page.locator('#menuBtn').click();
  const aufgabenNavigationPromise = page.waitForURL(url => url.pathname.endsWith('/mobile_tasks.html') && url.hash === '#aufgaben');
  await page.locator('.drawerLink[data-route="mobile_tasks.html#aufgaben"]').click({ force: true });
  await aufgabenNavigationPromise;
  await expect(page.locator('#taskList')).toBeVisible();
});
