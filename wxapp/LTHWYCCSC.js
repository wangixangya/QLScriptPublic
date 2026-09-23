// name: 骆驼户外运动城商城
// cron: 21 8,20 * * *
// 青龙面板签到脚本 · 微盟(Weimob)平台 · 适配 YYB Go openapi
// 环境变量 YYB_SERVER: 地址@微信账号标识, 多账号换行分隔
//   地址不要带 http:// 前缀，直接写 host:port
//   微信账号标识: YYB Go 账号 id / uin / openid（在 /accounts 接口可查）
// 多账号示例（一行一个）:
//   172.17.0.4:8000@2
//   172.17.0.4:8000@4
//   172.17.0.4:8000@5
//
// 无需额外依赖，使用 Node.js 原生 fetch（Node 18+）

// ====================== 青龙通知 ======================
let notify;
try { notify = require("./sendNotify"); } catch (_) { try { notify = require("sendNotify"); } catch (__) { notify = null; } }

// ====================== 环境变量解析 ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识，多行换行）");
    process.exit(1);
}

function parseEntry(raw) {
    const v = String(raw || "").trim();
    if (!v) return { server: "", ref: "" };
    const at = v.indexOf("@");
    if (at === -1) { console.log("⚠️ YYB_SERVER 格式应为 地址@微信账号标识，当前值: " + v); return { server: "", ref: "" }; }
    let server = v.slice(0, at).trim();
    const ref = v.slice(at + 1).trim();
    if (server.startsWith("http://")) server = server.slice(7);
    else if (server.startsWith("https://")) server = server.slice(8);
    server = server.replace(/\/+$/, "");
    if (!server || !ref) return { server: "", ref: "" };
    return { server, ref };
}

// ====================== 小程序配置（微盟平台） ======================
const APPID = "wx3d2bdbf67041d80e";
const APP_NAME = "骆驼户外运动城商城";

const WEIMOB_BASE = "https://xapi.weimob.com";
const LOGIN_URL = WEIMOB_BASE + "/fe/mapi/user/loginX";
const SIGN_MAIN_INFO_URL = WEIMOB_BASE + "/api3/onecrm/mactivity/sign/misc/sign/activity/c/signMainInfo";
const SIGN_URL = WEIMOB_BASE + "/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/sign";
const POINT_URL = WEIMOB_BASE + "/api3/onecrm/point/myPoint/get";

// 商户配置（从小程序 CMS SDK getFullVidInfo 抓取，已验证可用）
const WEIMOB_CONFIG = {
    bosId: "4021451615601",
    cid: "420878601",
    vid: 6015691407601,
    vidType: 2,
    productId: 146,
    productInstanceId: 7133098601,
    productVersionId: "14026",
    merchantId: "2000170906601",
    tcode: "weimob",
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823";

const REQUEST_TIMEOUT = 30000;

// ====================== 工具函数 ======================
function mask(v) {
    v = String(v || "");
    return v.length <= 12 ? v : v.slice(0, 6) + "..." + v.slice(-6);
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function rand(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }

function nowText() {
    return new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
}

// ====================== HTTP 请求封装 ======================
async function httpPost(url, body, headers, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs || REQUEST_TIMEOUT);
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: headers,
            body: typeof body === "string" ? body : JSON.stringify(body),
            signal: ctrl.signal,
        });
        const text = await res.text();
        try { return JSON.parse(text); } catch (_) { return { errcode: "-1", errmsg: text.slice(0, 500) }; }
    } finally {
        clearTimeout(timer);
    }
}

// ====================== YYB Go: 获取微信 code ======================
async function getCode(server, ref) {
    const url = "http://" + server + "/wxapp/getCode";
    console.log("  [授权] 请求 YYB Go 获取 code...");
    const data = await httpPost(url, { ref, app_id: APPID }, { "Content-Type": "application/json" }, 25000);
    if (Number(data.code) !== 0) throw new Error("getCode 失败: " + (data.msg || JSON.stringify(data)));
    const code = data?.data?.result?.code || data?.data?.code;
    if (!code) throw new Error("YYB Go 未返回 code: " + JSON.stringify(data));
    console.log("  [授权] code 获取成功");
    return code;
}

