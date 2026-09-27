// 京东 Cookie 安全录入页：仅写入本机青龙数据库，不发任何第三方
const http = require('http');
const https = require('https');
const fs = require('fs');
const { execSync } = require('child_process');

// wskey -> pt_key 转换(调 djun97 中继, wskey 仅此一跳到第三方换 token)
const CONVERT_URL = process.env.CONVERT_URL || 'https://wskey.djun97.top/convert';
function convertWskey(wsck) {
  // wsck: 'pin=xxx;wskey=yyy;' 或 'wskey=yyy;pin=xxx;'
  const body = JSON.stringify({ wsck });
  const u = new URL(CONVERT_URL);
  const opt = {
    method: 'POST',
    hostname: u.hostname, port: u.port || 443, path: u.pathname,
    headers: { 'Content-Type': 'application/json', 'User-Agent': 'JDHelper/1.0' }
  };
  return new Promise((resolve, reject) => {
    const req = https.request(opt, (res) => {
      let d = ''; res.on('data', c => d += c); res.on('end', () => {
        try { resolve(JSON.parse(d)); } catch (e) { reject(new Error('convert 返回解析失败: ' + d.slice(0, 120))); }
      });
    });
    req.on('error', reject);
    req.setTimeout(15000, () => req.destroy(new Error('convert 超时')));
    req.write(body); req.end();
  });
}
// 把 wskey 转成最终可用的 pt_key cookie; 失败抛错
async function wskeyToCookie(wsck) {
  const r = await convertWskey(wsck);
  if (!r || !r.success) throw new Error('convert 失败: ' + (r && r.message || '未知'));
  if (!r.cookie || !/pt_key=/.test(r.cookie)) throw new Error('convert 返回无 pt_key');
  return r.cookie;
}

const PORT = parseInt(process.env.PORT || '8899');
const QL_DB = process.env.QL_DB || '/root/docker/ql/data/db/database.sqlite';
const SQLITE = process.env.SQLITE || 'sqlite3';
const QQ_NOTIFY_URL = process.env.QQ_NOTIFY_URL || 'http://127.0.0.1:3000/send_private_msg';
const QQ_NOTIFY_TOKEN = process.env.QQ_NOTIFY_TOKEN || 'sg_qq_token_2026';
const QQ_USER = process.env.QQ_USER || '949194446';

let lastResult = { ts: '', msg: '' };

function log(...a) { console.log(new Date().toISOString().slice(11, 19), ...a); }

// 回传结果推 QQ(走 napcat)
function notifyQQ(text) {
  const body = JSON.stringify({ user_id: Number(QQ_USER), message: { type: 'text', data: { text } } });
  const u = new URL(QQ_NOTIFY_URL);
  const req = http.request({
    hostname: u.hostname, port: u.port || 80, path: u.pathname,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': QQ_NOTIFY_TOKEN }
  });
  req.on('error', e => log('[qq err]', e.message));
  req.write(body); req.end();
}

function qlEnvs() {
  try {
    return execSync(`${SQLITE} ${QL_DB} "SELECT id,name,value FROM Envs;"`, { encoding: 'utf-8' }).trim().split('\n').filter(Boolean).map(r => {
      const i = r.indexOf('|'); const j = r.indexOf('|', i + 1);
      return { id: r.slice(0, i), name: r.slice(i + 1, j), value: r.slice(j + 1) };
    });
  } catch (e) { return []; }
}

function writeCookie(cookie, realPin) {
  // cookie 形如 pt_key=...; pt_pin=...;  realPin: App 直传的真实 pin(用于 djun97 脱敏时回填)
  // djun97 把 pin 脱敏成 ***** 或 URL编码的 %2A%2A%2A%2A%2A%2A, 用 App 真实 pin 回填保证可匹配更新
  let decoded = decodeURIComponent(cookie);
  let m = decoded.match(/pt_pin=([^;]+)/);
  let pin = m ? m[1] : null;
  const masked = (!pin || /^\*+$/.test(pin) || /^%2A+$/i.test(pin || ''));
  if (masked && realPin) {
    pin = realPin;
    // 把脱敏的 pt_pin 段替换成真实 pin(兼容明文 ***** 与 %2A%2A%2A...)
    cookie = cookie.replace(/pt_pin=([^;]*)/, 'pt_pin=' + realPin);
  }
  if (!pin) throw new Error('cookie 中未找到 pt_pin');
  const envs = qlEnvs();
  const hit = envs.find(e => e.name === 'JD_COOKIE' && e.value.includes('pt_pin=' + pin));
  if (!hit) {
    // 找不到同 pin 的, 新建一条 JD_COOKIE（保留原 pin 落库, 不丢凭证）
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    execSync(`cp ${QL_DB} ${QL_DB}.bak_cookie_${ts}`);
    log('[backup]', `${QL_DB}.bak_cookie_${ts}`);
    // 取现有最大 id + 1
    const maxId = envs.reduce((mx, e) => Math.max(mx, parseInt(e.id) || 0), 0);
    const newId = maxId + 1;
    const now = new Date().toISOString().replace('T', ' ').slice(0, 19);
    execSync(`${SQLITE} ${QL_DB} "INSERT INTO Envs(id,name,value,status,remarks,createdAt,updatedAt) VALUES(${newId},'JD_COOKIE','${cookie.replace(/'/g, "''")}',1,'apk_recv','${now}','${now}');"`);
    log('[INSERT NEW] id=' + newId + ' pin=' + pin);
    return newId;
  }
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  execSync(`cp ${QL_DB} ${QL_DB}.bak_cookie_${ts}`);
  log('[backup]', `${QL_DB}.bak_cookie_${ts}`);
  execSync(`${SQLITE} ${QL_DB} "UPDATE Envs SET value='${cookie.replace(/'/g, "''")}' WHERE id=${hit.id};"`);
  return hit.id;
}

