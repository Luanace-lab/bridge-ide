const fs = require('fs');
const path = require('path');
const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

async function hideWelcomeOverlay(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_welcome_seen', '1');
  });
}

async function collectResponses(page, matcher) {
  const seen = [];
  page.on('response', async (resp) => {
    try {
      if (matcher(resp)) seen.push(resp);
    } catch {}
  });
  return seen;
}

test.describe('frontend clickpath audit', () => {
  test('landing page links are clickable and marketing docs/github CTAs are placeholders', async ({ page }) => {
    await page.goto(`${BASE_URL}/landing.html`, { waitUntil: 'domcontentloaded' });

    await page.getByRole('link', { name: 'Features' }).click();
    await expect(page).toHaveURL(/landing\.html#features$/);

    await page.getByRole('link', { name: 'Get Started' }).click();
    await expect(page).toHaveURL(/landing\.html#get-started$/);

    await page.getByRole('link', { name: /Start building/ }).click();
    await expect(page).toHaveURL(/landing\.html#get-started$/);

    await page.getByRole('link', { name: 'See how it works' }).click();
    await expect(page).toHaveURL(/landing\.html#features$/);

    await expect(page.locator('.nav__links a.nav__link').nth(1)).toHaveAttribute('href', '#');
    await expect(page.locator('.nav__links a.nav__link').nth(2)).toHaveAttribute('href', '#');
    await expect(page.locator('.cta__actions a').nth(0)).toHaveAttribute('href', '#');
    await expect(page.locator('.cta__actions a').nth(1)).toHaveAttribute('href', '##readme');
  });

  test('project config page executes safe clickpaths and exports JSON', async ({ page }) => {
    const tmpRoot = `/tmp/bridge-test/bridge_frontend_audit_${Date.now()}`;
    const projectName = `frontend-audit-${Date.now()}`;
    const projectTarget = path.join(tmpRoot, projectName);
    fs.rmSync(tmpRoot, { recursive: true, force: true });
    fs.mkdirSync(tmpRoot, { recursive: true });

    page.on('dialog', async (dialog) => {
      await dialog.dismiss();
    });

    await page.goto(`${BASE_URL}/project_config.html`, { waitUntil: 'domcontentloaded' });

    await page.locator('#pcThemeBtn').click();
    await page.locator('#pcThemeMenu button[data-theme="dark"]').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

    await page.locator('#browsePathBtn').click();
    await expect(page.locator('#projPath')).toBeVisible();

    await page.locator('#projName').fill('BRIDGE');
    await page.locator('#projPath').fill('.');
    await page.locator('#scanBtn').click();
    await expect(page.getByText('SCAN-ERGEBNISSE')).toBeVisible();
    await expect(page.getByText('Projekt erkannt.')).toBeVisible();

    await page.locator('#advancedToggle').click();
    await expect(page.locator('#advancedToggle')).toHaveAttribute('aria-expanded', 'true');

    await page.getByRole('button', { name: 'Team-Leiter Einstellungen' }).click();
    await page.getByRole('button', { name: 'Agent A Einstellungen' }).click();
    await page.getByRole('button', { name: 'Agent B Einstellungen' }).click();

    const beforeAgentCards = await page.locator('button.cardToggle').count();
    await page.locator('#addAgentBtn').click();
    await expect(page.locator('button.cardToggle')).toHaveCount(beforeAgentCards + 1);

    await page.locator('#projName').fill(projectName);
    await page.locator('#projPath').fill('/tmp');
    await page.locator('#createBtn').click();
    await expect(page.getByText('Projekt-Erstellung ist nur innerhalb von /tmp/bridge-test erlaubt.')).toBeVisible();

    await page.locator('#projName').fill(projectName);
    await page.locator('#projPath').fill(tmpRoot);
    await page.locator('#createBtn').click();
    await expect(page.getByText(`Projekt erstellt: ${projectTarget}`)).toBeVisible();

    const downloadPromise = page.waitForEvent('download');
    await page.locator('#exportBtn').click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe(`${projectName}.json`);

    await page.getByRole('button', { name: 'Hilfe oeffnen' }).click();
    await expect(page).toHaveURL(/control_center\.html\?help=1$/);

    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test('task tracker loads tasks, opens detail, exports both formats, and theme switch works', async ({ page }) => {
    await page.goto(`${BASE_URL}/task_tracker.html`, { waitUntil: 'domcontentloaded' });

    await expect(page.locator('#footerCount')).toContainText('Tasks gefunden', { timeout: 10000 });
    const trackerCount = await page.locator('#footerCount').textContent();
    expect(Number((trackerCount || '').match(/\d+/)?.[0] || '0')).toBeGreaterThan(0);

    await page.locator('#themeToggle').click();
    await page.locator('#themeMenu button[data-theme="dark"]').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

    await page.locator('#filterStatus').selectOption('failed');
    await page.locator('#btnFilter').click();
    await expect(page.locator('#footerTime')).toContainText('Letzte Aktualisierung', { timeout: 10000 });

    const csvDownloadPromise = page.waitForEvent('download');
    await page.locator('#btnExportCsv').click();
    const csvDownload = await csvDownloadPromise;
    expect(csvDownload.suggestedFilename()).toBe('task_tracker.csv');

    const jsonDownloadPromise = page.waitForEvent('download');
    await page.locator('#btnExportJson').click();
    const jsonDownload = await jsonDownloadPromise;
    expect(jsonDownload.suggestedFilename()).toBe('task_tracker.json');

    await page.locator('#taskBody tr').first().click();
    await expect(page.locator('#detailPanel')).toHaveClass(/open/);
    await page.locator('#detailClose').click();
    await expect(page.locator('#detailPanel')).not.toHaveClass(/open/);
  });

  test('buddy landing uses authenticated write paths and can start Buddy from the frontdoor', async ({ page }) => {
    const buddyStartPromise = page.waitForResponse(
      (resp) => resp.url() === `${BASE_URL}/agents/buddy/start` && resp.request().method() === 'POST'
    );
    await page.goto(`${BASE_URL}/buddy_landing.html?skip_onboarding=1`, { waitUntil: 'domcontentloaded' });
    const buddyStart = await buddyStartPromise;

    await expect(page.locator('#escape-hatch a')).toBeVisible();
    await expect(page.locator('#vol-btn')).toBeVisible();

    await page.waitForTimeout(3000);
    expect([401, 403]).not.toContain(buddyStart.status());
    await expect(page.locator('#response-area')).toContainText('Hey! Ich bin Buddy.');

    await page.locator('#vol-btn').click();
    await expect(page.locator('#vol-icon-off')).toBeVisible();

    await page.locator('#chat-input').fill('frontend audit ping');
    const sendPromise = page.waitForResponse(
      (resp) => resp.url() === `${BASE_URL}/send` && resp.request().method() === 'POST'
    );
    await page.locator('#send-btn').click();
    const sendResponse = await sendPromise;
    expect([401, 403]).not.toContain(sendResponse.status());
    await expect(page.locator('#response-area')).toContainText('frontend audit ping');

    await page.locator('#escape-hatch a').click();
    await expect(page).toHaveURL(/chat\.html\?agent=buddy/);
  });

  test('chat sidebar and control center top-level tabs are clickable on the live UI', async ({ page }) => {
    await hideWelcomeOverlay(page);
    await page.goto(`${BASE_URL}/chat.html`, { waitUntil: 'domcontentloaded' });

    await page.locator('.sidebarIcon[data-action="orgchart"]').click();
    await expect(page.locator('#orgPanel')).toHaveClass(/orgPanel--open/);
    await page.locator('#orgPanelClose').click();
    await expect(page.locator('#orgPanel')).not.toHaveClass(/orgPanel--open/);

    await page.locator('.sidebarIcon[data-action="workflows"]').click();
    await expect(page.locator('#wfPanel')).toHaveClass(/wfPanel--open/);
    await page.locator('#wfPanelClose').click();
    await expect(page.locator('#wfPanel')).not.toHaveClass(/wfPanel--open/);

    await page.locator('.sidebarIcon[data-action="tasks"]').click();
    await expect(page).toHaveURL(/control_center\.html\?tab=aufgaben$/);
    await expect(page.locator('.ccTab.active[data-tab="aufgaben"]')).toBeVisible();

    await page.locator('.ccTab[data-tab="hierarchie"]').click();
    await expect(page.locator('.ccTab.active[data-tab="hierarchie"]')).toBeVisible();

    await page.locator('.ccTab[data-tab="workflows"]').click();
    await expect(page.locator('.ccTab.active[data-tab="workflows"]')).toBeVisible();

    await page.locator('#wfAddBtn').click();
    await expect(page.locator('#wfTplOverlay')).toHaveClass(/open/);
    await page.locator('#wfTplOverlay .wfTplModal__tab', { hasText: 'Bridge Builder' }).click();
    await page.locator('#wfTplOverlay .wfTplModal__tab', { hasText: 'Templates' }).click();
    await page.locator('#wfTplOverlay .wfTplModal__close').click();
    await expect(page.locator('#wfTplOverlay')).not.toHaveClass(/open/);

    await page.locator('.topBar__navLink[href="project_config.html"]').click();
    await expect(page).toHaveURL(/project_config\.html$/);
  });
});
