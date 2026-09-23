// name: 杰士邦会员中心
// cron: 24 13,1 * * *
const axios = require("axios");
// ====================== YYB Go 账号（环境变量 YYB_SERVER = 地址@微信账号标识，多行） ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("未配置环境变量 YYB_SERVER，请设置后重试（格式：地址@微信账号标识，多行换行）");
    process.exit(1);
}
function parseYybGoEntry(rawValue) {
    const value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "" };
    const atIndex = value.indexOf("@");
    if (atIndex === -1) {
        console.log("YYB_SERVER 格式应为 地址@微信账号标识，当前值: " + value);
        return { server: "", ref: "" };
    }
    let server = value.slice(0, atIndex).trim();
    const ref = value.slice(atIndex + 1).trim();
    if (server.startsWith("http://")) server = server.slice(7);
    else if (server.startsWith("https://")) server = server.slice(8);
    server = server.replace(/\/+$/, "");
    if (!server || !ref) return { server: "", ref: "" };
    return { server, ref };
}
async function getCode(server) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;
    const url = "http://" + parsedServer + "/wxapp/getCode";
    try {
        const { data } = await axios.post(url, { ref, app_id: 'wx5966681b4a895dee' }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) {
            console.log(parsedServer + " 获取code失败: " + JSON.stringify(data));
            return null;
        }
        console.log(parsedServer + " 获取code成功");
        return code;
    } catch (e) {
        console.log(parsedServer + " 获取code异常: " + e.message);
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const APP = {
    name: "杰士邦会员中心",
    appid: "wx5966681b4a895dee",
    shopId: "467028",
    signActivityId: "170630",
};

const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

function short(value, max = 220) {
    if (value === undefined || value === null) return "";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > max ? `${text.slice(0, max)}...` : text;
}

function formatDate(date = new Date()) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

async function request(options) {
    const res = await axios.request({
        timeout: 20000,
        validateStatus: () => true,
        ...options,
        headers: {
            "User-Agent": USER_AGENT,
            Accept: "application/json, text/plain, */*",
            ...(options.headers || {}),
        },
    });
    return { status: res.status, headers: res.headers || {}, data: res.data };
}

async function getWxCode(server) {
        return await getCode(server);
    }


class JsbHuiyuan {
    constructor(openid) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.openid = openid;
        this.base = "https://api.vshop.hchiv.cn/jfmb";
        this.global = {
            appId: APP.appid,
            shopId: APP.shopId,
            openId: "",
            shopNick: "",
            mainShopNick: "",
            unionid: "",
            phoneNumber: "",
            jsession: "",
            clientToken: "",
            securePlatId: "",
            sourceShopId: "",
        };
    }

    buildData(data = {}, reqType = 2) {
        const timestamp = Date.now();
        const common = {
            appId: this.global.appId,
            openId: this.global.openId || this.openid,
            shopNick: this.global.shopNick || "",
            timestamp,
            interfaceSource: 0,
        };
        return reqType === 2 ? { ...common, ...data } : { ...data };
    }

    async api(path, data = {}, { reqType = 2, raw = false } = {}) {
        const headers = {
            "content-type": "application/json",
            appenv: "test",
        };
        if (this.global.jsession) headers.cookie = this.global.jsession;
        if (this.global.clientToken) headers.Authorization = `Bearer ${this.global.clientToken}`;
        const body = this.buildData(typeof data === "string" ? JSON.parse(data) : data, reqType);
        const timestamp = Date.now();
        const query =
            reqType === 2
                ? `?sideType=3&mob=${encodeURIComponent(this.global.phoneNumber || "")}&appId=${encodeURIComponent(this.global.appId)}&shopNick=${encodeURIComponent(this.global.mainShopNick || this.global.appId)}&timestamp=${timestamp}${this.global.guideNo ? `&guideNo=${encodeURIComponent(this.global.guideNo)}` : ""}${this.global.securePlatId ? `&securePlatId=${encodeURIComponent(this.global.securePlatId)}` : ""}${this.global.sourceShopId ? `&sourceShopId=${encodeURIComponent(this.global.sourceShopId)}` : ""}`
                : "";
        const res = await request({
            method: "POST",
            url: `${this.base}${path}${query}`,
            headers,
            data: body,
        });
        const setCookie = res.headers["set-cookie"];
        if (Array.isArray(setCookie) && setCookie[0]) this.global.jsession = setCookie[0].split(";")[0];
        const token = res.data?.data?.clientToken || res.data?.data?.data?.clientToken;
        if (token) this.global.clientToken = token;
        const securePlatId = res.data?.data?.data?.securePlatId || res.data?.securePlatId;
        if (securePlatId) this.global.securePlatId = securePlatId;
        return raw ? res : res.data;
    }

    async login() {
        const code = await getWxCode(this.server);
        const auth = await this.api("/cloud/member/wechatlogin/authLoginApplet", {
            wxInfo: code,
            extend: "{}",
            sessionIdForWxShop: "",
        });
        const data = auth?.data || {};
        this.global.openId = data.openId || data.openid || this.openid;
        this.global.unionid = data.unionId || data.unionid || "";
        return `authLoginApplet=${short(auth)}`;
    }

    async query() {
        const shop = await this.api("/cloud/member/shop/getShopInfo", {});
        const shopData = shop?.data?.data || shop?.data || {};
        if (shopData.sellerId) this.global.shopId = String(shopData.sellerId);
        if (shopData.mainShopNick) this.global.mainShopNick = shopData.mainShopNick;
        if (shopData.shopNick) this.global.shopNick = shopData.shopNick;
        const card = await this.api("/api/customize/get-card-info.do", {});
        const client = await this.api("/cloud/member/tblogin/getClientInfo", {});
        const d = card?.data || {};
        const c = client?.data || {};
        return `用户=${c.client_name || c.user_mob || d.name || "未知"} 积分=${d.residualIntegral ?? c.residualIntegral ?? "未知"} 等级=${d.currLevelName || c.member_level_str || ""} shop=${shopData.shopTitle || shopData.title || short(shopData || shop, 80)}`;
    }

    async sign() {
        const activityId = APP.signActivityId;
        const info = await this.api("/cloud/activity/sign/load-sign", { activityId });
        const infoBody = info?.data || {};
        const signInfo = infoBody?.data || {};
        if (Number(infoBody.code) !== 200) return `签到活动查询失败 activityId=${activityId}: ${short(info)}`;

        const ruleRes = await this.api("/cloud/activity/sign/getSignPrizeRules", { activityId });
        const rules = Array.isArray(ruleRes?.data?.data)
            ? ruleRes.data.data
                  .filter((item) => item && (item.ruleName || item.prizeName))
                  .map((item) => `${item.ruleName || ""}${item.prizeName ? `-${item.prizeName}` : ""}`)
                  .join("，")
            : "";

        if (signInfo.signed) {
            return `今日已签到 activityId=${activityId} 连续=${signInfo.continuousSignNum ?? 0} 累计=${signInfo.totalSignNum ?? 0}${rules ? ` 规则=${rules}` : ""}`;
        }

        const sign = await this.api("/cloud/activity/sign/add-sign", { activityId });
        const body = sign?.data || {};
        const data = body?.data || {};
        if (Number(body.code) === 200) {
            const prizes = Array.isArray(data.prizeList) && data.prizeList.length ? ` 奖励=${data.prizeList.map((x) => x.prizeName || x.name || short(x, 40)).join("，")}` : "";
            return `签到成功 activityId=${activityId} +${data.integralCount ?? "未知"}积分 连续=${data.continuousSignNum ?? 0} 累计=${data.totalSignNum ?? 0}${prizes}`;
        }
        if (/已签|重复/.test(String(body.message || sign?.message || ""))) {
            return `今日已签到 activityId=${activityId}: ${short(sign)}`;
        }
        return `签到失败 activityId=${activityId}: ${short(sign)}`;
    }
}

async function runAccount(openid, index) {
    console.log(`\n========== ${APP.name} 账号[${index}] ${openid} ==========`);
    const runner = new JsbHuiyuan(openid);
    try {
        console.log(`登录：${await runner.login()}`);
        console.log(`查询：${await runner.query()}`);
        console.log(`签到：${await runner.sign()}`);
    } catch (e) {
        console.log(`执行失败：${e.message || e}`);
    }
}

(async () => {
        if (!SERVERS.length) {
        console.log(`未配置 ${"YYB_SERVER"}`);
        return;
    }
    console.log(`共找到${SERVERS.length}个账号`);
    for (let i = 0; i < SERVERS.length; i++) {
        await runAccount(SERVERS[i], i + 1);
        await sleep(800);
    }
})().catch((e) => {
    console.log(`脚本异常：${e.stack || e.message || e}`);
});
