// name: 名创优品
// cron: 30 8,20 * * *
const axios = require('axios');
const CryptoJS = require('crypto-js');
const fs = require('fs');
const path = require('path');

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
const APPID = 'wx2a212470bade49bf';
const AES_KEY_HEX = '0f9f8b1e791f754d2ded9dfb38a4b628';
const AES_IV_HEX = '31323334353637383930313233343535';
const SIGN_PREFIX = '#storeexpress1.0#ffe232&t%4df!67sx55eas#';
const LOGIN_URL = 'https://cdn-storeexpress.miniso.com/wechat/login';
const CACHE_FILE = path.join(__dirname, 'mcypcookie.json');
const DEFAULT_STORE_ID = 'Z6XV';

// ====================== 工具函数 ======================
function generateLoginNonce() {
    const chars = '1234567890qwertyuiopasdfghjklzxc';
    let result = '';
    for (let i = 0; i < 32; i++) {
        result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
}

function aesEncrypt(plainText) {
    const key = CryptoJS.enc.Hex.parse(AES_KEY_HEX);
    const iv = CryptoJS.enc.Hex.parse(AES_IV_HEX);
    const encrypted = CryptoJS.AES.encrypt(plainText, key, {
        iv: iv,
        mode: CryptoJS.mode.CBC,
        padding: CryptoJS.pad.Pkcs7
    });
    return encrypted.ciphertext.toString(CryptoJS.enc.Hex);
}

function calcStoreExpressSign(time, nonce) {
    const str = `${SIGN_PREFIX}${time}#${nonce}`;
    return CryptoJS.MD5(str).toString().toUpperCase();
}

function loadCache() {
    try {
        if (fs.existsSync(CACHE_FILE)) {
            const data = fs.readFileSync(CACHE_FILE, 'utf-8');
            return JSON.parse(data);
        }
    } catch (e) {
        console.log('读取缓存文件失败，将重新获取token');
    }
    return {};
}

function saveCache(cache) {
    try {
        fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2), 'utf-8');
    } catch (e) {
        console.log('写入缓存文件失败:', e.message);
    }
}

async function getWxCode(server, ref) {
    try {
        const res = await axios.post(`http://${server}/wxapp/getCode`, {
            app_id: APPID,
            ref: String(ref)
        });
        if (res.data.code === 0 && res.data.data?.result?.code) {
            return res.data.data.result.code;
        }
        console.log(`✗ 获取账号${ref}的code失败:`, res.data.message || res.data.msg || '未知错误');
        return null;
    } catch (e) {
        console.log(parsedServer + " 获取code异常: " + e.message);;
        return null;
    }
}

async function loginByCode(code) {
    try {
        const time = Date.now().toString();
        const nonce = generateLoginNonce();
        const signature = calcStoreExpressSign(time, nonce);

        const plainBody = JSON.stringify({
            code: code,
            appid: APPID,
            isreturnuserinfo: 1
        });
        const encryptedBody = aesEncrypt(plainBody);

        const headers = {
            'content-type': 'application/json',
            'version': 'storeexpress1.0',
            'tenant-code': 'MINISO',
            'can-flash-send': 'false',
            'content-sceneid': '1027',
            'x-client-source': 'MINISO_WX_MINI',
            'content-longitude': '[object Undefined]',
            'content-latitude': '[object Undefined]',
            'content-weappcode': '',
            'content-appcode': '',
            'content-uid': '',
            'content-skey': '',
            'content-openid': '',
            'content-unionid': '',
            'content-pagetype': '%E9%A6%96%E9%A1%B5',
            'content-pagename': '%E9%A6%96%E9%A1%B5',
            'nonce': nonce,
            'time': time,
            'signature': signature,
            'charset': 'utf-8',
            'referer': 'https://servicewechat.com/wx2a212470bade49bf/1110/page-frame.html',
            'user-agent': 'Mozilla/5.0 (Linux; Android 16; 2308CPXD0C Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.178 Mobile Safari/537.36 XWEB/1460217 MMWEBSDK/20260202 MMWEBID/6435 MicroMessenger/8.0.70.3060(0x28004652) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android',
            'accept-encoding': 'gzip, deflate, br'
        };

        const res = await axios.post(LOGIN_URL, encryptedBody, { headers });
        if (res.data.code === 200 && res.data.data?.skey) {
            const data = res.data.data;
            return {
                openid: data.openid,
                unionid: data.unionid,
                skey: data.skey,
                uid: String(data.uid),
                phone: data.mobile,
                storeId: DEFAULT_STORE_ID
            };
        }
        console.log('✗ 登录失败:', res.data.message || res.data.msg || '未知错误');
        return null;
    } catch (e) {
        console.log('✗ 登录请求出错:', e.message);
        return null;
    }
}

