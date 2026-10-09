/*
------------------------------------------
@Description: 认养一头牛(牛奶卡商城) - 微信小程序手机号授权登录 + 每日签到
cron: 17 9 * * *
------------------------------------------
变量名：rytyn
变量值：wx_server 里的 openid/账号标识，多账号用 & 或换行分隔（可加 #备注）

依赖变量：
wx_server_url  默认 http://172.17.0.1:8000
wx_auth        必填，wx_server 鉴权值
------------------------------------------
契约（appid wx0408f3f20d769a2f，host www.milkcard.mall.ryytngroup.com）：
（迁移自 YYB-GO 系脚本，原脚本为“手机号授权登录”）

登录  POST /mall/xhr/minilogin
        body {encryptedData, offset:<iv>, wxCode:<wx.login code>, code:<新式phoneCode>}
        - encryptedData/offset(iv)/phoneCode 均取自 wx_server 的 /wx/getphonenumber
          (data.raw.encryptedData / data.raw.iv / data?.data?.result?.code || data?.code)
        - wxCode 取自 /wx/code，且【手机号授权在前、取code在后】以保证 session_key 一致(参 haitian.js)
        -> token 在响应头 X-Auth-Token（或 body data.token / data.x-auth-token）
签到  POST /mall/xhr/task/checkin/save   头 X-Auth-Token:<token>
        -> code==200，data.{grade,phone,point}（该接口即“签到并返回状态”，幂等）
规则  GET  /mall/xhr/task/checkin/getRule 头 X-Auth-Token:<token>（辅助，可选）

说明：本店为“手机号一键登录/注册”，minilogin 用授权手机号建号；无独立“未注册”态。
      若 wx_server 取不到手机号，则无法登录，如实报告。不含任何作者个人凭证。
------------------------------------------
*/

const { Env } = require("./env.js");


// === YYB ref auto-inject ===
// yyb-go 后端 /wx/code 与 /wx/getuserinfo 要求 body 带 ref(账号 token)。
// openid 在 YYB 模式下是账号整行 "server@ref", 从 @ 后取 ref 精确注入(避免串号)。
try {
    const _yybAxios = require("axios");
    if (_yybAxios && _yybAxios.defaults && !_yybAxios.defaults.__yybRefPatched) {
        _yybAxios.defaults.__yybRefPatched = true;
        const _yybRefOf = (v) => {
            const s = String(v || "");
            const at = s.lastIndexOf("@");
            return at >= 0 ? s.slice(at + 1).trim() : "";
        };
        const _yybPatch = (cfg) => {
            try {
                const url = String((cfg && cfg.url) || "");
                if (url.indexOf("/wx/code") >= 0 || url.indexOf("/wx/getuserinfo") >= 0) {
                    const d = cfg.data;
                    if (d && typeof d === "object" && !d.ref) {
                        const ref = _yybRefOf(d.openid || d.openId || d.id || d.account);
                        if (ref) d.ref = ref;
                        // /wx/code 要求 app_id(下划线), 上游脚本普遍写成 appid
                        if (!d.app_id && (d.appid || d.appId)) d.app_id = d.appid || d.appId;
                    } else if (typeof d === "string" && d.indexOf("ref") < 0) {
                        const obj = JSON.parse(d);
                        const ref = _yybRefOf(obj.openid || obj.openId || obj.id || obj.account);
                        if (ref) { obj.ref = ref; cfg.data = JSON.stringify(obj); }
                        if (!obj.app_id && (obj.appid || obj.appId)) { obj.app_id = obj.appid || obj.appId; cfg.data = JSON.stringify(obj); }
                    }
                }
            } catch (e) {}
            return cfg;
        };
        if (_yybAxios.interceptors && _yybAxios.interceptors.request) {
            _yybAxios.interceptors.request.use(_yybPatch);
        }
        if (typeof _yybAxios.create === "function") {
            const _origCreate = _yybAxios.create.bind(_yybAxios);
            _yybAxios.create = function () {
                const inst = _origCreate.apply(null, arguments);
                try { if (inst.interceptors && inst.interceptors.request) inst.interceptors.request.use(_yybPatch); } catch (e) {}
                return inst;
            };
        }
    }
} catch (e) {}
// === end YYB ref auto-inject ===
const $ = new Env("认养一头牛签到");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const WeChatServer = require("./wcs.js");