const HTML = `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>京东 Cookie 录入（仅本机）</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;background:#121212;color:#eee;max-width:680px;margin:0 auto;padding:16px}
h2{font-size:18px}
textarea,input{width:100%;box-sizing:border-box;font-size:14px;padding:10px;border-radius:6px;border:1px solid #444;background:#1e1e1e;color:#eee}
button{font-size:15px;padding:11px;margin-top:10px;border:0;border-radius:6px;background:#e1251b;color:#fff;font-weight:600;cursor:pointer;width:100%}
#status{margin-top:12px;padding:10px;border-radius:6px;background:#1e1e1e;font-size:14px;white-space:pre-wrap;word-break:break-all}
.ok{color:#4caf50}.err{color:#f44336}
.tip{font-size:13px;color:#999;line-height:1.7;margin-top:14px}
code{background:#222;padding:1px 5px;border-radius:3px;color:#ff9800}
</style></head><body>
<h2>京东 Cookie 录入</h2>
<p class="tip" style="color:#ff9800">⚠️ 本页只写入你自己的青龙数据库，<b>不会发往任何第三方服务器</b>。</p>
<textarea id="ck" rows="5" placeholder="粘贴京东 Cookie，形如：pt_key=AAJ...; pt_pin=949194446_m;"></textarea>
<button onclick="submitCk()">写入青龙</button>
<div id="status"></div>
<div class="tip">
<b>怎么拿 Cookie（在你自己手机/电脑，原生登录，验证码自己点）：</b><br>
1. 手机或电脑浏览器打开 <code>m.jd.com</code> 或 <code>jd.com</code>，登录京东<br>
2. 登录成功后在地址栏输入 <code>javascript:prompt('',document.cookie)</code> 复制全部 Cookie（手机可用「JS Box」类 App 或浏览器控制台）<br>
3. 把复制的内容粘贴到上面的框 → 点「写入青龙」<br>
（更简单的：电脑 Chrome 登录后按 F12 → Console 输入 <code>document.cookie.match(/pt_key=[^;]+|pt_pin=[^;]+/g).join('; ')</code> → 复制结果）
</div>
<script>
function submitCk(){
  const v=document.getElementById('ck').value.trim();
  const st=document.getElementById('status');
  if(!v||!/pt_key=/.test(v)){st.className='err';st.textContent='请输入包含 pt_key 的 Cookie';return;}
  st.className='';st.textContent='提交中…';
  fetch('/set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookie:v})})
    .then(r=>r.json()).then(j=>{
      st.className=j.ok?'ok':'err';
      st.textContent=(j.ok?'✅ ':'❌ ')+j.msg;
    }).catch(e=>{st.className='err';st.textContent='请求失败: '+e;});
}
function load(){fetch('/last').then(r=>r.json()).then(j=>{if(j.ts){const st=document.getElementById('status');if(!st.textContent){st.textContent=j.msg;}}});}
load();
</script></body></html>`;

