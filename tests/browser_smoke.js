'use strict';
// Reads the ledger the way a reader would: default view, search, the
// compliant-rows toggle, and the capture receipts behind the snapshot.
const assert = require('assert');
const { chromium } = require('playwright');

(async () => {
  const base = process.env.SMOKE_BASE;
  const origin = new URL(base).origin;
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  const foreign = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (new URL(r.url()).origin !== origin) foreign.push(r.url()); });
  const rowText = async id => {
    const row = page.locator('#tables tr:not(.hidden)', { has: page.locator(`span[title="${id}"]`) });
    // Cells joined with "|" so adjacent numbers stay separate.
    return (await row.count()) ? (await row.first().locator('td').allTextContents()).join('|') : null;
  };
  try {
    const response = await page.goto(base + `?v=${Date.now()}`, { waitUntil: 'networkidle' });
    assert(response.ok(), `index returned ${response.status()}`);
    await page.waitForSelector('#tables tr');
    assert((await page.textContent('#asof')).includes('fetched 2026-10-06'));
    const captures = await page.locator('.captures li').allTextContents();
    assert.strictEqual(captures.length, 2, `captures: ${captures.length}`);
    for (const c of captures) assert(/[0-9a-f]{64}/.test(c), `no receipt in: ${c}`);

    // Default hides compliant rows: a PASS row is absent, a SHORT row present.
    assert.strictEqual(await rowText('claude-sonnet-4-5-20250929'), null, 'PASS row shown while hidden');
    const cyber = await rowText('gpt-5.4-cyber');
    assert(cyber && cyber.split('|').includes('20') && cyber.includes('SHORT'), cyber);

    await page.uncheck('#hidePass');
    const s45 = await rowText('claude-sonnet-4-5-20250929');
    assert(s45 && s45.split('|').includes('61') && s45.includes('PASS'), s45);

    await page.fill('#search', 'tts-1');
    const tts = await rowText('tts-1');
    assert(tts && tts.split('|').includes('97') && tts.includes('SHORT') && tts.includes('PASS'), tts);
    assert.strictEqual(await rowText('gpt-5.4-cyber'), null, 'search did not filter');

    assert.deepStrictEqual(errors, []);
    assert.deepStrictEqual(foreign, [], `third-party requests: ${foreign}`);
    console.log(`Browser smoke passed (${base}): 2 capture receipts, compliant rows hidden by default, gpt-5.4-cyber 20d SHORT, Sonnet 4.5 61d PASS, tts-1 97d GA SHORT / specialized PASS, search filters, no errors, no third-party requests.`);
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
