const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

test('buddy landing scans multiple CLIs, lets the user choose one, materializes Buddy home, and starts Buddy', async ({ page }) => {
  const detectPromise = page.waitForResponse(
    (resp) => resp.url().startsWith(`${BASE_URL}/cli/detect`) && resp.request().method() === 'GET'
  );
  const setupPromise = page.waitForResponse(
    (resp) =>
      resp.url() === `${BASE_URL}/agents/buddy/setup-home` &&
      resp.request().method() === 'POST'
  );
  const startPromise = page.waitForResponse(
    (resp) =>
      resp.url() === `${BASE_URL}/agents/buddy/start` &&
      resp.request().method() === 'POST'
  );
  await page.goto(`${BASE_URL}/buddy_landing.html?skip_onboarding=1`, { waitUntil: 'domcontentloaded' });

  const detectResponse = await detectPromise;
  expect(detectResponse.status()).toBe(200);
  const detect = await detectResponse.json();
  expect(detect.cli.available).toContain('codex');
  expect(detect.cli.available.length).toBeGreaterThan(1);

  await page.waitForTimeout(3000);
  const responseArea = page.locator('#response-area');
  const currentText = (await responseArea.textContent()) || '';
  if (currentText.includes('Ich habe folgende CLIs gefunden')) {
    await page.getByRole('button', { name: /Codex CLI/ }).click();
  }

  const setupResponse = await setupPromise;
  expect(setupResponse.status()).toBe(200);
  const setup = await setupResponse.json();
  expect(setup.ok).toBeTruthy();
  expect(setup.engine).toBe('codex');
  expect(setup.agent_md).toMatch(/\/Buddy\/AGENTS\.md$/);

  const startResponse = await startPromise;
  expect([401, 403, 500]).not.toContain(startResponse.status());

  await expect(responseArea).toContainText(/Codex CLI (ist jetzt fuer Buddy vorbereitet|wurde als vorhandenes Buddy-Profil uebernommen)/);
  await expect(responseArea).toContainText('Hey! Ich bin Buddy.');
  await expect(responseArea).toContainText('Was fuehrt dich her?');
});
