// Optional end-to-end smoke test (real browser). Not part of `pytest`.
//
//   1. python scripts/seed_demo.py           (against a throwaway MEDITRACK_DB_PATH, with demo passwords set)
//   2. uvicorn app.main:get_app --factory --port 8123
//   3. npm i playwright && node tests/e2e/ui_smoke.js ./screenshots
//
// It signs in as staff, adds/duplicates/bulk-adds/reconciles appointments, opens the dashboard,
// downloads the CSV, checks the auditor is read-only, and checks phone width for horizontal overflow.
// Expected console noise: two 401s (pre-login session check, wrong password) and one 409 (the duplicate).
const { chromium } = require('playwright');
const SP = process.argv[2] || '.';
require('fs').mkdirSync(SP, { recursive: true });
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const problems = [];
  page.on('console', m => { if (['error','warning'].includes(m.type())) problems.push('console.' + m.type() + ': ' + m.text()); });
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  page.on('requestfailed', r => problems.push('requestfailed: ' + r.url()));

  await page.goto('http://localhost:8123/');
  await page.screenshot({ path: SP + '/01-login.png' });

  // wrong password first
  await page.fill('#username', 'staff'); await page.fill('#password', 'nope');
  await page.click('button[type=submit]');
  await page.waitForSelector('.alert.error');
  console.log('bad login message:', await page.textContent('.alert.error'));

  await page.fill('#password', 'staff-demo-2026'); await page.click('button[type=submit]');
  await page.waitForSelector('#tabs .tab');
  console.log('tabs:', await page.$$eval('#tabs .tab', els => els.map(e => e.textContent)));
  await page.waitForSelector('table tbody tr');
  console.log('rows today:', await page.$$eval('table tbody tr', r => r.length));
  console.log('summary:', await page.textContent('#list-heading + p'));

  // add one appointment
  await page.fill('#f-name', 'Playwright Patient'); await page.fill('#f-time', '16:30');
  await page.selectOption('#f-type', 'lab_test');
  await page.click('form button[type=submit] >> text=Add appointment');
  await page.waitForSelector('.toast');
  console.log('toast:', await page.textContent('.toast'));

  // duplicate -> error shown
  await page.fill('#f-name', 'Playwright Patient'); await page.fill('#f-time', '16:30');
  await page.click('text=Add appointment');
  await page.waitForSelector('.alert.error');
  console.log('dup error:', (await page.textContent('.alert.error')).trim());

  // bulk with a bad line, then good
  await page.fill('#bulk-text', 'Bulk One, 10:15\nBulk Two, 25:00');
  await page.click('text=Add all');
  await page.waitForSelector('#bulk-heading ~ form .alert.error, .alert.error >> nth=1');
  console.log('bulk err:', (await page.$$eval('.alert.error', e => e.map(x => x.textContent.trim()))).join(' | '));
  await page.fill('#bulk-text', 'Bulk One, 10:15\nBulk Two, 10:45, follow-up');
  await page.click('text=Add all');
  await page.waitForFunction(() => document.body.textContent.includes('Bulk Two'));

  // reconcile
  const row = page.locator('tr', { hasText: 'Playwright Patient' });
  await row.locator('text=No-show').click();
  await page.waitForFunction(() => [...document.querySelectorAll('tr')].some(r => r.textContent.includes('Playwright Patient') && r.textContent.includes('Undo')));
  console.log('reconciled ok');
  await page.screenshot({ path: SP + '/02-appointments.png', fullPage: true });

  // dashboard
  await page.click('#tab-dashboard');
  await page.waitForSelector('.kpi .value');
  console.log('kpis:', await page.$$eval('.kpi', k => k.map(x => x.querySelector('.label').textContent + '=' + x.querySelector('.value').textContent)));
  await page.screenshot({ path: SP + '/03-dashboard.png', fullPage: true });

  // export
  const [dl] = await Promise.all([page.waitForEvent('download'), page.click('text=Export CSV')]);
  const path = await dl.path(); const fs = require('fs');
  const csv = fs.readFileSync(path, 'utf8');
  console.log('download:', dl.suggestedFilename(), '| lines:', csv.trim().split('\n').length, '| header:', csv.split('\n')[0].replace('﻿',''));

  await page.click('#tab-model'); await page.waitForSelector('dl.facts');
  await page.screenshot({ path: SP + '/04-model.png', fullPage: true });
  console.log('retrain button as staff:', await page.locator('text=Retrain on reconciled data').count());

  // sign out and sign in as auditor
  await page.click('#logout'); await page.waitForSelector('#username');
  await page.fill('#username', 'auditor'); await page.fill('#password', 'auditor-demo-2026'); await page.click('button[type=submit]');
  await page.waitForSelector('#tabs .tab');
  console.log('auditor: add form present =', await page.locator('#f-name').count(), '| action buttons =', await page.locator('td.actions').count());
  await page.screenshot({ path: SP + '/05-auditor.png', fullPage: true });

  // mobile
  await page.setViewportSize({ width: 390, height: 800 });
  await page.click('#tab-dashboard'); await page.waitForSelector('.kpi .value');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  console.log('horizontal page overflow at 390px:', overflow);
  await page.screenshot({ path: SP + '/06-mobile.png', fullPage: false });

  console.log('PROBLEMS:', problems.length ? problems : 'none');
  await browser.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
