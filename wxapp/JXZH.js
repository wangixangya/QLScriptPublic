// name: 匠心中华
// cron: 8 13,1 * * *
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
async function getCode(server) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;
    const url = "http://" + parsedServer + "/wxapp/getCode";
    try {
        const { data } = await axios.post(url, { ref, app_id: 'wxddaa0832e6acc5f1' }, { timeout: 20000, proxy: false });
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

const APP = { name: "趣蛙/匠心优选", appid: "wxddaa0832e6acc5f1" };

const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

function short(value, max = 220) {
    if (value === undefined || value === null) return "";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > max ? `${text.slice(0, max)}...` : text;
}

function md5(text) {
    return crypto.createHash("md5").update(String(text)).digest("hex");
}

function sha1(text) {
    return crypto.createHash("sha1").update(String(text)).digest("hex");
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


class Quwa {
    constructor(openid) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.openid = openid;
        this.base = "https://api.quwayouxuan.com";
        this.token = "";
        this.userID = "";
        this.globalData = {
            current_time: Date.now(),
            os: "miniProgram",
            deviceabout: "miniProgram",
            version: "1.3.01",
            miniprogram_os: "",
        };
    }

    signKey(data) {
        const sorted = {};
        Object.keys(data || {})
            .sort()
            .forEach((key) => {
                sorted[key] = data[key];
            });
        const text = Object.keys(sorted)
            .map((key) => `${key}=${sorted[key]}`)
            .join("");
        const encoded = encodeURIComponent(`${text}superjing`.replace(/\s+/g, ""))
            .replace(/%20/gi, "")
            .replace(/(!)|(')|(\()|(\))|(\~)|(\*)/gi, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
        return sha1(encoded);
    }

    async api(path, data = {}) {
        const body = {
            ...this.globalData,
            current_time: Date.now(),
            ...(this.token ? { token: this.token } : {}),
            ...data,
        };
        body.key = this.signKey(body);
        const res = await request({
            method: "POST",
            url: `${this.base}${path}`,
            headers: { "content-type": "application/x-www-form-urlencoded" },
            data: new URLSearchParams(Object.entries(body).map(([k, v]) => [k, String(v)])).toString(),
        });
        return res.data;
    }

    async login() {
        const code = await getWxCode(this.server);
        const login = await this.api("/mini_program/get_openid.do", { code });
        if (String(login?.code) !== "1" || !login?.data?.token) throw new Error(`登录失败: ${short(login)}`);
        this.token = login.data.token;
        const check = await this.api("/consumer/consumer/checkOpenid.do", { invitation: "" });
        const data = check?.data || {};
        this.userID = data.userID || data.userid || data.id || login.data.userID || "";
        return `openid=${login.data.openid || ""} userID=${this.userID || "未知"}`;
    }

    async query() {
        const center = await this.api("/dmluser/center.do", {});
        const info = center?.data?.user_info || center?.data?.userinfo || center?.data || {};
        const score = info.integral || info.score || info.points || info.balance || info.user_integral;
        const name = info.nickname || info.nickName || info.mobile || info.username || "";
        return `用户=${name || "未知"} 积分=${score ?? "未知"} 返回=${short(center, 180)}`;
    }

    async sign() {
        const tasks = await this.api("/task/task/taskList.do", { source: 4 });
        const day = tasks?.data?.tasklist?.day || [];
        const task =
            day.find((item) => /签到|每日|趣赚分|积分/.test(`${item.name || item.title || ""}`) && String(item.status || item.is_finish || "") !== "1") ||
            day.find((item) => String(item.type) === "1" && String(item.status || item.is_finish || "") !== "1");
        if (!task) return `未找到可完成签到任务: taskList=${short(tasks, 220)}`;
        if (task.skiprule && task.skiprule !== "") return `任务需要跳转/广告，跳过: ${short(task)}`;
        const requestId = md5(`${this.userID}aopijkks${Date.now()}`);
        const sign = await this.api("/task/task/taskSuccrss.do", {
            taskid: task.id,
            subtask_id: task.subtask_id,
            request_id: requestId,
        });
        return `任务=${task.name || task.title || task.id} 返回=${short(sign)}`;
    }
}

async function runAccount(openid, index) {
    console.log(`\n========== ${APP.name} 账号[${index}] ${openid} ==========`);
    const runner = new Quwa(openid);
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