async function refreshAccountToken(server, ref) {
    const code = await getWxCode(server, ref);
    if (!code) return null;
    return await loginByCode(code);
}

// ====================== 业务类 ======================
class MinisoBot {
    constructor(config) {
        this.headers = {
            'host': 'api-saas.miniso.com',
            'content-pagetype': '%E6%BD%AC%E7%8E%A9%E7%AD%BE%E5%88%B0%E9%A1%B5%E9%9D%A2',
            'x-mi-store-id': config.storeId || 'Z6XV',
            'xweb_xhr': '1',
            'content-sceneid': '1256',
            'content-type': 'application/json',
            'content-weappcode': '52',
            'tenant-code': 'MINISO',
            'content-appcode': '51',
            'content-pagename': '%E6%BD%AC%E7%8E%A9%E7%AD%BE%E5%88%B0%E9%A1%B5%E9%9D%A2',
            'tenant': 'MINISO',
            'x-mi-version': '5.1.64',
            'x-client-source': 'MINISO_WX_MINI',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254181d) XWEB/19339',
            'version': 'storeexpress1.0',
            'accept': '*/*',
            'sec-fetch-site': 'cross-site',
            'sec-fetch-mode': 'cors',
            'sec-fetch-dest': 'empty',
            'referer': 'https://servicewechat.com/wx2a212470bade49bf/1084/page-frame.html',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'zh-CN,zh;q=0.9',
            'priority': 'u=1, i',
            'can-flash-send': 'true'
        };

        this.skey = config.skey;
        this.openid = config.openid;
        this.unionid = config.unionid;
        this.uid = config.uid;
        this.phone = config.phone;
        this.storeId = config.storeId || 'Z6XV';

