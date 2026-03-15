const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

test('mobile buddy boards support split drag and single-board focus toggles', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_theme', 'warm');
    window.localStorage.removeItem('mobile_buddy_surface:boardLayout');
    window.localStorage.removeItem('mobile_buddy_surface:managementBoardSize');
  });

  await page.setViewportSize({ width: 430, height: 932 });
  await page.goto(`${BASE_URL}/mobile_buddy.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1400);

  await expect(page.locator('#boardsStack')).toHaveAttribute('data-layout', 'split');
  await expect(page.locator('#boardDivider')).toBeVisible();
  await expect(page.locator('#managementBoardToggleBtn')).toBeVisible();
  await expect(page.locator('#teamBoardToggleBtn')).toBeVisible();

  const managementToggleBox = await page.locator('#managementBoardToggleBtn').boundingBox();
  const teamToggleBox = await page.locator('#teamBoardToggleBtn').boundingBox();
  expect(managementToggleBox.width).toBeGreaterThanOrEqual(44);
  expect(managementToggleBox.height).toBeGreaterThanOrEqual(44);
  expect(teamToggleBox.width).toBeGreaterThanOrEqual(44);
  expect(teamToggleBox.height).toBeGreaterThanOrEqual(44);

  const beforeDragManagement = await page.locator('#managementBoard').boundingBox();
  const beforeDragTeam = await page.locator('#teamBoard').boundingBox();
  const dividerBox = await page.locator('#boardDivider').boundingBox();

  await page.mouse.move(dividerBox.x + dividerBox.width / 2, dividerBox.y + dividerBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(dividerBox.x + dividerBox.width / 2, dividerBox.y + dividerBox.height / 2 + 80, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(250);

  const afterDragManagement = await page.locator('#managementBoard').boundingBox();
  const afterDragTeam = await page.locator('#teamBoard').boundingBox();
  expect(afterDragManagement.height).toBeGreaterThan(beforeDragManagement.height + 30);
  expect(afterDragTeam.height).toBeLessThan(beforeDragTeam.height - 30);

  await page.locator('#managementBoardToggleBtn').click();
  await expect(page.locator('#boardsStack')).toHaveAttribute('data-layout', 'team-focus');
  await expect(page.locator('#teamBoardToggleBtn')).toHaveAttribute('aria-label', 'Beide Boards zeigen');
  await expect.poll(async () => (await page.locator('#managementBoard').boundingBox())?.height || 0).toBeLessThan(4);

  await page.locator('#teamBoardToggleBtn').click();
  await expect(page.locator('#boardsStack')).toHaveAttribute('data-layout', 'split');

  await page.locator('#teamBoardToggleBtn').click();
  await expect(page.locator('#boardsStack')).toHaveAttribute('data-layout', 'management-focus');
  await expect(page.locator('#managementBoardToggleBtn')).toHaveAttribute('aria-label', 'Beide Boards zeigen');
  await expect.poll(async () => (await page.locator('#teamBoard').boundingBox())?.height || 0).toBeLessThan(4);

  await page.locator('#managementBoardToggleBtn').click();
  await expect(page.locator('#boardsStack')).toHaveAttribute('data-layout', 'split');

  await page.locator('#boardDivider').focus();
  const preKeyboard = await page.locator('#managementBoard').boundingBox();
  await page.keyboard.press('End');
  await page.waitForTimeout(200);
  const postKeyboard = await page.locator('#managementBoard').boundingBox();
  expect(postKeyboard.height).toBeGreaterThan(preKeyboard.height + 20);
});
