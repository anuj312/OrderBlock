// Dev helper: screenshot the terminal and report console errors.
// node tools/shot.js [url] [outDir]   (uses an existing Playwright install via PW_PATH)
const path = require('path');
const pwPath = process.env.PW_PATH || 'playwright';
const { chromium } = require(pwPath);

(async () => {
  const url = process.argv[2] || 'http://127.0.0.1:8010/';
  const out = process.argv[3] || path.join(__dirname, '..', '.shots');
  require('fs').mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(url);
  await page.waitForSelector('.tile[data-s]', { timeout: 20000 });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(out, 'board.png') });
  const tile = await page.$('#tilesBull .tile[data-rank="1"]');
  await tile.hover();
  await page.waitForSelector('#pop:not([hidden]) .p-chart', { timeout: 8000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(out, 'popup.png') });
  const pop = await page.$('#pop');
  await pop.screenshot({ path: path.join(out, 'popup-only.png') });
  await page.mouse.move(5, 890);
  await page.waitForTimeout(500);
  const card = await page.$('#cardsBear .card[data-s]');
  if (card) await card.screenshot({ path: path.join(out, 'card-bear.png') });
  // light theme via the sun/moon toggle
  await page.click('#theme');
  await page.waitForTimeout(1200);
  const theme = await page.evaluate(() => [document.documentElement.dataset.theme, localStorage.getItem('xray:theme'), document.querySelector('#theme').getAttribute('aria-label')]);
  console.log('theme after toggle:', JSON.stringify(theme));
  await page.screenshot({ path: path.join(out, 'board-light.png') });
  await (await page.$('#tilesBear .tile[data-rank="1"]')).hover();
  try {
    await page.waitForSelector('#pop:not([hidden]) .p-chart', { timeout: 8000 });
  } catch (e) {
    console.log('second popup failed; page errors:', JSON.stringify(errors));
    console.log('pop state:', await page.evaluate(() => ({ hidden: document.querySelector('#pop').hidden, html: document.querySelector('#pop').innerHTML.slice(0, 200) })));
    throw e;
  }
  await page.waitForTimeout(400);
  await (await page.$('#pop')).screenshot({ path: path.join(out, 'popup-light.png') });
  await page.mouse.move(5, 890);
  await page.reload();
  await page.waitForSelector('.tile[data-s]', { timeout: 20000 });
  console.log('theme after reload:', await page.evaluate(() => document.documentElement.dataset.theme));
  await page.setViewportSize({ width: 420, height: 900 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(out, 'mobile.png'), fullPage: false });
  console.log(JSON.stringify({ errors }, null, 1));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
