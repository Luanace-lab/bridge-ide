const fs = require('fs');
const path = require('path');
const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';
const VIEWPORT = { width: 430, height: 932 };
const OUTPUT_PATH = '/tmp/mobile_buddy_route_audit.json';
const SCREENSHOT_DIR = '/tmp/mobile_buddy_route_audit';

test.setTimeout(120000);

function targetFileFromUrl(url) {
  try {
    const parsed = new URL(url);
    const file = parsed.pathname.split('/').filter(Boolean).pop() || 'mobile_buddy.html';
    return parsed.search ? `${file}${parsed.search}` : file;
  } catch (error) {
    return String(url || '');
  }
}

async function capturePageState(page) {
  return page.evaluate(() => ({
    url: window.location.href,
    title: document.title,
    targetFile: (() => {
      const file = window.location.pathname.split('/').filter(Boolean).pop() || 'mobile_buddy.html';
      return `${file}${window.location.search || ''}`;
    })(),
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    hasHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    visibleButtons: Array.from(document.querySelectorAll('button'))
      .filter(node => node.offsetParent !== null)
      .length,
    visibleLinks: Array.from(document.querySelectorAll('a'))
      .filter(node => node.offsetParent !== null)
      .length,
    visibleInputs: Array.from(document.querySelectorAll('input, textarea, select'))
      .filter(node => node.offsetParent !== null)
      .length
  }));
}

