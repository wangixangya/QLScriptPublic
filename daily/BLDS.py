#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 布鲁大师
# cron: 8 17,5 * * *

"""
布鲁大师小程序（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code
  2. code 换 token
  3. 每日签到
  4. 查询用户信息和积分
  5. 青龙 notify 推送

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
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import requests

try:
    import notify
except ImportError:
    notify = None

APP_NAME = "布鲁大师小程序"
APPID = "wx73555499305578f8"

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

BASE_URL = "https://wxsc.blue-dash.com/prod-api"
LOGIN_URL = f"{BASE_URL}/app-api/member/auth/social-login"
USER_INFO_URL = f"{BASE_URL}/app-api/member/user/get"
SIGN_URL = f"{BASE_URL}/app-api/member/sign-log/sign"
SIGN_LOG_URL = f"{BASE_URL}/app-api/member/sign-log/page"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541938) XWEB/19899"
)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def mask(value: Any) -> str:
    value = str(value or "")
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-6:]}"


def json_preview(data: Any, limit: int = 800) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)[:limit]
    except Exception:
        return str(data)[:limit]


def to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def log_title() -> None:
    print()
    print("+" + "=" * 50 + "+")
    print("| 🏀 布鲁大师小程序（YYB Go版）                    |")
    print(f"| 🕒 启动时间: {now_text():<35}|")
    print(f"| 🔢 账号数量: {len(SERVERS):<37}|")
    print("+" + "=" * 50 + "+")


def log_account_header(index: int, total: int, server: str) -> None:
    print()
    print("+" + "-" * 50 + "+")
    print(f"| 🧩 账号 {index} / {total:<41}|")
    print(f"| 🌍 来源 {server:<44}|")
    print("+" + "-" * 50 + "+")


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


def parse_proxy_response(text: Any) -> Dict[str, Any] | None:
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


def build_proxy_dict(proxy_info: Dict[str, Any] | None) -> Dict[str, str] | None:
    if not proxy_info:
        return None
    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info.get("username", "")
    password = proxy_info.get("password", "")
    auth = ""
    if username and password:
        auth = f"{quote(username)}:{quote(password)}@"
    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"
    print(f"  [代理] 生成 {scheme.upper()} 代理 {host}:{port}")
    return {"http": proxy_url, "https": proxy_url}


def get_valid_proxy(account_name: str) -> Tuple[Dict[str, str] | None, str]:
    if not PROXY_API:
        return None, ""
    print(f"  [代理] {account_name} 正在获取品赞代理...")
    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(response.text)
            if not proxy_info:
                print(f"  [代理] 第 {index} 次代理解析失败")
                continue
            print(f"  [代理] 提取到 {proxy_info['host']}:{proxy_info['port']}")
            proxies = build_proxy_dict(proxy_info)
            try:
                resp = requests.get("http://www.baidu.com", proxies=proxies, timeout=10)
                if resp.status_code == 200:
                    return proxies, proxy_info["host"]
            except Exception:
                pass
            print(f"  [代理] 第 {index} 次代理不可用")
        except Exception as exc:
            print(f"  [代理] 第 {index} 次获取代理异常: {exc}")
        if index < PROXY_RETRY_TIMES:
            sleep(2)
    print("  [代理] 获取失败，使用直连")
    return None, ""


def request_with_proxy(
    method: str, url: str, *,
    proxies: Dict[str, str] | None = None, server: str = "", **kwargs,
) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(f"  [代理] {server} 代理请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("  [兜底] 切换直连重试")
    session = direct_session()
    return session.request(method, url, **kwargs)


# ============ 业务接口 ============

def common_headers(token: str | None = None) -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Referer": f"https://servicewechat.com/{APPID}/39/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def login_by_code(server: str, code: str, proxies: Dict[str, str] | None) -> Tuple[str | None, Dict[str, Any] | None]:
    try:
        print("  [登录] 使用 code 换 token")
        response = request_with_proxy(
            "POST", LOGIN_URL,
            headers=common_headers(),
            json={"code": code, "type": "34", "state": "blue_dash"},
            proxies=proxies, server=server,
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:800]}

        if data.get("code") == 0 and data.get("data", {}).get("accessToken"):
            token = data["data"]["accessToken"]
            print(f"  [登录] token 获取成功: {mask(token)}")
            return token, data

        print(f"  [登录] 登录失败: {json_preview(data)}")
        return None, data
    except Exception as exc:
        print(f"  [登录] 请求异常: {exc}")
        return None, None


def api_get(server: str, url: str, token: str, proxies: Dict[str, str] | None) -> Dict[str, Any]:
    response = request_with_proxy("GET", url, headers=common_headers(token), proxies=proxies, server=server)
    try:
        return response.json()
    except Exception:
        return {"code": -1, "msg": f"JSON解析失败: {response.text[:300]}"}


def api_post(server: str, url: str, token: str, proxies: Dict[str, str] | None, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = request_with_proxy("POST", url, headers=common_headers(token), json=payload, proxies=proxies, server=server)
    try:
        return response.json()
    except Exception:
        return {"code": -1, "msg": f"JSON解析失败: {response.text[:300]}"}


# ============ 账号执行 ============

def run_account(index: int, total: int, server_entry: str) -> Dict[str, Any]:
    parsed_server, wxid = parse_yyb_go_entry(server_entry)
    result = {
        "server": parsed_server or server_entry,
        "wxid": mask(wxid),
        "success": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "token": "-",
        "userInfo": "-",
        "initialScore": 0,
        "finalScore": 0,
        "signMsg": "-",
        "signDetails": [],
        "error": "",
    }

    log_account_header(index, total, parsed_server or server_entry)

    proxies, proxy_ip = get_valid_proxy(str(parsed_server))
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    delay = random.randint(2, 6)
    print(f"  [延迟] 启动延迟 {delay}s")
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
        # 用户信息
        user_info_resp = api_get(parsed_server, USER_INFO_URL, token, proxies)
        if user_info_resp.get("code") == 0:
            user_data = user_info_resp.get("data", {})
            nickname = user_data.get("nickname", "未知")
            score = to_int(user_data.get("score"))
            level = user_data.get("level", 1)
            result["initialScore"] = score
            result["userInfo"] = f"{nickname} 等级{level} 积分{score}"
            print(f"  [用户] {result['userInfo']}")
        else:
            result["userInfo"] = user_info_resp.get("msg") or "获取用户信息失败"
            print(f"  [用户] {result['userInfo']}")

        sleep(2)

        # 签到
        sign_resp = api_post(parsed_server, SIGN_URL, token, proxies, {})
        if sign_resp.get("code") == 0:
            sign_data = sign_resp.get("data", {})
            date = sign_data.get("date", "")
            sign_score = to_int(sign_data.get("score"))
            coiled_day = sign_data.get("coiledDay", 0)
            result["signMsg"] = f"签到成功 {date} 连续{coiled_day}天 +{sign_score}积分"
            print(f"  [签到] {result['signMsg']}")
        else:
            result["signMsg"] = sign_resp.get("msg") or "签到失败"
            print(f"  [签到] {result['signMsg']}")

        sleep(2)

        # 最终积分
        final_resp = api_get(parsed_server, USER_INFO_URL, token, proxies)
        if final_resp.get("code") == 0:
            score = to_int(final_resp.get("data", {}).get("score"))
            result["finalScore"] = score
            score_change = score - result["initialScore"]
            if score_change > 0:
                print(f"  [最终] 积分{score} (本次+{score_change})")
            else:
                print(f"  [最终] 积分{score}")

        sleep(2)

        # 签到记录
        sign_log_resp = api_get(parsed_server, f"{SIGN_LOG_URL}?pageNo=1&pageSize=10", token, proxies)
        if sign_log_resp.get("code") == 0:
            page_result = sign_log_resp.get("data", {}).get("pageResult", {})
            sign_list = page_result.get("list", [])
            if sign_list:
                result["signDetails"] = []
                print(f"  [明细] 最近{len(sign_list)}条签到记录：")
                for item in sign_list[:5]:
                    date = item.get("date", "")
                    score = to_int(item.get("score"))
                    coiled_day = item.get("coiledDay", 0)
                    result["signDetails"].append({"date": date, "score": score, "coiledDay": coiled_day})
                    print(f"    {date} 连续{coiled_day}天 +{score}积分")

        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        print(f"  [账号] 执行失败: {exc}")
        return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    total_score = sum(r.get("finalScore", 0) for r in results)

    lines = [f"🏀 布鲁大师任务结果", "—" * 30]
    lines.append(f"✅ {success_count}成功 / ❌ {fail_count}失败")
    lines.append(f"💎 总积分: {total_score}")
    lines.append(f"🕒 {now_text()}")
    lines.append("")

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"
        lines.append(f"{icon} 账号{idx} ({res.get('wxid', '-')})")
        lines.append(f"  用户: {res['userInfo']}")
        lines.append(f"  签到: {res['signMsg']}")
        score_change = res["finalScore"] - res["initialScore"]
        if score_change > 0:
            lines.append(f"  积分: {res['initialScore']}→{res['finalScore']} (+{score_change})")
        else:
            lines.append(f"  积分: {res['finalScore']}")
        if res.get("signDetails"):
            for detail in res["signDetails"][:3]:
                lines.append(f"    {detail['date']} 连续{detail['coiledDay']}天 +{detail['score']}")
        if not res["success"]:
            lines.append(f"  错误: {res['error'][:100]}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    log_title()

    results: List[Dict[str, Any]] = []

    for index, server_entry in enumerate(SERVERS, 1):
        try:
            result = run_account(index, len(SERVERS), server_entry)
            results.append(result)
        except Exception as exc:
            print(f"  [主程序] 执行异常: {exc}")
            _, wxid = parse_yyb_go_entry(server_entry)
            results.append({
                "server": server_entry, "wxid": mask(wxid),
                "success": False, "error": traceback.format_exc().strip(),
                "token": "-", "userInfo": "-",
                "initialScore": 0, "finalScore": 0,
                "signMsg": "-", "signDetails": [],
                "proxyStatus": "-", "proxyIp": "-",
            })

        if index < len(SERVERS):
            print("  [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    total_score = sum(r.get("finalScore", 0) for r in results)

    print()
    print("+" + "=" * 50 + "+")
    print("| 🏀 布鲁大师任务执行完成                            |")
    print(f"| ✅ 成功: {success_count:<39}|")
    print(f"| ❌ 失败: {fail_count:<39}|")
    print(f"| 💎 总积分: {total_score:<38}|")
    print(f"| 🕒 结束时间: {now_text():<32}|")
    print("+" + "=" * 50 + "+")

    if notify:
        notify.send(APP_NAME, build_notify(results))


if __name__ == "__main__":
    main()
