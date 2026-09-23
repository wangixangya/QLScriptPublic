#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 安吉尔
# cron: 25 8,20 * * *

"""
安吉尔积分签到动态 code 版

功能：
  1. 四端口本地服务获取微信 code
  2. wxLogin 使用 code 换 token + userId
  3. token 缓存，失效自动重登
  4. 每月签到表签到
  5. 查询积分
  6. PushPlus 推送
  7. 品赞代理，业务请求优先代理，失败直连兜底

环境变量：
  YYB_SERVER        YYB Go 服务地址，格式：地址@微信账号标识，多账号换行分隔
  PLUSPLUS_TOKEN    PushPlus token，可选
  PROXY_API         品赞代理提取 API，可选
  PROXY_TYPE        http / socks5，默认 http

依赖：
  pip install requests
  socks5 代理需：
  pip install requests[socks]
"""

import json
import os
import random
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


APP_NAME = "安吉尔微信小程序"
APPID = "wxc4a1f99a6c90c1a4"

_YYB_SERVER_RAW = os.getenv("YYB_SERVER", "")
SERVERS = [line.strip() for line in _YYB_SERVER_RAW.splitlines() if line.strip()]
if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识，多账号换行分隔）")
    exit(1)
print(f"✅ 读取到 {len(SERVERS)} 个 YYB Go 账号")

TOKEN_FILE = "ajecookie.json"

PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()

PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

LOGIN_URL = "https://userone.angelgroup.com.cn/api/member/app/wxLogin"
USER_INFO_URL = "https://userone.angelgroup.com.cn/api/member/v1/user/queryInfo"
SIGN_TABLE_URL = "https://userone.angelgroup.com.cn/api/member/marketSign/signTable"

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16; 2308CPXD0C Build/BP2A.250605.031.A3; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.178 "
    "Mobile Safari/537.36 XWEB/1460249 MMWEBSDK/20260502 MMWEBID/6435 "
    "MicroMessenger/8.0.76.3141(0x28004C3C) WeChat/arm64 Weixin NetType/WIFI "
    "Language/zh_CN ABI/arm64 MiniProgramEnv/android"
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


def log_title() -> None:
    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🏷️ 安吉尔积分签到动态 code 版                  ║")
    print(f"║ 🕒 启动时间: {now_text():<32}║")
    print(f"║ 🔢 账号数量: {len(SERVERS):<34}║")
    print("╚" + "═" * 50 + "╝")


def log_account_header(index: int, total: int, server: str) -> None:
    print()
    print("┌" + "─" * 50 + "┐")
    print(f"│ 🧩 账号 {index} / {total:<37}│")
    print(f"│ 🌍 来源 {server:<40}│")
    print("└" + "─" * 50 + "┘")


def direct_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


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
                    "host": str(host),
                    "port": int(port),
                    "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                    "password": proxy_obj.get("pass") or proxy_obj.get("password") or "",
                }
    except Exception:
        pass

    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            return {
                "host": parts[0],
                "port": int(parts[1]),
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

    print(f"🛠️ [代理] 生成 {scheme.upper()} 代理 {host}:{port}")

    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def validate_proxy(proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    if not proxies:
        return False, ""

    try:
        response = requests.get(PROXY_VALIDATE_URL, proxies=proxies, timeout=15)
        if response.status_code == 200:
            try:
                ip = response.json().get("origin", "未知")
            except Exception:
                ip = "未知"
            print(f"✅ [代理] 验证通过，出口 IP: {ip}")
            return True, ip
    except Exception as exc:
        print(f"⚠️ [代理] 验证失败: {exc}")

    return False, ""


def get_valid_proxy(account_name: str) -> Tuple[Dict[str, str] | None, str]:
    if not PROXY_API:
        print(f"⚠️ [代理] {account_name} 未配置 PROXY_API，使用直连")
        return None, ""

    print(f"🌐 [代理] {account_name} 正在获取品赞代理...")

    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(response.text)

            if not proxy_info:
                print(f"⚠️ [代理] 第 {index} 次代理解析失败")
                continue

            print(f"✅ [代理] 提取到 {proxy_info['host']}:{proxy_info['port']}")
            proxies = build_proxy_dict(proxy_info)

            ok, ip = validate_proxy(proxies)
            if ok:
                return proxies, ip

            print(f"⚠️ [代理] 第 {index} 次代理不可用")
        except Exception as exc:
            print(f"⚠️ [代理] 第 {index} 次获取代理异常: {exc}")

        if index < PROXY_RETRY_TIMES:
            sleep(2)

    print("⚠️ [代理] 获取失败，使用直连")
    return None, ""


def request_with_proxy(
    method: str,
    url: str,
    *,
    proxies: Dict[str, str] | None = None,
    server: str = "",
    **kwargs,
) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    kwargs.setdefault("verify", False)

    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(f"⚠️ [代理] {server} 代理请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("🔁 [兜底] 切换直连重试")

    session = direct_session()
    return session.request(method, url, **kwargs)


def send_pushplus(title: str, content: str) -> None:
    if not PLUSPLUS_TOKEN:
        print("⚠️ [PushPlus] 未配置 PLUSPLUS_TOKEN，跳过推送")
        return

    try:
        requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": PLUSPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "txt",
            },
            timeout=10,
        )
        print("✅ [PushPlus] 推送成功")
    except Exception as exc:
        print(f"❌ [PushPlus] 推送失败: {exc}")


# ==================== 缓存管理 ====================
def load_cache() -> Dict[str, Any]:
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: Dict[str, Any]) -> None:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ==================== 本地 code 服务 ====================
def parse_yyb_entry(raw: str) -> Tuple[str, str]:
    """解析 YYB_SERVER 条目：地址@微信账号标识 → (server, ref)"""
    raw = raw.strip()
    if "@" not in raw:
        print(f"❌ YYB_SERVER 格式应为 地址@微信账号标识，当前值：{raw}")
        return "", ""
    server, ref = raw.split("@", 1)
    server = server.strip().lstrip("http://").lstrip("https://").rstrip("/")
    ref = ref.strip()
    if not server or not ref:
        print(f"❌ YYB_SERVER 缺少地址或微信账号标识，当前值：{raw}")
        return "", ""
    return server, ref