        this.updateHeaders();
    }

    updateHeaders() {
        this.headers['content-skey'] = this.skey;
        this.headers['content-openid'] = this.openid;
        this.headers['content-unionid'] = this.unionid;
        this.headers['content-uid'] = this.uid;
        this.headers['content-latitude'] = '[object Undefined]';
        this.headers['content-longitude'] = '[object Undefined]';
        this.headers['x-mi-city'] = '';
        this.headers['x-mi-store-id'] = this.storeId;
    }

    md5(str) {
        return CryptoJS.MD5(str).toString().toUpperCase();
    }

    getTimestamp() {
        return Date.now();
    }

    generateNonce() {
        const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
        let result = '';
        for (let i = 0; i < 32; i++) {
            result += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        return result;
    }

    updateRequestHeaders(headers) {
        const timestamp = this.getTimestamp();
        const nonce = this.generateNonce();
        headers['time'] = timestamp;
        headers['nonce'] = nonce;
        return { headers, timestamp, nonce };
    }

    async getVirtualCoinInfo() {
        try {
            let reqData = this.updateRequestHeaders({ ...this.headers });
            reqData.headers['signature'] = this.md5('virtualCoinMember' + reqData.timestamp + reqData.nonce);
            const response = await axios.get(
                'https://api-saas.miniso.com/task-manage-platform/api/virtualCoin/member',
                { headers: reqData.headers }
            );
            if (response.data.code === 200) {
                console.log(`✓ 虚拟币信息获取成功: 当前mini币余额 ${response.data.data.quantity}`);
                return response.data.data;
            } else {
                console.log(`✗ 获取虚拟币信息失败: ${response.data.message}`);
                return null;
            }
        } catch (error) {
            console.log(`✗ 获取虚拟币信息出错: ${error.message}`);
            return null;
        }
    }

    async getSignInTaskDetail(activityId = 18) {
        try {
            let reqData = this.updateRequestHeaders({ ...this.headers });
            reqData.headers['signature'] = this.md5('signInTaskDetail' + activityId + reqData.timestamp + reqData.nonce);
            const response = await axios.get(
                `https://api-saas.miniso.com/task-manage-platform/api/activity/signInTask/taskDetail?activityId=${activityId}`,
                { headers: reqData.headers }
            );
            if (response.data.code === 200) {
                const taskData = response.data.data;
                console.log(`✓ 签到任务详情: 连续签到 ${taskData.signInFinishDays} 天，今日${taskData.todaySignInFinishFlag ? '已完成' : '待完成'}`);
                return taskData;
            } else {
                console.log(`✗ 获取签到任务详情失败: ${response.data.message}`);
                return null;
            }
        } catch (error) {
            console.log(`✗ 获取签到任务详情出错: ${error.message}`);
            return null;
        }
    }

    async completeSignIn(taskId, activityId = 18) {
        try {
            let reqData = this.updateRequestHeaders({ ...this.headers });
            const body = { activityId: String(activityId), taskId: taskId };
            reqData.headers['signature'] = this.md5(JSON.stringify(body) + reqData.timestamp + reqData.nonce);
            const response = await axios.post(
                'https://api-saas.miniso.com/task-manage-platform/api/activity/signInTask/award/receive',
                body,
                { headers: reqData.headers }
            );
            if (response.data.code === 200) {
                console.log('✓ 签到成功');
                return true;
            } else {
                console.log(`✗ 签到失败: ${response.data.message}`);
                return false;
            }
        } catch (error) {
            console.log(`✗ 签到出错: ${error.message}`);
            return false;
        }
    }

    async getPeriodTaskList(activityId = 18) {
        try {
            let reqData = this.updateRequestHeaders({ ...this.headers });
            const url = `https://api-saas.miniso.com/task-manage-platform/api/activity/periodTask/taskDetail?activityId=${activityId}&unionId=${this.unionid}`;
            reqData.headers['signature'] = this.md5('periodTaskList' + activityId + this.unionid + reqData.timestamp + reqData.nonce);
            const response = await axios.get(url, { headers: reqData.headers });
            if (response.data.code === 200 && response.data.success) {
                const periods = response.data.data;
                let allTasks = [];
                for (const period of periods) {
                    if (period.periodTasks && Array.isArray(period.periodTasks)) {
                        allTasks = allTasks.concat(period.periodTasks);
                    }
                }
                console.log(`✓ 每日任务列表获取成功: 共 ${allTasks.length} 个任务`);
                return { periods, periodTasks: allTasks };
            } else {
                console.log(`✗ 获取每日任务列表失败: ${response.data.message || response.data.msg || '未知错误'}`);
                return null;
            }
        } catch (error) {
            console.log(`✗ 获取每日任务列表出错: ${error.message}`);
            return null;
        }
    }

    async completeTask(taskId, taskType, activityId = 18) {
        try {
            let reqData = this.updateRequestHeaders({ ...this.headers });
            const dataStr = JSON.stringify({ activityId, taskId, taskType });
            reqData.headers['signature'] = this.md5(dataStr + reqData.timestamp + reqData.nonce);
            const response = await axios.post(
                'https://api-saas.miniso.com/task-manage-platform/api/activity/task/finish',
                { activityId, taskId, taskType },
                { headers: reqData.headers }
            );
            if (response.data.code === 200) {
                console.log(`✓ 任务完成成功: ${response.data.data}`);
                return true;
            } else {
                console.log(`✗ 任务完成失败: ${response.data.message}`);
                return false;
            }
        } catch (error) {
            console.log(`✗ 任务完成出错: ${error.message}`);
            return false;
        }
    }

    async completeBrowseTask(taskId, activityId = 18) {
        try {
            const browseHeaders = {
                'host': 'api.multibrands.miniso.com',
                'content-pagetype': '%E8%90%BD%E5%9C%B0%E9%A1%B5',
                'can-flash-send': 'true',
                'x-mi-store-id': this.headers['x-mi-store-id'],
                'xweb_xhr': '1',
                'content-sceneid': '1256',
                'content-type': 'application/json',
                'content-weappcode': '52',
                'tenant-code': 'MINISO',
                'content-openid': this.headers['content-openid'],
                'content-latitude': '[object Undefined]',
                'content-appcode': '51',
                'x-mi-city': '',
                'content-pagename': '%E8%90%BD%E5%9C%B0%E9%A1%B5',
                'content-unionid': this.headers['content-unionid'],
                'tenant': 'MINISO',
                'x-mi-version': '5.1.64',
                'x-client-source': 'MINISO_WX_MINI',
                'content-longitude': '[object Undefined]',
                'content-uid': this.headers['content-uid'],
                'user-agent': this.headers['user-agent'],
                'content-skey': this.headers['content-skey'],
                'version': 'storeexpress1.0',
                'accept': '*/*',
                'sec-fetch-site': 'cross-site',
                'sec-fetch-mode': 'cors',
                'sec-fetch-dest': 'empty',
                'referer': 'https://servicewechat.com/wx2a212470bade49bf/1084/page-frame.html',
                'accept-encoding': 'gzip, deflate, br',
                'accept-language': 'zh-CN,zh;q=0.9',
                'priority': 'u=1, i'
            };
            const timestamp = this.getTimestamp();
            const nonce = this.generateNonce();
            browseHeaders['time'] = timestamp;
            browseHeaders['nonce'] = nonce;
            browseHeaders['content-nonce'] = timestamp + 1;
            browseHeaders['signature'] = this.md5('browseTask' + taskId + timestamp + nonce);
            browseHeaders['content-sign'] = this.md5('browseTask' + taskId + (timestamp + 1) + nonce);

            const response = await axios.post(
                'https://api.multibrands.miniso.com/multi-configure-platform/api/activity/task/browse/finish',
                { activityId, taskId },
                { headers: browseHeaders }
            );
            if (response.data.code === 200) {
                console.log(`✓ 浏览任务完成`);
                return true;
            } else {
                console.log(`✗ 浏览任务完成失败: ${response.data.message}`);
                return false;
            }
        } catch (error) {
            console.log(`✗ 浏览任务完成出错: ${error.message}`);
            return false;
        }
    }

    async recordTaskUV(activityId, taskId, taskType = 1) {
        try {
            let reqData = this.updateRequestHeaders({ ...this.headers });
            const dataStr = JSON.stringify({ activityId, taskId, taskType });
            reqData.headers['signature'] = this.md5(dataStr + reqData.timestamp + reqData.nonce);
            const response = await axios.post(
                'https://api-saas.miniso.com/task-manage-platform/api/activity/task/uvClick',
                { activityId, taskId, taskType },
                { headers: reqData.headers }
            );
            if (response.data.code === 200) {
                console.log('✓ 任务UV记录成功');
                return true;
            } else {
                console.log(`✗ 任务UV记录失败: ${response.data.message}`);
                return false;
            }
        } catch (error) {
            console.log(`✗ 任务UV记录出错: ${error.message}`);
            return false;
        }
    }

    async receiveAward(taskId, activityId = 18) {
        try {
            let reqData = this.updateRequestHeaders({ ...this.headers });
            const dataStr = JSON.stringify({ activityId, taskId });
            reqData.headers['signature'] = this.md5(dataStr + reqData.timestamp + reqData.nonce);
            const response = await axios.post(
                'https://api-saas.miniso.com/task-manage-platform/api/activity/periodTask/award/receive',
                { activityId, taskId },
                { headers: reqData.headers }
            );
            if (response.data.code === 200) {
                const awardData = response.data.data;
                console.log(`✓ 领取奖励: ${awardData.awardName}, ${awardData.awardDesc}`);
                return true;
            } else {
                console.log(`✗ 领取奖励失败: ${response.data.message}`);
                return false;
            }
        } catch (error) {
            console.log(`✗ 领取奖励出错: ${error.message}`);
            return false;
        }
    }

    async performSignInTask() {
        console.log('→ 开始执行签到任务...');
        const taskDetail = await this.getSignInTaskDetail();
        if (!taskDetail) {
            console.log('✗ 无法获取签到任务详情');
            return;
        }
        if (taskDetail.todaySignInFinishFlag === 1) {
            console.log(`✓ 今日签到已完成，连续签到 ${taskDetail.signInFinishDays} 天`);
            await this.recordTaskUV(18, taskDetail.taskId);
            return;
        }
        const nextDay = (taskDetail.signInFinishDays || 0) + 1;
        console.log(`→ 准备签到第 ${nextDay} 天`);
        const result = await this.completeSignIn(taskDetail.taskId, 18);
        if (result) {
            console.log(`✓ 第 ${nextDay} 天签到成功`);
            await this.recordTaskUV(18, taskDetail.taskId);
        }
    }

    async performDailyTasks() {
        console.log('→ 开始执行每日任务...');
        const periodTaskData = await this.getPeriodTaskList();
        if (!periodTaskData) {
            console.log('✗ 无法获取每日任务列表');
            return;
        }
        const tasks = periodTaskData.periodTasks || [];
        console.log(`→ 发现 ${tasks.length} 个每日任务`);

        for (const task of tasks) {
            console.log(`→ 处理任务: ${task.taskName} (ID: ${task.taskId})`);

            if (task.periodFinishTimes >= task.periodAllowTimes) {
                console.log(` ✓ 任务 "${task.taskName}" 已完成 (${task.periodFinishTimes}/${task.periodAllowTimes})`);
                if (task.buttonStatus !== 3) {
                    console.log(` → 尝试领取 "${task.taskName}" 的奖励...`);
                    await this.receiveAward(task.taskId, 18);
                }
                continue;
            }

            switch (task.taskType) {
                case 5:
                    console.log(` → 浏览任务 "${task.taskName}", 需浏览 ${task.browseSeconds || 0} 秒`);
                    if (task.browseSeconds > 0) {
                        console.log(` 正在浏览 ${task.browseSeconds} 秒...`);
                        await new Promise(resolve => setTimeout(resolve, task.browseSeconds * 1000));
                    }
                    await this.recordTaskUV(18, task.taskId, 5);
                    const completed = await this.completeBrowseTask(task.taskId, 18);
                    if (completed) {
                        console.log(` ✓ 浏览任务 "${task.taskName}" 完成，获得: ${task.awardName}`);
                        await new Promise(resolve => setTimeout(resolve, 1000));
                        await this.receiveAward(task.taskId, 18);
                    } else {
                        console.log(` ✗ 浏览任务 "${task.taskName}" 执行失败`);
                    }
                    break;
                case 2:
                    console.log(` → 分享任务 "${task.taskName}"，奖励: ${task.awardName}（需手动完成）`);
                    break;
                case 3:
                    console.log(` → 添加微信任务 "${task.taskName}"，奖励: ${task.awardName}（需手动完成）`);
                    break;
                default:
                    console.log(` → 未知类型 ${task.taskType}: ${task.taskName}`);
                    const genericCompleted = await this.completeTask(task.taskId, task.taskType);
                    if (genericCompleted) {
                        console.log(` ✓ 任务 "${task.taskName}" 完成`);
                        await new Promise(resolve => setTimeout(resolve, 1000));
                        await this.receiveAward(task.taskId, 18);
                    } else {
                        console.log(` ✗ 任务 "${task.taskName}" 执行失败`);
                    }
            }
            await new Promise(resolve => setTimeout(resolve, 2000));
        }
    }

    async executeAllTasks() {
        console.log('→ 开始执行所有任务...');
        const coinInfo = await this.getVirtualCoinInfo();
        await this.performSignInTask();
        await this.performDailyTasks();
        const finalCoinInfo = await this.getVirtualCoinInfo();
        if (finalCoinInfo && coinInfo) {
            const gain = finalCoinInfo.quantity - coinInfo.quantity;
            if (gain > 0) {
                console.log(`✓ 本次共获得 ${gain} 个mini币`);
            }
        }
        console.log('✓ 所有任务执行完成');
    }
}

