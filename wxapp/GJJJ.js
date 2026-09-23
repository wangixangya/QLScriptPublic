// name: 顾家家居会员俱乐部
// cron: 20 8,20 * * *
const axios = require("axios");
const crypto = require("crypto");

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

// ====================== 配置常量 ======================
const MINI_APP_ID = "wx0770280d160f09fe";
const PAGE_VERSION = "293";
const API_BASE = "https://mc.kukahome.com/club-server";
const INTEGRAL_BASE = "https://mc.kukahome.com/integral-server";
const BRAND_CODE = "K001";
const SMALL_APPLICATION_ID = "667516";
const SMALL_CRYPTO = "FH3yRrHG2RfexND8";
const VERSION_NUMBER = "2.0.184";
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

// ====================== 取微信 code ======================
async function getCode(serverEntry, appid) {
    const { server, ref } = parseYybGoEntry(serverEntry);
    if (!server || !ref) return null;
    const url = "http://" + server + "/wxapp/getCode";
    const res = await axios.request({
        method: "POST",
        url,
        data: { app_id: appid, ref },
        headers: { "Content-Type": "application/json" },
        timeout: 20000,
        validateStatus: () => true,
    });
    if (res.status !== 200) {
        throw new Error(`getCode HTTP ${res.status}: ${JSON.stringify(res.data)}`);
    }
    const body = res.data || {};
    if (Number(body.code) !== 0) {
        throw new Error(`getCode失败: ${body.msg || JSON.stringify(body)}`);
    }
    const code = body?.data?.result?.code || body?.data?.code;
    if (!code) throw new Error(`wx_server 未返回 code: ${JSON.stringify(body)}`);
    return code;
}

// ====================== 工具函数 ======================
function md5(input) {
    return crypto.createHash("md5").update(String(input)).digest("hex");
}

function isObject(val) {
    return Object.prototype.toString.call(val) === "[object Object]";
}

function buildParameterBase(data) {
    if (!data) return null;
    if (Array.isArray(data) || typeof data === "string") return null;
    if (!isObject(data)) return null;
    const keys = Object.keys(data).sort((a, b) => {
        const ac = [...a].map((ch) => ch.charCodeAt(0));
        const bc = [...b].map((ch) => ch.charCodeAt(0));
        for (let i = 0; i < Math.min(ac.length, bc.length); i++) {
            if (ac[i] !== bc[i]) return ac[i] - bc[i];
        }
        return ac.length - bc.length;
    });
    const pairs = [];
    for (const key of keys) {
        const value = data[key];
        if (value === null || value === undefined || value === "") continue;
        if (Array.isArray(value)) continue;
        if (typeof value === "object" && value !== null) {
            pairs.push(`${key}=${JSON.stringify(value)}`);
            continue;
        }
        if (typeof value === "number" && value === 0) {
            pairs.push(`${key}=0`);
            continue;
        }
        pairs.push(`${key}=${value}`);
    }
    return pairs.length ? pairs.join("&") : null;
}

function buildParameterSign(data, timestamp) {
    const base = buildParameterBase(data);
    if (!base) return "";
    const salt = String(timestamp).substring(4, 10);
    return md5(md5(base) + salt);
}

function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

// ====================== Task ======================
class Task {
    constructor(serverEntry, index) {
        this.serverEntry = serverEntry;
        this.index = index;
        const { ref } = parseYybGoEntry(serverEntry);
        this.openid = ref;
        this.tmpToken = "";
        this.accessToken = "";
        this.memberId = "";
        this.userInfo = {};
    }

    applyToken(data = {}) {
        this.accessToken = data.accessToken || data.token || this.accessToken;
        this.memberId = String(data.memberId || this.memberId || "");
    }