def get_code(entry: str) -> str | None:
    """通过 YYB Go 取码服务获取微信小程序 login code"""
    server, ref = parse_yyb_entry(entry)
    if not server or not ref:
        return None

    url = f"http://{server}/wxapp/getCode"
    print(f"🔐 [授权] 请求 YYB Go 取码: {url}")

    try:
        response = direct_session().post(
            url,
            json={"ref": ref, "app_id": APPID},
            timeout=20,
        )
        data = response.json()

        code = ((data.get("data") or {}).get("result") or {}).get("code")
        if data.get("code") != 0 or not code:
            print(f"❌ [授权] 取码失败: {json_preview(data)}")
            return None

        print("✅ [授权] 取码成功")
        return code
    except Exception as exc:
        print(f"❌ [授权] 取码异常: {exc}")
        return None


# ==================== 业务接口 ====================
def login_headers() -> Dict[str, str]:
    return {
        "behavior": "{}",
        "content-type": "application/json",
        "merchantId": "10000",
        "charset": "utf-8",
        "Referer": f"https://servicewechat.com/{APPID}/76/page-frame.html",
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate, br",
    }


def wx_login(server: str, code: str, proxies: Dict[str, str] | None) -> Tuple[str | None, str | None, Dict[str, Any] | None]:
    try:
        print("🔐 [登录] 使用 code 换 token")
        response = request_with_proxy(
            "POST",
            LOGIN_URL,
            headers=login_headers(),
            json={"sourceType": 1, "code": code},
            proxies=proxies,
            server=server,
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:800]}

        if str(data.get("code")) == "200":
            inner = data.get("data") or {}
            token = inner.get("token")
            user_id = inner.get("buyerUserId")
            if token and user_id:
                print(f"✅ [登录] token 获取成功: {mask(token)}")
                return token, str(user_id), data
        print(f"❌ [登录] 登录失败: {json_preview(data)}")
        return None, None, data
    except Exception as exc:
        print(f"❌ [登录] 请求异常: {exc}")
        return None, None, None