// ====================== 主流程 ======================
async function main() {
    console.log('┌─────────────────────────────┐');
    console.log('│ 名创优品小程序签到 │');
    console.log('└─────────────────────────────┘');

    const cache = loadCache();

    for (let i = 0; i < SERVERS.length; i++) {
        const { server, ref } = parseYybGoEntry(SERVERS[i]);
        if (!server || !ref) {
            console.log(`✗ YYB_SERVER 第${i + 1}行格式无效，跳过`);
            continue;
        }

        console.log(`\n┌─ 账号${i + 1} (${ref}) ──────────┐`);

        let userInfo = cache[ref];
        let needRefresh = !userInfo || !userInfo.skey;

        if (needRefresh) {
            console.log('→ 无有效缓存，通过code换取token...');
            userInfo = await refreshAccountToken(server, ref);
            if (!userInfo) {
                console.log('✗ 获取token失败，跳过此账号');
                console.log('└────────────────────────────┘');
                continue;
            }
            cache[ref] = { ...userInfo, updateTime: Date.now() };
            saveCache(cache);
            console.log('✓ token获取成功，已更新缓存');
        } else {
            console.log('→ 使用本地缓存token');
        }

        const bot = new MinisoBot(userInfo);
        const testResult = await bot.getVirtualCoinInfo();

        if (!testResult) {
            console.log('→ token已失效，重新获取...');
            userInfo = await refreshAccountToken(server, ref);
            if (!userInfo) {
                console.log('✗ token刷新失败，跳过此账号');
                console.log('└────────────────────────────┘');
                continue;
            }
            cache[ref] = { ...userInfo, updateTime: Date.now() };
            saveCache(cache);
            console.log('✓ token刷新成功，重新执行');
            const newBot = new MinisoBot(userInfo);
            await newBot.executeAllTasks();
        } else {
            await bot.performSignInTask();
            await bot.performDailyTasks();
            await bot.getVirtualCoinInfo();
            console.log('✓ 所有任务执行完成');
        }

        if (i < SERVERS.length - 1) {
            console.log('├─ 等待5秒处理下一账号 ──────┤');
            await new Promise(resolve => setTimeout(resolve, 5000));
        }
        console.log('└────────────────────────────┘');
    }

    saveCache(cache);
    console.log('\n┌─────────────────────────────┐');
    console.log('│ 所有账户任务处理完成 │');
    console.log('└─────────────────────────────┘');
}

module.exports = main;

if (require.main === module) {
    main().catch(err => {
        console.log('✗ 脚本执行出错:', err);
    });
}