    async request({ method = "POST", url, data = {}, params = {}, withAuth = true, withTmpToken = true }) {
        const timestamp = Date.now();
        const sign = md5(`${SMALL_APPLICATION_ID}${SMALL_CRYPTO}${timestamp}`).toLowerCase();
        const bodyForSign = method.toUpperCase() === "GET" ? params : data;
        const parameterSign = buildParameterSign(bodyForSign, timestamp);
        const headers = {
            "User-Agent": USER_AGENT,
            Referer: `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            Accept: "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Customer": this.memberId || "",
            brandCode: BRAND_CODE,
            appid: SMALL_APPLICATION_ID,
            "E-Opera": "",
            "xweb_xhr": "1",
            sign,
            timestamp,
            versionNumber: VERSION_NUMBER,
        };
        if (parameterSign) headers.parameterSign = parameterSign;
        if (withAuth && this.accessToken) headers.AccessToken = this.accessToken;
        if (withTmpToken && this.tmpToken) headers.tmpToken = this.tmpToken;

        const res = await axios.request({
            method,
            url,
            data,
            params,
            headers,
            timeout: 20000,
            validateStatus: () => true,
        });

        if (res.status !== 200) {
            throw new Error(`HTTP ${res.status}: ${JSON.stringify(res.data)}`);
        }
        const result = res.data || {};
        if (result.code !== undefined && ![0, 401, 402, 515].includes(Number(result.code))) {
            const err = new Error(result.message || result.msg || JSON.stringify(result));
            err.rawResponse = result;
            throw err;
        }
        return result;
    }

    async login() {
        const code = await getCode(this.serverEntry, MINI_APP_ID);
        const identify = await this.request({
            method: "POST",
            url: `${API_BASE}/api/user/identify`,
            params: { code },
            withAuth: false,
            withTmpToken: false,
        });
        if (identify.code !== 0 || !identify.data) {
            throw new Error(`identify失败: ${identify.message || JSON.stringify(identify)}`);
        }
        if (Number(identify.data.status) !== 4) {
            throw new Error(`登录状态异常: status=${identify.data.status}`);
        }
        this.tmpToken = identify.data.token || "";
        if (!this.tmpToken) throw new Error("identify未返回tmpToken");

        const auth = await this.request({
            method: "POST",
            url: `${API_BASE}/api/user/authorizeLogin`,
            data: { source: "顾家小程序", contentName: "" },
            withAuth: false,
            withTmpToken: true,
        });
        if (auth.code !== 0 || !auth.data?.token) {
            throw new Error(`authorizeLogin失败: ${auth.message || JSON.stringify(auth)}`);
        }
        this.accessToken = auth.data.token;
        this.memberId = String(auth.data.memberId || "");
        this.tmpToken = "";
    }

    async getUserInfo() {
        const info = await this.request({
            method: "POST",
            url: `${API_BASE}/api/user/info`,
            data: {},
            withAuth: true,
            withTmpToken: false,
        });
        if (!info.data) throw new Error("user/info返回为空");
        this.userInfo = info.data;
        this.applyToken(info.data);
        const openidMask = this.openid.length >= 12
            ? this.openid.slice(0, 6) + "..." + this.openid.slice(-6)
            : this.openid;
        const nick = this.userInfo.nickName || this.userInfo.name || "";
        const mobile = this.userInfo.mobile || "";
        let label = `【${openidMask}】`;
        if (nick) label += `(${nick})`;
        if (mobile) label += ` 手机：${mobile}`;
        console.log(`账号[${this.index}] 👤 用户: ${label}`);
    }

    async ensureLogin() {
        await this.login();
        await this.getUserInfo();
        console.log(`账号[${this.index}] ✅ 登录成功`);
    }

    async getPoints() {
        const ret = await this.request({
            method: "POST",
            url: `${API_BASE}/front/member/personalCenter`,
            data: { t: Date.now() },
            withAuth: true,
            withTmpToken: false,
        });
        if (!ret || ret.point === undefined) throw new Error("查询积分失败");
        return Number(ret.point || 0);
    }

    async getSignCalendar() {
        const ret = await this.request({
            method: "GET",
            url: `${INTEGRAL_BASE}/user/sign/calendar`,
            params: {},
            withAuth: true,
            withTmpToken: false,
        });
        if (ret.code !== 0) throw new Error(ret.message || ret.msg || "查询签到日历失败");
        return ret.data || {};
    }

    async sign() {
        let ret;
        try {
            ret = await this.request({
                method: "POST",
                url: `${INTEGRAL_BASE}/scenePoint/scene/point`,
                data: {
                    scene: "sign",
                    brandCode: BRAND_CODE,
                },
                withAuth: true,
                withTmpToken: false,
            });

            if (ret.code === 0) {
                const gain = typeof ret.data === "number" ? ret.data : null;
                return { status: "success", ret, gain };
            }

            const msg = ret.message || ret.msg || JSON.stringify(ret);
            if (/已签|重复|already|今日/.test(msg)) {
                return { status: "already", ret, gain: null };
            }

            throw new Error(msg);
        } catch (e) {
            const msg = e.message || String(e);
            if (/已签|重复|already|今日/.test(msg)) {
                return { status: "already", ret: e.rawResponse, gain: null };
            }
            console.log(`账号[${this.index}] ❌ 签到接口返回失败: ${msg}`);
            throw e;
        }
    }

    // ---- 做任务：社区互动（点赞/收藏/分享晒家帖子赚积分）----
    async getTaskList() {
        const ret = await this.request({
            method: "GET",
            url: `${API_BASE}/front/member/selectPointTask`,
            params: { brandCode: BRAND_CODE },
            withAuth: true,
            withTmpToken: false,
        });
        if (ret.code === 0 && Array.isArray(ret.data) && ret.data.length) {
            const names = ret.data
                .map((t) => t.taskName || t.name || t.title || JSON.stringify(t))
                .join("、");
            console.log(`账号[${this.index}] 📋 可接任务(${ret.data.length}): ${names}`);
        } else {
            console.log(`账号[${this.index}] 📋 无可用任务列表或查询失败`);
        }
        return ret.data || [];
    }

    async findPost() {
        for (let pageNum = 1; pageNum <= 5; pageNum++) {
            const ret = await this._safe("帖子列表", () =>
                this.request({
                    method: "POST",
                    url: `${API_BASE}/applet/waterfall/newWaterfall`,
                    data: { source: 1, pageNum, pageSize: 6 },
                    withAuth: true,
                    withTmpToken: false,
                })
            );
            if (!ret || ret.code !== 0) break;
            const items = Array.isArray(ret.data) ? ret.data : (ret.data && ret.data.list) || [];
            if (!items.length) break;
            for (const post of items) {
                const detail = await this._safe("帖子详情", () =>
                    this.request({
                        method: "POST",
                        url: `${API_BASE}/front/postOrder/postOrderDetail`,
                        data: { id: Number(post.id) },
                        withAuth: true,
                        withTmpToken: false,
                    })
                );
                if (detail && detail.code === 0 && detail.data) {
                    const likeStatus = detail.data.likeStatus;
                    const collectStatus = detail.data.collectStatus;
                    const untouched =
                        (likeStatus == null && collectStatus == null) ||
                        (String(likeStatus) === "0" && String(collectStatus) === "0");
                    if (untouched) {
                        const show = (post.title || "").toString().replace(/[\r\n]+/g, " ").trim();
                        console.log(`账号[${this.index}] 🔍 找到可互动帖子: 「${show}」`);
                        return post;
                    }
                }
            }
        }
        return null;
    }

    async _safe(marker, fn) {
        try {
            return await fn();
        } catch (e) {
            console.log(`账号[${this.index}] ⚠️ ${marker}: ${e.message || e}`);
            return null;
        }
    }

    async pushEvent(eventId, content, targetId, targetName, businessId, businessName) {
        return this._safe("事件上报", () =>
            this.request({
                method: "POST",
                url: `${API_BASE}/front/member/pushEvent`,
                data: { eventId, content, targetId, targetName, businessId, businessName },
                withAuth: true,
                withTmpToken: false,
            })
        );
    }

    async insertFootPoint(buriedPointLogo, subordinateTerminal, businessName, businessCode, currentPageLink) {
        return this._safe("埋点上报", () =>
            this.request({
                method: "POST",
                url: `${API_BASE}/front/foot/point/insertFootPoint`,
                data: {
                    brandCode: BRAND_CODE,
                    buriedPointLogo,
                    subordinateTerminal,
                    businessName: businessName || "",
                    businessCode: businessCode || "",
                    currentPageLink: currentPageLink || "",
                },
                withAuth: true,
                withTmpToken: false,
            })
        );
    }

    async likeSendPoint(postOrderId, triggerType, content, forwardType) {
        const data = { postOrderId: Number(postOrderId), triggerType, content };
        if (forwardType !== undefined) data.forwardType = forwardType;
        try {
            const ret = await this.request({
                method: "POST",
                url: `${API_BASE}/front/member/likeSendPoint`,
                data,
                withAuth: true,
                withTmpToken: false,
            });
            if (Number(ret.code) !== 0) {
                console.log(`账号[${this.index}] ⚠️ 送积分未成功: ${content} (code=${ret.code}, msg=${ret.message || ret.msg || ""})`);
            }
            return ret;
        } catch (e) {
            console.log(`账号[${this.index}] ❌ 送积分异常: ${content} (${e.message || e})`);
            return null;
        }
    }

    async likePost(post) {
        const postId = Number(post.id);
        const title = (post.title || post.id).toString().replace(/[\r\n]+/g, " ").trim();
        console.log(`账号[${this.index}] 👍 点赞: 「${title}」`);
        await this.pushEvent("c_showhome_like", "晒家-点赞", "300001", "晒家-点赞", String(postId), title);
        const likeRet = await this._safe("点赞", () =>
            this.request({ method: "POST", url: `${API_BASE}/front/postOrder/like`, data: { id: postId }, withAuth: true, withTmpToken: false })
        );
        if (!likeRet || Number(likeRet.code) !== 0) {
            console.log(`账号[${this.index}] ⚠️ 点赞接口未返回成功: ${JSON.stringify(likeRet && likeRet.data !== undefined ? likeRet.data : likeRet)}`);
        }
        await this.insertFootPoint("do_good_btn", "会员小程序", "", "", "");
        await this.likeSendPoint(postId, 1, "点赞");
    }

    async collectPost(post) {
        const postId = Number(post.id);
        const title = (post.title || post.id).toString().replace(/[\r\n]+/g, " ").trim();
        console.log(`账号[${this.index}] ⭐ 收藏: 「${title}」`);
        const collectRet = await this._safe("收藏", () =>
            this.request({ method: "POST", url: `${API_BASE}/front/postOrder/collect`, data: { id: postId }, withAuth: true, withTmpToken: false })
        );
        if (!collectRet || Number(collectRet.code) !== 0) {
            console.log(`账号[${this.index}] ⚠️ 收藏接口未返回成功: ${JSON.stringify(collectRet && collectRet.data !== undefined ? collectRet.data : collectRet)}`);
        }
        await this.insertFootPoint("buriedPointLogo", "会员小程序", "", "", "");
        await this.likeSendPoint(postId, 2, "收藏");
    }

    async sharePost(post) {
        const postId = Number(post.id);
        const title = (post.title || post.id).toString().replace(/[\r\n]+/g, " ").trim();
        console.log(`账号[${this.index}] 🔁 分享: 「${title}」`);
        const shareRet = await this._safe("分享", () =>
            this.request({ method: "POST", url: `${API_BASE}/front/postOrder/share`, data: { id: postId }, withAuth: true, withTmpToken: false })
        );
        if (!shareRet || Number(shareRet.code) !== 0) {
            console.log(`账号[${this.index}] ⚠️ 分享接口未返回成功: ${JSON.stringify(shareRet && shareRet.data !== undefined ? shareRet.data : shareRet)}`);
        }
        await this.insertFootPoint("share_friend_btn", "会员小程序", "", "", "");
        await this.likeSendPoint(postId, 3, "微信好友转发", 2);
    }

    async communityTasks() {
        if (String(process.env.GJJJ_COMMUNITY) === "0") {
            console.log(`账号[${this.index}] ℹ️ 已关闭社区互动(GJJJ_COMMUNITY=0)`);
            return;
        }
        try {
            const post = await this.findPost();
            if (!post) {
                console.log(`账号[${this.index}] ⚠️ 社区无未互动帖子`);
                return;
            }
            const title = (post.title || post.id).toString().replace(/[\r\n]+/g, " ").trim();
            console.log(`账号[${this.index}] 📝 社区互动帖子: 「${title}」`);

            await this.likePost(post);
            await this.collectPost(post);
            await this.sharePost(post);

            console.log(`账号[${this.index}] 🎉 社区互动结束 (赞1/藏1/享1)`);
        } catch (e) {
            console.log(`账号[${this.index}] ❌ 社区互动异常: ${e.message || e}`);
        }
    }

    async run() {
        try {
            await this.ensureLogin();
            const pStart = await this.getPoints().catch(() => null);
            if (pStart !== null) console.log(`账号[${this.index}] 💰 当前积分: 【${pStart}】`);

            const cal = await this.getSignCalendar().catch(() => null);
            if (cal === null) {
                console.log(`账号[${this.index}] ⚠️ 签到日历查询失败，将尝试执行签到`);
            }

            let signRes = null;
            let cal2 = cal;
            const signed = cal ? !!cal.isTodaySigned : null;
            if (signed !== true) {
                signRes = await this.sign();
                cal2 = await this.getSignCalendar().catch(() => null);
            }

            if ((signRes && signRes.status === "already") || (signed === true && !signRes)) {
                console.log(`账号[${this.index}] 📝 每日签到： ⚠️ 今日已签到`);
            } else {
                const signConfirmed = cal2 ? !!cal2.isTodaySigned : true;
                if (!signConfirmed) {
                    if (cal2 === null) {
                        console.log(`账号[${this.index}] 📝 每日签到： ⚠️ 签到后日历查询失败，无法确认是否生效`);
                    } else {
                        console.log(`账号[${this.index}] 📝 每日签到： ❌ 签到接口返回成功但日历未确认`);
                    }
                } else if (signRes && typeof signRes.gain === "number" && signRes.gain > 0) {
                    console.log(`账号[${this.index}] 📝 每日签到： 🎉 签到成功 (+${signRes.gain}积分)`);
                } else {
                    console.log(`账号[${this.index}] 📝 每日签到： 🎉 签到成功`);
                }
            }

            if (cal2 && cal2.signCount !== undefined && cal2.signCount !== null) {
                console.log(`账号[${this.index}] 📅 累计签到: 【${cal2.signCount}】天`);
            }

            await this.getTaskList().catch(() => {});
            await this.communityTasks().catch(() => {});

            let pEnd = pStart;
            let lastP = pStart;
            let stable = 0;
            for (let i = 0; i < 8; i++) {
                if (i > 0) await sleep(2500);
                const pTry = await this.getPoints().catch(() => null);
                if (pTry === null) continue;
                pEnd = pTry;
                if (pTry === lastP) {
                    stable++;
                    if (pTry !== pStart && stable >= 2) break;
                    if (stable >= 3) break;
                } else {
                    stable = 0;
                    lastP = pTry;
                }
            }
            if (pStart !== null) {
                const delta = pEnd - pStart;
                const signGain = signRes && typeof signRes.gain === "number" ? signRes.gain : 0;
                const communityGain = delta - signGain;
                const parts = [];
                if (signGain !== 0) parts.push(`签到+${signGain}积分`);
                if (communityGain !== 0) parts.push(`社区+${communityGain}积分`);
                const detail = parts.length ? `（${parts.join("，")}）` : "";
                const arrow = delta === 0 ? `【${pEnd}】` : `【${pStart}】→【${pEnd}】 本次 +${delta}积分${detail}`;
                console.log(`账号[${this.index}] 💰 积分: ${arrow}`);
            }
        } catch (e) {
            const msg = e.message || String(e);
            console.log(`账号[${this.index}] 执行失败: ${msg}`);
        }
    }
}

// ====================== 主入口 ======================
(async () => {
    console.log(`============ 顾家家居会员俱乐部 ============`);
    console.log(`共 ${SERVERS.length} 个账号`);
    for (let i = 0; i < SERVERS.length; i++) {
        await new Task(SERVERS[i], i + 1).run();
        if (i < SERVERS.length - 1) await sleep(3000);
    }
    console.log(`============ 顾家家居会员俱乐部 执行结束 ============`);
})().catch((e) => console.log(e.message || e));
