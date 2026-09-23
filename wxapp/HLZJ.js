// name: 海澜之家
// cron: 30 8,20 * * *

/**
 * 海澜之家 游戏签到（铛铛一下 code 服务适配版）
 *
 * 功能：
 *  - 通过铛铛一下四端口本地服务获取微信 code（替换原 8000 服务
 *  - 通过小程序 code 换取 unionId
 *  - 执行签到、电力、宝箱、投资等原版全部业务
 *  - 使用 hlzjcookie.json 缓存 token，避免重复登录
 *  - 品赞代理，业务请求优先代理，失败直连兜底
 *  - PushPlus 推送（替换原青龙 sendNotify）
 *
 * 依赖：仅需 axios（青龙已内置）
 * 环境变量：
 *   PLUSPLUS_TOKEN    PushPlus token，可选
 *   PROXY_API         品赞代理提取 API，可选
 *   PROXY_TYPE        http / socks5，默认 http
 *   YYB_SERVER        YYB Go 服务地址，格式：地址@微信账号标识，多账号换行分隔
 */

const axios = require('axios');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// ========== 配置 ==========
const HLZJ_APPID = 'wx315431cc3b5e930f';
const SERVERS = (() => {
    const raw = (process.env.YYB_SERVER || '').trim();
    const lines = raw.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    if (!lines.length) {
        console.log('❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识，多账号换行分隔）');
        process.exit(1);
    }
    console.log(`✅ 读取到 ${lines.length} 个 YYB Go 账号`);
    return lines;
})();

const PLUSPLUS_TOKEN = process.env.PLUSPLUS_TOKEN || '';
const PROXY_API = process.env.PROXY_API || '';
const PROXY_TYPE = (process.env.PROXY_TYPE || 'http').toLowerCase();

const PROXY_RETRY_TIMES = 3;
const PROXY_VALIDATE_URL = 'http://httpbin.org/ip';
const ENABLE_DIRECT_FALLBACK = true;
const REQUEST_TIMEOUT = 30000;

const CONVERT_URL = 'https://wxa-tp.ezrpro.com/myvip/Base/User/WxAppOnLoginNew';
const BASE_URL = 'https://gmdevpro.hlzjppgl.cn';
const COOKIE_FILE = path.join(__dirname, 'hlzjcookie.json');
const SIGNATURE_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';

// 通用工具
const randomUA = () => {
    const list = [
        'Mozilla/5.0 (Linux; Android 13; SM-S9080 Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40',
    ];
    return list[Math.floor(Math.random() * list.length)];
};
const randomWait = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const md5 = str => crypto.createHash('md5').update(str).digest('hex');
const generateNonce = (len = 20) => {
    let s = '';
    for (let i = 0; i < len; i++) s += SIGNATURE_CHARS[Math.floor(Math.random() * SIGNATURE_CHARS.length)];
    return s;
};
const generatePingId = () => {
    let s = '';
    for (let i = 0; i < 32; i++) s += SIGNATURE_CHARS[Math.floor(Math.random() * SIGNATURE_CHARS.length)];
    return s;
};
const getPingDate = () => {
    const d = new Date();
    const pad = n => n.toString().padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};
const nowText = () => {
    const d = new Date();
    const pad = n => n.toString().padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};
const jsonPreview = (data, limit = 800) => {
    try { return JSON.stringify(data).slice(0, limit); } catch { return String(data).slice(0, limit); }
};

// 缓存读写
let cookieStore = {};
const loadCookie = () => {
    try { if (fs.existsSync(COOKIE_FILE)) cookieStore = JSON.parse(fs.readFileSync(COOKIE_FILE, 'utf8')); }
    catch { cookieStore = {}; }
};
const saveCookie = () => fs.writeFileSync(COOKIE_FILE, JSON.stringify(cookieStore, null, 2));

// ========== 品赞代理（移植自铛铛一下） ==========
const directAxios = async (config) => {
    const agent = axios.create({});
    agent.defaults.proxy = false;
    return agent(config);
};

