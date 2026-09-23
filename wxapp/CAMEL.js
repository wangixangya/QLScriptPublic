// name: CAMEL骆驼签到
// cron: 18 8,20 * * *
// 青龙环境变量：YYB_SERVER=YYB地址@微信账号标识（多账号换行）
// 可选调试环境变量：CAMEL_TOKEN=accessToken[@sessionId][@kdtId]
// 说明：有赞小程序签到，使用 YYB Go 获取 wx code 后走有赞 authorize 登录。

const fs = require("fs");
const path = require("path");

let notify;
try { notify = require("./sendNotify"); } catch (_) { try { notify = require("sendNotify"); } catch (__) { notify = null; } }
let axios = null;
try { axios = require("axios"); } catch (_) {}

// ====================== 小程序配置（first-miniapp 抓取） ======================
const APP_NAME = "CAMEL骆驼";
const MINI_APP_ID = "wxa82836302320ca29";
const CLIENT_BIZ = "weapp_wsc";
// 当前商城/签到页上下文 kdt_id；首页总部 kdt_id 为 150703152，签到接口两者均可返回活动，优先使用商城 182479100
const DEFAULT_KDT_ID = "182479100";
const FALLBACK_CHECKIN_ID = "5540097";
const USER_VERSION = "3.197.5.102";
const PAGE_VERSION = "32";
const API_BASE = "https://h5.youzan.com";
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "camel_token_cache.json");

const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823";

try { fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true }); } catch (_) {}

const YYB_SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);

const DIRECT_TOKENS = (process.env.CAMEL_TOKEN || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function rand(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }
function mask(v = "") { v = String(v); return v.length <= 12 ? v : v.slice(0, 6) + "..." + v.slice(-6); }
function maskPhone(phone = "") { return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2"); }

function parseYybGoEntry(rawValue) {
    const value = String(rawValue || "").trim();
    const atIndex = value.indexOf("@");
    if (atIndex === -1) return { server: "", ref: "" };
    let server = value.slice(0, atIndex).trim();
    const ref = value.slice(atIndex + 1).trim();
    if (server.startsWith("http://")) server = server.slice(7);
    if (server.startsWith("https://")) server = server.slice(8);
    server = server.replace(/\/+$/, "");
    return { server, ref };
}

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch (_) { return {}; }
}

function writeTokenCache(cache) {
    try { fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8"); }
    catch (e) { console.log(`写入 token 缓存失败：${e.message || e}`); }
}

function pickToken(data = {}) { return data.accessToken || data.access_token || data.token || ""; }

function parseSetCookie(headers) {
    if (!headers) return "";
    let cookies = [];
    if (typeof headers.getSetCookie === "function") cookies = headers.getSetCookie();
    if (!cookies.length) {
        const one = headers.get && headers.get("set-cookie");
        if (one) cookies = one.split(/,(?=\s*[^;,=]+=[^;,]+)/g);
    }
    return cookies.map(s => String(s).split(";")[0].trim()).filter(Boolean).join("; ");
}

async function httpRequest(url, options = {}) {
    const timeout = options.timeout || 20000;
    if (typeof fetch === "function") {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), timeout);
        try {
            const res = await fetch(url, { ...options, signal: ctrl.signal });
            const text = await res.text();
            let data;
            try { data = JSON.parse(text); } catch (_) { data = text; }
            return { status: res.status, headers: res.headers, data, text };
        } finally { clearTimeout(timer); }
    }

    if (!axios) throw new Error("Current Node.js has no fetch and axios is not installed. Install axios in QingLong dependencies or upgrade Node.js.");
    let body = options.body;
    if (typeof body === "string" && /^\s*[\[{]/.test(body)) {
        try { body = JSON.parse(body); } catch (_) {}
    }
    const res = await axios.request({
        url,
        method: options.method || "GET",
        headers: options.headers || {},
        data: body,
        timeout,
        validateStatus: () => true,
        proxy: false,
    });
    const data = res.data;
    const text = typeof data === "string" ? data : JSON.stringify(data);
    const headers = {
        getSetCookie: () => {
            const c = res.headers && res.headers["set-cookie"];
            return Array.isArray(c) ? c : (c ? [c] : []);
        },
        get: (name) => res.headers && res.headers[String(name).toLowerCase()],
    };
    return { status: res.status, headers, data, text };
}

async function getCode(entry) {
    const { server, ref } = parseYybGoEntry(entry);
    if (!server || !ref) throw new Error(`YYB_SERVER 格式错误：${entry}，应为 地址@微信账号标识`);
    const url = `http://${server}/wxapp/getCode`;
    const { data, status } = await httpRequest(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref, app_id: MINI_APP_ID }),
        timeout: 25000,
    });
    const code = data?.data?.result?.code || data?.data?.code || data?.result?.code;
    if (status !== 200 || Number(data?.code) !== 0 || !code) throw new Error(`获取 code 失败：${JSON.stringify(data).slice(0, 300)}`);
    console.log(`  [YYB] ${server} 获取 code 成功`);
    return code;
}

