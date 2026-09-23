#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 统一快乐星球茄皇（五期）
# cron: 25 10,22 * * *

"""
统一快乐星球茄皇五期（YYB Go 版）

功能：
  1. YYB_SERVER 获取微信 code
  2. 微盟 loginX 换 wid + openId
  3. 每日任务（签到/浏览/分享）
  4. 好友能量收取
  5. 使用能量种番茄
  6. 青龙 notify 推送

环境变量：
  YYB_SERVER    必填：YYB Go 服务地址@微信账号标识，多账号换行分隔

依赖：
  pip install requests cryptography
"""

import base64
import json
import os
import random
import time

import requests

try:
    from notify import send
except ImportError:
    send = None

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    CRYPTO_BACKEND = "cryptography"
except ImportError:
    try:
        from Crypto.Cipher import AES, PKCS1_OAEP
        from Crypto.Hash import SHA256
        from Crypto.PublicKey import RSA

        CRYPTO_BACKEND = "pycryptodome"
    except ImportError:
        CRYPTO_BACKEND = None


BASE_URL = "https://farmgames.ioutu.cn"
APP_ID = "wx532ecb3bdaaf92f9"
WEIMOB_LOGIN_URL = "https://xapi.weimob.com/fe/mapi/user/loginX"
WEIMOB_CID = "176205957"
WEIMOB_BOS_ID = "4020112618957"
WEIMOB_VID = "6013753979957"
PUBLIC_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA70sK419vy3MabW3lEGlk"
    "7Zh1u78OdnVlioVazp5Y46eBh+/TDqo/wZ9VrQ/4MmAtoP0vJ2vmwP5gqO3WPoj"
    "b07WddXfF1eU+5M+Rj3s0eSRrvZvBcGZ3qK0dOgZJScK66IDQazt/c4xqhDcsI"
    "tIyNRahUqB/IKc6E80GZJvMvFtZVSCseAXC0mAJXhi1AdUOlP+3Pv0fiUVejTJp"
    "1j7LBNWJ7Z5/8mRcclQH0vmxsdYsaV3qZiJ2d/CfNoKcwmI2IWmeZy8NP5U8Hn"
    "0AsxPEwjdHoEqG/iy/SoA46TZL+RLtWqUSHXpaKR/VFN0rbl25SE91X8FTfLqyD"
    "8LfGMCwRQIDAQAB"
)
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 26_5_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.75(0x18004b42) NetType/WIFI Language/zh_CN "
    "miniProgram/wx532ecb3bdaaf92f9"
)
SUPPORTED_TASK_TYPES = {"SIGN", "BROWSE", "SHARE"}
FRIEND_TASK_TYPE = "FRIEND_STEAL_ENERGY"
FRIEND_STATUS_CLAIMABLE = "0"


# ============ YYB Go 解析 ============

def parse_yyb_servers():
    raw = os.getenv("YYB_SERVER", "")
    servers = [line.strip() for line in raw.splitlines() if line.strip() and "@" in line.strip()]
    return servers


def parse_yyb_entry(raw):
    raw = raw.strip()
    at_idx = raw.index("@")
    server = raw[:at_idx].strip()
    ref = raw[at_idx + 1:].strip()
    if server.startswith("http://"):
        server = server[7:]
    elif server.startswith("https://"):
        server = server[8:]
    server = server.rstrip("/")
    return server, ref


def get_wx_code(server_entry):
    """通过 YYB Go 获取微信 code"""
    server, ref = parse_yyb_entry(server_entry)
    url = f"http://{server}/wxapp/getCode"
    try:
        resp = requests.post(
            url,
            json={"ref": ref, "app_id": APP_ID},
            timeout=20,
            proxies={"http": None, "https": None},
        )
        data = resp.json()
        code = (((data.get("data") or {}).get("result") or {}).get("code"))
        if data.get("code") == 0 and code:
            return code
        else:
            raise RuntimeError(f"YYB Go 返回异常：{str(data)[:200]}")
    except requests.RequestException as exc:
        raise RuntimeError(f"YYB Go 请求失败：{exc}")


# ============ 微盟登录 ============

