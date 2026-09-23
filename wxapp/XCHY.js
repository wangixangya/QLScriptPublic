// name: 携程会员
// cron: 24 7,19 * * *
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
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
    server = server.replace(/\/+$/, "");
    if (!server || !ref) return { server: "", ref: "" };
    return { server, ref };
}
async function getCode(server) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;
    const url = `${/^https?:\/\//i.test(parsedServer) ? parsedServer : `http://${parsedServer}`}/wxapp/getCode`;
    try {
        const { data } = await postJson(url, { ref, app_id: MINI_APP_ID }, {}, 20000);
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

const MINI_APP_ID = "wx0e6ed4f51db9d078";
const PACKAGE_VERSION = "1055";
const CLIENT_ID = "09031101311473737701";
const ACCESS_CODE = "XTHYY69RNSKLWEICHATMINI";
const API_BASE = "https://m.ctrip.com";
const SEC_API_BASE = "https://sec-m.ctrip.com";
const PASSPORT_BASE = "https://passport.ctrip.com/gateway/api";
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "ctrip_token_cache.json");
const NOTIFY_ENABLED = process.env.XCHY_NOTIFY !== "0";
try { fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true }); } catch (e) {}
const TASK_CHANNELS = [
  { label: "做任务赚积分", channelCode: "2H3294O46M" },
  { label: "升级赚积分", channelCode: "5EBG1WS7J1" },
];

global.wx = global.wx || { j() {} };
global.window = global.window || {};
global.navigator = global.navigator || {
  userAgent: "Mozilla/5.0 MicroMessenger MiniProgramEnv/Windows",
  plugins: [],
};
global.document = global.document || { cookie: "" };
global.screen = global.screen || { width: 1920, height: 1080 };

const csign = null;

function readCache() {
  try {
    if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
    return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
  } catch {
    return {};
  }
}

function writeCache(cache) {
  try {
    fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
  } catch (e) {
    console.log(`token缓存写入失败: ${e.message || e}`);
  }
}

function md5(text) {
  return crypto.createHash("md5").update(String(text)).digest("hex");
}

function mask(value = "") {
  value = String(value);
  if (!value) return "";
  if (value.length <= 12) return `${value.slice(0, 3)}***`;
  return `${value.slice(0, 6)}***${value.slice(-6)}`;
}

function parseJsonMaybe(text) {
  if (!text || typeof text !== "string") return text;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function postJson(url, data, headers = {}, timeout = 30000) {
  let lastError;
  for (let attempt = 1; attempt <= 2; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(data || {}),
        signal: controller.signal,
      });
      const text = await response.text();
      return { status: response.status, data: parseJsonMaybe(text), text };
    } catch (error) {
      lastError = error;
      if (attempt < 2) await sleep(800);
    } finally {
      clearTimeout(timer);
    }
  }
  throw new Error(`${new URL(url).host} 请求失败: ${lastError?.cause?.code || lastError?.message || lastError}`);
}

function parseAccount(raw) {
  const text = String(raw || "").trim();
  if (!text) return {};

  if (text.startsWith("{")) {
    try {
      const data = JSON.parse(text);
      return {
        openid: data.openid || data.openId || data.account || "",
        ticket: data.ticket || data.auth || "",
        duid: data.duid || "",
        udl: data.udl || "",
      };
    } catch {}
  }

  for (const sep of ["#", "|"]) {
    if (text.includes(sep)) {
      const [openid, ticket, duid, udl] = text.split(sep).map((v) => v.trim());
      return { openid, ticket, duid, udl };
    }
  }

  if (/^[A-Z0-9]{48,}$/i.test(text) && !/^o[A-Za-z0-9_-]{20,}$/.test(text)) {
    return { ticket: text };
  }
  return { openid: text };
}

function okResponseStatus(data) {
  return data?.ResponseStatus?.Ack === "Success" || data?.responseStatus?.ack === "Success";
}