const ckName = "rytyn";
const MINI_APP_ID = "wx0408f3f20d769a2f";
const BASE_URL = "https://www.milkcard.mall.ryytngroup.com";
const PAGE_VERSION = "323";
const TOKEN_CACHE_FILE = path.join(__dirname, "rytyn_token_cache.json");
const UA =
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) " +
    "Mobile/15E148 MicroMessenger/8.0.61(0x18003d24) NetType/4G Language/zh_CN";

const EP_LOGIN = "/mall/xhr/minilogin";
const EP_CHECKIN = "/mall/xhr/task/checkin/save";
const EP_RULE = "/mall/xhr/task/checkin/getRule";

const WX_SERVER_URL = process.env.wx_server_url || "http://172.17.0.1:8000";
const WX_AUTH = process.env.wx_auth || "";

const wechat = new WeChatServer({ url: WX_SERVER_URL, appid: MINI_APP_ID, auth: WX_AUTH });

function readCache() {
    try { if (!fs.existsSync(TOKEN_CACHE_FILE)) return {}; return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {}; } catch (e) { return {}; }
}
function writeCache(c) {
    try { fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(c, null, 2), "utf8"); } catch (e) { $.log(`写入缓存失败: ${e.message || e}`); }
}
function parseAccount(raw = "") {
    const [id, remark] = String(raw).split("#").map((s) => (s || "").trim());
    return { openid: id, remark: remark || "" };
}
function short(v, n = 300) {
    const t = typeof v === "string" ? v : JSON.stringify(v);
    return !t ? "" : t.length > n ? `${t.slice(0, n)}...` : t;
}
function maskPhone(p) {
    p = String(p || "");
    return p.length >= 11 ? `${p.slice(0, 3)}****${p.slice(-4)}` : p;
}
function maskToken(t) {
    t = String(t || "");
    return t.length <= 12 ? t : `${t.slice(0, 6)}****${t.slice(-4)}`;
}

