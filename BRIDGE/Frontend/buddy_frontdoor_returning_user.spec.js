const fs = require('fs');
const os = require('os');
const path = require('path');
const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';
const USER_TOKEN = JSON.parse(
  fs.readFileSync(path.join(os.homedir(), '.config/bridge/tokens.json'), 'utf8')
).user_token;

test('buddy landing keeps returning user on frontdoor when buddy is down, starts buddy, and avoids premature chat redirect', async ({ page, request }) => {
  const deactivate = await request.patch(`${BASE_URL}/agents/buddy/active`, {
    headers: {
      'Content-Type': 'application/json',
      'X-Bridge-Token': USER_TOKEN,
    },
    data: { active: false },
  });
  expect(deactivate.ok()).toBeTruthy();
  await expect.poll(async () => {
    const resp = await request.get(`${BASE_URL}/agents/buddy`, {
      headers: { 'X-Bridge-Token': USER_TOKEN },
    });
    const detail = await resp.json();
    return detail.tmux_alive || detail.online;
  }).toBeFalsy();

  const onboardingPromise = page.waitForResponse(
    (resp) =>
      resp.url() === `${BASE_URL}/onboarding/status?user_id=user` &&
      resp.request().method() === 'GET'
  );
  const startPromise = page.waitForResponse(
    (resp) => resp.url() === `${BASE_URL}/agents/buddy/start` && resp.request().method() === 'POST'
  );

  await page.goto(`${BASE_URL}/buddy_landing.html`, { waitUntil: 'domcontentloaded' });

  const onboardingResponse = await onboardingPromise;
  expect(onboardingResponse.status()).toBe(200);

  const startResponse = await startPromise;
  expect([401, 403, 500]).not.toContain(startResponse.status());

  await page.waitForTimeout(3500);
  await expect(page).toHaveURL(/buddy_landing\.html/);
  await expect(page.locator('#escape-hatch a')).toBeVisible();
  await expect(page.locator('#response-area')).toContainText('Hey! Ich bin Buddy.');
  await expect(page.locator('#response-area')).not.toContainText('Ich habe folgende CLIs gefunden');
});
