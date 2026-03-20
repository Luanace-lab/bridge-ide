const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

test('mobile buddy root loads with drawer navigation and settings shell', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_theme', 'warm');
    window.localStorage.removeItem('mobile_buddy_surface:buddyWidgetPos');
    window.localStorage.removeItem('mobile_buddy_surface:buddyWidgetBubblePos');
    window.localStorage.removeItem('mobile_buddy_surface:buddyWidgetBubbleSize');
    window.localStorage.removeItem('mobile_buddy_surface:boardLayout');
    window.localStorage.removeItem('mobile_buddy_surface:managementBoardSize');
  });

  await page.goto(`${BASE_URL}/mobile_buddy.html`, { waitUntil: 'domcontentloaded' });

  await expect(page.locator('#menuBtn')).toBeVisible();
  await expect(page.locator('h1')).toHaveCount(0);
  await expect(page.locator('#statusPill')).toContainText(/Startet|Bereit|Degradiert|Offline/);
  await expect(page.locator('#managementBoardTitle')).toBeVisible();
  await expect(page.locator('#teamBoardTitle')).toBeVisible();
  await expect(page.locator('.footerNote')).toHaveCount(0);
  await expect(page.locator('#managementComposerInput')).toBeVisible();
  await expect(page.locator('#managementAttachBtn')).toBeVisible();
  await expect(page.locator('#managementSendBtn')).toBeVisible();
  await expect(page.locator('#teamComposerInput')).toBeVisible();
  await expect(page.locator('#teamAttachBtn')).toBeVisible();
  await expect(page.locator('#teamSendBtn')).toBeVisible();
  await expect(page.locator('#teamPickerDropdown')).toBeHidden();
  await expect(page.locator('#memberBar')).toBeHidden();
  await expect(page.locator('#buddyWidgetIcon')).toBeVisible();
  await expect(page.locator('#buddyWidgetBubble')).not.toHaveClass(/open/);

  const warmBoard = await page.evaluate(() => getComputedStyle(document.querySelector('.mobileBoard--management')).backgroundColor);
  const warmChatSurface = await page.evaluate(() => getComputedStyle(document.querySelector('#managementMessages')).backgroundColor);
  expect(warmBoard).toBe('rgb(253, 252, 250)');
  expect(warmChatSurface).toBe('rgb(255, 255, 255)');

  const shellBox = await page.locator('#shell').boundingBox();
  const iconBox = await page.locator('#buddyWidgetIcon').boundingBox();
  expect(shellBox).not.toBeNull();
  expect(iconBox).not.toBeNull();
  expect(iconBox.x).toBeGreaterThanOrEqual(shellBox.x);
  expect(iconBox.y).toBeGreaterThanOrEqual(shellBox.y);
  expect(iconBox.y).toBeGreaterThan(220);

  await expect.poll(async () => (await page.locator('#teamSummaryPill').textContent()) || '').not.toContain('Kein Team aktiv');
  await expect(page.locator('#teamPickerBtnLabel')).not.toHaveText('Teams');
  const teamPickerBox = await page.locator('#teamPickerBtn').boundingBox();
  const memberToggleBox = await page.locator('#memberToggleBtn').boundingBox();
  const teamBoardToggleBox = await page.locator('#teamBoardToggleBtn').boundingBox();
  expect(Math.abs(teamPickerBox.y - memberToggleBox.y)).toBeLessThan(8);
  expect(Math.abs(teamPickerBox.y - teamBoardToggleBox.y)).toBeLessThan(8);
  await expect(page.locator('#memberToggleBtn .teamDisclosureBtn__label')).not.toHaveText('Agenten');

  const managementFileName = `mobile-management-${Date.now()}.txt`;
  await page.locator('#managementFileInput').setInputFiles({
    name: managementFileName,
    mimeType: 'text/plain',
    buffer: Buffer.from('management attachment smoke')
  });
  await expect(page.locator('#managementAttachPreview')).toBeVisible();
  await expect(page.locator('#managementSendBtn')).toHaveAttribute('data-enabled', 'true');
  await page.locator('#managementSendBtn').click();
  await expect(page.locator('#managementAttachPreview')).toBeHidden();
  await expect(page.locator('#managementMessagesInner .msgAttachmentFile__name').last()).toContainText(managementFileName);

  const teamFileName = `mobile-team-${Date.now()}.txt`;
  await page.locator('#teamFileInput').setInputFiles({
    name: teamFileName,
    mimeType: 'text/plain',
    buffer: Buffer.from('team attachment smoke')
  });
  await expect(page.locator('#teamAttachPreview')).toBeVisible();
  await expect(page.locator('#teamSendBtn')).toHaveAttribute('data-enabled', 'true');
  await page.locator('#teamSendBtn').click();
  await expect(page.locator('#teamAttachPreview')).toBeHidden();
  await expect(page.locator('#teamMessagesInner .msgAttachmentFile__name').last()).toContainText(teamFileName);

  await page.locator('#teamPickerBtn').click();
  await expect(page.locator('#teamPickerDropdown')).toBeVisible();
  await page.locator('#memberToggleBtn').click();
  await expect(page.locator('#memberBar')).toBeVisible();

  await page.locator('#buddyWidgetIcon').click();
  await expect(page.locator('#buddyWidgetBubble')).toHaveClass(/open/);
  await expect(page.locator('#bwInput')).toBeVisible();
  const bubbleTailDisplay = await page.evaluate(() => getComputedStyle(document.querySelector('#buddyWidgetBubble'), '::after').display);
  expect(bubbleTailDisplay).toBe('none');
  const bubbleBox = await page.locator('#buddyWidgetBubble').boundingBox();
  expect(bubbleBox.width).toBeLessThan(300);
  expect(bubbleBox.height).toBeLessThan(320);
  await page.locator('#bwInput').fill('Buddy Mobile Smoke');
  await page.locator('#bwSend').click();
  await expect(page.locator('.bwMsg--user').last()).toContainText('Buddy Mobile Smoke');
  await page.locator('#buddyWidgetIcon').click();
  await expect(page.locator('#buddyWidgetBubble')).not.toHaveClass(/open/);

  await page.getByRole('button', { name: 'Navigation oeffnen' }).click();
  await expect(page.locator('#mobileDrawer')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Verdichtete Lage' })).toBeVisible();
  const drawerOverflowOk = await page.evaluate(() => {
    const drawer = document.getElementById('mobileDrawer');
    const nav = drawer && drawer.querySelector('.drawerNav');
    if (!drawer || !nav) return false;
    return drawer.scrollWidth <= drawer.clientWidth + 2 && nav.scrollWidth <= nav.clientWidth + 2;
  });
  expect(drawerOverflowOk).toBe(true);
  const summaryCardTops = await page.locator('.summaryGrid > .summaryCard').evaluateAll(cards =>
    cards.map(card => Math.round(card.getBoundingClientRect().top))
  );
  expect(new Set(summaryCardTops).size).toBeGreaterThan(1);
  await expect(page.locator('#tasksSummaryCard')).toBeVisible();
  await expect(page.locator('#projectsSummaryCard')).toBeVisible();
  await expect(page.locator('#workflowSummaryCard')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Neu laden' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Top 3 Tasks' })).toBeVisible();
  await expect(page.getByRole('link', { name: /Buddy Home/i })).toBeVisible();
  await expect(page.locator('#mobileDrawer .drawerLink[data-route="control_center.html"]')).toBeVisible();
  await expect(page.locator('#mobileDrawer .drawerLink[data-route="control_center.html?tab=workflows"]')).toBeVisible();
  await page.getByRole('button', { name: 'Top 3 Tasks' }).click();
  await expect(page.locator('#managementComposerInput')).toHaveValue(/wichtigsten offenen Tasks/);

  await page.getByRole('button', { name: 'Navigation oeffnen' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.locator('#settingsSheet')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Warm' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Hell' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Dunkel' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Black' })).toBeVisible();
  await page.getByRole('button', { name: 'Black' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'black');
  await expect.poll(async () => page.evaluate(() => window.localStorage.getItem('bridge_theme'))).toBe('black');
  await expect(page.getByRole('button', { name: 'Buddy neu verbinden' }).last()).toBeVisible();

  await page.locator('#buddyWidgetIcon').click();
  await expect(page.locator('#buddyWidgetBubble')).toHaveClass(/open/);
  const darkBubbleBg = await page.evaluate(() => getComputedStyle(document.querySelector('#buddyWidgetBubble')).backgroundColor);
  expect(darkBubbleBg).not.toMatch(/0\.(?:0|1|2|3|4|5|6|7|8|9)\)?$/);
  expect(darkBubbleBg).not.toContain(' / 0.');
});
