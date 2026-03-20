const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

async function hideWelcomeOverlay(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_welcome_seen', '1');
  });
}

test('control center degrades clearly when n8n workflow endpoints are unavailable', async ({ page }) => {
  let workflowRequests = 0;
  let executionRequests = 0;

  await hideWelcomeOverlay(page);

  await page.route(`${BASE_URL}/workflows*`, async (route) => {
    workflowRequests += 1;
    await route.fulfill({
      status: 502,
      contentType: 'application/json; charset=utf-8',
      body: JSON.stringify({ error: 'n8n connection failed: test outage' }),
    });
  });

  await page.route(`${BASE_URL}/n8n/executions*`, async (route) => {
    executionRequests += 1;
    await route.fulfill({
      status: 502,
      contentType: 'application/json; charset=utf-8',
      body: JSON.stringify({ error: 'n8n connection failed: test outage' }),
    });
  });

  await page.goto(`${BASE_URL}/control_center.html`, { waitUntil: 'domcontentloaded' });

  await expect(page.locator('#glanceWfBody')).toContainText('n8n nicht erreichbar');
  expect(executionRequests).toBeGreaterThanOrEqual(1);
  expect(workflowRequests).toBe(0);

  await page.click('.ccTab[data-tab="workflows"]');
  await expect(page.locator('#wfEmpty')).toBeVisible();
  await expect(page.locator('#wfEmpty')).toContainText('n8n nicht erreichbar');

  const afterFirstWorkflowLoad = workflowRequests;
  await page.click('.ccTab[data-tab="dashboard"]');
  await page.click('.ccTab[data-tab="workflows"]');
  await page.waitForTimeout(300);

  expect(afterFirstWorkflowLoad).toBe(0);
  expect(workflowRequests).toBe(afterFirstWorkflowLoad);
});

test('control center shows live workflows against the real backend when n8n proxy is healthy', async ({ page }) => {
  await hideWelcomeOverlay(page);
  await page.goto(`${BASE_URL}/control_center.html`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#glanceWfBody')).not.toContainText('n8n nicht erreichbar');
  await expect(page.locator('#glanceWfBody')).toContainText('Workflow #');
  await page.click('.ccTab[data-tab="workflows"]');
  await expect(page.locator('#wfCards .wfCard').first()).toBeVisible();
  await expect(page.locator('#wfEmpty')).toBeHidden();
});
