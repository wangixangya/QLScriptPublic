// 京东通用验证码解题: 先读题目(DOM) -> 按题目类型(滑块/点选)分流 -> 解 -> 登录拿 cookie
const { chromium } = require('playwright');
const fs = require('fs');
const { execSync } = require('child_process');
const QL_DB = process.env.QL_DB || '';   // 不填则只输出 cookie 不写库
const SQLITE = 'sqlite3';
const PHONE = process.env.JD_PHONE;
const PWD = process.env.JD_PWD;

function run(cmd) { return execSync(cmd, { encoding: 'utf-8' }).toString(); }
function findEnvIdByPin(pin) {
  try {
    const rows = run(`${SQLITE} ${QL_DB} "SELECT id,value FROM Envs WHERE name='JD_COOKIE';"`).trim().split('\n');
    for (const r of rows) { const [id, val] = r.split('|'); if (val && val.includes('pt_pin=' + pin)) return id; }
  } catch (e) {}
  return null;
}
function backupDb() {
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const bak = `${QL_DB}.bak_jdlogin_${ts}`;
  run(`cp ${QL_DB} ${bak}`); console.log('[backup]', bak);
}
function writeCookie(envId, ptKey, ptPin) {
  const cookie = `pt_key=${ptKey}; pt_pin=${ptPin};`;
  run(`${SQLITE} ${QL_DB} "UPDATE Envs SET value='${cookie}' WHERE id=${envId};"`);
  console.log('[write] id=' + envId + ' pin=' + ptPin);
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/chromium', args: ['--no-sandbox','--disable-setuid-sandbox','--disable-gpu','--disable-dev-shm-usage'] });
  const ctx = await browser.newContext({ viewport: { width: 500, height: 900 }, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1' });
  const page = await ctx.newPage();
  await page.goto('https://passport.jd.com/new/login.aspx?appid=web-m&returnurl=https%3A%2F%2Fm.jd.com%2F', { waitUntil: 'domcontentloaded' }).catch(() => {});
  await page.waitForTimeout(3000);
  try { await page.locator('text=密码登录').first().click({ timeout: 3000 }); } catch (e) {}
  await page.waitForTimeout(1200);
  await page.click('#loginname').catch(() => {});
  await page.type('#loginname', PHONE, { delay: 80 });
  await page.click('#nloginpwd').catch(() => {});
  await page.type('#nloginpwd', PWD, { delay: 80 });
  await page.waitForTimeout(600);
  await page.focus('#nloginpwd').catch(() => {});
  await page.keyboard.press('Enter');
  console.log('[submit] Enter');

  // 等验证码(滑块 或 点选)
  let type = null;
  for (let w = 0; w < 25; w++) {
    await page.waitForTimeout(2000);
    const drag = await page.locator('.drag-box').count();
    if (drag > 0) { type = 'slide'; console.log('[type] 滑块'); break; }
    const t = await page.locator('body').innerText().catch(() => '');
    if (/请点击/.test(t)) { type = 'click'; console.log('[type] 点选'); break; }
  }
  if (!type) {
    const ck0 = await ctx.cookies('https://jd.com');
    const pk0 = ck0.find(c => c.name === 'pt_key');
    if (pk0 && pk0.value.length > 16) console.log('[type] 无需验证码');
    else { console.log('[fail] 未知验证类型'); await page.screenshot({ path: '/tmp/jdlogin/unknown.png' }); await browser.close(); process.exit(1); }
  }

  if (type === 'click') {
    // 读题目文字
    const hint = await page.evaluate(() => {
      const els = document.querySelectorAll('div,span,p');
      for (const e of els) {
        const t = (e.innerText || '').trim();
        if (/请点击/.test(t) && t.length < 40) return t;
      }
      return '';
    }).catch(() => '');
    console.log('[hint]', hint);

    // 验证码图片: 截弹窗区域
    const capSel = '[class*=captcha], [class*=verify], [class*=check], [id*=captcha]';
    let cap = page.locator(capSel).first();
    let box = null;
    if (await cap.count() > 0) box = await cap.boundingBox().catch(() => null);
    await page.screenshot({ path: '/tmp/jdlogin/cap_full.png' });
    console.log('[capbox]', JSON.stringify(box));

    // python 分析(传入题目+图)
    let pts = [];
    try {
      const out = run(`cd /tmp/jdlogin && python3 solve_click.py /tmp/jdlogin/cap_full.png "${hint.replace(/"/g, '')}" ${box ? Math.round(box.x) + ',' + Math.round(box.y) + ',' + Math.round(box.width) + ',' + Math.round(box.height) : '0,0,0,0'}`);
      console.log('[solve]', out.trim().slice(0, 400));
      const m = out.match(/POINTS=([\d,;\s]+)/);
      if (m) pts = m[1].trim().split(';').filter(Boolean).map(s => { const [x, y] = s.split(',').map(Number); return { x, y }; });
    } catch (e) { console.log('[solve err]', e.message); }

    if (!pts.length) { console.log('[fail] 没算出点击点'); await browser.close(); process.exit(1); }
    console.log('[points]', JSON.stringify(pts));
    for (const p of pts) {
      await page.mouse.click(p.x, p.y);
      await page.waitForTimeout(500);
    }
    try { await page.locator('text=确定').first().click({ timeout: 3000 }); console.log('[确定] clicked'); }
    catch (e) { try { await page.locator('button:has-text("确")').first().click({ timeout: 2000 }); } catch (e2) { console.log('[确定 warn]'); } }
  } else if (type === 'slide') {
    let sliderBox = null, btnBox = null;
    try {
      const db = page.locator('.drag-box').first();
      sliderBox = await db.boundingBox();
      const inner = await db.evaluate(el => {
        for (const k of el.querySelectorAll('*')) {
          const r = k.getBoundingClientRect();
          if (r.width > 15 && r.width < 90 && r.height > 10) return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
        }
        return null;
      }).catch(() => null);
      btnBox = inner;
    } catch (e) {}
    // 取背景图原图(base64, 不缩放) 用于精确算缺口
    let bgPath = '/tmp/jdlogin/slide_bg_orig.png';
    let origW = 320, dispW = 290, bgX = 105;
    try {
      const info = await page.evaluate(() => {
        const imgs = Array.from(document.querySelectorAll('img'));
        // 背景图: 显示宽在 200-400 且高>150
        for (const e of imgs) {
          const r = e.getBoundingClientRect();
          if (r.width > 200 && r.width < 420 && r.height > 120 && e.naturalWidth > 200) {
            return { src: e.src, natW: e.naturalWidth, dispW: Math.round(r.width), x: Math.round(r.x) };
          }
        }
        return null;
      });
      if (info && info.src.startsWith('data:')) {
        const b64 = info.src.split(',')[1];
        fs.writeFileSync(bgPath, Buffer.from(b64, 'base64'));
        origW = info.natW; dispW = info.dispW; bgX = info.x;
        console.log('[bg] orig saved natW=' + origW + ' dispW=' + dispW + ' x=' + bgX);
      } else {
        fs.copyFileSync('/tmp/jdlogin/slide_full.png', bgPath);
        console.log('[bg] fallback fullpage');
      }
    } catch (e) { console.log('[bg err]', e.message); fs.copyFileSync('/tmp/jdlogin/slide_full.png', bgPath); }

    const startX = btnBox ? (btnBox.x + btnBox.w / 2) : (sliderBox ? sliderBox.x + 20 : 100);
    const startY = btnBox ? (btnBox.y + btnBox.h / 2) : (sliderBox ? sliderBox.y + sliderBox.height / 2 : 500);
    let dist = null;
    try {
      const out = run(`cd /tmp/jdlogin && python3 calc_slide2.py ${bgPath} ${dispW} ${startX}`);
      console.log('[calc]', out.trim());
      const m = out.match(/DISTANCE=(\d+)/);
      if (m) dist = parseInt(m[1]);
    } catch (e) { console.log('[calc err]', e.message); }
    if (!dist || dist < 5) dist = Math.round(dispW * 0.65);
    console.log('[drag] dist=' + dist + ' (dispW=' + dispW + ')');
    console.log('[drag] dist=' + dist + ' from (' + startX + ',' + startY + ')');
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    for (let i = 1; i <= 30; i++) {
      await page.mouse.move(startX + (dist * i / 30), startY + Math.sin(i / 3) * 1.5);
      await page.waitForTimeout(25);
    }
    await page.waitForTimeout(300);
    await page.mouse.up();
    console.log('[drag] done');
  }

  // 等登录结果(若需短信验证码: 读 /tmp/jdlogin/sms.txt 填入)
  const SMS_FILE = '/tmp/jdlogin/sms.txt';
  let logged = false;
  let smsHandled = false;
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(2000);
    const cookies = await ctx.cookies('https://jd.com');
    const pk = cookies.find(c => c.name === 'pt_key');
    const pp = cookies.find(c => c.name === 'pt_pin');
    if (pk && pk.value && pk.value.length > 16 && !pk.value.startsWith('app_open') && pp && pp.value) {
      console.log('[ok] 登录成功 pin=' + pp.value);
      if (QL_DB) { const envId = findEnvIdByPin(pp.value); await backupDb(); writeCookie(envId || parseInt(process.env.QL_ENV_ID||'0'), pk.value, pp.value); }
      else console.log('[COOKIE] pt_key=' + pk.value + '; pt_pin=' + pp.value + ';');
      logged = true; break;
    }
    // 检测短信验证码页面并等待外部写入 sms.txt
    if (!smsHandled) {
      const t = await page.locator('body').innerText().catch(() => '');
      if (/短信|验证码/.test(t)) {
        // 找短信输入框
        const inputs = await page.locator('input[type="text"], input[type="tel"], input[type="number"], input[placeholder*="验证码"]').count();
        if (inputs > 0) {
          console.log('[sms] 等待验证码 -> 写入 ' + SMS_FILE);
          fs.writeFileSync('/tmp/jdlogin/sms_waiting', String(Date.now()));
          // 轮询文件
          for (let k = 0; k < 90; k++) {
            if (fs.existsSync(SMS_FILE)) {
              const code = fs.readFileSync(SMS_FILE, 'utf8').trim();
              if (code && /^\d{4,8}$/.test(code)) {
                console.log('[sms] 填入验证码 ' + code.replace(/\d/g, '*'));
                // 填所有可能的验证码输入框
                try {
                  const inp = page.locator('input[placeholder*="验证码"], input[type="tel"], input[type="number"]').first();
                  await inp.fill(code);
                  await page.waitForTimeout(500);
                  // 点确定/提交
                  for (const s of ['text=确定', 'text=提交', 'text=验证', 'button:has-text("确")', 'text=登录']) {
                    try { const el = page.locator(s).first(); if (await el.count() > 0) { await el.click({ timeout: 2500 }); console.log('[sms] clicked', s); break; } } catch (e) {}
                  }
                } catch (e) { console.log('[sms fill err]', e.message); }
                smsHandled = true;
                break;
              }
            }
            await page.waitForTimeout(2000);
          }
          if (!smsHandled) { console.log('[sms] 超时没拿到验证码'); break; }
        }
      }
    }
    if (i % 6 === 0) {
      const t = await page.locator('body').innerText().catch(() => '');
      const e2 = t.match(/(短信|手机号验证|验证码|错误|失败|频繁)/);
      if (e2) console.log('[page]', e2[0]);
    }
  }
  if (!logged) { console.log('[fail] 未登录'); await page.screenshot({ path: '/tmp/jdlogin/final.png' }); }
  await browser.close();
  console.log('[done]');
})().catch(e => { console.error('[FATAL]', e); process.exit(1); });