async function prepareRoot(page) {
  await page.setViewportSize(VIEWPORT);
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_theme', 'warm');
    window.localStorage.removeItem('mobile_buddy_surface:buddyWidgetPos');
    window.localStorage.removeItem('mobile_buddy_surface:buddyWidgetBubblePos');
    window.localStorage.removeItem('mobile_buddy_surface:buddyWidgetBubbleSize');
    window.localStorage.removeItem('mobile_buddy_surface:boardLayout');
    window.localStorage.removeItem('mobile_buddy_surface:managementBoardSize');
  });
  await page.goto(`${BASE_URL}/mobile_buddy.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
}

test('audit mobile buddy actions and current route targets under mobile viewport', async ({ page }) => {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  const audit = {
    generated_at: new Date().toISOString(),
    viewport: VIEWPORT,
    root: {},
    in_page_actions: [],
    route_targets: []
  };

  await prepareRoot(page);

  audit.root = await capturePageState(page);

  await expect(page.locator('#menuBtn')).toBeVisible();
  await expect(page.locator('#managementMessages')).toBeVisible();
  await expect(page.locator('#teamMessages')).toBeVisible();

  await page.locator('#menuBtn').click();
  await expect(page.locator('#mobileDrawer')).toBeVisible();
  audit.in_page_actions.push({
    key: 'drawer.open',
    result: {
      drawerOpen: await page.locator('#drawerLayer').getAttribute('data-open'),
      summaryCards: await page.locator('.summaryCard').count(),
      drawerLinks: await page.locator('.drawerLink').count()
    }
  });

  await page.locator('#tasksSummaryCard .summaryAction[data-fill-prompt]').click({ force: true });
  await expect(page.locator('#managementComposerInput')).toHaveValue(/priorisiere die wichtigsten offenen Tasks/i);
  audit.in_page_actions.push({
    key: 'summary.tasks.prompt',
    result: {
      drawerOpen: await page.locator('#drawerLayer').getAttribute('data-open'),
      composerValue: await page.locator('#managementComposerInput').inputValue(),
      targetFile: targetFileFromUrl(page.url())
    }
  });

  await page.locator('#menuBtn').click();
  await expect(page.locator('#mobileDrawer')).toBeVisible();
  await page.locator('button.promptChip').first().click({ force: true });
  await expect(page.locator('#managementComposerInput')).toHaveValue(/drei wichtigsten offenen Tasks/i);
  audit.in_page_actions.push({
    key: 'prompt.top3',
    result: {
      drawerOpen: await page.locator('#drawerLayer').getAttribute('data-open'),
      composerValue: await page.locator('#managementComposerInput').inputValue(),
      targetFile: targetFileFromUrl(page.url())
    }
  });

  const managementAuditText = `Mobile route audit ${Date.now()}`;
  await page.locator('#managementComposerInput').fill(managementAuditText);
  const managementSendResponse = page.waitForResponse(response =>
    response.url().endsWith('/send') && response.request().method() === 'POST'
  ).catch(() => null);
  await page.locator('#managementSendBtn').click({ force: true });
  const managementResponse = await Promise.race([
    managementSendResponse,
    page.waitForTimeout(1800).then(() => null)
  ]);
  const managementPayload = managementResponse
    ? await managementResponse.json().catch(() => ({}))
    : null;
  await page.waitForTimeout(1200);
  audit.in_page_actions.push({
    key: 'management.send',
    result: {
      responseStatus: managementResponse ? managementResponse.status() : null,
      responseOk: managementPayload ? managementPayload.ok : null,
      lastVisibleUserMessage: await page.locator('#managementMessagesInner .chatMsg--user').last().textContent().catch(() => null),
      status: await page.locator('#statusPill').textContent(),
      targetFile: targetFileFromUrl(page.url())
    }
  });

  await expect.poll(async () => (await page.locator('#teamSummaryPill').textContent()) || '').not.toContain('Kein Team aktiv');
  await page.locator('#teamPickerBtn').click({ force: true });
  await page.waitForTimeout(200);
  let teamPickerExpanded = await page.locator('#teamPickerBtn').getAttribute('aria-expanded');
  if (teamPickerExpanded !== 'true') {
    await page.evaluate(() => {
      const button = document.getElementById('teamPickerBtn');
      if (button) button.click();
    });
    await page.waitForTimeout(200);
    teamPickerExpanded = await page.locator('#teamPickerBtn').getAttribute('aria-expanded');
  }
  audit.in_page_actions.push({
    key: 'teamPicker.open',
    result: {
      expanded: teamPickerExpanded,
      options: await page.locator('#teamPickerDropdown [data-team-key]').count()
    }
  });

  if (await page.locator('#teamPickerDropdown [data-team-key]').count()) {
    await page.locator('#teamPickerDropdown [data-team-key]').first().click({ force: true });
  }
  await expect(page.locator('#teamSummaryPill')).not.toContainText('Kein Team aktiv');
  audit.in_page_actions.push({
    key: 'team.select',
    result: {
      teamPill: await page.locator('#teamSummaryPill').textContent(),
      teamTarget: await page.locator('#teamTargetLabel').textContent()
    }
  });

  if (!(await page.locator('#memberToggleBtn').isDisabled())) {
    await page.locator('#memberToggleBtn').click({ force: true });
    await page.waitForTimeout(200);
  }
  audit.in_page_actions.push({
    key: 'memberToggle.open',
    result: {
      expanded: await page.locator('#memberToggleBtn').getAttribute('aria-expanded'),
      members: await page.locator('#memberBar .memberChip').count()
    }
  });

  const teamAuditText = `Mobile team audit ${Date.now()}`;
  await page.locator('#teamComposerInput').fill(teamAuditText);
  if (!(await page.locator('#teamSendBtn').isDisabled())) {
    const teamSendResponse = page.waitForResponse(response =>
      response.url().endsWith('/send') && response.request().method() === 'POST'
    ).catch(() => null);
    await page.locator('#teamSendBtn').click({ force: true });
    const teamResponse = await Promise.race([
      teamSendResponse,
      page.waitForTimeout(1800).then(() => null)
    ]);
    const teamPayload = teamResponse ? await teamResponse.json().catch(() => ({})) : null;
    await page.waitForTimeout(1200);
    audit.in_page_actions.push({
      key: 'team.send',
      result: {
        responseStatus: teamResponse ? teamResponse.status() : null,
        responseOk: teamPayload ? teamPayload.ok : null,
        sentText: teamAuditText,
        visibleUserMessage: await page.locator('#teamMessagesInner .chatMsg--user').last().textContent().catch(() => null)
      }
    });
  } else {
    audit.in_page_actions.push({
      key: 'team.send',
      result: {
        responseStatus: null,
        responseOk: null,
        sentText: teamAuditText,
        visibleUserMessage: null,
        disabledAfterInput: true
      }
    });
  }

  await expect(page.locator('#buddyWidgetIcon')).toBeVisible();
  await page.locator('#buddyWidgetIcon').click();
  await expect(page.locator('#buddyWidgetBubble')).toHaveClass(/open/);
  audit.in_page_actions.push({
    key: 'widget.open',
    result: {
      bubbleOpen: await page.locator('#buddyWidgetBubble').getAttribute('class'),
      bounds: await page.locator('#buddyWidgetBubble').boundingBox()
    }
  });

  const widgetAuditText = `Widget route audit ${Date.now()}`;
  await page.locator('#bwInput').fill(widgetAuditText);
  await page.locator('#bwSend').click({ force: true });
  await expect(page.locator('.bwMsg--user').last()).toContainText(widgetAuditText);
  audit.in_page_actions.push({
    key: 'widget.send',
    result: {
      lastUserMessage: await page.locator('.bwMsg--user').last().textContent()
    }
  });

  await page.locator('#buddyWidgetIcon').click();
  await expect(page.locator('#buddyWidgetBubble')).not.toHaveClass(/open/);
  audit.in_page_actions.push({
    key: 'widget.close',
    result: {
      bubbleClass: await page.locator('#buddyWidgetBubble').getAttribute('class')
    }
  });

  await page.locator('#menuBtn').click();
  await expect(page.locator('#mobileDrawer')).toBeVisible();
  await page.locator('#settingsBtn').click({ force: true });
  await expect(page.locator('#settingsSheet')).toBeVisible();
  await page.locator('.themeChip[data-theme-choice="black"]').click({ force: true });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'black');
  audit.in_page_actions.push({
    key: 'settings.black',
    result: {
      theme: await page.locator('html').getAttribute('data-theme'),
      storedTheme: await page.evaluate(() => window.localStorage.getItem('bridge_theme'))
    }
  });

  await page.locator('#settingsReconnectBtn').click({ force: true });
  await page.waitForTimeout(800);
  audit.in_page_actions.push({
    key: 'settings.reconnect',
    result: {
      status: await page.locator('#statusPill').textContent(),
      detail: await page.locator('#statusDetail').textContent()
    }
  });

  const routes = [
    { key: 'summary.tasks.tracker', selector: '#tasksSummaryCard a.summaryLink[href="mobile_tasks.html"]' },
    { key: 'summary.projects.start', selector: '#projectsSummaryCard a.summaryLink[href="mobile_projects.html"]' },
    { key: 'summary.workflows', selector: '#workflowSummaryCard a.summaryLink[href="control_center.html?tab=workflows"]' },
    { key: 'drawer.chat', selector: '.drawerLink[data-route="chat.html"]' },
    { key: 'drawer.control_center', selector: '.drawerLink[data-route="control_center.html"]' },
    { key: 'drawer.task_tracker', selector: '.drawerLink[data-route="mobile_tasks.html"]' },
    { key: 'drawer.project_config', selector: '.drawerLink[data-route="mobile_projects.html"]' },
    { key: 'drawer.aufgaben', selector: '.drawerLink[data-route="mobile_tasks.html#aufgaben"]' },
    { key: 'drawer.hierarchie', selector: '.drawerLink[data-route="control_center.html?tab=hierarchie"]' },
    { key: 'drawer.workflows', selector: '.drawerLink[data-route="control_center.html?tab=workflows"]' }
  ];

  for (const route of routes) {
    await prepareRoot(page);
    await page.locator('#menuBtn').click();
    await expect(page.locator('#mobileDrawer')).toBeVisible();
    await page.locator(route.selector).click({ force: true });
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(900);

    const state = await capturePageState(page);
    const screenshotPath = path.join(SCREENSHOT_DIR, `${route.key.replace(/[^a-z0-9]+/gi, '_')}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: false });

    audit.route_targets.push({
      key: route.key,
      ...state,
      screenshot: screenshotPath,
      isMobileNativeTarget: /^mobile_/i.test(state.targetFile)
    });
  }

  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(audit, null, 2));
});