function okBusiness(data) {
  const code = Number(data?.code);
  return okResponseStatus(data) && (code === 0 || code === 200);
}

function taskId(task = {}) {
  return task.id || task.taskId || task.taskID || task.taskNo || "";
}

function taskTitle(task = {}) {
  return task.displayName || task.internalName || task.taskName || task.title || task.name || task.buttonName || `任务${taskId(task)}`;
}

function taskErrorText(data = {}) {
  const code = Number(data?.code);
  const messages = {
    400121: "任务行为校验未通过，需在真实页面内完成",
    400134: "任务类型禁止接口直接上报，需完成指定页面或活动",
    401010: "当前不可领取该奖励",
    410200: "该任务不支持当前领奖方式",
    404001: "携程登录态无效",
    404002: "账号不满足活动参与条件",
  };
  return messages[code] || data?.message || "未知错误";
}

class AccountError extends Error {
  constructor(kind, message) {
    super(message);
    this.kind = kind;
  }
}

function loggedIn(data = {}) {
  const status = data?.baseLoginStatus;
  return okBusiness(data) && (status === true || Number(status) === 1);
}

function awardErrorText(data = {}) {
  const code = Number(data?.code);
  const messages = {
    401010: "当前不可领取该升级奖励",
    404001: "登录状态无效",
    404002: "不满足活动参与条件",
    500027: "需要滑块验证，已跳过",
  };
  const message = String(data?.message || "");
  if (messages[code]) return messages[code];
  if (/SUCCESS/i.test(message)) return "成功";
  if (/CITY_ID/i.test(message)) return "当前旅行城市状态不满足领奖条件";
  return message || "领取失败";
}

function chineseMessage(message, fallback = "成功") {
  const text = String(message || "").trim();
  return !text || /^SUCCESS$/i.test(text) ? fallback : text;
}

async function sendQingLongNotify(lines) {
  if (!NOTIFY_ENABLED) {
    console.log("青龙通知已关闭（XCHY_NOTIFY=0）");
    return;
  }
  const candidates = [
    "./sendNotify",
    path.join(process.cwd(), "sendNotify"),
    "/ql/data/scripts/sendNotify",
  ];
  let sender = null;
  for (const candidate of candidates) {
    try {
      const mod = require(candidate);
      sender = mod?.sendNotify || (typeof mod === "function" ? mod : null);
      if (typeof sender === "function") break;
    } catch {}
  }
  if (typeof sender !== "function") {
    console.log("青龙通知发送失败：未找到 sendNotify 模块");
    return;
  }
  try {
    await sender("携程会员任务", lines.join("\n"), { disableHitokoto: true });
    console.log("青龙通知发送成功");
  } catch (e) {
    console.log(`青龙通知发送失败：${e.message || e}`);
  }
}

function pickTasks(data = {}) {
  const keys = ["taskList", "todoTaskList", "finishTaskList", "filteredTaskList"];
  const map = new Map();
  for (const key of keys) {
    const list = Array.isArray(data[key]) ? data[key] : [];
    for (const item of list) {
      const id = taskId(item);
      if (id && !map.has(String(id))) map.set(String(id), item);
    }
  }
  return [...map.values()];
}

async function gateway(pathname, data) {
  const res = await postJson(`${PASSPORT_BASE}/${pathname}`, data, {
      "User-Agent": "Mozilla/5.0 MicroMessenger MiniProgramEnv/Windows",
      Referer: `https://servicewechat.com/${MINI_APP_ID}/${PACKAGE_VERSION}/page-frame.html`,
  });
  if (res.status !== 200 || Number(res.data?.ReturnCode) !== 0) {
    throw new Error(`${pathname}失败: ${JSON.stringify(res.data)}`);
  }
  return parseJsonMaybe(res.data.Result || "{}");
}

