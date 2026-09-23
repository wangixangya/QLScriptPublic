#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 海尔智家
# cron: 16 9,21 * * *

"""
海尔智家小程序（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code
  2. SHA256 签名认证 + jscode2session 换取 accountToken
  3. 查询用户信息 / 积分 / 红包
  4. 每日签到
  5. 青龙 notify 推送

环境变量：
  YYB_SERVER    YYB Go 服务地址，格式：server@wxid，多账号换行分隔
  PROXY_API     品赞代理提取 API，可选
  PROXY_TYPE    http / socks5，默认 http
"""

import hashlib
import json
import os
import random
import string
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

APP_NAME = "海尔智家"
APPID = "wxe24b2f1f4e378891"
PAGE_VERSION = "475"
HA_APP_ID = "MB-SHEZJAPPWXXCX-0000"
HA_APP_KEY = "79ce99cc7f9804663939676031b8a427"
API_HOST = "https://zj.haier.net"

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

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.31(0x18001e31) NetType/WIFI Language/zh_CN miniProgram"
)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def mask(value: Any) -> str:
    value = str(value or "")
    if len(value) <= 12:
        return f"{value[:3]}***"
    return f"{value[:6]}***{value[-6:]}"


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 7:
        return str(phone)
    return f"{str(phone)[:3]}****{str(phone)[-4:]}"


def json_preview(data: Any, limit: int = 300) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)[:limit]
    except Exception:
        return str(data)[:limit]


def random_string(length: int = 12) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def sign256(path: str, body: Dict[str, Any] | None, timestamp: int) -> str:
    body_str = json.dumps(body, separators=(",", ":")) if body else ""
    sign_str = f"{path}{body_str}{HA_APP_ID}{HA_APP_KEY}{timestamp}"
    return hashlib.sha256(sign_str.encode()).hexdigest()


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
            host = proxy_obj.get("ip") or proxy_obj.get("host") or proxy_obj.get("Ip")
            port = proxy_obj.get("port") or proxy_obj.get("Port")
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
    host, port = proxy_info["host"], proxy_info["port"]
    username, password = proxy_info.get("username", ""), proxy_info.get("password", "")
    auth = f"{quote(username)}:{quote(password)}@" if username and password else ""
    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"
    print(f"  [代理] 生成 {scheme.upper()} 代理 {host}:{port}")
    return {"http": proxy_url, "https": proxy_url}


def get_valid_proxy(server: str) -> Tuple[Dict[str, str] | None, str]:
    if not PROXY_API:
        return None, ""
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
                    return proxies, info["host"]
            except Exception:
                pass
        except Exception as exc:
            print(f"  [代理] 第{i}次获取异常: {exc}")
        if i < PROXY_RETRY_TIMES:
            sleep(2)
    print("  [代理] 获取失败，使用直连")
    return None, ""