// ====================== 微盟 loginX: 换 token + wid ======================
async function loginByCode(code) {
    console.log("  [登录] 使用 code 换 token...");
    const payload = {
        appid: APPID,
        basicInfo: {
            bosId: WEIMOB_CONFIG.bosId,
            cid: WEIMOB_CONFIG.cid,
            tcode: WEIMOB_CONFIG.tcode,
            vid: String(WEIMOB_CONFIG.vid),
        },
        env: "production",
        extendInfo: { source: 1 },
        is_pre_fetch_open: true,
        parentVid: 0,
        pid: WEIMOB_CONFIG.bosId,
        storeId: "0",
        code: code,
        queryAuthConfig: true,
    };
    const data = await httpPost(LOGIN_URL, payload, { "Content-Type": "application/json", "User-Agent": UA });
    if (String(data.errcode) !== "0") throw new Error("loginX 失败: " + (data.errmsg || JSON.stringify(data).slice(0, 300)));
    const d = data.data || {};
    const token = d.token;
    const wid = d.wid;
    if (!token || !wid) throw new Error("loginX 未返回 token/wid: " + JSON.stringify(d).slice(0, 300));
    console.log("  [登录] token: " + mask(token) + " wid: " + wid);
    return { token, wid };
}

// ====================== 构建完整请求体 ======================
function buildRequestBody(wid) {
    return {
        appid: APPID,
        basicInfo: {
            vid: WEIMOB_CONFIG.vid,
            vidType: WEIMOB_CONFIG.vidType,
            bosId: Number(WEIMOB_CONFIG.bosId),
            productId: WEIMOB_CONFIG.productId,
            productInstanceId: WEIMOB_CONFIG.productInstanceId,
            productVersionId: WEIMOB_CONFIG.productVersionId,
            merchantId: Number(WEIMOB_CONFIG.merchantId),
            tcode: WEIMOB_CONFIG.tcode,
            cid: WEIMOB_CONFIG.cid,
        },
        extendInfo: {
            source: 1,
            channelsource: 5,
            refer: "onecrm-signgift",
            mpScene: 1005,
        },
        queryParameter: null,
        i18n: { language: "zh", timezone: "8" },
        pid: WEIMOB_CONFIG.bosId,
        storeId: "0",
        customInfo: { source: 0, wid: wid },
    };
}

function apiHeaders(token) {
    return {
        "Content-Type": "application/json",
        "X-WX-Token": token,
        "User-Agent": UA,
        "Referer": "https://servicewechat.com/" + APPID + "/93/page-frame.html",
    };
}

// ====================== 查询签到状态 ======================
async function getSignMainInfo(token, wid) {
    const data = await httpPost(SIGN_MAIN_INFO_URL, buildRequestBody(wid), apiHeaders(token));
    if (String(data.errcode) !== "0") throw new Error("signMainInfo 失败: " + (data.errmsg || JSON.stringify(data).slice(0, 300)));
   const d = data.data || {};
   return {
       hasSign: d.hasSign === true,
        keepSignDate: d.keepSignDate,
        signedDate: d.signedDate,
       monthCumulativeSignDays: d.monthCumulativeSignDays,
       activityCumulativeSignDays: d.activityCumulativeSignDays,
   };
}

// ====================== 执行签到 ======================
async function doSign(token, wid) {
    const data = await httpPost(SIGN_URL, buildRequestBody(wid), apiHeaders(token));
    if (String(data.errcode) === "0" && data.data) {
        const r = data.data;
        const rewards = [];
        const fr = r.fixedReward || {};
        if ((fr.points || 0) > 0) rewards.push(fr.points + (r.pointName || "积分"));
        if ((fr.growth || 0) > 0) rewards.push(fr.growth + (r.growthName || "成长值"));
        if ((fr.amount || 0) > 0) rewards.push(fr.amount + "元");
        const er = r.extraReward || {};
        if ((er.points || 0) > 0) rewards.push("额外" + er.points + (r.pointName || "积分"));
        return { success: true, message: rewards.join("、") || "签到成功", already: false };
    }
    const msg = data.errmsg || "";
    if (msg.includes("重复") || msg.includes("已签到") || msg.includes("今日") || String(data.errcode) === "60070013000332") {
        return { success: true, message: msg || "今日已签到", already: true };
    }
    return { success: false, message: msg || "签到失败 errcode=" + data.errcode, already: false };
}

// ====================== 查询积分 ======================
async function queryPoints(token, wid) {
    const body = buildRequestBody(wid);
    body.request = { isNeedRecordDisplay: true, isQueryAllAccount: true };
    const data = await httpPost(POINT_URL, body, apiHeaders(token));
    if (String(data.errcode) === "0" && data.data) {
        return { success: true, available: data.data.availablePoint || 0, total: data.data.totalPoint || 0 };
    }
    return { success: false, available: 0, total: 0 };
}

