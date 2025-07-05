// core/scrapers/escreen.js
const puppeteer     = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const path          = require('path');
const fs            = require('fs');

require('dotenv').config({
  path: path.resolve(__dirname, '../../.env')
});

puppeteer.use(StealthPlugin());

// ensure download and debug dirs exist
const BASE_DIR     = path.resolve(__dirname, '..'); 
const DOWNLOAD_DIR = process.env.DOWNLOAD_DIR
  || path.join(BASE_DIR, 'core', 'downloads');
const DEBUG_DIR    = path.join(BASE_DIR, 'core', 'debug');
for (const d of [DOWNLOAD_DIR, DEBUG_DIR]) {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
}

const sleep = ms => new Promise(res => setTimeout(res, ms));

/**
 * Dismiss the TrustArc banner if it appears on the given page.
 */
async function dismissTrustArc(page, timeout = 10000) {
  try {
    await page.waitForSelector('#truste-consent-required', {
      visible: true,
      timeout: 3000
    });
    console.log('🐛 [dismissTrustArc] Found REJECT → clicking…');
    await page.click('#truste-consent-required');
    console.log('🐛 [dismissTrustArc] Clicked. Waiting for banner to disappear…');
    await page.waitForFunction(
      () => !document.querySelector('#truste-consent-track'),
      { timeout }
    );
    console.log('✅ [dismissTrustArc] Banner dismissed');
  } catch (err) {
    // probably never appeared
    console.log('ℹ️ [dismissTrustArc] No TrustArc banner found (or timed out).');
  }
}