const server = http.createServer((req, res) => {
  const send = (c, b, t) => { res.writeHead(c, { 'Content-Type': t || 'text/plain; charset=utf-8' }); res.end(b); };
  if (req.method === 'GET' && (req.url === '/' || req.url.startsWith('/?'))) return send(200, HTML, 'text/html; charset=utf-8');
  if (req.method === 'GET' && req.url.startsWith('/last')) return send(200, JSON.stringify(lastResult), 'application/json');
  if (req.method === 'POST' && (req.url === '/recv' || req.url === '/api/Doraemon/bigNai/wskey/service')) {
    let body = ''; req.on('data', c => body += c); req.on('end', async () => {
      try {
        const j = JSON.parse(body || '{}');
        // APK 提交体: {wskey, pin, full_ck, callback_id}
        const wskey = j.wskey || '';
        const pin = j.pin || '';
        let fullCk = j.full_ck || '';
        // 1) 优先用 App 直传的完整 ck(含 pt_key)
        let cookie = fullCk.trim();
        // 2) 只有 wskey 时: 现场转成 pt_key 再落库
        if (!/pt_key=/.test(cookie) && wskey && pin) {
          const wsck = `pin=${pin};wskey=${wskey};`;
          try {
            cookie = await wskeyToCookie(wsck);
            log('[conv] wskey->pt_key ok pin=' + pin);
          } catch (e) {
            lastResult = { ts: new Date().toISOString(), msg: '❌ [APK回传] wskey转pt_key失败: ' + e.message };
            log('[conv err]', e.message);
            notifyQQ('❌ 京东登录回传失败\nwskey转pt_key失败: ' + e.message + '\npin=' + pin);
            return send(200, JSON.stringify({ ok: false, msg: lastResult.msg }));
          }
        }
        if (!/pt_key=/.test(cookie)) { notifyQQ('❌ 京东登录回传失败\n未收到有效凭证(wskey/full_ck 均无效)'); return send(200, JSON.stringify({ ok: false, msg: 'recv: 未收到有效凭证' })); }
        const id = writeCookie(cookie, pin);
        const p = pin || (cookie.match(/pt_pin=([^;]+)/) || [])[1] || '';
        lastResult = { ts: new Date().toISOString(), msg: `✅ [APK回传] 已写入青龙 Envs.id=${id} pin=${p}` };
        log('[APK RECV] wskey=' + (wskey ? 'yes' : 'no') + ' pin=' + p);
        notifyQQ('✅ 京东登录回传成功\n已写入青龙 JD_COOKIE\npin=' + p + '\nenv_id=' + id);
        return send(200, JSON.stringify({ ok: true, msg: lastResult.msg }));
      } catch (e) {
        lastResult = { ts: new Date().toISOString(), msg: '❌ recv: ' + e.message };
        log('[recv err]', e.message);
        notifyQQ('❌ 京东登录回传异常\n' + e.message);
        return send(200, JSON.stringify({ ok: false, msg: e.message }));
      }
    });
    return;
  }
  if (req.method === 'POST' && req.url === '/convert') {
    let body = ''; req.on('data', c => body += c); req.on('end', async () => {
      try {
        const j = JSON.parse(body || '{}');
        // App convertWsck 期望: {wsck:"pin=..;wskey=..;"} -> {success,cookie,message}
        const wsck = j.wsck || '';
        if (!/wskey=/.test(wsck)) return send(200, JSON.stringify({ success: false, message: '缺少 wskey' }));
        const cookie = await wskeyToCookie(wsck);
        const pin = (cookie.match(/pt_pin=([^;]+)/) || [])[1] || '';
        lastResult = { ts: new Date().toISOString(), msg: `✅ [convert] pin=${pin}` };
        log('[convert ok] pin=' + pin);
        return send(200, JSON.stringify({ success: true, cookie, message: 'JD_WSCK转换成功' }));
      } catch (e) {
        lastResult = { ts: new Date().toISOString(), msg: '❌ convert: ' + e.message };
        log('[convert err]', e.message);
        return send(200, JSON.stringify({ success: false, cookie: '', message: e.message }));
      }
    });
    return;
  }
  if (req.method === 'POST' && req.url === '/set') {
    let body = ''; req.on('data', c => body += c); req.on('end', () => {
      try {
        const j = JSON.parse(body || '{}');
        const ck = j.cookie || '';
        if (!/pt_key=/.test(ck)) return send(400, JSON.stringify({ ok: false, msg: 'Cookie 缺少 pt_key' }));
        const cookie = ck.replace(/\s+/g, ' ').trim();
        const pin = (cookie.match(/pt_pin=([^;]+)/) || [])[1];
        const id = writeCookie(cookie, pin);
        lastResult = { ts: new Date().toISOString(), msg: `✅ 已写入青龙 Envs.id=${id} pin=${pin}` };
        log('[WRITE OK] id=' + id + ' pin=' + pin);
        return send(200, JSON.stringify({ ok: true, msg: lastResult.msg }));
      } catch (e) {
        lastResult = { ts: new Date().toISOString(), msg: '❌ ' + e.message };
        log('[err]', e.message);
        return send(200, JSON.stringify({ ok: false, msg: e.message }));
      }
    });
    return;
  }
  send(404, 'not found');
});

server.listen(PORT, '0.0.0.0', () => log('[server] http://0.0.0.0:' + PORT + ' (仅本机青龙)'));