async function h5Api(pathname, data, account) {
  const cookies = [];
  if (account.ticket) cookies.push(`cticket=${account.ticket}`);
  if (account.duid) cookies.push(`DUID=${encodeURIComponent(account.duid)}`);
  if (account.udl) cookies.push(`_udl=${account.udl}`);
  cookies.push(`GUID=${CLIENT_ID}`);
  const base = /^\/restapi\/soa2\/22769\//.test(pathname) ? SEC_API_BASE : API_BASE;
  const res = await postJson(`${base}${pathname}`, data || {}, {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF",
      Referer: "https://m.ctrip.com/",
      Cookie: `${cookies.join("; ")};`,
  });
  return {
    status: res.status,
    data: res.data,
    text: typeof res.data === "string" ? res.data : JSON.stringify(res.data),
  };
}

class Task {
  constructor(raw) {
    this.server = raw;
    const yyb = parseYybGoEntry(raw);
    this.ref = yyb.ref;
    this.index = userIdx++;
    this.openid = "";
    this.ticket = "";
    this.duid = "";
    this.udl = "";
    this.uid = "";
    this.authToken = "";
    this.cacheKey = this.ref || `account_${this.index}`;
    this.initialPoints = null;
    this.finalPoints = null;
    this.summary = "未执行";
  }

  getCached() {
    return readCache()[this.cacheKey] || {};
  }

  saveCache(extra = {}) {
    const cache = readCache();
    cache[this.cacheKey] = {
      ...(cache[this.cacheKey] || {}),
      ...(this.openid ? { openid: this.openid } : {}),
      ...(this.ticket ? { ticket: this.ticket } : {}),
      ...(this.duid ? { duid: this.duid } : {}),
      ...(this.udl ? { udl: this.udl } : {}),
      ...(this.uid ? { uid: this.uid } : {}),
      ...(this.authToken ? { authToken: this.authToken } : {}),
      ...extra,
      updatedAt: new Date().toISOString(),
    };
    writeCache(cache);
  }

  clearCachedLogin() {
    const cache = readCache();
    if (cache[this.cacheKey]) {
      for (const key of ["ticket", "duid", "udl", "uid", "authToken"]) delete cache[this.cacheKey][key];
      writeCache(cache);
    }
    this.ticket = "";
    this.duid = "";
    this.udl = "";
    this.uid = "";
    this.authToken = "";
  }

  async getOperateData() {
    const code = await getCode(this.server);
    return { code, encryptedData: "", iv: "" };
  }

  async login() {
    const op = await this.getOperateData();
    if (!op.code) throw new AccountError("login_failed", "获取微信登录凭证失败");
    const wxLogin = await gateway("soa2/14553/wechatLogin.json", {
      AccountHead: {},
      Data: {
        authCode: op.code,
        thirdConfigCode: ACCESS_CODE,
        Context: {},
      },
    });
    if (!wxLogin?.wechatCode || wxLogin?.resultStatus?.returnCode !== 0) {
      throw new Error(`wechatLogin未返回wechatCode: ${JSON.stringify(wxLogin)}`);
    }

    const auth = await gateway("soa2/14553/authenticate.json", {
      AccountHead: {},
      Data: {
        authCode: wxLogin.wechatCode,
        thirdType: "wechat_app",
        thirdConfigCode: ACCESS_CODE,
        context: {
          encryptedData: op.encryptedData,
          iv: op.iv,
          uuid: "",
        },
      },
    });
    if (!auth?.token || auth?.resultStatus?.returnCode !== 0) {
      throw new Error(`authenticate未返回第三方token: ${JSON.stringify(auth)}`);
    }
    this.authToken = auth.token;

    const login = await gateway("soa2/12559/thirdPartyLogin.json", {
      AccountHead: {},
      Data: {
        accountHead: {
          locale: "zh_CN",
          platform: "MINIAPP",
        },
        token: auth.token,
        extendedProperties: {
          clientID: CLIENT_ID,
          page_id: "",
          Url: "",
          thirdConfigCode: ACCESS_CODE,
          deviceName: "Windows PC",
          OsType: "windows",
        },
      },
    });
    if (!login?.ticket || login?.resultStatus?.returnCode !== 0) {
      if (Number(login?.resultStatus?.returnCode) === 550005) {
        throw new AccountError("unbound", "未绑定携程，登录失败");
      }
      throw new AccountError("login_failed", `携程登录失败（代码 ${login?.resultStatus?.returnCode ?? "未知"}）`);
    }

    this.ticket = login.ticket;
    this.duid = login.duid || login.extendedProperties?.duid || "";
    this.udl = login.udl || "";
    this.uid = login.uid || "";
    this.saveCache({ isNewUser: login.extendedProperties?.isNewUser || "" });
    console.log(`账号[${this.index}] 登录成功: ${mask(this.uid || this.ticket)}`);
  }