;(async () => {
  console.log('🛠️  Starting eScreen scraper…');
  const inDocker = fs.existsSync('/.dockerenv')
    || process.env.RUNNING_IN_DOCKER === 'true';
  console.log(`🔍 Running in Docker? ${inDocker}`);

  const launchOpts = inDocker
    ? {
        headless: true,
        executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/chromium',
        args: [
          '--no-sandbox',
          '--disable-setuid-sandbox',
          '--disable-dev-shm-usage',
          '--remote-debugging-port=9222',
          '--remote-debugging-address=0.0.0.0'
        ]
      }
    : {
        headless: true,
        defaultViewport: null,
        args: ['--start-maximized']
      };

  try {
    console.log('🌐 Launching browser…', launchOpts);
    const browser = await puppeteer.launch(launchOpts);
    console.log('✅ Browser launched');

    const page = await browser.newPage();
    console.log('✅ New page opened');

    // set up downloads
    console.log('⬇️  Configuring download behavior →', DOWNLOAD_DIR);
    const cdp = await page.target().createCDPSession();
    await cdp.send('Page.setDownloadBehavior', {
      behavior: 'allow',
      downloadPath: DOWNLOAD_DIR
    });
    console.log('✅ Download behavior set');

    //
    // ──────────────────────────────────────────────────────────────────────────────
    //   STEP 0: Navigate to landing page & dismiss TrustArc
    // ──────────────────────────────────────────────────────────────────────────────
    //
    console.log('🌐 Going to landing page…');
    await page.goto('https://www.myescreen.com/', {
      waitUntil: 'networkidle2',
      timeout: 60000
    });
    await dismissTrustArc(page);

    //
    // ──────────────────────────────────────────────────────────────────────────────
    //   STEP 1: Login
    // ──────────────────────────────────────────────────────────────────────────────
    //
    console.log('🚪 Waiting for sign-in field…');
    await page.waitForSelector('input#signInName', { timeout: 30000 });
    await page.type('input#signInName', process.env.ESCREEN_USERNAME);
    await page.keyboard.press('Enter');

    console.log('🔐 Waiting for password field…');
    await page.waitForSelector('input[type="password"]', { timeout: 30000 });
    await page.type('input[type="password"]', process.env.ESCREEN_PASSWORD);
    await page.keyboard.press('Enter');
    await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 });
    console.log('✅ Logged in');

    //
    // ──────────────────────────────────────────────────────────────────────────────
    //   STEP 2: Open Reports menu (then dismiss banner again just in case)
    // ──────────────────────────────────────────────────────────────────────────────
    //
    console.log('🔎 opening Reports menu');
    await page.waitForSelector('div.mainNavLink', { timeout: 30000 });
    await page.evaluate(() => {
      for (let el of document.querySelectorAll('div.mainNavLink'))
        if (el.innerText.trim() === 'Reports') el.click();
    });
    await sleep(3000);
    await dismissTrustArc(page);

    //
    // ──────────────────────────────────────────────────────────────────────────────
    //   STEP 3: Select Drug Test Summary Report
    // ──────────────────────────────────────────────────────────────────────────────
    //
    console.log('🔎 selecting Summary Report');
    await page.waitForSelector('a[target="mainFrame"]', { timeout: 30000 });
    await page.evaluate(() => {
      const link = Array.from(document.querySelectorAll('a[target="mainFrame"]'))
        .find(a => a.innerText.includes('Drug Test Summary Report'));
      link.click();
    });
    await sleep(5000);
    await dismissTrustArc(page);

    //
    // ──────────────────────────────────────────────────────────────────────────────
    //   STEP 4: Click “View All” inside the iframe
    // ──────────────────────────────────────────────────────────────────────────────
    //
    console.log('🔎 clicking View All in report iframe');
    let container = await page.waitForSelector('iframe[name="mainFrame"]', { timeout: 30000 });
    let frame = await container.contentFrame();
    await frame.waitForSelector('input#btnViewAll', { timeout: 30000 });
    await frame.click('input#btnViewAll');
    await sleep(5000);

    //
    // ──────────────────────────────────────────────────────────────────────────────
    //   STEP 4.5: Re-acquire the frame & debug-dump
    // ──────────────────────────────────────────────────────────────────────────────
    //
    console.log('🔄 re-acquiring mainFrame');
    container = await page.waitForSelector('iframe[name="mainFrame"]', { timeout: 30000 });
    frame = await container.contentFrame();


    //
    // ──────────────────────────────────────────────────────────────────────────────
    //   STEP 5: Set date 20 days ago
    // ──────────────────────────────────────────────────────────────────────────────
    //
    console.log('📅 setting start date…');
    await frame.waitForSelector('input#txtStart', { timeout: 30000 });
    const d20     = new Date(Date.now() - 20 * 24 * 60 * 60 * 1000);
    const mm      = String(d20.getMonth() + 1).padStart(2, '0');
    const dd      = String(d20.getDate()).padStart(2, '0');
    const yr      = d20.getFullYear();
    const dateStr = `${mm}/${dd}/${yr}`;
    await frame.click('input#txtStart', { clickCount: 3 });
    await frame.type('input#txtStart', dateStr, { delay: 50 });
    await sleep(2000);

    //
    // ──────────────────────────────────────────────────────────────────────────────
    //   STEP 6: Run & Download
    // ──────────────────────────────────────────────────────────────────────────────
    //
    console.log('▶ clicking Run');
    await frame.waitForSelector('input#cmdRun', { timeout: 30000 });
    await frame.click('input#cmdRun');
    await sleep(10000);

    console.log('⬇️  clicking download icon');
    await frame.waitForSelector('i.abt-icon.icon-Inbox', { timeout: 30000 });
    await frame.click('i.abt-icon.icon-Inbox');

    console.log('⌛ waiting for file…');
    const outPath = path.join(DOWNLOAD_DIR, 'DrugTestSummaryReport_Total.xlsx');
    for (let i = 0; i < 30; i++) {
      if (fs.existsSync(outPath)) break;
      await sleep(1000);
    }
    if (!fs.existsSync(outPath)) {
      throw new Error(`XLSX not found at ${outPath}`);
    }

    console.log('✅ Download complete →', outPath);
    await browser.close();
    process.exit(0);

  } catch (err) {
    const ts = Date.now();
    console.error('❌ eScreen scraper error:', err);
    if (typeof page !== 'undefined') {
      try {
        const shot = path.join(DEBUG_DIR, `err-${ts}.png`);
        const snapHtml = path.join(DEBUG_DIR, `err-${ts}.html`);
        await page.screenshot({ path: shot, fullPage: true });
        fs.writeFileSync(snapHtml, await page.content());
        console.error('🧪 Saved debug files:', shot, snapHtml);
      } catch (e) {
        console.error('⚠️ Failed to capture debug artifacts', e);
      }
    }
    process.exit(1);
  }
})();