def get_user_info(token: str, proxies: Dict[str, str] | None, server: str) -> Tuple[str | None, Any]:
    headers = {
        "merchantId": "10000",
        "Authorization": f"Bearer {token}",
        "Cache-Control": "no-cache",
        "behavior": "{}",
        "xweb_xhr": "1",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Referer": f"https://servicewechat.com/{APPID}/49/page-frame.html",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        response = request_with_proxy("GET", USER_INFO_URL, headers=headers, proxies=proxies, server=server)
        result = response.json()
        if str(result.get("code")) == "200":
            data = result.get("data") or {}
            return data.get("nickName", "未知用户"), data.get("integral", 0)
        return None, None
    except Exception:
        return None, None


def checkin(token: str, user_id: str, proxies: Dict[str, str] | None, server: str) -> Tuple[bool, str]:
    now = datetime.now()
    year = now.year
    month = now.month

    if month == 12:
        next_month_start = datetime(year + 1, 1, 1)
    else:
        next_month_start = datetime(year, month + 1, 1)
    month_end = next_month_start.replace(hour=23, minute=59, second=59) - timedelta(days=1)
    month_start = datetime(year, month, 1, 0, 0, 0)

    payload = json.dumps({
        "checkInDateStart": month_start.strftime("%Y-%m-%d %H:%M:%S"),
        "checkInDateEnd": month_end.strftime("%Y-%m-%d %H:%M:%S"),
        "month": month,
        "userId": user_id,
    })

    headers = {
        "Authorization": f"Bearer {token}",
        "behavior": "{}",
        "merchantId": "10000",
        "content-type": "application/json",
        "charset": "utf-8",
        "Referer": f"https://servicewechat.com/{APPID}/49/page-frame.html",
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "*/*",
    }

    try:
        response = request_with_proxy(
            "POST",
            SIGN_TABLE_URL,
            headers=headers,
            data=payload,
            proxies=proxies,
            server=server,
        )
        result = response.json()
        if result.get("code") == 200 or result.get("success"):
            return True, f"签到成功: {result.get('message', 'OK')}"
        return False, f"签到失败: {result.get('message', '未知错误')}"
    except Exception as exc:
        return False, f"请求异常: {exc}"


def run_account(index: int, total: int, server: str) -> Dict[str, Any]:
    cache = load_cache()

    result = {
        "server": server,
        "success": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "token": "-",
        "signMsg": "-",
        "points": "-",
        "user": "-",
        "error": "",
    }

    log_account_header(index, total, server)

    proxies, proxy_ip = get_valid_proxy(server)
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    sleep(PROXY_FETCH_INTERVAL)

    delay = random.randint(2, 6)
    print(f"⏳ [延迟] 启动延迟 {delay}s")
    sleep(delay)

    token_data = cache.get(server) or {}
    token = token_data.get("token")
    user_id = token_data.get("userId")

    for attempt in range(2):
        if token:
            nick, integral = get_user_info(token, proxies, server)
            if nick is not None:
                result["user"] = nick
                result["points"] = str(integral)
                print(f"💰 [积分] {nick}: {integral}")

                status, msg = checkin(token, user_id, proxies, server)
                result["signMsg"] = msg
                print(f"📝 [签到] {msg}")

                if status:
                    result["token"] = mask(token)
                    result["success"] = True
                    return result

                print("🔄 [重试] 签到失败，尝试重新登录")
                token = None
                continue

            print("❌ [验证] token 失效，重新登录")
            token = None
            continue

        code = get_code(server)
        if not code:
            result["error"] = "获取 code 失败"
            return result

        new_token, new_user_id, raw_login = wx_login(server, code, proxies)
        if not new_token or not new_user_id:
            result["error"] = f"登录失败: {json_preview(raw_login)}"
            return result

        token = new_token
        user_id = new_user_id
        cache[server] = {
            "token": token,
            "userId": user_id,
            "update_time": now_text(),
        }
        save_cache(cache)
        print("✅ [登录] token 已缓存")

    result["error"] = "多次重试后仍失败"
    return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count

    content = f"""🏷️ 安吉尔签到任务结果

━━━━━━━━━━━━━━━━━━━━
🏁 总结：{success_count} 成功 / {fail_count} 失败
🕒 时间：{now_text()}
━━━━━━━━━━━━━━━━━━━━
"""

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"
        content += f"""
🧩 账号 {idx}
🌍 来源：{res["server"]}
🌐 代理：{res["proxyStatus"]}
📡 出口IP：{res["proxyIp"]}
🔐 Token：{res["token"]}
👤 用户：{res["user"]}
📝 签到：{res["signMsg"]}
💰 积分：{res["points"]}
{icon} 结果：{"成功" if res["success"] else "失败"}
"""
        if not res["success"]:
            content += f"❌ 原因：{res['error']}\n"
        content += "━━━━━━━━━━━━━━━━━━━━\n"

    return content


def main() -> None:
    log_title()

    results: List[Dict[str, Any]] = []

    for index, server in enumerate(SERVERS, 1):
        try:
            result = run_account(index, len(SERVERS), server)
            results.append(result)
        except Exception as exc:
            print(f"❌ [主程序] {server} 执行异常: {exc}")
            results.append({
                "server": server,
                "success": False,
                "proxyStatus": "-",
                "proxyIp": "-",
                "token": "-",
                "signMsg": "-",
                "points": "-",
                "user": "-",
                "error": traceback.format_exc().strip(),
            })

        if index < len(SERVERS):
            print("⏳ [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count

    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🏁 安吉尔任务执行完成                          ║")
    print(f"║ ✅ 成功: {success_count:<39}║")
    print(f"║ ❌ 失败: {fail_count:<39}║")
    print(f"║ 🕒 结束时间: {now_text():<32}║")
    print("╚" + "═" * 50 + "╝")

    send_pushplus("🏷️ 安吉尔签到任务完成", build_notify(results))


if __name__ == "__main__":
    main()
