const { test, expect } = require('playwright/test');

const BASE_URL = 'http://127.0.0.1:9111';

async function hideWelcomeOverlay(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('bridge_welcome_seen', '1');
  });
}

test('chat hides internal agent system-chatter while keeping real agent replies', async ({ page }) => {
  await hideWelcomeOverlay(page);
  await page.goto(`${BASE_URL}/chat.html`, { waitUntil: 'domcontentloaded' });

  await page.evaluate(() => {
    const leftInner = document.querySelector('#chatMessagesLeft .chatMessagesInner');
    const rightInner = document.querySelector('#chatMessagesRight .chatMessagesInner');
    if (leftInner) leftInner.innerHTML = '';
    if (rightInner) rightInner.innerHTML = '';

    const messages = [
      {
        id: 91001,
        from: 'codex',
        to: 'user',
        content: "Systemnachricht 77369 verarbeitet: created(limit=50)=0, keine claimbaren Tasks. Antwort an `system` wurde via bridge_send versucht, aber vom Routing unterdrückt ('system' kein gültiger Empfänger).",
        timestamp: new Date(Date.UTC(2026, 2, 14, 21, 20, 0)).toISOString(),
      },
      {
        id: 91002,
        from: 'codex',
        to: 'user',
        content: 'Ich habe den Runtime-Fehler eingegrenzt und den kleinsten Fix gesetzt.',
        timestamp: new Date(Date.UTC(2026, 2, 14, 21, 20, 5)).toISOString(),
      },
      {
        id: 91003,
        from: 'codex',
        to: 'user',
        content: 'Duplikat erkannt: Nachricht 77369 erneut zugestellt. Idempotent verarbeitet; created(limit=50)=0, keine claimbaren Tasks.',
        timestamp: new Date(Date.UTC(2026, 2, 14, 21, 20, 10)).toISOString(),
      },
    ];

    messages.forEach((msg) => window.renderMessage(msg));
  });

  await expect(page.locator('#chatMessagesRight .chatMsg')).toHaveCount(1);
  await expect(page.locator('#chatMessagesRight .chatMsg').first()).toContainText('Ich habe den Runtime-Fehler eingegrenzt');
});

test('chat hides internal agent to-system messages even when content looks normal', async ({ page }) => {
  await hideWelcomeOverlay(page);
  await page.goto(`${BASE_URL}/chat.html`, { waitUntil: 'domcontentloaded' });

  await page.evaluate(() => {
    const leftInner = document.querySelector('#chatMessagesLeft .chatMessagesInner');
    const rightInner = document.querySelector('#chatMessagesRight .chatMessagesInner');
    if (leftInner) leftInner.innerHTML = '';
    if (rightInner) rightInner.innerHTML = '';

    [
      {
        id: 92001,
        from: 'codex',
        to: 'system',
        content: 'Interner Heartbeat-Bericht fuer system.',
        timestamp: new Date(Date.UTC(2026, 2, 14, 21, 25, 0)).toISOString(),
      },
      {
        id: 92002,
        from: 'codex',
        to: 'user',
        content: 'Sichtbare Nutzerantwort von codex.',
        timestamp: new Date(Date.UTC(2026, 2, 14, 21, 25, 5)).toISOString(),
      },
    ].forEach((msg) => window.renderMessage(msg));
  });

  await expect(page.locator('#chatMessagesRight .chatMsg')).toHaveCount(1);
  await expect(page.locator('#chatMessagesRight .chatMsg').first()).toContainText('Sichtbare Nutzerantwort von codex.');
});
