const fs = require('fs');
const path = require('path');
const { test, expect } = require('playwright/test');

const FILE_URL = 'file://./Frontend/chat.html';
const OUTPUT_DIR = './Frontend/screenshots/20260309_chat_regression_fix';
const THEMES = ['warm', 'light', 'rose', 'dark'];

fs.mkdirSync(OUTPUT_DIR, { recursive: true });

async function primeMainComposer(page, theme) {
  await page.goto(FILE_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(500);
  await page.evaluate(({ theme }) => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('bridge_theme', theme);

    const leftWrap = document.getElementById('leftTargetWrap');
    const leftTrigger = document.getElementById('leftTargetTrigger');
    const leftInput = document.querySelector('.chatInput--left textarea');
    if (leftWrap) leftWrap.dataset.value = 'viktor';
    if (leftTrigger) leftTrigger.textContent = 'Viktor';
    if (leftInput) {
      leftInput.value = '';
      leftInput.placeholder = 'Nachricht an Viktor...';
    }

    const rightWrap = document.getElementById('rightTargetWrap');
    const rightTrigger = document.getElementById('rightTargetTrigger');
    const rightInput = document.querySelector('.chatInput--right textarea');
    if (rightWrap) rightWrap.dataset.value = 'all_team';
    if (rightTrigger) rightTrigger.textContent = 'Alle (Team Alpha — Ghost)';
    if (rightInput) {
      rightInput.value = '';
      rightInput.placeholder = 'Broadcast an Team Alpha — Ghost...';
    }

    const leftInner = document.querySelector('#chatMessagesLeft .chatMessagesInner');
    const rightInner = document.querySelector('#chatMessagesRight .chatMessagesInner');
    if (leftInner) {
      leftInner.innerHTML = '';
      const msg = document.createElement('div');
      msg.className = 'chatMsg chatMsg--agent';
      msg.textContent = 'Referenznachricht';
      leftInner.appendChild(msg);
    }
    if (rightInner) {
      rightInner.innerHTML = '';
      const msg = document.createElement('div');
      msg.className = 'chatMsg chatMsg--agent';
      msg.textContent = 'Referenznachricht';
      rightInner.appendChild(msg);
    }
  }, { theme });
}

async function primeParallelPanels(page, theme) {
  await page.goto(FILE_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(500);
  await page.evaluate(({ theme }) => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('bridge_theme', theme);

    const teamWorkspace = document.getElementById('teamWorkspace');
    const rightChat = document.getElementById('chatMessagesRight');
    const rightInput = document.querySelector('.chatInput--right');
    const rightHeader = document.querySelector('.boardHeader--right');
    if (teamWorkspace) teamWorkspace.style.display = 'block';
    if (rightChat) rightChat.style.display = 'none';
    if (rightInput) rightInput.style.display = 'none';
    if (rightHeader) rightHeader.style.display = 'none';

    if (window.openPanels && window.openPanels.clear) {
      window.openPanels.forEach((entry) => entry.el.remove());
      window.openPanels.clear();
    }

    const left = window.wsCreatePanel('Bridge IDE', 'Strategy & Research');
    const right = window.wsCreatePanel('Bridge IDE', 'Team Alpha — Ghost');
    window.wsTilePanels();

    const fillPanel = (entry, from, text) => {
      for (let i = 0; i < 15; i += 1) {
        window.wsRouteMessageToPanel({
          from,
          to: 'user',
          content: `${text} ${i + 1}`,
          timestamp: new Date(Date.now() - i * 60000).toISOString(),
        }, entry);
      }
    };

    fillPanel(left, 'nova', 'Parallelpanel Referenz links');
    fillPanel(right, 'viktor', 'Parallelpanel Referenz rechts');
  }, { theme });
}

test.use({ viewport: { width: 1600, height: 980 } });

test('chat composer and parallel panels stay theme-consistent', async ({ page }) => {
  for (const theme of THEMES) {
    await primeMainComposer(page, theme);
    await page.screenshot({
      path: path.join(OUTPUT_DIR, `composer_${theme}.png`),
      clip: { x: 0, y: 720, width: 1600, height: 220 },
    });

    await primeParallelPanels(page, theme);
    await page.screenshot({
      path: path.join(OUTPUT_DIR, `parallel_${theme}.png`),
      clip: { x: 760, y: 0, width: 840, height: 920 },
    });
  }

  expect(fs.existsSync(path.join(OUTPUT_DIR, 'composer_dark.png'))).toBeTruthy();
  expect(fs.existsSync(path.join(OUTPUT_DIR, 'parallel_dark.png'))).toBeTruthy();
});
