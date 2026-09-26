// 京东验证码样本采集器: 自动登录触发验证码 -> 截图+OCR题 -> 点刷新换题, 循环采集
// 输出: samples/NNN.png + samples/labels.csv (文件名,题目)
const { chromium } = require('playwright');
const fs = require('fs');
const { execSync } = require('child_process');
const PHONE = process.env.JD_PHONE;
const PWD = process.env.JD_PWD;
const N = parseInt(process.env.N || '100');
const OUT = '/tmp/jdlogin/samples';

function run(cmd) { return execSync(cmd, { encoding: 'utf-8' }).toString(); }

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/chromium', args: ['--no-sandbox','--disable-setuid-sandbox','--disable-gpu','--disable-dev-shm-usage'] });
  const ctx = await browser.newContext({ viewport: { width: 500, height: 900 }, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1' });
  const page = await ctx.newPage();
  await page.goto('https://passport.jd.com/new/login.aspx?appid=web-m&returnurl=https%3A%2F%2Fm.jd.com%2F', { waitUntil: 'domcontentloaded' }).catch(() => {});
  await page.waitForTimeout(3000);
  try { await page.locator('text=密码登录').first().click({ timeout: 3000 }); } catch (e) {}
  await page.waitForTimeout(1200);
  await page.click('#loginname').catch(() => {});
  await page.type('#loginname', PHONE, { delay: 60 });
  await page.click('#nloginpwd').catch(() => {});
  await page.type('#nloginpwd', PWD, { delay: 60 });
  await page.waitForTimeout(500);
  await page.focus('#nloginpwd').catch(() => {});
  await page.keyboard.press('Enter');
  console.log('[submit] 开始采集');

  // 等第一个验证码
  for (let w = 0; w < 20; w++) {
    await page.waitForTimeout(2000);
    const t = await page.locator('body').innerText().catch(() => '');
    if (/安全验证/.test(t) || (await page.locator('.drag-box').count()) > 0) { console.log('[cap] 首次出现'); break; }
  }

  const csv = [];
  for (let i = 1; i <= N; i++) {
    const png = `${OUT}/s${String(i).padStart(3,'0')}.png`;
    await page.screenshot({ path: png });
    // OCR 题目
    let hint = '';
    try {
      const out = run(`cd /tmp/jdlogin && python3 ocr_hint.py ${png}`);
      const m = out.match(/HINT=(.*)/);
      if (m) hint = m[1].trim();
    } catch (e) {}
    csv.push(`s${String(i).padStart(3,'0')}.png,${hint}`);
    console.log(`[${i}/${N}] ${png} hint=${hint}`);
    // 刷新换题
    try { await page.locator('text=刷新').first().click({ timeout: 3000 }); }
    catch (e) { try { await page.locator('.refresh, [class*=refresh]').first().click({ timeout: 2000 }); } catch (e2) {} }
    await page.waitForTimeout(2500);
  }
  fs.writeFileSync(`${OUT}/labels.csv`, csv.join('\n'));
  console.log('[done] 采集完成 ' + N + ' 张, labels.csv 已写');
  await browser.close();
})().catch(e => { console.error('[FATAL]', e); process.exit(1); });
