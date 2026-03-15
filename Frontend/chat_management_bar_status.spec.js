const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

async function hideWelcomeOverlay(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_welcome_seen', '1');
  });
}

test('chat management chips keep runtime colors even when an agent is deactivated in config', async ({ page }) => {
  await hideWelcomeOverlay(page);
  await page.goto(`${BASE_URL}/chat.html`, { waitUntil: 'domcontentloaded' });

  await page.evaluate(() => {
    window.eval(`
      agentStatusCache = [
        { agent_id: 'ordo', status: 'running', active: false, online: true },
        { agent_id: 'lucy', status: 'waiting', active: true, online: true },
        { agent_id: 'nova', status: 'disconnected', active: true, online: false }
      ];
      orgchartAgentMap = {
        ordo: { id: 'ordo', name: 'Ordo', role: 'manager', active: false, online: true, status: 'running' },
        lucy: { id: 'lucy', name: 'Lucy', role: 'assistant', active: true, online: true, status: 'waiting' },
        nova: { id: 'nova', name: 'Nova', role: 'strategist', active: true, online: false, status: 'disconnected' }
      };
      renderMgmtMemberBar([{ members: ['ordo', 'lucy', 'nova'] }]);
    `);
  });

  const colors = await page.evaluate(() => {
    const readColor = (agentId) => {
      const dot = document.querySelector('#mgmtMemberBar .memberChip[data-agent="' + agentId + '"] .memberChip__dot');
      return dot ? getComputedStyle(dot).backgroundColor : null;
    };
    return {
      ordo: readColor('ordo'),
      lucy: readColor('lucy'),
      nova: readColor('nova'),
      ordoDeactivated: document.querySelector('#mgmtMemberBar .memberChip[data-agent="ordo"]')?.classList.contains('memberChip--deactivated') || false,
    };
  });

  expect(colors.ordo).toBe('rgb(34, 197, 94)');
  expect(colors.lucy).toBe('rgb(245, 158, 11)');
  expect(colors.nova).toBe('rgb(239, 68, 68)');
  expect(colors.ordoDeactivated).toBe(true);
});