let userIdx = 1;

class Task {
    constructor(entry, mode = "yyb") {
        this.entry = entry;
        this.mode = mode;
        this.index = userIdx++;
        this.ref = mode === "yyb" ? parseYybGoEntry(entry).ref : `direct_${this.index}`;
        this.cacheKey = this.ref || entry;
        this.token = "";
        this.sessionId = "";
        this.cookie = "";
        this.kdtId = DEFAULT_KDT_ID;
        this.userInfo = {};
        this.checkinId = FALLBACK_CHECKIN_ID;
        this.logs = [];
    }

    log(msg) {
        const line = `账号[${this.index}] ${msg}`;
        this.logs.push(line);
        console.log(line);
    }

    applyToken(data = {}) {
        this.token = pickToken(data);
        this.sessionId = data.sessionId || data.session_id || this.sessionId || "";
        // 登录返回的 kdtId 可能是总部 150703152；签到页实际商城为 182479100，所以默认不被空值覆盖
        this.kdtId = String(data.kdtId || data.kdt_id || this.kdtId || DEFAULT_KDT_ID);
        this.cookie = data.cookie || this.cookie || "";
        if (this.sessionId && !/KDTWEAPPSESSIONID=/.test(this.cookie)) {
            this.cookie = [this.cookie, `KDTSESSIONID=${this.sessionId}`, `KDTWEAPPSESSIONID=${this.sessionId}`, `_kdt_id_=${this.kdtId}`]
                .filter(Boolean).join("; ");
        }
    }

    getCachedToken() { return readTokenCache()[this.cacheKey] || null; }

    saveCachedToken() {
        if (!this.token) return;
        const cache = readTokenCache();
        cache[this.cacheKey] = {
            accessToken: this.token,
            sessionId: this.sessionId,
            kdtId: this.kdtId,
            cookie: this.cookie,
            mobile: this.userInfo.mobile || "",
            nickName: this.userInfo.nick_name || this.userInfo.nickName || "",
            updatedAt: new Date().toISOString(),
        };
        writeTokenCache(cache);
    }

    removeCachedToken() {
        const cache = readTokenCache();
        if (cache[this.cacheKey]) {
            delete cache[this.cacheKey];
            writeTokenCache(cache);
        }
        this.token = "";
        this.sessionId = "";
        this.cookie = "";
    }