  async ensureLogin() {
    const cached = this.getCached();
    this.ticket = this.ticket || cached.ticket || "";
    this.duid = this.duid || cached.duid || "";
    this.udl = this.udl || cached.udl || "";
    this.uid = this.uid || cached.uid || "";
    this.authToken = this.authToken || cached.authToken || "";
    if (this.ticket && await this.validateLogin()) return;
    if (this.ticket) {
      console.log(`账号[${this.index}] 缓存登录态已失效，重新登录`);
      this.clearCachedLogin();
    }
    await this.login();
    if (!await this.validateLogin()) {
      this.clearCachedLogin();
      throw new AccountError("login_failed", "登录状态无效");
    }
  }

  async validateLogin() {
    const point = await this.h5Model("22769", "getSignInUserBasicInfo", {});
    return point.status === 200 && loggedIn(point.data);
  }

  headers(raw) {
    const headers = {
      "Content-Type": "application/json",
      Accept: "*/*",
      "x-ctx-locale": "zh-CN",
      "x-ctx-group": "ctrip",
      "x-ctx-region": "CN",
      "x-ctx-currency": "CNY",
      "x-wx-include-credentials": "env",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF",
      Referer: `https://servicewechat.com/${MINI_APP_ID}/${PACKAGE_VERSION}/page-frame.html`,
    };
    if (this.openid) headers["x-wx-openid"] = this.openid;
    if (this.duid) headers.duid = this.duid;
    if (this.udl) headers.udl = this.udl;
    const cookies = [];
    if (this.duid) cookies.push(`DUID=${encodeURIComponent(this.duid)}`);
    if (this.udl) cookies.push(`_udl=${this.udl}`);
    cookies.push(`GUID=${CLIENT_ID}`);
    headers.Cookie = `${cookies.join("; ")};`;
    if (csign?.cSign) headers["n-payload-source"] = csign.cSign(md5(raw));
    return headers;
  }

  dataHead(extra = {}) {
    const { useAuthToken = false, ...fields } = extra;
    return {
      cid: CLIENT_ID,
      ctok: "",
      cver: "1.2.170",
      lang: "01",
      sid: "",
      syscode: "30",
      auth: useAuthToken ? (this.authToken || "") : "",
      sauth: "",
      ...fields,
      extension: [
        { name: "appId", value: MINI_APP_ID },
        { name: "scene", value: "1001" },
      ],
    };
  }

  async ctripRequest(pathname, data = {}, { addHead = true } = {}) {
    const body = { ...(data || {}) };
    if (addHead) body.head = this.dataHead(body.head || {});
    const raw = JSON.stringify(body);
    const res = await postJson(`${API_BASE}${pathname}?_fxpcqlniredt=${CLIENT_ID}`, body, this.headers(raw));
    return {
      status: res.status,
      data: res.data,
      text: typeof res.data === "string" ? res.data : JSON.stringify(res.data),
    };
  }