def login_weimob_by_code(code):
    payload = {
        "basicInfo": {
            "cid": WEIMOB_CID,
            "vid": WEIMOB_VID,
            "tcode": "weimob",
            "bosId": WEIMOB_BOS_ID,
        },
        "extendInfo": {"source": 1},
        "parentVid": 0,
        "is_pre_fetch_open": True,
        "env": "production",
        "storeId": "0",
        "appid": APP_ID,
        "pid": WEIMOB_BOS_ID,
        "code": code,
        "queryAuthConfig": True,
        "relevanceAuthRequest": None,
    }
    response = requests.post(
        WEIMOB_LOGIN_URL,
        json=payload,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": f"https://servicewechat.com/{APP_ID}/288/page-frame.html",
            "Content-Type": "application/json",
            "x-biz-id": "1",
            "cloud-pid": WEIMOB_BOS_ID,
            "weimob-cid": WEIMOB_CID,
            "weimob-bosid": WEIMOB_BOS_ID,
            "x-req-from": "cms",
            "cloud-project-name": "tongyixiangmu",
            "weimob-pid": WEIMOB_BOS_ID,
        },
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    data = result.get("data") or {}
    errcode = result.get("errcode")
    wid = data.get("wid")
    open_id = data.get("openId") or data.get("openid")
    if str(errcode) != "0" or not wid or not open_id:
        message = result.get("errmsg") or "未返回 wid/openId"
        raise RuntimeError(f"code 登录失败：{message}；{str(result)[:180]}")
    return str(wid), str(open_id)


def resolve_identity(server_entry):
    last_error = None
    for attempt in range(1, 4):
        try:
            return login_weimob_by_code(get_wx_code(server_entry))
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2)
    raise RuntimeError(f"YYB Go/微盟登录失败（已重试 3 次）：{last_error}")


# ============ 加密 ============

def encrypt_payload(payload):
    """RSA-OAEP-SHA256 + AES-256-GCM"""
    if CRYPTO_BACKEND is None:
        raise RuntimeError("缺少加密依赖，请安装 cryptography：pip install cryptography")

    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    aes_key = os.urandom(32)
    iv = os.urandom(12)
    public_key_der = base64.b64decode(PUBLIC_KEY)

    if CRYPTO_BACKEND == "cryptography":
        public_key = serialization.load_der_public_key(public_key_der)
        encrypted_data = AESGCM(aes_key).encrypt(iv, plaintext, None)
        encrypted_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    else:
        cipher = AES.new(aes_key, AES.MODE_GCM, nonce=iv)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        encrypted_data = ciphertext + tag
        public_key = RSA.import_key(public_key_der)
        encrypted_key = PKCS1_OAEP.new(public_key, hashAlgo=SHA256).encrypt(aes_key)

    return {
        "data": base64.b64encode(encrypted_data).decode(),
        "key": base64.b64encode(encrypted_key).decode(),
        "iv": base64.b64encode(iv).decode(),
    }


# ============ 业务客户端 ============

