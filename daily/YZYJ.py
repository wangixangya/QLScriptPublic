#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 优智云家
# cron: 23 9,21 * * *

"""
优智云家品牌商城小程序（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code
  2. 微盟 loginX 换 token
  3. 每日签到
  4. 青龙 notify 推送

环境变量：
  YYB_SERVER    YYB Go 服务地址，格式：server@wxid，多账号换行分隔
  PROXY_API     品赞代理提取 API，可选
  PROXY_TYPE    http / socks5，默认 http
"""

import json
import os
import random
import time
import traceback
from datetime import datetime
from urllib.parse import quote

import requests

try:
    import notify
except ImportError:
    notify = None

APP_NAME = "优智云家"
APPID = "wxa61f98248d20178b"

BASE_URL = "https://xapi.weimob.com"
LOGIN_URL = f"{BASE_URL}/fe/mapi/user/loginX"
SIGN_STATUS_URL = f"{BASE_URL}/api3/onecrm/mactivity/sign/misc/sign/activity/c/signMainInfo"
SIGN_SUBMIT_URL = f"{BASE_URL}/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/sign"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541938) XWEB/19823"
)

# YYB_SERVER 解析
SERVERS = []
env_YYB_SERVER = os.getenv("YYB_SERVER", "")
if env_YYB_SERVER:
    SERVERS = [line.strip() for line in env_YYB_SERVER.splitlines() if line.strip()]

if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER")
    print("格式：地址@微信账号标识，多账号换行分隔")
    exit(1)

print(f"✅ 读取到 {len(SERVERS)} 个 YYB Go 账号")

PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def mask(value) -> str:
    value = str(value or "")
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-6:]}"


def json_preview(data, limit: int = 300) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)[:limit]
    except Exception:
        return str(data)[:limit]


# ============ YYB Server 交互 ============

def parse_yyb_go_entry(raw_value: str):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None, None
    if "@" not in raw_value:
        print(f"❌ YYB_SERVER 格式应为 地址@微信账号标识，当前值：{raw_value}")
        return None, None
    server, ref = raw_value.split("@", 1)
    server = server.strip()
    ref = ref.strip()
    if server.startswith("http://"):
        server = server[7:]
    elif server.startswith("https://"):
        server = server[8:]
    server = server.rstrip("/")
    if not server or not ref:
        return None, None
    return server, ref


def get_wx_code(server_entry: str) -> str | None:
    parsed_server, ref = parse_yyb_go_entry(server_entry)
    if not parsed_server or not ref:
        return None
    url = f"http://{parsed_server}/wxapp/getCode"
    print(f"  [授权] 请求YYB Go获取code")
    try:
        resp = requests.post(
            url,
            json={"ref": ref, "app_id": APPID},
            timeout=20,
            proxies={"http": None, "https": None},
        )
        data = resp.json()
        code = (((data.get("data") or {}).get("result") or {}).get("code"))
        if data.get("code") == 0 and code:
            print(f"  [授权] code获取成功")
            return code
        else:
            print(f"  [授权] code获取失败: {str(data)[:200]}")
            return None
    except Exception as exc:
        print(f"  [授权] code获取异常: {exc}")
        return None


# ============ 代理系统（可选） ============

_persistent_session = None

def get_persistent_session() -> requests.Session:
    global _persistent_session
    if _persistent_session is None:
        _persistent_session = requests.Session()
        _persistent_session.trust_env = False
    return _persistent_session


def direct_session() -> requests.Session:
    return get_persistent_session()


def parse_proxy_response(text) -> dict | None:
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        proxy_obj = None
        if isinstance(data.get("data"), list) and data["data"]:
            proxy_obj = data["data"][0]
        elif isinstance(data.get("data"), dict):
            proxy_obj = data["data"]
        elif data.get("ip") and data.get("port"):
            proxy_obj = data
        elif isinstance(data.get("result"), dict):
            proxy_obj = data["result"]
        if proxy_obj:
            host = proxy_obj.get("ip") or proxy_obj.get("host")
            port = proxy_obj.get("port")
            if host and port:
                return {
                    "host": str(host), "port": int(port),
                    "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                    "password": proxy_obj.get("pass") or proxy_obj.get("password") or "",
                }
    except Exception:
        pass
    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            return {
                "host": parts[0], "port": int(parts[1]),
                "username": parts[2] if len(parts) > 2 else "",
                "password": parts[3] if len(parts) > 3 else "",
            }
    return None


def build_proxy_dict(proxy_info: dict | None) -> dict | None:
    if not proxy_info:
        return None
    host, port = proxy_info["host"], proxy_info["port"]
    username, password = proxy_info.get("username", ""), proxy_info.get("password", "")
    auth = f"{quote(username)}:{quote(password)}@" if username and password else ""
    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"
    print(f"  [代理] 生成 {scheme.upper()} 代理 {host}:{port}")
    return {"http": proxy_url, "https": proxy_url}