const parseProxyResponse = (text) => {
    if (typeof text !== 'string') {
        try { text = JSON.stringify(text); } catch { text = String(text); }
    }
    text = (text || '').trim();
    if (!text) return null;
    try {
        const data = JSON.parse(text);
        let proxyObj = null;
        if (Array.isArray(data.data) && data.data.length) proxyObj = data.data[0];
        else if (data.data && typeof data.data === 'object') proxyObj = data.data;
        else if (data.ip && data.port) proxyObj = data;
        else if (data.result && typeof data.result === 'object') proxyObj = data.result;
        if (proxyObj) {
            const host = proxyObj.ip || proxyObj.host;
            const port = proxyObj.port;
            if (host && port) {
                return {
                    host: String(host),
                    port: parseInt(port, 10),
                    username: proxyObj.user || proxyObj.username || '',
                    password: proxyObj.pass || proxyObj.password || '',
                };
            }
        }
    } catch (e) {}
    if (text.includes(':')) {
        const parts = text.split(':');
        if (parts.length >= 2) {
            return {
                host: parts[0],
                port: parseInt(parts[1], 10),
                username: parts[2] || '',
                password: parts[3] || '',
            };
        }
    }
    return null;
};

const buildProxyConfig = (proxyInfo) => {
    if (!proxyInfo) return null;
    const host = proxyInfo.host;
    const port = proxyInfo.port;
    const username = proxyInfo.username || '';
    const password = proxyInfo.password || '';
    const scheme = PROXY_TYPE === 'socks5' ? 'socks5' : 'http';
    console.log(`🛠️ [代理] 生成 ${scheme.toUpperCase()} 代理 ${host}:${port}`);
    return {
        protocol: `${scheme}:`,
        host,
        port: parseInt(port, 10),
        auth: (username && password) ? { username, password } : undefined,
    };
};

const validateProxy = async (proxyConfig) => {
    if (!proxyConfig) return { ok: false, ip: '' };
    try {
        const resp = await axios.get(PROXY_VALIDATE_URL, { proxy: proxyConfig, timeout: 15000 });
        const ip = (resp.data && resp.data.origin) || '未知';
        console.log(`✅ [代理] 验证通过，出口 IP: ${ip}`);
        return { ok: true, ip };
    } catch (e) {
        console.log(`⚠️ [代理] 验证失败: ${e.message}`);
        return { ok: false, ip: '' };
    }
};

const getValidProxy = async (accountName) => {
    if (!PROXY_API) {
        console.log(`⚠️ [代理] ${accountName} 未配置 PROXY_API，使用直连`);
        return { proxyConfig: null, ip: '' };
    }
    console.log(`🌐 [代理] ${accountName} 正在获取品赞代理...`);
    for (let i = 1; i <= PROXY_RETRY_TIMES; i++) {
        try {
            const resp = await directAxios({ method: 'GET', url: PROXY_API, timeout: 15000 });
            const proxyInfo = parseProxyResponse(resp.data);
            if (!proxyInfo) { console.log(`⚠️ [代理] 第 ${i} 次代理解析失败`); continue; }
            console.log(`✅ [代理] 提取到 ${proxyInfo.host}:${proxyInfo.port}`);
            const proxyConfig = buildProxyConfig(proxyInfo);
            const { ok, ip } = await validateProxy(proxyConfig);
            if (ok) return { proxyConfig, ip };
            console.log(`⚠️ [代理] 第 ${i} 次代理不可用`);
        } catch (e) {
            console.log(`⚠️ [代理] 第 ${i} 次获取代理异常: ${e.message}`);
        }
        if (i < PROXY_RETRY_TIMES) await wait(2000);
    }
    console.log('⚠️ [代理] 获取失败，使用直连');
    return { proxyConfig: null, ip: '' };
};