def request_with_proxy(
    method: str, url: str, *,
    headers: Dict[str, str] = None,
    json_data: Dict = None,
    data: str = None,
    params: Dict = None,
    proxies: Dict[str, str] | None = None,
    server: str = "",
) -> requests.Response:
    kwargs: Dict[str, Any] = {"headers": headers, "timeout": REQUEST_TIMEOUT}
    if json_data is not None:
        kwargs["json"] = json_data
    if data is not None:
        kwargs["data"] = data
    if params is not None:
        kwargs["params"] = params
    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(f"  [代理] 请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("  [兜底] 切换直连重试")
    return direct_session().request(method, url, **kwargs)


# ============ 业务逻辑 ============

def build_headers(token: str, client_id: str, path: str, body: Dict | None, ts: int) -> Dict[str, str]:
    return {
        "host": "zj.haier.net",
        "Content-Type": "application/json;charset=UTF-8",
        "appId": HA_APP_ID,
        "appKey": HA_APP_KEY,
        "timestamp": str(ts),
        "platForm": "sc-mp-wx-zjapp",
        "ENV": "",
        "accessToken": token,
        "accountToken": token,
        "ak": token,
        "clientId": client_id,
        "accept": "*/*",
        "accept-language": "zh-CN,zh-Hans;q=0.9",
        "user-agent": USER_AGENT,
        "referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
        "sign": sign256(path, body, ts),
    }


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
        "points": "-",
        "wallet": "-",
        "signDay": "-",
        "error": "",
    }

    print(f"\n{'='*50}")
    print(f"账号 {index}/{total} ({mask(wxid)})")
    print(f"{'='*50}")

    proxies, proxy_ip = get_valid_proxy(str(parsed_server))
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    code = get_wx_code(server_entry)
    if not code:
        result["error"] = "获取 code 失败"
        return result

    client_id = f"{int(time.time() * 1000)}{random_string(12)}"

    try:
        # 1. jscode2session 登录
        ts = int(time.time() * 1000)
        path = "/api-gw/oauthserver/applet/v1/jscode2session"
        headers = build_headers("", client_id, path, {"code": code}, ts)
        headers["accessToken"] = ""
        headers["accountToken"] = ""
        headers["ak"] = ""

        resp = request_with_proxy(
            "POST", f"{API_HOST}{path}",
            headers=headers,
            json_data={"code": code},
            proxies=proxies, server=parsed_server,
        )
        try:
            login_data = resp.json()
        except Exception:
            login_data = {}
        print(f"  [登录] 响应: {json_preview(login_data)}")

        if login_data.get("retCode") != "00000":
            result["error"] = f"登录失败: {login_data.get('retInfo', json_preview(login_data))}"
            return result

        token_info = login_data.get("data", {}).get("tokenInfo", login_data.get("data", {}))
        token = token_info.get("accountToken", "")
        if not token:
            result["error"] = "登录未返回 accountToken"
            return result

        result["token"] = mask(token)
        print(f"  [登录] 成功: {mask(token)}")

        # 2. 查询用户信息
        ts = int(time.time() * 1000)
        path = "/api-gw/oauthserver/applet/v1/userinfo/query"
        headers = build_headers(token, client_id, path, {"accountToken": token}, ts)
        headers["accessToken"] = ""
        headers["accountToken"] = ""
        headers["ak"] = ""

        resp = request_with_proxy(
            "POST", f"{API_HOST}{path}",
            headers=headers,
            json_data={"accountToken": token},
            proxies=proxies, server=parsed_server,
        )
        try:
            user_data = resp.json()
        except Exception:
            user_data = {}

        if user_data.get("retCode") != "00000":
            result["userInfo"] = f"查询失败: {user_data.get('retInfo', '')}"
        else:
            user_info = user_data.get("data", {}).get("userinfo", {})
            name = user_info.get("nickName", user_info.get("nickname", "未知"))
            phone = user_info.get("mobile", user_info.get("phoneNumber", ""))
            result["userInfo"] = f"{name} {mask_phone(phone)}" if phone else name
            print(f"  [用户] {result['userInfo']}")

        # 3. 查询积分
        ts = int(time.time() * 1000)
        path = "/zjapi/zjBaseServer/signDetail/getUserPointsAndWallet"

        resp = request_with_proxy(
            "POST", f"{API_HOST}{path}",
            headers=build_headers(token, client_id, path, {}, ts),
            json_data={},
            proxies=proxies, server=parsed_server,
        )
        try:
            point_data = resp.json()
        except Exception:
            point_data = {}

        if point_data.get("retCode") == "00000":
            pd = point_data.get("data", {})
            result["points"] = str(pd.get("haiBeiTotal", "未知"))
            result["wallet"] = str(pd.get("wallet", "未知"))
            print(f"  [积分] 海贝:{result['points']} 红包:{result['wallet']}")
        else:
            result["points"] = "查询失败"
            result["wallet"] = "查询失败"

        # 4. 签到
        ts = int(time.time() * 1000)
        path = "/api-gw/zjBaseServer/daily/sign"

        resp = request_with_proxy(
            "POST", f"{API_HOST}{path}",
            headers=build_headers(token, client_id, path, {}, ts),
            json_data={},
            proxies=proxies, server=parsed_server,
        )
        try:
            sign_data = resp.json()
        except Exception:
            sign_data = {}

        if sign_data.get("retCode") == "00000":
            sd = sign_data.get("data", {})
            result["signDay"] = str(sd.get("totalSignDay", "未知"))
            print(f"  [签到] 已签到 {result['signDay']} 天")
            result["success"] = True
        else:
            result["error"] = f"签到失败: {sign_data.get('retInfo', '')}"
            print(f"  [签到] {result['error']}")

    except Exception as exc:
        result["error"] = f"{exc}"
        print(f"  [账号] 执行异常: {exc}")

    return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    lines = [f"海尔智家签到结果", "—" * 30]
    lines.append(f"✅ {ok}成功 / ❌ {fail}失败")
    lines.append(f"🕒 {now_text()}")
    lines.append("")
    for i, r in enumerate(results, 1):
        icon = "✅" if r.get("success") else "❌"
        lines.append(f"{icon} 账号{i} ({r.get('wxid', '-')})")
        lines.append(f"  用户: {r['userInfo']}")
        lines.append(f"  海贝: {r['points']} | 红包: {r['wallet']}")
        lines.append(f"  签到: 已签到{r['signDay']}天")
        if not r.get("success"):
            lines.append(f"  错误: {r['error'][:100]}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    print(f"\n{'='*50}")
    print(f"海尔智家（YYB Go版）")
    print(f"启动: {now_text()} | 账号: {len(SERVERS)}")
    print(f"{'='*50}")

    results: List[Dict[str, Any]] = []
    for idx, server_entry in enumerate(SERVERS):
        try:
            r = run_account(idx + 1, len(SERVERS), server_entry)
            results.append(r)
        except Exception as exc:
            _, wxid = parse_yyb_go_entry(server_entry)
            results.append({
                "server": server_entry, "wxid": mask(wxid),
                "success": False, "error": f"{exc}",
                "token": "-", "userInfo": "-",
                "points": "-", "wallet": "-", "signDay": "-",
                "proxyStatus": "-", "proxyIp": "-",
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