class Task {
    constructor(raw) {
        this.index = $.userIdx++;
        this.account = parseAccount(raw);
        this.token = "";
    }
    log(text) {
        $.log(`账号[${this.index}]${this.account.remark ? `[${this.account.remark}]` : ""} ${text}`);
    }
    // 直接 POST wx_server（wcs.js 只有 getCode，手机号要自己发）
    async wxServer(endpoint) {
        if (!WX_AUTH) throw new Error("缺少 wx_auth，无法从 wx_server 获取登录数据");
        const res = await axios.post(
            `${WX_SERVER_URL}${endpoint}`,
            { appid: MINI_APP_ID, openid: this.account.openid },
            { headers: { auth: WX_AUTH }, timeout: 45000, validateStatus: () => true }
        );
        const d = res.data;
        if (!d || d.status === false) throw new Error(`wx_server ${endpoint} 失败: ${d?.message || d?.error || short(d)}`);
        return d;
    }
    // 手机号授权数据：encryptedData/iv(老式) + phoneCode(新式)
    async getPhoneAuth() {
        const d = await this.wxServer("/wx/getphonenumber");
        const env = d.data || d;
        const raw = env.raw || {};
        const encryptedData = raw.encryptedData || env.encryptedData || "";
        const iv = raw.iv || env.iv || "";
        const phoneCode = env.code || d.code || raw.code || "";
        if (!encryptedData || !iv) throw new Error(`/wx/getphonenumber 未返回手机号加密数据: ${short(Object.keys(raw))} | ${short(env)}`);
        return { encryptedData, iv, phoneCode };
    }
    // 取 wx.login code（放在手机号之后，保证 session_key 一致）
    async getWxCode() {
        const { data } = await wechat.getCode(this.account.openid);
        if (data && data.status === false) throw new Error(`wx_server 取code失败: ${data.message || short(data)}`);
        const code = data?.data?.result?.code || data?.data?.code || data?.code;
        if (!code || typeof code !== "string") throw new Error(`wx_server 未返回 code: ${short(data)}`);
        return code;
    }
    async login() {
        const { encryptedData, iv, phoneCode } = await this.getPhoneAuth();
        const wxCode = await this.getWxCode();
        const body = { encryptedData, offset: iv, wxCode, code: phoneCode };
        const res = await axios.request({
            method: "POST", url: `${BASE_URL}${EP_LOGIN}`, data: body,
            headers: {
                "Content-Type": "application/json", Accept: "application/json", "User-Agent": UA,
                Referer: `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            },
            timeout: 30000, validateStatus: () => true,
        });
        // token 优先响应头 X-Auth-Token
        let token = res.headers?.["x-auth-token"] || res.headers?.["X-Auth-Token"] || "";
        const b = res.data;
        if (!token && b && typeof b === "object") {
            const dd = b.data || {};
            token = dd.token || dd["x-auth-token"] || dd.xAuthToken || b.token || "";
        }
        if (!token) {
            const msg = (b && (b.msg || b.message)) || short(b);
            throw new Error(`登录未返回 token: HTTP ${res.status} code=${b?.code} msg=${msg}`);
        }
        this.token = String(token);
        const cache = readCache();
        cache[this.account.openid] = { token: this.token, updatedAt: new Date().toISOString() };
        writeCache(cache);
        this.log(`登录成功 token:${maskToken(this.token)}`);
    }
    async api(method, apiPath, payload) {
        const res = await axios.request({
            method, url: `${BASE_URL}${apiPath}`, data: method === "GET" ? undefined : (payload || {}),
            headers: {
                "Content-Type": "application/json", Accept: "application/json", "User-Agent": UA,
                "X-Auth-Token": this.token,
                Referer: `https://servicewechat.com/${MINI_APP_ID}/305/page-frame.html`,
            },
            timeout: 30000, validateStatus: () => true,
        });
        return { status: res.status, data: res.data };
    }
    isAuthErr(codeOrMsg) {
        return /token|登录|未授权|失效|过期|未登录|鉴权|401|403/i.test(String(codeOrMsg));
    }
    async sign(retry = true) {
        // checkin/save = 签到并返回状态（幂等）
        const { status, data } = await this.api("POST", EP_CHECKIN, {});
        const code = data && data.code;
        const msg = (data && (data.msg || data.message)) || "";
        if (code === 200 || code === "200") {
            const d = (data && data.data) || {};
            const parts = [];
            if (d.point !== undefined) parts.push(`积分 ${d.point}`);
            if (d.phone) parts.push(`手机 ${maskPhone(d.phone)}`);
            if (d.grade !== undefined) parts.push(`等级 ${d.grade}`);
            this.log(`✅ 签到成功${parts.length ? "（" + parts.join("，") + "）" : ""}`);
            // 辅助拉一次规则（不影响结果）
            try { await this.api("GET", EP_RULE); } catch (e) {}
            return true;
        }
        if (/已签|签到过|重复|已完成|今日已/.test(String(msg))) { this.log(`✅ 今日已签到（${msg}）`); return true; }
        if (retry && (this.isAuthErr(code) || this.isAuthErr(msg) || status === 401 || status === 403)) {
            this.log("会话失效，重新登录后重试");
            this.token = "";
            await this.login();
            return this.sign(false);
        }
        this.log(`❌ 签到失败: HTTP ${status} code=${code} msg=${msg || short(data)}`);
        return false;
    }
    async ensureLogin() {
        const cached = readCache()[this.account.openid] || {};
        if (!this.token && cached.token) { this.token = cached.token; this.log("使用缓存token"); return; }
        if (!this.token) await this.login();
    }
    async run() {
        if (!this.account.openid) { this.log("跳过：变量值里没有 openid"); return; }
        try {
            await this.ensureLogin();
            await this.sign();
        } catch (e) {
            this.log(`执行失败: ${e.message || e}`);
        }
    }
}

!(async () => {
    $.checkEnv(ckName);
// === YYB-Go 兼容层 ===
if (!$.userCount) {
    const yybServers = (process.env.YYB_SERVER || "").split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    if (yybServers.length) {
        $.userList = yybServers;
        $.userCount = yybServers.length;
        $.log("YYB-Go: 加载了 " + yybServers.length + " 个账号");
    }
}






    if (!$.userCount) { $.log(`未找到变量 ${ckName}`); return; }
    for (let i = 0; i < $.userList.length; i++) {
        await new Task($.userList[i]).run();
        if (i < $.userList.length - 1) await $.wait(1500, 3000);
    }
})().catch((e) => $.log(e.message || e)).finally(() => $.done());