  async querySignStatus() {
    const res = await this.ctripRequest("/restapi/soa2/13012/getSignTodayInfoProxy", { head: this.dataHead({ useAuthToken: true }) });
    if (res.status === 401 && res.data?.code === "11001") {
      console.log(`账号[${this.index}] 签到状态接口被携程运行态校验拦截: ${res.data.message}`);
      return null;
    }
    if (res.status !== 200) {
      console.log(`账号[${this.index}] 签到状态查询异常[${res.status}]: ${res.text.slice(0, 300)}`);
      return null;
    }
    if (!okResponseStatus(res.data)) {
      console.log(`账号[${this.index}] 签到状态查询失败: ${res.text.slice(0, 500)}`);
      return null;
    }
    const info = parseJsonMaybe(res.data.responseJson || "{}");
    const signed = !!(info && info.message === "成功" && info.sign === false);
    console.log(`账号[${this.index}] 今日签到状态: ${signed ? "已签到" : "未签到/未知"}`);
    return { signed, raw: info };
  }

  async trySignEndpoint(pathname) {
    const payloads = [
      {},
      { activityId: "wechat_signin_activity" },
      { source: "wxapp", activityId: "wechat_signin_activity" },
    ];
    for (const payload of payloads) {
      const res = await this.ctripRequest(pathname, payload);
      const body = res.text.slice(0, 600);
      if (res.status === 200 && (okResponseStatus(res.data) || /成功|已签到|sign/i.test(body))) {
        console.log(`账号[${this.index}] 签到接口 ${pathname} 返回: ${body}`);
        return true;
      }
      if (res.status !== 404 && res.status !== 403) {
        console.log(`账号[${this.index}] 候选接口 ${pathname} [${res.status}]: ${body}`);
      }
    }
    return false;
  }

  async sign() {
    await this.querySignStatus();
    const res = await h5Api("/restapi/soa2/22769/signToday", { openId: this.openid || "" }, this);
    if (res.status !== 200) {
      console.log(`账号[${this.index}] 签到请求异常[${res.status}]: ${res.text.slice(0, 500)}`);
      return;
    }
    if (okResponseStatus(res.data)) {
      const message = res.data.message || "";
      const points = Number(res.data.baseIntegratedPoint || 0) + Number(res.data.extraIntegratedPoint || 0);
      if (Number(res.data.code) === 0 || /成功/.test(message)) {
        console.log(`账号[${this.index}] 签到成功: ${message || "成功"}${points ? `，积分+${points}` : ""}`);
      } else if (/已签到|无法补签/.test(message) || Number(res.data.code) === 400001) {
        console.log(`账号[${this.index}] 今日已签到: ${message}`);
      } else {
        console.log(`账号[${this.index}] 签到返回: ${res.text.slice(0, 800)}`);
      }
      return;
    }
    console.log(`账号[${this.index}] 签到失败: ${res.text.slice(0, 800)}`);
  }

  async h5Model(code, name, data = {}) {
    return h5Api(`/restapi/soa2/${code}/${name}`, data, this);
  }

  async taskModel(name, data = {}) {
    const res = await this.h5Model("22598", name, data);
    if (res.status !== 200) {
      console.log(`账号[${this.index}] 任务接口 ${name} 异常[${res.status}]: ${res.text.slice(0, 500)}`);
      return null;
    }
    if (!okBusiness(res.data)) {
      const code = res.data?.code ?? "未知";
      console.log(`账号[${this.index}] 任务接口 ${name} 失败: ${taskErrorText(res.data)}（代码 ${code}）`);
      return res.data;
    }
    return res.data;
  }

