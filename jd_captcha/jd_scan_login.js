// 京东扫码登录 -> 抓 pt_key/pt_pin -> 写青龙1(id=108)
// 使用系统 chromium (/usr/bin/chromium), 直连(不经代理, 京东登录接口代理502)
const { chromium } = require('playwright');
const QL_DB = '/root/docker/ql/data/db/database.sqlite';
const ENV_ID = 108; // 949194446_m
const SQLITE = 'sqlite3';
const QR_IMG = '/tmp/jdlogin/qrcode.png';

function run(cmd) {
  const { execSync } = require('child_process');
  return execSync(cmd, { encoding: 'utf-8' }).toString();
}
function backupDb() {
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const bak = `${QL_DB}.bak_jdlogin_${ts}`;
  run(`cp ${QL_DB} ${bak}`);
  console.log('[backup]', bak);
}
function readCookie() {
  try { return run(`${SQLITE} ${QL_DB} "SELECT value FROM Envs WHERE id=${ENV_ID};"`).trim(); } catch (e) { return ''; }
}
function writeCookie(ptKey, ptPin) {
  const cookie = `pt_key=${ptKey}; pt_pin=${ptPin};`;
  run(`${SQLITE} ${QL_DB} "UPDATE Envs SET value='${cookie}' WHERE id=${ENV_ID};"`);
  console.log('[write] id=' + ENV_ID + ' len=' + cookie.length + ' cookie=' + cookie.slice(0, 40) + '...');
}

(async () => {
  console.log('[start] chromium...');
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/usr/bin/chromium',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
  });
  const ctx = await browser.newContext({ viewport: { width: 420, height: 820 }, isMobile: true, hasTouch: true, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1' });
  const page = await ctx.newPage();

  console.log('[goto] passport login');
  await page.goto('https://passport.jd.com/new/login.aspx?appid=web-m&returnurl=https%3A%2F%2Fm.jd.com%2F', { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(e => console.log('[goto warn]', e.message));
  console.log('[wait] 二维码元素...');
  try { await page.waitForSelector('img[src*="qr.m.jd.com/show"]', { timeout: 15000 }); console.log('[ok] 二维码出现'); }
  catch (e) { console.log('[warn] 等二维码超时, 直接截图'); }
  await page.waitForTimeout(2000);
  try { await page.screenshot({ path: QR_IMG }); console.log('[qr]', QR_IMG); } catch (e) { console.log('[qr warn]', e.message); }

  // 轮询登录态
  console.log('[poll] 等扫码登录(最多400s)...');
  let logged = false;
  for (let i = 0; i < 200; i++) {
    const cookies = await ctx.cookies('https://jd.com');
    const pk = cookies.find(c => c.name === 'pt_key');
    const pp = cookies.find(c => c.name === 'pt_pin');
    if (pk && pk.value && pk.value.length > 16 && !pk.value.startsWith('app_open') && pp && pp.value) {
      console.log('[ok] 登录成功');
      console.log('  pt_key=', pk.value.slice(0, 40) + '...');
      console.log('  pt_pin=', pp.value);
      await backupDb();
      writeCookie(pk.value, pp.value);
      logged = true;
      break;
    }
    await page.waitForTimeout(2000);
  }
  if (!logged) console.log('[fail] 超时未登录');

  await browser.close();
  console.log('[done]');
})().catch(e => { console.error('[FATAL]', e); process.exit(1); });