// ====================== 单账号流程 ======================
async function runAccount(index, total, entry) {
    const { server, ref } = parseEntry(entry);
    const result = { ref: mask(ref), success: false, signMsg: "-", pointsMsg: "-", error: "" };

    console.log("\n" + "=".repeat(50));
    console.log("账号 " + index + "/" + total + " (" + mask(ref) + ")");
    console.log("=".repeat(50));

    if (!server || !ref) { result.error = "YYB_SERVER 格式错误"; return result; }

    await sleep(rand(1000, 3000));

    let code, token, wid;
    try {
        code = await getCode(server, ref);
    } catch (e) { result.error = "获取 code 失败: " + e.message; console.log("  ❌ " + result.error); return result; }

    try {
        const loginRes = await loginByCode(code);
        token = loginRes.token;
        wid = loginRes.wid;
    } catch (e) { result.error = "登录失败: " + e.message; console.log("  ❌ " + result.error); return result; }

    // 查签到状态
    let info;
    try {
       info = await getSignMainInfo(token, wid);
        console.log("  [签到] 已签到: " + info.hasSign + " 连续: " + (info.signedDate || 0) + "天 本月: " + (info.monthCumulativeSignDays || 0) + "天");
    } catch (e) {
        console.log("  [签到] 查询状态失败: " + e.message + "，直接尝试签到");
    }

    // 签到
   if (info && info.hasSign) {
        result.signMsg = "今日已签到（连续" + (info.signedDate || 0) + "天）";
       result.success = true;
    } else {
        try {
            const signRes = await doSign(token, wid);
            if (signRes.already) result.signMsg = "今日已签到: " + signRes.message;
            else result.signMsg = "签到成功: " + signRes.message;
            result.success = signRes.success;
            console.log("  [签到] " + result.signMsg);
        } catch (e) {
            result.signMsg = "签到异常: " + e.message;
            console.log("  ❌ " + result.signMsg);
        }
    }

    // 积分
    try {
        const pts = await queryPoints(token, wid);
        result.pointsMsg = pts.success ? ("可用: " + pts.available + " / 总计: " + pts.total) : "积分查询失败";
        console.log("  [积分] " + result.pointsMsg);
    } catch (e) {
        result.pointsMsg = "积分查询异常";
    }

    return result;
}

// ====================== 通知报告 ======================
function buildNotify(results) {
    const ok = results.filter(r => r.success).length;
    const fail = results.length - ok;
    const lines = [APP_NAME + " 签到结果", "—".repeat(30), "✅ " + ok + "成功 / ❌ " + fail + "失败", "🕒 " + nowText(), ""];
    for (let i = 0; i < results.length; i++) {
        const r = results[i];
        const icon = r.success ? "✅" : "❌";
        lines.push(icon + " 账号" + (i + 1) + " (" + r.ref + ")");
        lines.push("  签到: " + r.signMsg);
        lines.push("  积分: " + r.pointsMsg);
        if (!r.success) lines.push("  错误: " + (r.error || "").slice(0, 80));
        lines.push("");
    }
    return lines.join("\n");
}

// ====================== 主函数 ======================
async function main() {
    console.log("\n" + "=".repeat(50));
    console.log(APP_NAME + "（YYB Go 版）");
    console.log("启动: " + nowText() + " | 账号: " + SERVERS.length);
    console.log("=".repeat(50));

    const results = [];
    for (let i = 0; i < SERVERS.length; i++) {
        try {
            results.push(await runAccount(i + 1, SERVERS.length, SERVERS[i]));
        } catch (e) {
            results.push({ ref: mask(parseEntry(SERVERS[i]).ref), success: false, signMsg: "-", pointsMsg: "-", error: String(e.message || e) });
        }
        if (i < SERVERS.length - 1) await sleep(rand(2000, 4000));
    }

    const ok = results.filter(r => r.success).length;
    console.log("\n" + "=".repeat(50));
    console.log("完成: ✅" + ok + " ❌" + (results.length - ok) + " | 🕒" + nowText());
    console.log("=".repeat(50));

    if (notify && typeof notify.send === "function") {
        try { notify.send(APP_NAME, buildNotify(results)); } catch (e) { console.log("通知发送失败: " + e.message); }
    }
}

main().catch(e => { console.error("运行异常: " + e.message); process.exit(1); });