  async queryTaskList(channelCode, label) {
    const payload = {
      channelCode,
      rmsToken: "",
      platform: "miniProgram",
      oAuthHead: {},
      version: "3",
      osType: "ios",
      appVersion: "",
      subOsType: "iphone",
    };
    if (channelCode === "2H3294O46M") {
      payload.extMap = { mktTaskSort: "", filterFields: "", blackField: "" };
    }
    const data = await this.taskModel("userTaskList", payload);
    if (!data) return [];
    if (Object.prototype.hasOwnProperty.call(data, "isLogin") && Number(data.isLogin) !== 1) {
      throw new AccountError("login_failed", "登录状态无效");
    }
    const tasks = pickTasks(data);
    console.log(
      `账号[${this.index}] ${label}: ${data.projectName || channelCode}，待做${(data.todoTaskList || []).length}，已完成${(data.finishTaskList || []).length}，过滤${(data.filteredTaskList || []).length}`
    );
    if (!tasks.length) console.log(`账号[${this.index}] ${label}: 暂无可处理任务`);
    return tasks;
  }

  async receiveTaskAward(channelCode, task, receivedTaskId) {
    const id = taskId(task);
    if (!id || !receivedTaskId) return;
    const data = await this.taskModel("receiveTaskAward", {
      channelCode,
      taskId: id,
      receiveTaskId: receivedTaskId,
    });
    if (okBusiness(data)) {
      console.log(`账号[${this.index}] 领取任务发奖成功: ${taskTitle(task)}，${chineseMessage(data.message)}`);
    }
  }

  async doTask(channelCode, task, label) {
    const id = taskId(task);
    if (!id) return;
    const status = Number(task.status ?? task.taskStatus ?? 0);
    const title = taskTitle(task);
    const base = { channelCode, taskId: id, status: 0 };
    console.log(`账号[${this.index}] ${label} 执行任务: ${title}，status=${status}`);
    let receivedTaskId = "";
    if (status === 0) {
      const receive = await this.taskModel("todoTask", { ...base, done: 0 });
      if (!okBusiness(receive)) return;
      receivedTaskId = receive?.infoMap?.receivedTaskId || receive?.receivedTaskId || "";
      console.log(`账号[${this.index}] ${label} 任务领取成功: ${title}`);
    }

    await sleep(1200);
    const done = await this.taskModel("todoTask", { ...base, done: 1 });
    if (okBusiness(done)) {
      console.log(`账号[${this.index}] ${label} 浏览完成上报成功: ${title}，${chineseMessage(done.message)}`);
      receivedTaskId ||= done?.infoMap?.receivedTaskId || done?.receivedTaskId || "";
      await this.receiveTaskAward(channelCode, task, receivedTaskId);
    }
  }

  async awardTask(channelCode, task, label) {
    const id = taskId(task);
    if (!id) return;
    const data = await this.taskModel("awardTask", { channelCode, taskId: id });
    if (okBusiness(data)) {
      const award = chineseMessage(data.awardName || data.rewardName || data.message);
      console.log(`账号[${this.index}] ${label} 领奖成功: ${taskTitle(task)}，${award}`);
    } else if (data) {
      console.log(`账号[${this.index}] ${label} 领奖失败: ${taskTitle(task)}，${taskErrorText(data)}（代码 ${data.code ?? "未知"}）`);
    }
  }

  async runTaskChannel({ channelCode, label }) {
    let tasks = await this.queryTaskList(channelCode, label);
    for (const task of tasks) {
      const status = Number(task.status ?? task.taskStatus ?? 0);
      if (status === 0 || status === 1) {
        await this.doTask(channelCode, task, label);
        await sleep(1000);
      }
    }

    tasks = await this.queryTaskList(channelCode, `${label}复查`);
    for (const task of tasks) {
      const status = Number(task.status ?? task.taskStatus ?? 0);
      if (status === 2) {
        await this.awardTask(channelCode, task, label);
        await sleep(1000);
      } else if (status === 3) {
        console.log(`账号[${this.index}] ${label} 已完成: ${taskTitle(task)}`);
      }
    }
  }

