// 京东 Cookie 安全录入页：仅写入本机青龙数据库，不发任何第三方
const http = require('http');
const fs = require('fs');
const { execSync } = require('child_process');

const PORT = parseInt(process.env.PORT || '8899');
const QL_DB = process.env.QL_DB || '/root/docker/ql/data/db/database.sqlite';
const SQLITE = process.env.SQLITE || 'sqlite3';

let lastResult = { ts: '', msg: '' };

function log(...a) { console.log(new Date().toISOString().slice(11, 19), ...a); }

function qlEnvs() {
  try {
    return execSync(`${SQLITE} ${QL_DB} "SELECT id,name,value FROM Envs;"`, { encoding: 'utf-8' }).trim().split('\n').filter(Boolean).map(r => {
      const i = r.indexOf('|'); const j = r.indexOf('|', i + 1);
      return { id: r.slice(0, i), name: r.slice(i + 1, j), value: r.slice(j + 1) };
    });
  } catch (e) { return []; }
}

function writeCookie(cookie) {
  // cookie 形如 pt_key=...; pt_pin=...;
  const m = cookie.match(/pt_pin=([^;]+)/);
  const pin = m ? decodeURIComponent(m[1]) : null;
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
    execSync(`${SQLITE} ${QL_DB} "INSERT INTO Envs(id,name,value,status,remarks) VALUES(${newId},'JD_COOKIE','${cookie.replace(/'/g, "''")}',1,'apk_recv');"`);
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
    let body = ''; req.on('data', c => body += c); req.on('end', () => {
      try {
        const j = JSON.parse(body || '{}');
        // APK 提交体: {wskey, pin, full_ck, callback_id}
        const wskey = j.wskey || '';
        const pin = j.pin || '';
        const fullCk = j.full_ck || '';
        let cookie = fullCk.trim();
        if (!cookie && wskey && pin) cookie = `wskey=${wskey};pin=${pin};`;
        if (!/pt_key=|wskey=/.test(cookie)) return send(200, JSON.stringify({ ok: false, msg: 'recv: 未收到有效凭证' }));
        const id = writeCookie(cookie);
        const p = (cookie.match(/pt_pin=([^;]+)/) || [])[1] || pin;
        lastResult = { ts: new Date().toISOString(), msg: `✅ [APK回传] 已写入青龙 Envs.id=${id} pin=${p}` };
        log('[APK RECV] wskey=' + (wskey ? 'yes' : 'no') + ' pin=' + p);
        return send(200, JSON.stringify({ ok: true, msg: lastResult.msg }));
      } catch (e) {
        lastResult = { ts: new Date().toISOString(), msg: '❌ recv: ' + e.message };
        log('[recv err]', e.message);
        return send(200, JSON.stringify({ ok: false, msg: e.message }));
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
        const id = writeCookie(cookie);
        const pin = (cookie.match(/pt_pin=([^;]+)/) || [])[1];
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
