#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 小紫有约
# cron: 35 8,20 * * *

"""
小紫有约积分签到动态 code 版

功能：
  1. 四端口本地服务获取微信 code
  2. wechatAuthenticate 使用 code 换 sessionId
  3. SESSION 缓存，失效自动重登
  4. actCode 自动发现（每月缓存）
  5. 每日签到
  6. 查询积分
  7. PushPlus 推送
  8. 品赞代理，业务请求优先代理，失败直连兜底

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

import datetime
import json
import os
import random
import time
import traceback
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import requests


APP_NAME = "小紫有约微信小程序"
APPID = "wx3db193ecdebd3fea"
HOST = "sxkyziqidonglai.cn"
BASE_URL = f"https://{HOST}"

_YYB_SERVER_RAW = os.getenv("YYB_SERVER", "")
SERVERS = [line.strip() for line in _YYB_SERVER_RAW.splitlines() if line.strip()]
if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识，多账号换行分隔）")
    exit(1)
print(f"✅ 读取到 {len(SERVERS)} 个 YYB Go 账号")

CHANNEL_CODE = "WXjxriol8e8293wezu"
DEVICE_HASH = "lkmtJuKGKQ0_S6Oem6ZIv3YoiHYGgoMf"
SITE_ID = "SITE_33254242630091515087"

SESSION_FILE = "xzyycookie.json"
ACTCODE_CACHE_FILE = "actCode_cache.json"

PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()

PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

API_USER_INFO = f"{BASE_URL}/api/mobile/eShop/eshopVipUser/getUserInfo"
API_SIGN = f"{BASE_URL}/api/mobile/activity-v2/activity/launchByValidater"
API_WX_AUTH = f"{BASE_URL}/api/platform/wechatAuthenticate"

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16; 2308CPXD0C Build/BP2A.250605.031.A3; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.178 "
    "Mobile Safari/537.36 XWEB/1460217 MMWEBSDK/20260202 MMWEBID/6435 "
    "REV/89918ef4d19865ac6236e9f77c99567b0ec6d85b "
    "MicroMessenger/8.0.70.3060(0x28004652) WeChat/arm64 Weixin "
    "NetType/WIFI Language/zh_CN ABI/arm64"
)


def now_text() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
    print("║ 🍇 小紫有约积分签到动态 code 版                  ║")
    print(f"║ 🕒 启动时间: {now_text():<32}║")
    print(f"║ 🔢 账号数量: {len(SERVERS):<34}║")
    print(f"║ 🎫 actCode 自动发现                            ║")
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


# ==================== 缓存 ====================
def load_session_cache() -> Dict[str, Any]:
    if not os.path.exists(SESSION_FILE):
        return {}
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"⚠️ [缓存] 读取缓存文件失败: {exc}")
        return {}


def save_session_cache(cache: Dict[str, Any]) -> None:
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"⚠️ [缓存] 保存缓存文件失败: {exc}")


def load_actcode_cache() -> Tuple[str | None, str | None]:
    if not os.path.exists(ACTCODE_CACHE_FILE):
        return None, None
    try:
        with open(ACTCODE_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("actCode"), data.get("month")
    except Exception:
        return None, None


def save_actcode_cache(act_code: str, month: str) -> None:
    with open(ACTCODE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"actCode": act_code, "month": month}, f)


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
def common_headers(session: str) -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/mall/personal?siteId={SITE_ID}&channelCode={CHANNEL_CODE}",
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Android WebView";v="146"',
        "sec-ch-ua-mobile": "?1",
        "x-requested-with": "com.tencent.mm",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "cookie": f"SESSION={session}",
    }


def get_session_by_code(server: str, code: str, proxies: Dict[str, str] | None) -> str | None:
    params = {
        "code": code,
        "channelCode": CHANNEL_CODE,
        "siteId": SITE_ID,
        "deviceHash": DEVICE_HASH,
    }
    headers = {
        "User-Agent": USER_AGENT,
        "accept": "application/json, text/plain, */*",
        "sec-ch-ua-platform": '"Android"',
        "cache-control": "no-cache",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Android WebView";v="146"',
        "sec-ch-ua-mobile": "?1",
        "x-requested-with": "com.tencent.mm",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": f"{BASE_URL}/mall/personal?siteId={SITE_ID}&channelCode={CHANNEL_CODE}",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        response = request_with_proxy("GET", API_WX_AUTH, headers=headers, params=params, proxies=proxies, server=server)
        response.raise_for_status()
        res = response.json()
        if res.get("success") and res.get("status") == 200:
            session_id = res["data"]["sessionId"]
            print(f"✅ [登录] SESSION 获取成功: {mask(session_id)}")
            return session_id
        print(f"❌ [登录] 换取 SESSION 失败: {res.get('msg', '未知错误')}")
        return None
    except Exception as exc:
        print(f"❌ [登录] 换取 SESSION 异常: {exc}")
        return None


def get_user_info(server: str, session: str, proxies: Dict[str, str] | None) -> Tuple[str | None, Any]:
    headers = common_headers(session)
    headers["content-type"] = "application/x-www-form-urlencoded"
    data = {"siteId": SITE_ID}
    try:
        response = request_with_proxy(
            "POST", API_USER_INFO, headers=headers, data=data, proxies=proxies, server=server
        )
        rs = response.json()
        if rs.get("status") == 200:
            inner = rs.get("data") or {}
            return inner.get("phone", "未知用户"), inner.get("balance", 0)
        print(f"❌ [验证] 登录失效: {rs.get('msg')}")
        return None, None
    except Exception as exc:
        print(f"❌ [验证] 请求用户信息异常: {exc}")
        return None, None


def do_sign(server: str, session: str, act_code: str, proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    headers = common_headers(session)
    data = {"actCode": act_code, "siteId": SITE_ID}
    try:
        response = request_with_proxy("POST", API_SIGN, headers=headers, json=data, proxies=proxies, server=server)
        rs = response.json()
        status = rs.get("status")
        msg = rs.get("msg", "")
        if status == 200:
            return True, "签到成功"
        if status == 412 and "已完成签到" in msg:
            return True, "今日已签到，无需重复签到"
        return False, f"签到失败: {msg}"
    except Exception as exc:
        return False, f"请求异常: {exc}"


def test_actcode(server: str, session: str, act: str, proxies: Dict[str, str] | None) -> bool:
    headers = common_headers(session)
    data = {"actCode": act, "siteId": SITE_ID}
    try:
        response = request_with_proxy("POST", API_SIGN, headers=headers, json=data, proxies=proxies, server=server)
        response.raise_for_status()
        res = response.json()
        print(f"\n[actCode 探测] {act}: {json_preview(res, 300)}")
        status = res.get("status")
        msg = str(res.get("msg", ""))
        if res.get("success") or status == 200:
            return True
        if status == 412 and "已完成签到" in msg:
            return True
        return False
    except Exception as exc:
        print(f"\n[actCode 探测] {act} 异常: {exc}")
        return False


def generate_candidates(now: datetime.datetime) -> List[str]:
    if now.month == 1:
        last_year = now.year - 1
        last_month = 12
    else:
        last_year = now.year
        last_month = now.month - 1
    year_2 = last_year % 100
    prefix = f"SG{year_2:02d}{last_month}"
    return [prefix + str(i) for i in range(10)]


def discover_act_code(proxies: Dict[str, str] | None) -> str | None:
    """使用第一个本地端口获取 code 来探测 actCode"""
    server = SERVERS[0]
    print(f"ℹ️ [actCode] 使用本地端口【{server}】探测 actCode")

    code = get_code(server)
    if not code:
        print("❌ [actCode] 获取 code 失败")
        return None
    session = get_session_by_code("actCode 探测", code, proxies)
    if not session:
        print("❌ [actCode] 获取 SESSION 失败")
        return None

    candidates = generate_candidates(datetime.datetime.now())
    print(f"ℹ️ [actCode] 生成 {len(candidates)} 个候选，开始测试")
    for act in candidates:
        print(f"测试 {act} ...", end=" ")
        if test_actcode("actCode 探测", session, act, proxies):
            print("✅ 有效")
            return act
        print("❌ 无效")
        sleep(1.5)
    print()
    print("❌ [actCode] 未找到有效 actCode")
    return None


def run_account(index: int, total: int, server: str, cache: Dict[str, Any], act_code: str) -> Dict[str, Any]:
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

    cached_session = cache.get(server)
    session = cached_session if cached_session else None

    for attempt in range(2):
        if session:
            nick, points = get_user_info(server, session, proxies)
            if nick is not None:
                result["user"] = nick
                result["points"] = str(points)
                result["token"] = mask(session)
                print(f"💰 [积分] {nick}: {points}")

                if not act_code:
                    result["signMsg"] = "actCode 为空，跳过签到"
                    result["success"] = True
                    return result

                status, msg = do_sign(server, session, act_code, proxies)
                result["signMsg"] = msg
                print(f"📝 [签到] {msg}")

                if status:
                    _, new_points = get_user_info(server, session, proxies)
                    if new_points is not None:
                        result["points"] = str(new_points)
                    result["success"] = True
                    return result

                print("🔄 [重试] 签到失败，尝试重新登录")
                session = None
                continue

            print("❌ [验证] SESSION 失效，重新登录")
            session = None
            continue

        code = get_code(server)
        if not code:
            result["error"] = "获取 code 失败"
            return result

        new_session = get_session_by_code(server, code, proxies)
        if not new_session:
            result["error"] = "兑换 SESSION 失败"
            return result

        session = new_session
        cache[server] = session
        save_session_cache(cache)
        print("✅ [登录] SESSION 已缓存")

    result["error"] = "多次重试后仍失败"
    return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count

    content = f"""🍇 小紫有约签到任务结果

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
🔐 Session：{res["token"]}
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

    cached_act, cached_month = load_actcode_cache()
    now = datetime.datetime.now()
    current_month = f"{now.year}-{now.month:02d}"

    act_code: str | None = None
    if cached_act and cached_month == current_month:
        act_code = cached_act
        print(f"ℹ️ [actCode] 使用缓存: {act_code} (月份 {cached_month})")
    else:
        print("ℹ️ [actCode] 正在自动发现本月签到 actCode")
        act_code = discover_act_code(None)
        if act_code:
            save_actcode_cache(act_code, current_month)
            print(f"ℹ️ [actCode] 发现并缓存: {act_code}")
        else:
            print("❌ [actCode] 自动发现失败，签到将被跳过")

    print(f"🔢 [账号] 共 {len(SERVERS)} 个本地端口")

    cache = load_session_cache()

    results: List[Dict[str, Any]] = []

    for index, server in enumerate(SERVERS, 1):
        try:
            result = run_account(index, len(SERVERS), server, cache, act_code or "")
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
    print("║ 🏁 小紫有约任务执行完成                        ║")
    print(f"║ ✅ 成功: {success_count:<39}║")
    print(f"║ ❌ 失败: {fail_count:<39}║")
    print(f"║ 🕒 结束时间: {now_text():<32}║")
    print("╚" + "═" * 50 + "╝")

    send_pushplus("🍇 小紫有约签到任务完成", build_notify(results))


if __name__ == "__main__":
    main()