  async queryPointInfo() {
    const point = await this.h5Model("22769", "getSignInUserBasicInfo", {});
    if (point.status === 200 && loggedIn(point.data)) {
      const value = Number(point.data.integratedPoint);
      console.log(`账号[${this.index}] 当前会员积分: ${Number.isFinite(value) ? value : "未知"}`);
      return Number.isFinite(value) ? value : null;
    } else {
      throw new AccountError("login_failed", "登录状态无效，积分查询失败");
    }
  }

  async queryYoyoInfo() {
    const yoyo = await this.h5Model("22769", "travelGameUserAccountInfo", {});
    if (yoyo.status === 200 && okBusiness(yoyo.data)) {
      const info = yoyo.data.travelGameUserInfoDto || {};
      const travel = yoyo.data.travelGameUserTravelDto || {};
      const levelText = info.levelName || (info.level ? `LV${info.level}` : "");
      console.log(
        `账号[${this.index}] YOYO信息: ${levelText}，${info.titleName || ""}，还差${info.needFishCount ?? "未知"}条小鱼升级，旅行状态${travel.travelStatus ?? yoyo.data.travelStatus ?? "未知"}`
      );
    } else {
      console.log(`账号[${this.index}] YOYO信息查询失败: ${yoyo.text.slice(0, 500)}`);
    }
  }

  async tryUpgradeAwards() {
    const awards = [
      { name: "travelGameFirstTimeFishAward", label: "首次小鱼升级奖励" },
      { name: "travelGameDailyFishAward", label: "每日小鱼升级奖励" },
      { name: "travelGameTravelAward", label: "云旅行升级奖励" },
    ];
    for (const item of awards) {
      const data = await this.h5Model("22769", item.name, { platform: "H5" });
      if (data.status !== 200) {
        console.log(`账号[${this.index}] ${item.label} 请求异常[${data.status}]: ${data.text.slice(0, 300)}`);
        continue;
      }
      if (okBusiness(data.data)) {
        const exp = data.data.expChangeResultDto || {};
        const point = exp.levelUpIntegralNumber || data.data.travelIntegralNumber || 0;
        console.log(
          `账号[${this.index}] ${item.label} 领取成功: ${data.data.message || "成功"}${point ? `，积分+${point}` : ""}${exp.levelUp ? "，已升级" : ""}`
        );
      } else if (Number(data.data?.code) === 500027) {
      } else {
        console.log(`账号[${this.index}] ${item.label}: ${awardErrorText(data.data)}（代码 ${data.data?.code ?? "未知"}）`);
      }
      await sleep(1000);
    }
  }

  async run() {
    await this.ensureLogin();
    this.initialPoints = await this.queryPointInfo();
    await this.queryYoyoInfo();
    await this.sign();
    for (const channel of TASK_CHANNELS) {
      await this.runTaskChannel(channel);
    }
    await this.tryUpgradeAwards();
    this.finalPoints = await this.queryPointInfo();
    await this.queryYoyoInfo();
    this.summary = "执行完成";
    this.saveCache();
  }
}

!(async () => {
  const results = [];
  for (const account of SERVERS) {
    const task = new Task(account);
    try {
      await task.run();
    } catch (e) {
      task.summary = e?.kind === "unbound" ? "未绑定携程，登录失败" : (e.message || "执行失败");
      console.log(`账号[${task.index}] ${task.summary}`);
    }
    results.push(task);
    await sleep(1000);
  }

  console.log("\n===== 执行总结 =====");
  const summaryLines = [];
  for (const task of results) {
    if (task.summary === "未绑定携程，登录失败") {
      const line = `账号${task.index}：${task.summary}`;
      console.log(line);
      summaryLines.push(line);
      continue;
    }
    const initial = task.initialPoints ?? "未知";
    const final = task.finalPoints ?? "未知";
    const line = `账号${task.index}：${task.summary}，初始积分${initial} → 结束积分${final}`;
    console.log(line);
    summaryLines.push(line);
  }
  await sendQingLongNotify(summaryLines);
})()
  .catch((e) => console.log(e.message || e))