class TomatoClient:
    def __init__(self, wid, open_id):
        self.wid = wid
        self.open_id = open_id
        self.tomato_user_id = None
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/?wid={wid}&openId={open_id}",
            }
        )

    def request(self, method, path, payload=None, encrypted=True, retry=2):
        url = f"{BASE_URL}{path}"
        for attempt in range(retry + 1):
            kwargs = {"timeout": 20}
            if payload:
                kwargs["json"] = encrypt_payload(payload) if encrypted else payload
                if encrypted:
                    kwargs["headers"] = {"X-Request-Encrypted": "true"}
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 429 and attempt < retry:
                retry_after = response.headers.get("Retry-After", "2")
                try:
                    wait_seconds = max(1.0, float(retry_after))
                except ValueError:
                    wait_seconds = 2.0
                time.sleep(wait_seconds + attempt)
                continue
            response.raise_for_status()
            try:
                result = response.json()
            except ValueError as exc:
                raise RuntimeError(f"接口返回非 JSON 数据：{response.text[:200]}") from exc

            msg = str(result.get("msg", ""))
            if result.get("code") == 200:
                return result
            if attempt < retry and (
                response.status_code == 429 or "频繁" in msg or "稍后" in msg
            ):
                time.sleep(2.5 + attempt * 1.5)
                continue
            raise RuntimeError(msg or f"接口返回 code={result.get('code')}")
        raise RuntimeError("请求重试后仍未成功")

    def login(self):
        result = self.request(
            "POST",
            "/api/web/open/tomato/login",
            {
                "shareTomatoUserId": None,
                "openId": self.open_id,
                "wid": self.wid,
                "queryCardStatus": True,
            },
        )
        data = result.get("data") or {}
        token = data.get("token")
        if not token:
            raise RuntimeError("登录响应中没有 token")
        self.session.headers["Authorization"] = token
        self.tomato_user_id = data.get("tomatoUserId")
        return data

    def home(self):
        return self.request("GET", "/api/web/member/tomato/home").get("data") or {}

    def tasks(self):
        return self.request("GET", "/api/web/member/tomato/tasks").get("data") or []

    def complete_task(self, task):
        task_type = task.get("taskType")
        payload = {"taskType": task_type}
        if task_type != "SHARE":
            payload["browseTarget"] = task.get("browseTarget") or ""
        elif self.tomato_user_id:
            try:
                self.request(
                    "POST",
                    "/api/web/member/tomato/miniprogram/qrcode/create",
                    {
                        "page": "packages/wm-cloud-qiehuang/home/index",
                        "scene": str(self.tomato_user_id),
                    },
                )
            except Exception:
                pass
        return self.request(
            "POST", "/api/web/member/tomato/tasks/complete", payload
        ).get("data") or {}

    def friends(self, page_size=20):
        friends = []
        page_num = 1
        while True:
            result = self.request(
                "GET",
                f"/api/web/member/tomato/friends?pageNum={page_num}&pageSize={page_size}",
            )
            rows = result.get("rows") or []
            friends.extend(rows)
            total = int(result.get("total") or 0)
            if not rows or (total and len(friends) >= total) or len(rows) < page_size:
                break
            page_num += 1
        return friends

    def friend_home(self, friend_user_id):
        return self.request(
            "GET",
            f"/api/web/member/tomato/friends/{friend_user_id}/home",
        ).get("data") or {}

    def steal_friend_energy(self, friend_user_id):
        return self.request(
            "POST",
            "/api/web/member/tomato/friends/steal",
            {"friendTomatoUserId": friend_user_id},
        ).get("data")

    def use_energy(self):
        return self.request(
            "POST", "/api/web/member/tomato/energy/use", encrypted=False
        ).get("data") or {}


# ============ 工具函数 ============

def short_open_id(open_id):
    return f"{open_id[:6]}...{open_id[-4:]}" if len(open_id) > 12 else open_id


def home_line(data, prefix="当前状态"):
    return (
        f"{prefix}：能量 {data.get('energyBalance', 0)}，"
        f"番茄 {data.get('tomatoBalance', 0)}，"
        f"{data.get('stageName', '未知阶段')} "
        f"{data.get('currentExp', 0)}/{data.get('stageRequiredExp', 0)}"
    )


# ============ 主流程 ============