    getHeaders(extra = {}) {
        const headers = {
            "User-Agent": USER_AGENT,
            "Referer": `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            "Accept": "*/*",
            "Extra-Data": JSON.stringify({
                sid: this.sessionId || "",
                version: USER_VERSION,
                clientType: "weapp-miniprogram",
                client: "weapp",
                bizEnv: "wsc",
            }),
            ...extra,
        };
        if (this.cookie) headers.Cookie = this.cookie;
        return headers;
    }

    buildUrl(apiPath, params = {}, skipToken = false) {
        const url = new URL(apiPath.startsWith("http") ? apiPath : `${API_BASE}${apiPath.startsWith("/") ? apiPath : "/" + apiPath}`);
        const merged = skipToken ? params : { app_id: MINI_APP_ID, kdt_id: this.kdtId, access_token: this.token, ...params };
        for (const [k, v] of Object.entries(merged)) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
        return url.toString();
    }

    async request({ method = "GET", path: apiPath, params = {}, data = {}, skipToken = false }) {
        const isPost = method.toUpperCase() !== "GET";
        const headers = this.getHeaders(isPost ? { "Content-Type": "application/json" } : {});
        const url = this.buildUrl(apiPath, params, skipToken);
        const res = await httpRequest(url, {
            method,
            headers,
            body: isPost ? JSON.stringify(data || {}) : undefined,
            timeout: 20000,
        });
        const newCookie = parseSetCookie(res.headers);
        if (newCookie) this.cookie = [this.cookie, newCookie].filter(Boolean).join("; ");
        if (res.status !== 200) throw new Error(`HTTP ${res.status}: ${String(res.text).slice(0, 300)}`);
        const result = res.data;
        if (!result || Number(result.code) !== 0) throw new Error(result?.msg || JSON.stringify(result).slice(0, 300));
        return result.data;
    }

    async loginByWxCode() {
        const code = await getCode(this.entry);
        const data = await this.request({
            method: "POST",
            path: "/wscshop/weapp/authorize.json",
            skipToken: true,
            data: { appId: MINI_APP_ID, clientBiz: CLIENT_BIZ, code },
        });
        this.applyToken(data);
        this.userInfo = data || {};
        this.saveCachedToken();
        this.log(`登录成功：${data.nick_name || data.nickName || ""} ${maskPhone(data.mobile || "")} token=${mask(this.token)}`);
    }

    applyDirectToken() {
        const [accessToken, sessionId = "", kdtId = DEFAULT_KDT_ID] = String(this.entry).split("@").map(s => s.trim());
        this.applyToken({ accessToken, sessionId, kdtId });
        this.log(`使用 CAMEL_TOKEN：${mask(this.token)}`);
    }

    async checkToken() {
        try {
            await this.getPoints("缓存校验");
            return true;
        } catch (_) { return false; }
    }

    async getCheckinInfo() {
        const data = await this.request({ path: "/wscump/checkin/show_checkin_page_v2.json" });
        this.checkinId = data?.checkinId || data?.checkin_id || this.checkinId || FALLBACK_CHECKIN_ID;
        this.log(`签到活动：checkinId=${this.checkinId || "未获取"} isShow=${!!data?.isShow} showPage=${!!data?.showPage}`);
        return data;
    }

    async doCheckin() {
        if (!this.checkinId) {
            this.log("未获取到 checkinId，跳过签到");
            return;
        }
        try {
            const data = await this.request({
                path: "/wscump/checkin/checkinV2.json",
                params: { checkinId: this.checkinId },
            });
            const awards = (data?.list || []).map(item => item?.infos?.title || item?.title).filter(Boolean).join("，");
            this.log(`签到成功：${data?.desc || ""}${awards ? "，奖励：" + awards : ""}`);
        } catch (e) {
            const message = String(e.message || e);
            if (/已达最大参与次数|已签到|重复签到|今日已|最大参与次数/.test(message)) {
                this.log(`今日已签到：${message}`);
                return;
            }
            throw e;
        }
    }

    async getPoints(label = "积分") {
        const data = await this.request({ path: "/wscump/integral/user_points.json" });
        const points = data?.current_points ?? data?.real_points ?? data?.total_points ?? "未知";
        this.log(`${label}：${points}`);
        return points;
    }

    async run() {
        this.log("开始执行 CAMEL骆驼签到");
        try {
            if (this.mode === "direct") {
                this.applyDirectToken();
            } else {
                const cached = this.getCachedToken();
                if (cached) {
                    this.applyToken(cached);
                    this.log("使用缓存 token");
                    if (!(await this.checkToken())) {
                        this.log("缓存 token 失效，重新登录");
                        this.removeCachedToken();
                    }
                }
                if (!this.token) await this.loginByWxCode();
            }

            if (!this.token) throw new Error("未获取到 accessToken");
            await sleep(rand(800, 1800));
            await this.getPoints("签到前积分");
            await this.getCheckinInfo();
            await this.doCheckin();
            await this.getPoints("签到后积分");
        } catch (e) {
            const msg = e.message || String(e);
            this.log(`执行失败：${msg}`);
            if (/access_token|token|授权|登录|invalid session|session/i.test(msg)) this.removeCachedToken();
        }
        return this.logs.join("\n");
    }
}

!(async () => {
    const entries = [];
    for (const t of DIRECT_TOKENS) entries.push({ entry: t, mode: "direct" });
    for (const s of YYB_SERVERS) entries.push({ entry: s, mode: "yyb" });

    if (!entries.length) {
        console.log("未配置环境变量：请设置 YYB_SERVER=地址@微信账号标识（多账号换行）。可选 CAMEL_TOKEN=accessToken[@sessionId][@kdtId] 用于调试。");
        return;
    }

    const results = [];
    for (const item of entries) {
        const task = new Task(item.entry, item.mode);
        results.push(await task.run());
        await sleep(rand(1200, 3000));
    }

    const summary = `${APP_NAME}签到结果\n\n${results.join("\n\n")}`;
    if (notify?.sendNotify) await notify.sendNotify(`${APP_NAME}签到`, summary);
})().catch(e => console.log(e.message || e));
