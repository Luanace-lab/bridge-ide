const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

async function hideWelcomeOverlay(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_welcome_seen', '1');
  });
}

async function openChat(page) {
  await hideWelcomeOverlay(page);
  await page.goto(`${BASE_URL}/chat.html`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.sidebarIcon[data-action="workflows"]')).toBeVisible();
}

async function bridgeFetch(page, path, init = {}) {
  return await page.evaluate(async ({ baseUrl, path, init }) => {
    const res = await fetch(baseUrl + path, init);
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (err) {
      data = { raw: text };
    }
    return { ok: res.ok, status: res.status, data };
  }, { baseUrl: BASE_URL, path, init });
}

async function deleteWorkflow(page, workflowId) {
  if (!workflowId) return;
  await bridgeFetch(page, `/workflows/${workflowId}`, { method: 'DELETE' });
}

test.describe.serial('chat workflow actions', () => {
  test('workflow panel deploys a template against the real backend', async ({ page }) => {
    let createdWorkflowId = null;
    try {
      await openChat(page);
      const before = await bridgeFetch(page, '/workflows');
      expect(before.ok).toBeTruthy();

      await page.click('.sidebarIcon[data-action="workflows"]');
      await expect(page.locator('#wfPanel')).toHaveClass(/wfPanel--open/);
      await expect(page.locator('#wfTemplates .wfTplCard').first()).toBeVisible();
      await expect(page.locator('.wfPanel__manage')).toHaveAttribute('href', 'control_center.html#workflows');

      await page.locator('#wfTemplates .wfTplCard').filter({ hasText: 'Wochenreport' }).click();
      await expect(page.locator('.wfDeployForm')).toBeVisible();
      await page.locator('#wfVar_day_of_week').fill('5');
      await page.locator('#wfVar_bridge_url').fill('http://localhost:9111');

      const deployResponsePromise = page.waitForResponse(
        (resp) => resp.url() === `${BASE_URL}/workflows/deploy-template` && resp.request().method() === 'POST'
      );
      await page.locator('.wfDeployForm__submit').click();
      const deployResponse = await deployResponsePromise;
      const deployBody = await deployResponse.json();
      createdWorkflowId = deployBody.workflow && deployBody.workflow.id;

      expect(deployResponse.status()).toBe(201);
      expect(deployBody.ok).toBeTruthy();
      expect(createdWorkflowId).toBeTruthy();
      await expect(page.locator('#wfDeployMsg')).toContainText('Workflow deployed!');

      const after = await bridgeFetch(page, '/workflows');
      expect(after.ok).toBeTruthy();
      expect(after.data.count).toBe(before.data.count + 1);
      expect(after.data.workflows.some((wf) => wf.id === createdWorkflowId)).toBeTruthy();
    } finally {
      await deleteWorkflow(page, createdWorkflowId);
    }
  });

  test('workflow panel toggles and deletes a unique bridge workflow', async ({ page }) => {
    let createdWorkflowId = null;
    const workflowName = `Bridge UI Toggle Probe ${Date.now()}`;
    try {
      await openChat(page);
      const deployResult = await bridgeFetch(page, '/workflows/deploy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          activate: true,
          definition: {
            name: workflowName,
            nodes: [
              {
                id: 'sched',
                kind: 'bridge.trigger.schedule',
                config: { cron: '0 0 1 1 *' },
              },
              {
                id: 'notify',
                kind: 'bridge.action.send_message',
                config: { to: 'user', content: `workflow probe ${workflowName}` },
              },
            ],
            edges: [{ from: 'sched', to: 'notify' }],
          },
        }),
      });

      expect(deployResult.status).toBe(201);
      expect(deployResult.ok).toBeTruthy();
      createdWorkflowId = deployResult.data.workflow && deployResult.data.workflow.id;
      expect(createdWorkflowId).toBeTruthy();

      await page.click('.sidebarIcon[data-action="workflows"]');
      await expect(page.locator('#wfPanel')).toHaveClass(/wfPanel--open/);

      const card = page.locator('#wfList .wfCard').filter({ hasText: workflowName });
      await expect(card).toBeVisible({ timeout: 10000 });
      await card.scrollIntoViewIfNeeded();

      const toggleResponsePromise = page.waitForResponse(
        (resp) => resp.url() === `${BASE_URL}/workflows/${createdWorkflowId}/toggle` && resp.request().method() === 'PATCH'
      );
      await card.locator('.wfToggle').click();
      const toggleResponse = await toggleResponsePromise;
      const toggleBody = await toggleResponse.json();

      expect(toggleResponse.status()).toBe(200);
      expect(toggleBody.ok).toBeTruthy();
      expect(toggleBody.workflow.active).toBeFalsy();
      await expect(card.locator('.wfCard__meta')).toContainText('Inaktiv');

      page.once('dialog', (dialog) => dialog.accept());
      const deleteResponsePromise = page.waitForResponse(
        (resp) => resp.url() === `${BASE_URL}/workflows/${createdWorkflowId}` && resp.request().method() === 'DELETE'
      );
      await card.locator('.wfDeleteBtn').click();
      const deleteResponse = await deleteResponsePromise;
      const deleteBody = await deleteResponse.json();

      expect(deleteResponse.status()).toBe(200);
      expect(deleteBody.ok).toBeTruthy();
      await expect(page.locator('#wfList .wfCard').filter({ hasText: workflowName })).toHaveCount(0);

      const afterDelete = await bridgeFetch(page, '/workflows');
      expect(afterDelete.ok).toBeTruthy();
      expect(afterDelete.data.workflows.some((wf) => wf.id === createdWorkflowId)).toBeFalsy();
      createdWorkflowId = null;
    } finally {
      await deleteWorkflow(page, createdWorkflowId);
    }
  });

  test('workflow suggestion card deploys a real template workflow', async ({ page }) => {
    let createdWorkflowId = null;
    try {
      await openChat(page);
      await page.evaluate(() => {
        const leftInner = document.querySelector('#chatMessagesLeft .chatMessagesInner');
        const rightInner = document.querySelector('#chatMessagesRight .chatMessagesInner');
        if (leftInner) leftInner.innerHTML = '';
        if (rightInner) rightInner.innerHTML = '';
      });

      const before = await bridgeFetch(page, '/workflows');
      expect(before.ok).toBeTruthy();

      await page.evaluate(async () => {
        await checkWorkflowSuggest('workflow erstellen wochenreport', 'left');
      });

      const suggestionCard = page.locator('.wfBot__card').filter({ hasText: 'Wochenreport' });
      await expect(suggestionCard).toBeVisible({ timeout: 10000 });
      await suggestionCard.locator('.wfBot__card__btn').click();
      await expect(page.locator('.wfBot__form')).toBeVisible();

      await page.locator('.wfBot__form input[data-var="day_of_week"]').fill('5');
      await page.locator('.wfBot__form input[data-var="bridge_url"]').fill('http://localhost:9111');

      const deployResponsePromise = page.waitForResponse(
        (resp) => resp.url() === `${BASE_URL}/workflows/deploy-template` && resp.request().method() === 'POST'
      );
      await page.locator('.wfBot__deploy').click();
      const deployResponse = await deployResponsePromise;
      const deployBody = await deployResponse.json();
      createdWorkflowId = deployBody.workflow && deployBody.workflow.id;

      expect(deployResponse.status()).toBe(201);
      expect(deployBody.ok).toBeTruthy();
      expect(createdWorkflowId).toBeTruthy();
      await expect(page.locator('.wfBot__msg').last()).toContainText('Workflow "Wochenreport" erstellt!');

      const after = await bridgeFetch(page, '/workflows');
      expect(after.ok).toBeTruthy();
      expect(after.data.count).toBe(before.data.count + 1);
      expect(after.data.workflows.some((wf) => wf.id === createdWorkflowId)).toBeTruthy();
    } finally {
      await deleteWorkflow(page, createdWorkflowId);
    }
  });
});
