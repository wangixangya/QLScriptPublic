// 京东滑块验证码样本采集器(只采滑块): 存整页图 + 背景图原图 + 缺口标注待补
// 输出: slide_samples/NNN_full.png, NNN_bg.png, labels.csv
const { chromium } = require('playwright');
const fs = require('fs');
const PHONE = process.env.JD_PHONE;
const PWD = process.env.JD_PWD;
const N = parseInt(process.env.N || '60');
const OUT = '/tmp/jdlogin/slide_samples';

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
  console.log('[submit] 开始采集滑块样本');

  for (let w = 0; w < 20; w++) {
    await page.waitForTimeout(2000);
    if ((await page.locator('.drag-box').count()) > 0) { console.log('[cap] 首次出现'); break; }
  }

  const csv = [];
  let got = 0;
  for (let i = 1; i <= N * 4 && got < N; i++) {
    // 判断是否滑块
    const drag = await page.locator('.drag-box').count();
    const t = await page.locator('body').innerText().catch(() => '');
    const isSlide = drag > 0 || /拖动滑块|拼图/.test(t);
    if (!isSlide) {
      // 点选题: 刷新换题
      try { await page.locator('text=刷新').first().click({ timeout: 2500 }); } catch (e) {}
      await page.waitForTimeout(2200);
      continue;
    }
    got++;
    const tag = String(got).padStart(3, '0');
    const full = `${OUT}/s${tag}_full.png`;
    const bgp  = `${OUT}/s${tag}_bg.png`;
    await page.screenshot({ path: full });
    // 背景图原图
    let natW = 0, dispW = 0;
    try {
      const info = await page.evaluate(() => {
        for (const e of document.querySelectorAll('img')) {
          const r = e.getBoundingClientRect();
          if (r.width > 200 && r.width < 420 && r.height > 120 && e.naturalWidth > 200) {
            return { src: e.src, natW: e.naturalWidth, dispW: Math.round(r.width) };
          }
        }
        return null;
      });
      if (info && info.src.startsWith('data:')) {
        fs.writeFileSync(bgp, Buffer.from(info.src.split(',')[1], 'base64'));
        natW = info.natW; dispW = info.dispW;
      }
    } catch (e) {}
    csv.push(`s${tag},${natW},${dispW},`);   // 缺口x待标注
    console.log(`[${got}/${N}] s${tag} bg natW=${natW} dispW=${dispW}`);
    // 刷新换题(保持滑块或换类型)
    try { await page.locator('text=刷新').first().click({ timeout: 2500 }); } catch (e) {}
    await page.waitForTimeout(2200);
  }
  fs.writeFileSync(`${OUT}/labels.csv`, 'tag,natW,dispW,gapx\n' + csv.join('\n'));
  console.log(`[done] 采到 ${got} 张滑块样本`);
  await browser.close();
})().catch(e => { console.error('[FATAL]', e); process.exit(1); });