def get_valid_proxy(server: str) -> dict | None:
    if not PROXY_API:
        return None
    for i in range(1, PROXY_RETRY_TIMES + 1):
        try:
            resp = direct_session().get(PROXY_API, timeout=15)
            info = parse_proxy_response(resp.text)
            if not info:
                continue
            proxies = build_proxy_dict(info)
            try:
                r = requests.get("http://www.baidu.com", proxies=proxies, timeout=10)
                if r.status_code == 200:
                    return proxies
            except Exception:
                pass
        except Exception as exc:
            print(f"  [代理] 第{i}次获取异常: {exc}")
        if i < PROXY_RETRY_TIMES:
            sleep(2)
    print("  [代理] 获取失败，使用直连")
    return None


def request_with_proxy(method: str, url: str, *, proxies: dict | None = None, server: str = "", **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(f"  [代理] {server} 请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("  [兜底] 切换直连重试")
    return direct_session().request(method, url, **kwargs)


# ============ 业务逻辑 ============

def common_headers(token: str | None = None, extra: dict | None = None) -> dict:
    headers = {
        "Host": "xapi.weimob.com",
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Referer": f"https://servicewechat.com/{APPID}/109/page-frame.html",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["X-WX-Token"] = token
    if extra:
        headers.update(extra)
    return headers


def extract_token(data) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ["token", "accessToken", "access_token", "jwt"]:
        val = data.get(key) or (data.get("data") or {}).get(key)
        if val and str(val) != "null":
            return str(val)
    return None


def login_by_code(server: str, code: str, proxies: dict | None) -> tuple[str | None, dict | None]:
    print("  [登录] 使用 code 换 token")
    payload = {
        "appid": APPID,
        "basicInfo": {"bosId": "4022115200359", "cid": "821033359", "tcode": "weimob", "vid": "6016741943359"},
        "env": "production", "extendInfo": {"source": 1},
        "is_pre_fetch_open": True, "parentVid": 0, "pid": "", "storeId": "",
        "code": code, "queryAuthConfig": True,
    }
    try:
        resp = request_with_proxy(
            "POST", LOGIN_URL,
            headers=common_headers(),
            json=payload,
            proxies=proxies, server=server,
        )
        data = resp.json()
        if data.get("errcode") == 0:
            token = extract_token(data)
            if token:
                print(f"  [登录] token获取成功: {mask(token)}")
                return token, data
        print(f"  [登录] 失败: {data.get('errmsg', '未知错误')}")
        return None, data
    except Exception as exc:
        print(f"  [登录] 异常: {exc}")
        return None, None


def check_sign_status(server: str, token: str, proxies: dict | None) -> tuple[bool, dict]:
    extra = {
        "x-wmsdk-vid": "6016741943359", "x-biz-id": "146",
        "cloud-project-name": "fansquan", "x-component-is": "onecrm/signgift",
        "cloud-bosid": "4022115200359", "weimob-bosId": "4022115200359",
    }
    payload = {
        "appid": APPID,
        "basicInfo": {"vid": 6016741943359, "vidType": 2, "bosId": 4022115200359, "productId": 146,
                      "productInstanceId": 15532102359, "productVersionId": "10003",
                      "merchantId": 2000230069359, "tcode": "weimob", "cid": 821033359},
        "extendInfo": {"wxTemplateId": 7930},
    }
    try:
        resp = request_with_proxy(
            "POST", SIGN_STATUS_URL,
            headers=common_headers(token, extra),
            json=payload,
            proxies=proxies, server=server,
        )
        data = resp.json()
        if data.get("errcode") == 0:
            sign_data = data.get("data", {})
            return sign_data.get("isSign", False), sign_data
        return False, {}
    except Exception as exc:
        print(f"  [签到状态] 检查失败: {exc}")
        return False, {}


def submit_signin(server: str, token: str, proxies: dict | None) -> tuple[bool, str, int]:
    extra = {
        "x-wmsdk-vid": "6016741943359", "x-biz-id": "146",
        "cloud-project-name": "fansquan", "x-component-is": "onecrm/signgift",
        "cloud-bosid": "4022115200359", "weimob-bosId": "4022115200359",
        "parentrpcid": "a6e117c9d2dad0ad",
    }
    payload = {
        "appid": APPID,
        "basicInfo": {"vid": 6016741943359, "vidType": 2, "bosId": 4022115200359, "productId": 146,
                      "productInstanceId": 15532102359, "productVersionId": "10003",
                      "merchantId": 2000230069359, "tcode": "weimob", "cid": 821033359},
        "extendInfo": {
            "wxTemplateId": 8105, "analysis": [], "bosTemplateId": 1000002154,
            "childTemplateIds": [
                {"customId": 90004, "version": "crm@0.1.81"},
                {"customId": 90002, "version": "ec@80.0"},
                {"customId": 90006, "version": "hudong@0.0.251"},
                {"customId": 90008, "version": "cms@0.0.524"},
                {"customId": 90070, "version": "1.0.12"},
            ],
            "quickdeliver": {"enable": True}, "youshu": {"enable": False},
            "source": 1, "channelsource": 5, "refer": "onecrm-signgift", "mpScene": 1005,
        },
        "queryParameter": None,
        "i18n": {"language": "zh", "timezone": "8"},
        "pid": "", "storeId": "",
        "customInfo": {"source": 0, "wid": 11983225884},
    }
    try:
        resp = request_with_proxy(
            "POST", SIGN_SUBMIT_URL,
            headers=common_headers(token, extra),
            json=payload,
            proxies=proxies, server=server,
        )
        data = resp.json()
        print(f"  [签到] 响应: {json_preview(data)}")

        if data.get("errcode") == 0:
            sign_data = data.get("data", {})
            is_sign = sign_data.get("isSign", False)
            reward_info = sign_data.get("rewardInfo", {})
            reward_name = reward_info.get("rewardName", "签到奖励")
            integral = reward_info.get("integral", 0) or reward_info.get("score", 0)
            if is_sign:
                return True, f"签到成功: {reward_name} +{integral}积分", int(integral) if integral else 0
            return True, "签到成功", 0

        return False, data.get("errmsg", "签到失败"), 0
    except Exception as exc:
        return False, f"签到异常: {exc}", 0


def run_account(index: int, total: int, server_entry: str) -> dict:
    parsed_server, wxid = parse_yyb_go_entry(server_entry)
    result = {
        "wxid": mask(wxid or ""),
        "success": False,
        "proxy_status": "未使用代理",
        "token": "-",
        "sign_msg": "-",
        "earned": "0",
        "error": "",
    }

    print(f"\n{'='*50}")
    print(f"账号 {index}/{total} ({mask(wxid or '')})")
    print(f"{'='*50}")

    proxies = get_valid_proxy(str(parsed_server))
    result["proxy_status"] = "使用专属代理" if proxies else "使用直连"

    delay = random.randint(2, 6)
    sleep(delay)

    code = get_wx_code(server_entry)
    if not code:
        result["error"] = "获取 code 失败"
        return result

    token, raw_login = login_by_code(parsed_server, code, proxies)
    if not token:
        result["error"] = f"登录失败: {json_preview(raw_login)}"
        return result

    result["token"] = mask(token)

    try:
        sleep(random.randint(1, 3))
        print("  [签到] 检查签到状态...")
        is_signed, sign_data = check_sign_status(parsed_server, token, proxies)

        if is_signed:
            result["sign_msg"] = "今日已签到"
            print("  [签到] 今日已签到")
        else:
            print("  [签到] 未签到，开始签到...")
            sign_ok, sign_msg, earned = submit_signin(parsed_server, token, proxies)
            result["sign_msg"] = sign_msg
            result["earned"] = str(earned)
            if sign_ok:
                print(f"  [签到] {sign_msg}")
            else:
                print(f"  [签到] {sign_msg}")

        sleep(random.randint(1, 3))
        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        print(f"  [账号] 执行失败: {exc}")
        return result


def build_notify(results: list) -> str:
    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    total_earned = sum(int(r.get("earned", 0)) for r in results if r.get("success"))
    lines = [f"优智云家签到结果", "—" * 30]
    lines.append(f"✅ {ok}成功 / ❌ {fail}失败")
    lines.append(f"💰 总获得积分: {total_earned}")
    lines.append(f"🕒 {now_text()}")
    lines.append("")
    for i, r in enumerate(results, 1):
        icon = "✅" if r.get("success") else "❌"
        lines.append(f"{icon} 账号{i} ({r.get('wxid', '-')})")
        lines.append(f"  签到: {r['sign_msg']}")
        lines.append(f"  获得: {r['earned']}积分")
        if not r.get("success"):
            lines.append(f"  错误: {r.get('error', '')[:80]}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    print(f"\n{'='*50}")
    print(f"优智云家（YYB Go版）")
    print(f"启动: {now_text()} | 账号: {len(SERVERS)}")
    print(f"{'='*50}")

    results = []
    for idx, server_entry in enumerate(SERVERS):
        try:
            r = run_account(idx + 1, len(SERVERS), server_entry)
            results.append(r)
        except Exception as exc:
            _, wxid = parse_yyb_go_entry(server_entry)
            results.append({
                "wxid": mask(wxid or ""), "success": False, "error": str(exc),
                "token": "-", "sign_msg": "-", "earned": "0", "proxy_status": "-",
            })
        if idx < len(SERVERS) - 1:
            sleep(2)

    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    print(f"\n{'='*50}")
    print(f"完成: ✅{ok} ❌{fail} | 🕒{now_text()}")
    print(f"{'='*50}")

    if notify:
        notify.send(APP_NAME, build_notify(results))


if __name__ == "__main__":
    main()
