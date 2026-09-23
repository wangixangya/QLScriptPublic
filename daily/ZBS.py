#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 植白说
# cron: 32 6,18 * * *

"""
植白说官方商城小程序（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code，code 换 token 登录
  2. Token 缓存（失效自动重新登录）
  3. 每日签到
  4. 分享加积分
  5. 领取优惠券（自动遍历可领券列表）
  6. 订阅通知
  7. 查询积分/连签天数
  8. 青龙 notify 推送

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

APP_NAME = "植白说官方商城小程序"
APPID = "wx6b6c5243359fe265"

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

BASE_URL = "https://www.kozbs.com/demo/wx"

SIGN_URL = f"{BASE_URL}/home/sign"
ADD_INTEGRAL_BY_SHARE_URL = f"{BASE_URL}/user/addIntegralByShare"
COUPON_LIST_URL = f"{BASE_URL}/coupon/list"
COUPON_MY_LIST_URL = f"{BASE_URL}/coupon/mylist"
COUPON_RECEIVE_URL = f"{BASE_URL}/coupon/receive"
SUBSCRIPTION_URL = f"{BASE_URL}/user/subscription"
USER_INDEX_URL = f"{BASE_URL}/user/index"
USER_INTEGRAL_URL = f"{BASE_URL}/user/getUserIntegral"
USER_IS_SIGN_URL = f"{BASE_URL}/user/getUserIsSign"
SIGN_DAY_URL = f"{BASE_URL}/home/signDay"
LOGIN_URL = f"{BASE_URL}/auth/login_by_weixin"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541a1d) XWEB/19899"
)

# Token 缓存
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "zbs_token_cache.json")


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
    print("+" + "=" * 50 + "+")
    print("| 💚 植白说官方商城（YYB Go版）                    |")
    print(f"| 🕒 启动时间: {now_text():<35}|")
    print(f"| 🔢 账号数量: {len(SERVERS):<37}|")
    print("+" + "=" * 50 + "+")


def log_account_header(index: int, total: int, server: str) -> None:
    print()
    print("+" + "-" * 50 + "+")
    print(f"| 🧩 账号 {index} / {total:<41}|")
    print(f"| 🌍 来源 {server:<44}|")
    print("+" + "-" * 50 + "+")


# ============ Token 缓存 ============

def read_token_cache() -> Dict[str, Any]:
    try:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_token_cache(cache: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"  [缓存] 写入失败: {exc}")


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
        "Referer": f"https://servicewechat.com/{APPID}/171/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["X-Dts-Token"] = token
    return headers


def api_get(url: str, token: str, proxies: Dict[str, str] | None, server: str = "") -> Dict[str, Any]:
    response = request_with_proxy("GET", url, headers=common_headers(token), proxies=proxies, server=server)
    try:
        return response.json()
    except Exception:
        return {"errno": -1, "errmsg": f"JSON解析失败: {response.text[:300]}"}


def api_post(url: str, token: str, proxies: Dict[str, str] | None, payload: Dict[str, Any], server: str = "") -> Dict[str, Any]:
    response = request_with_proxy("POST", url, headers=common_headers(token), json=payload, proxies=proxies, server=server)
    try:
        return response.json()
    except Exception:
        return {"errno": -1, "errmsg": f"JSON解析失败: {response.text[:300]}"}


def is_token_error(message: str) -> bool:
    import re
    return bool(re.search(r'(^|[^0-9])501([^0-9]|$)|token|登录|授权|未登录|失效|过期', str(message), re.IGNORECASE))


def login_by_wx_code(server_entry: str, proxies: Dict[str, str] | None) -> Tuple[str | None, Dict[str, Any]]:
    """通过 YYB Go 获取 code，然后登录换 token"""
    parsed_server, _ = parse_yyb_go_entry(server_entry)
    code = get_wx_code(server_entry)
    if not code:
        return None, {}

    try:
        resp = request_with_proxy(
            "POST", LOGIN_URL,
            headers=common_headers(),
            json={"code": code, "userInfo": {}, "shareUserId": 1},
            proxies=proxies, server=parsed_server or "",
        )
        data = resp.json()
        if data.get("errno") != 0:
            print(f"  [登录] 登录失败: {data.get('errmsg', json_preview(data))}")
            return None, {}

        token = (data.get("data") or {}).get("token")
        if not token:
            print(f"  [登录] 响应未返回token: {json_preview(data)}")
            return None, {}

        user_info = (data.get("data") or {}).get("userInfo", {})
        nickname = user_info.get("nickname", "")
        mobile = user_info.get("mobile", "")
        print(f"  [登录] 登录成功: {nickname or mask(mobile)}")
        return token, user_info

    except Exception as exc:
        print(f"  [登录] 登录异常: {exc}")
        return None, {}


def check_token(token: str, user_id: str, proxies: Dict[str, str] | None, server: str) -> bool:
    """检查 token 是否有效"""
    url = f"{USER_INTEGRAL_URL}?userId={user_id}"
    resp = api_get(url, token, proxies, server)
    if resp.get("errno") == 0:
        return True
    if is_token_error(str(resp.get("errmsg", ""))):
        return False
    # 其他错误可能是业务问题，token 本身可能还有效
    return True


def do_sign(token: str, user_id: str, proxies: Dict[str, str] | None, server: str) -> str:
    url = f"{SIGN_URL}?userId={user_id}"
    resp = api_get(url, token, proxies, server)
    if resp.get("errno") == 0:
        return "签到成功"
    msg = resp.get("errmsg") or "签到失败"
    if "已签" in msg or "重复" in msg:
        return "今日已签到"
    return msg


def do_add_integral_by_share(token: str, user_id: str, proxies: Dict[str, str] | None, server: str) -> str:
    url = f"{ADD_INTEGRAL_BY_SHARE_URL}?userId={user_id}"
    resp = api_get(url, token, proxies, server)
    if resp.get("errno") == 0:
        return "分享积分+1"
    return resp.get("errmsg") or "分享积分失败"


def do_receive_coupons(token: str, proxies: Dict[str, str] | None, server: str) -> str:
    list_url = f"{COUPON_LIST_URL}?page=1&size=100"
    resp = api_get(list_url, token, proxies, server)
    if resp.get("errno") != 0:
        return f"获取券列表失败: {resp.get('errmsg', '')}"
    coupon_list = resp.get("data", {}).get("data", [])
    if not coupon_list:
        return "暂无可领优惠券"

    my_resp = api_get(f"{COUPON_MY_LIST_URL}?status=0&page=1&size=100", token, proxies, server)
    my_coupon_ids = set()
    if my_resp.get("errno") == 0:
        for c in my_resp.get("data", {}).get("data", []):
            my_coupon_ids.add(c.get("id"))

    received = []
    for coupon in coupon_list:
        coupon_id = coupon.get("id")
        coupon_name = coupon.get("name", "未知券")
        if coupon.get("isGet") == 1 or coupon_id in my_coupon_ids:
            continue
        sleep(random.uniform(1, 3))
        recv_resp = api_post(COUPON_RECEIVE_URL, token, proxies, {"couponId": coupon_id}, server)
        if recv_resp.get("errno") == 0:
            received.append(coupon_name)
            print(f"    [领券] {coupon_name} - 成功")
        else:
            print(f"    [领券] {coupon_name} - 失败: {recv_resp.get('errmsg', '未知错误')}")
        my_coupon_ids.add(coupon_id)

    if not received:
        return "所有优惠券已领完"
    return f"领取 {len(received)} 张: {'、'.join(received)}"


def do_subscription(token: str, proxies: Dict[str, str] | None, server: str) -> str:
    resp = api_post(SUBSCRIPTION_URL, token, proxies, {"type": "1"}, server)
    if resp.get("errno") == 0:
        return "订阅成功"
    return resp.get("errmsg") or "订阅失败"


def do_get_integral(token: str, user_id: str, proxies: Dict[str, str] | None, server: str) -> Tuple[str, int]:
    url = f"{USER_INTEGRAL_URL}?userId={user_id}"
    resp = api_get(url, token, proxies, server)
    if resp.get("errno") == 0:
        integral = resp.get("data", {}).get("integer", 0)
        return str(int(integral)), int(integral)
    return "查询失败", 0


def do_check_sign(token: str, user_id: str, proxies: Dict[str, str] | None, server: str) -> bool:
    url = f"{USER_IS_SIGN_URL}?userId={user_id}"
    resp = api_get(url, token, proxies, server)
    if resp.get("errno") == 0:
        return resp.get("data", {}).get("isSign", False)
    return False


def do_sign_day(token: str, user_id: str, proxies: Dict[str, str] | None, server: str) -> str:
    url = f"{SIGN_DAY_URL}?userId={user_id}"
    resp = api_get(url, token, proxies, server)
    if resp.get("errno") == 0:
        data = resp.get("data", {})
        sign_count = data.get("signCount", 0)
        integral = data.get("integral", 0)
        lottery_num = data.get("lotteryNum", 0)
        return f"已签{sign_count}天, 积分{integral}, 抽奖{lottery_num}次"
    return "查询签到天数失败"


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
        "userId": "-",
        "signMsg": "-",
        "shareMsg": "-",
        "couponMsg": "-",
        "subscribeMsg": "-",
        "integral": "-",
        "signDayMsg": "-",
        "error": "",
    }

    log_account_header(index, total, parsed_server or server_entry)

    proxies, proxy_ip = get_valid_proxy(str(parsed_server))
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    delay = random.randint(2, 6)
    print(f"  [延迟] 启动延迟 {delay}s")
    sleep(delay)

    # 尝试从缓存获取 token
    cache = read_token_cache()
    cached = cache.get(wxid) or {}
    token = cached.get("token", "")
    user_info = cached.get("userInfo", {})
    user_id = str(user_info.get("userId") or user_info.get("id") or "")

    if token:
        print(f"  [缓存] 使用缓存token: {mask(token)}")
        if not check_token(token, user_id, proxies, parsed_server or ""):
            print("  [缓存] token已失效，重新登录")
            # 清除缓存
            if wxid in cache:
                del cache[wxid]
                write_token_cache(cache)
            token = ""
            user_info = {}
            user_id = ""

    # 缓存无效则重新登录
    if not token:
        token, user_info = login_by_wx_code(server_entry, proxies)
        if not token:
            result["error"] = "登录失败"
            return result
        user_id = str(user_info.get("userId") or user_info.get("id") or "")
        # 保存缓存
        cache = read_token_cache()
        cache[wxid] = {"token": token, "userInfo": user_info, "updatedAt": now_text()}
        write_token_cache(cache)

    result["token"] = mask(token)
    result["userId"] = user_id or "未知"

    try:
        # 检查是否已签到
        already_signed = do_check_sign(token, user_id, proxies, parsed_server or "")
        if already_signed:
            result["signMsg"] = "今日已签到"
            print("  [签到] 今日已签到，跳过")
        else:
            sign_msg = do_sign(token, user_id, proxies, parsed_server or "")
            result["signMsg"] = sign_msg
            print(f"  [签到] {sign_msg}")

        sleep(random.uniform(1, 3))

        # 连签信息
        sign_day_msg = do_sign_day(token, user_id, proxies, parsed_server or "")
        result["signDayMsg"] = sign_day_msg
        print(f"  [连签] {sign_day_msg}")

        sleep(random.uniform(1, 3))

        # 分享加积分
        share_msg = do_add_integral_by_share(token, user_id, proxies, parsed_server or "")
        result["shareMsg"] = share_msg
        print(f"  [分享] {share_msg}")

        sleep(random.uniform(1, 3))

        # 领券
        coupon_msg = do_receive_coupons(token, proxies, parsed_server or "")
        result["couponMsg"] = coupon_msg
        print(f"  [领券] {coupon_msg}")

        sleep(random.uniform(1, 2))

        # 订阅
        sub_msg = do_subscription(token, proxies, parsed_server or "")
        result["subscribeMsg"] = sub_msg
        print(f"  [订阅] {sub_msg}")

        # 积分
        integral_text, _ = do_get_integral(token, user_id, proxies, parsed_server or "")
        result["integral"] = integral_text
        print(f"  [积分] 当前积分: {integral_text}")

        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        print(f"  [账号] 执行失败: {exc}")
        return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    lines = [f"💚 植白说官方商城任务结果", "—" * 30]
    lines.append(f"✅ {success_count}成功 / ❌ {fail_count}失败")
    lines.append(f"🕒 {now_text()}")
    lines.append("")

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"
        lines.append(f"{icon} 账号{idx} ({res.get('wxid', '-')})")
        lines.append(f"  签到: {res['signMsg']}")
        lines.append(f"  连签: {res['signDayMsg']}")
        lines.append(f"  分享: {res['shareMsg']}")
        lines.append(f"  领券: {res['couponMsg']}")
        lines.append(f"  订阅: {res['subscribeMsg']}")
        lines.append(f"  积分: {res['integral']}")
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
                "token": "-", "userId": "-",
                "signMsg": "-", "shareMsg": "-",
                "couponMsg": "-", "subscribeMsg": "-",
                "integral": "-", "signDayMsg": "-",
                "proxyStatus": "-", "proxyIp": "-",
            })

        if index < len(SERVERS):
            print("  [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    print()
    print("+" + "=" * 50 + "+")
    print("| 💚 植白说任务执行完成                              |")
    print(f"| ✅ 成功: {success_count:<39}|")
    print(f"| ❌ 失败: {fail_count:<39}|")
    print(f"| 🕒 结束时间: {now_text():<32}|")
    print("+" + "=" * 50 + "+")

    if notify:
        notify.send(APP_NAME, build_notify(results))


if __name__ == "__main__":
    main()