const requestWithProxy = async (config, proxyConfig, server = '') => {
    const cfg = { ...config, timeout: config.timeout || REQUEST_TIMEOUT };
    if (proxyConfig) {
        try {
            return await axios({ ...cfg, proxy: proxyConfig });
        } catch (e) {
            console.log(`⚠️ [代理] ${server} 代理请求失败: ${e.message}`);
            if (!ENABLE_DIRECT_FALLBACK) throw e;
            console.log('🔁 [兜底] 切换直连重试');
        }
    }
    return directAxios(cfg);
};

// ========== PushPlus 推送（移植自铛铛一下，替换原 Env.sendNotify） ==========
const sendPushPlus = async (title, content) => {
    if (!PLUSPLUS_TOKEN) { console.log('⚠️ [PushPlus] 未配置 PLUSPLUS_TOKEN，跳过推送'); return; }
    try {
        await axios.post('https://www.pushplus.plus/send', {
            token: PLUSPLUS_TOKEN,
            title,
            content,
            template: 'txt',
        }, { timeout: 10000 });
        console.log('✅ [PushPlus] 推送成功');
    } catch (e) {
        console.log(`❌ [PushPlus] 推送失败: ${e.message}`);
    }
};

// ========== 铛铛一下四端口本地 code 服务（替换原 8000 服务） ==========
const parseYybEntry = (raw) => {
    raw = raw.trim();
    if (!raw.includes('@')) {
        console.log(`❌ YYB_SERVER 格式应为 地址@微信账号标识，当前值：${raw}`);
        return { server: '', ref: '' };
    }
    const [server, ref] = raw.split('@', 2);
    const s = server.trim().replace(/^https?:\/\//, '').replace(/\/+$/, '');
    const r = ref.trim();
    if (!s || !r) {
        console.log(`❌ YYB_SERVER 缺少地址或微信账号标识，当前值：${raw}`);
        return { server: '', ref: '' };
    }
    return { server: s, ref: r };
};

const getCode = async (entry) => {
    const { server, ref } = parseYybEntry(entry);
    if (!server || !ref) return null;
    const url = `http://${server}/wxapp/getCode`;
    console.log(`🔐 [授权] 请求 YYB Go 取码: ${url}`);
    try {
        const resp = await directAxios({ method: 'POST', url, data: { ref, app_id: HLZJ_APPID }, timeout: 20000 });
        const data = resp.data;
        const code = ((data.data || {}).result || {}).code;
        if (data.code !== 0 || !code) {
            console.log(`❌ [授权] 取码失败: ${jsonPreview(data)}`);
            return null;
        }
        console.log('✅ [授权] 取码成功');
        return code;
    } catch (e) {
        console.log(`❌ [授权] 取码异常: ${e.message}`);
        return null;
    }
};

// ========== code 转 unionId ==========
const codeToUnionId = async (code, proxyConfig, server) => {
    const headers = {
        Host: 'wxa-tp.ezrpro.com',
        'Content-Type': 'application/json',
        'ezr-sp': '2',
        'ezr-source': 'weapp',
        'ezr-brand-id': '5896',
        'uber-trace-id': `${generateNonce(16)}:${generateNonce(16)}:0:1`,
        'ezr-client-name': 'EZR.FE.MultiMall.Mini',
        Referer: 'https://servicewechat.com/wx315431cc3b5e930f/38/page-frame.html',
        'User-Agent': randomUA(),
        'Accept-Encoding': 'gzip, deflate, br',
        charset: 'utf-8'
    };
    const payload = {
        code,
        CommonIdType: '',
        CommonId: '',
        ShopId: 0,
        CommonIdSource: 0,
        Latitude: 0,
        Longitude: 0,
        PingId: generatePingId(),
        PingDate: getPingDate()
    };
    const resp = await requestWithProxy({ method: 'POST', url: CONVERT_URL, headers, data: payload }, proxyConfig, server);
    const data = resp.data;
    if (!data.Success) throw new Error(`code换unionId失败: ${data.Msg}`);
    return {
        unionId: data.Result.UnionId,
        openId: data.Result.OpenId,
        sessionId: data.Result.SessionId,
        signStr: data.Result.SignStr
    };
};

// ========== 游戏业务接口（带签名，含品赞代理） ==========
const createSignedBody = (data, userId) => {
    const nonce = generateNonce();
    const timestamp = Date.now().toString();
    return { ...data, nonce, timestamp, sign: md5(`ff${nonce}nn${timestamp}${userId}mm`) };
};

const currentProxyConfig = () => cookieStore.current?.proxyConfig || null;

const bizRequest = async (url, method, extraHeaders = {}, bodyData = {}, userId = '') => {
    const headers = {
        Host: 'gmdevpro.hlzjppgl.cn',
        'Content-Type': 'application/json',
        Accept: '*/*',
        Origin: 'https://gmdevpro.hlzjppgl.cn',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'User-Agent': randomUA(),
        ...extraHeaders
    };
    if (cookieStore.current?.authorization) headers.Authorization = cookieStore.current.authorization;
    const data = /^(post|put)$/i.test(method) ? createSignedBody(bodyData, userId) : bodyData;
    const resp = await requestWithProxy({ method, url, headers, data }, currentProxyConfig(), cookieStore.current?.server || '');
    return resp.data;
};

const authorizedLogin = async (unionId, inviteUserId = '78630') => {
    const res = await bizRequest(`${BASE_URL}/server/api/authorized-login`, 'post', {},
        { union_id: unionId, invite_user_id: inviteUserId });
    if (res.code !== 200) throw new Error(`授权登录失败: ${res.message}`);
    return res.data;
};

// ========== 业务函数（完整保留） ==========
const getUserInfo = async () => {
    const res = await bizRequest(`${BASE_URL}/server/api/authorized-login`, 'post', {},
        { union_id: cookieStore.current.unionId, invite_user_id: '78630' }, cookieStore.current.userId);
    if (res.code !== 200) throw new Error(res.message);
    cookieStore.current.authorization = `Bearer ${res.data.token}`;
    cookieStore.current.userId = res.data.user_info.id;
    cookieStore.current.treeId = res.data.user_info.tree_id;
    saveCookie();
    console.log(`${res.data.user_info.nick_name}(${res.data.user_info.user_no})`);
    return res.data.user_info;
};

const getDayList = async () => {
    const res = await bizRequest(`${BASE_URL}/server/api/day-list`, 'post', {}, {}, cookieStore.current.userId);
    if (res.code !== 200) return console.error(res.message);
    if (res.data.day_sign_status) {
        console.log('今日已签到！');
        return;
    }
    console.log('开始签到');
    await wait(randomWait(1000, 1500));
    await signIn();
};

const signIn = async () => {
    const res = await bizRequest(`${BASE_URL}/server/api/day-sign`, 'post', {}, {}, cookieStore.current.userId);
    if (res.code !== 200) return console.error(res.message);
    console.log(`签到成功！电力 X${res.data.water_num}\n已连续签到${res.data.day_sign_list.day_num}天`);
};

const getTodayWater = async () => {
    const res = await bizRequest(`${BASE_URL}/server/api/user/get-today-water`, 'post', {}, {}, cookieStore.current.userId);
    if (res.code !== 200) {
        console.log('今日电力奖励已领取');
        return;
    }
    console.log(`已领取今日电力奖励：${res.data.get_water}\n明日可领${res.data.tomorrow_get_water_num}电力`);
};

const joinPower = async () => {
    let res = await bizRequest(`${BASE_URL}/server/api/game/use-power`, 'post', {},
        { num: 1, user_tree_id: cookieStore.current.treeId }, cookieStore.current.userId);
    if (res.code === 309) {
        const login = await authorizedLogin(cookieStore.current.unionId, '');
        cookieStore.current.treeId = login.user_info.tree_id;
        cookieStore.current.authorization = `Bearer ${login.token}`;
        cookieStore.current.userId = login.user_info.id;
        saveCookie();
        res = await bizRequest(`${BASE_URL}/server/api/game/use-power`, 'post', {},
            { num: 1, user_tree_id: cookieStore.current.treeId }, cookieStore.current.userId);
    }
    if (res.code !== 200) return console.error(`加入电力失败: ${res.message}`);
    let energy = res.data.info.sy_water;
    let joins = res.data.user_tree.send_water;
    console.log(`当前电力：${energy}，可加入次数：${joins}`);
    while (joins > 0) {
        await wait(randomWait(1200, 1800));
        const sub = await bizRequest(`${BASE_URL}/server/api/game/use-power`, 'post', {},
            { num: 1, user_tree_id: cookieStore.current.treeId }, cookieStore.current.userId);
        if (sub.code === 309) {
            const login = await authorizedLogin(cookieStore.current.unionId, '');
            cookieStore.current.treeId = login.user_info.tree_id;
            cookieStore.current.authorization = `Bearer ${login.token}`;
            cookieStore.current.userId = login.user_info.id;
            saveCookie();
            continue;
        }
        if (sub.code !== 200) break;
        energy = sub.data.info.sy_water;
        joins = sub.data.user_tree.send_water;
        console.log(`当前电力：${energy}，可加入次数：${joins}`);
    }
    await wait(randomWait(1000, 1500));
    console.log('开始领取宝箱...');
    await receiveBox();
};

const receiveBox = async () => {
    const res = await bizRequest(`${BASE_URL}/server/api/game/receive-box`, 'post', {}, {}, cookieStore.current.userId);
    if (res.code !== 200) return console.error(`领取宝箱失败: ${res.message}`);
    console.log(`领取宝箱成功！电力 X${res.data.add_water}`);
};

const chooseInvest = async () => {
    console.log('开始投资任务，默认选择最小投资');
    const res = await bizRequest(`${BASE_URL}/server/api/power/choose-invest`, 'post', {},
        { condition: 'min' }, cookieStore.current.userId);
    if (res.code !== 200) return console.error(`选择投资失败: ${res.message}`);
    console.log('选择最小投资成功');
};

const receiveInvest = async () => {
    const res = await bizRequest(`${BASE_URL}/server/api/power/receive-invest`, 'post', {}, {}, cookieStore.current.userId);
    if (res.code !== 200) return console.error(`领取投资失败: ${res.message}`);
    console.log(`领取投资成功！获得电力X${res.data.add_power_num}`);
};

// ========== 单账号执行 ==========
const runAccount = async (index, total, server) => {
    const result = {
        server,
        success: false,
        proxyStatus: '未使用代理',
        proxyIp: '-',
        loginMsg: '-',
        signMsg: '-',
        powerMsg: '-',
        boxMsg: '-',
        error: '',
    };

    console.log(`\n┌${'─'.repeat(50)}┐`);
    console.log(`│ 🧩 账号 ${index} / ${total}`.padEnd(54) + '│');
    console.log(`│ 🌍 来源 ${server}`.padEnd(54) + '│');
    console.log(`└${'─'.repeat(50)}┘`);

    if (!cookieStore[server]) cookieStore[server] = {};
    cookieStore.current = cookieStore[server];
    cookieStore.current.server = server;

    try {
        const { proxyConfig, ip } = await getValidProxy(server);
        cookieStore.current.proxyConfig = proxyConfig;
        cookieStore.current.proxyIp = ip;
        result.proxyStatus = proxyConfig ? '使用专属代理' : '使用直连';
        result.proxyIp = ip || '-';
        await wait(3000);
        const delay = Math.floor(Math.random() * 5) + 2;
        console.log(`⏳ [延迟] 启动延迟 ${delay}s`);
        await wait(delay * 1000);

        if (!cookieStore.current.authorization) {
            console.log('缓存未命中，开始微信登录...');
            const code = await getCode(server);
            if (!code) { result.error = '获取 code 失败'; return result; }
            console.log(`获取到 code: ${code.substring(0, 10)}...`);
            const unionInfo = await codeToUnionId(code, proxyConfig, server);
            console.log(`获取到 unionId: ${unionInfo.unionId}`);
            cookieStore.current.unionId = unionInfo.unionId;
            const loginData = await authorizedLogin(unionInfo.unionId);
            cookieStore.current.authorization = `Bearer ${loginData.token}`;
            cookieStore.current.userId = loginData.user_info.id;
            cookieStore.current.treeId = loginData.user_info.tree_id;
            saveCookie();
            console.log('游戏登录成功，token已缓存');
            result.loginMsg = '登录成功';
        } else {
            result.loginMsg = '缓存命中';
        }

        await getUserInfo();
        result.signMsg = `昵称:${cookieStore.current.userId || '未知'}`;

        await wait(randomWait(2000, 3000));
        await getTodayWater();
        await wait(randomWait(2000, 3000));
        await getDayList();
        result.signMsg += ' 签到完成';
        await wait(randomWait(2000, 3000));

        await joinPower();
        result.powerMsg = '电力任务完成';
        result.boxMsg = '宝箱已处理';

        result.success = true;
        return result;
    } catch (e) {
        console.error(`账号 ${server} 执行异常: ${e.message}`);
        delete cookieStore[server];
        saveCookie();
        result.error = e.message;
        return result;
    }
};

const buildNotify = (results) => {
    const successCount = results.filter(r => r.success).length;
    const failCount = results.length - successCount;
    let content = `🌍 海澜之家游戏任务结果\n\n━━━━━━━━━━━━━━━━━━━━\n🏁 总结：${successCount} 成功 / ${failCount} 失败\n🕒 时间：${nowText()}\n━━━━━━━━━━━━━━━━━━━━\n`;
    results.forEach((res, idx) => {
        const icon = res.success ? '✅' : '❌';
        content += `\n🧩 账号 ${idx + 1}\n🌍 来源：${res.server}\n🌐 代理：${res.proxyStatus}\n📡 出口IP：${res.proxyIp}\n🔐 登录：${res.loginMsg}\n📝 签到：${res.signMsg}\n⚡ 电力：${res.powerMsg}\n🎁 宝箱：${res.boxMsg}\n${icon} 结果：${res.success ? '成功' : '失败'}\n`;
        if (!res.success) content += `❌ 原因：${res.error}\n`;
        content += '━━━━━━━━━━━━━━━━━━━━\n';
    });
    return content;
};

// ========== 主流程 ==========
!(async () => {
    console.log(`\n╔${'═'.repeat(50)}╗`);
    console.log('║ 🌍 海澜之家游戏 铛铛一下 code 服务版        ║');
    console.log(`║ 🕒 启动时间: ${nowText()}`.padEnd(54) + '║');
    console.log(`║ 🔢 账号数量: ${SERVERS.length}`.padEnd(54) + '║');
    console.log(`╚${'═'.repeat(50)}╝`);

    loadCookie();

    const results = [];
    for (let i = 0; i < SERVERS.length; i++) {
        const result = await runAccount(i + 1, SERVERS.length, SERVERS[i]);
        results.push(result);
        if (i < SERVERS.length - 1) {
            console.log('⏳ [间隔] 等待 2s 后处理下一个账号');
            await wait(2000);
        }
    }

    const successCount = results.filter(r => r.success).length;
    const failCount = results.length - successCount;
    console.log(`\n╔${'═'.repeat(50)}╗`);
    console.log('║ 🏁 海澜之家任务执行完成                     ║');
    console.log(`║ ✅ 成功: ${successCount}`.padEnd(54) + '║');
    console.log(`║ ❌ 失败: ${failCount}`.padEnd(54) + '║');
    console.log(`║ 🕒 结束时间: ${nowText()}`.padEnd(54) + '║');
    console.log(`╚${'═'.repeat(50)}╝`);

    await sendPushPlus('🌍 海澜之家游戏任务完成', buildNotify(results));
})().catch(e => console.error(`❌ [主流程] 异常: ${e.message}`));