def process_user(wid, open_id, index):
    logs = [f"账号{index}（wid={wid}，openId={short_open_id(open_id)}）"]
    client = TomatoClient(wid, open_id)

    login_data = client.login()
    logs.append(f"登录成功：{login_data.get('nickName') or '未设置昵称'}")
    home = client.home()
    logs.append(home_line(home))

    completed = 0
    skipped = 0
    friend_task = None
    for task in client.tasks():
        name = task.get("taskName") or task.get("taskCode") or "未知任务"
        task_type = task.get("taskType")
        if task_type == FRIEND_TASK_TYPE:
            friend_task = task
            if str(task.get("completed")) == "1":
                logs.append(f"任务已完成：{name}")
            continue
        if str(task.get("completed")) == "1":
            logs.append(f"任务已完成：{name}")
            continue
        if task_type not in SUPPORTED_TASK_TYPES:
            skipped += 1
            logs.append(f"跳过任务：{name}（需在小程序内操作）")
            continue
        try:
            result = client.complete_task(task)
            reward = result.get("rewardText") or task.get("rewardText") or "已领取"
            logs.append(f"任务完成：{name}，{reward}")
            completed += 1
        except Exception as exc:
            logs.append(f"任务失败：{name}，{exc}")
        time.sleep(random.uniform(2.5, 3.5))

    try:
        claimable_friends = [
            friend
            for friend in client.friends()
            if str(friend.get("friendStatus")) == FRIEND_STATUS_CLAIMABLE
            and friend.get("friendTomatoUserId")
        ]
        stolen_count = 0
        stolen_energy = 0
        failed_count = 0
        for friend in claimable_friends:
            friend_user_id = friend["friendTomatoUserId"]
            try:
                friend_home = client.friend_home(friend_user_id)
                amount = int(friend_home.get("stealAmount") or 0)
                if str(friend_home.get("canSteal")) != "1" or amount <= 0:
                    continue
                client.steal_friend_energy(friend_user_id)
                stolen_count += 1
                stolen_energy += amount
            except Exception:
                failed_count += 1
            time.sleep(random.uniform(1.5, 2.5))

        if stolen_count:
            detail = f"好友能量：成功收取 {stolen_count} 位好友，共 {stolen_energy} 能量"
            if failed_count:
                detail += f"，失败 {failed_count} 位"
            logs.append(detail)
            if friend_task and str(friend_task.get("completed")) != "1":
                completed += 1
        elif failed_count:
            logs.append(f"好友能量：收取失败 {failed_count} 位")
        else:
            logs.append("好友能量：暂无可收取能量")
    except Exception as exc:
        logs.append(f"好友能量失败：{exc}")

    home = client.home()
    logs.append(home_line(home, "任务后状态"))
    energy = int(home.get("energyBalance") or 0)
    if energy > 0:
        before_tomato = int(home.get("tomatoBalance") or 0)
        try:
            grown = client.use_energy()
            after_tomato = int(grown.get("tomatoBalance") or 0)
            gained = int(grown.get("gainedTomatoAmount") or 0)
            if not gained:
                gained = max(0, after_tomato - before_tomato)
            logs.append(
                f"使用能量：消耗 {grown.get('usedEnergyAmount', energy)}，"
                f"成长到 {grown.get('stageName', '未知阶段')} "
                f"{grown.get('currentExp', 0)}/{grown.get('stageRequiredExp', 0)}，"
                f"获得番茄 {gained}"
            )
            home = grown
        except Exception as exc:
            logs.append(f"使用能量失败：{exc}")
    else:
        logs.append("使用能量：当前没有可用能量")

    logs.append(home_line(home, "最终状态"))
    logs.append(f"本次完成任务 {completed} 个，跳过 {skipped} 个")
    return logs


def render_report(all_logs):
    lines = ["统一茄皇五期"]
    for logs in all_logs:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.extend(logs)
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def safe_send(title, message):
    if send is None:
        return
    try:
        send(title, message)
    except Exception as exc:
        print(f"通知发送失败（不影响脚本执行结果）：{exc}")


def main():
    servers = parse_yyb_servers()
    if CRYPTO_BACKEND is None:
        message = "缺少加密依赖，请安装 cryptography：pip install cryptography"
        print(message)
        safe_send("统一茄皇五期", message)
        return
    if not servers:
        message = "没有可用账号：未读取到 YYB_SERVER 环境变量"
        print(message)
        safe_send("统一茄皇五期", message)
        return

    print(f"✅ 读取到 {len(servers)} 个 YYB Go 账号")

    all_logs = []
    for index, server_entry in enumerate(servers, 1):
        wid = ""
        open_id = ""
        print(f"\n===== 开始处理账号 {index} =====")
        try:
            wid, open_id = resolve_identity(server_entry)
            print(f"  登录成功：wid={wid}，openId={short_open_id(open_id)}")
            logs = process_user(wid, open_id, index)
        except Exception as exc:
            logs = [
                f"账号{index}（wid={wid}，openId={short_open_id(open_id) or '-'}）",
                f"处理失败：{exc}",
            ]
        all_logs.append(logs)
        print("\n".join(logs))
        if index < len(servers):
            time.sleep(random.uniform(3, 5))

    report = render_report(all_logs)
    safe_send("统一茄皇五期", report)


if __name__ == "__main__":
    main()
