#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 大参林健康
# cron: 8 9,21 * * *

"""
大参林健康小程序人参游戏（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code
  2. /wechat/login 使用 code 换 mini_token
  3. 签到领水滴、浇水、浏览任务
  4. 积分商城签到、优惠券领取
  5. 青龙 notify 推送

环境变量：
  YYB_SERVER       YYB Go 服务地址，格式：server@wxid，多账号换行分隔
  STORE_NO         门店编号，默认 1017013258
  PROXY_API        品赞代理提取 API，可选
  PROXY_TYPE       http / socks5，默认 http
"""

import json
import os
import random
import time
import hashlib
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import requests

try:
    import notify
except ImportError:
    notify = None

APP_NAME = "大参林健康小程序人参游戏"
APPID = "wx16ed9a8bbb188228"
ACTIVITY_ID = "1654405290741305345"

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
print("-" * 50)

STORE_NO = os.getenv("STORE_NO", "1017013258")

PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()

PROXY_RETRY_TIMES = 5
PROXY_VALIDATE_URL = "http://www.baidu.com"
PROXY_FETCH_INTERVAL = 1
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 15

BASE_URL = "https://dcapi.dslbuy.com"
CRM_BASE = "https://crmweixin.dslbuy.com"
LOGIN_URL = f"{CRM_BASE}/member-center/entrance/registryByWeiXinCode"

INTEGRAL_SIGN_BASE = CRM_BASE
INTEGRAL_SIGN_SALT = "LYq76ucaPg2nsO7E"

USER_LEVEL_INFO_URL = f"{BASE_URL}/dc-biz-activity/applet/ginsengGameRecord/userLevelInfo"
USER_NEW_AWARD_GROUP_TASK_ID_URL = f"{BASE_URL}/dc-biz-activity/applet/ginsengDripRecord/userNewAwardGroupTaskId"
USER_NEW_DRIP_URL = f"{BASE_URL}/dc-biz-activity/applet/ginsengDripRecord/userNewDrip"
GET_DRIP_URL = f"{BASE_URL}/dc-biz-activity/applet/ginsengDripRecord/getDrip"
WATERING_URL = f"{BASE_URL}/dc-biz-activity/applet/ginsengDripRecord/watering"
USER_DRIP_WATER_URL = f"{BASE_URL}/dc-biz-activity/applet/ginsengDripRecord/userDripWater"
USER_TASKS_URL = f"{BASE_URL}/dc-biz-activity/applet/ginsengTask/userTasks"
GET_USER_SIGN_INFO_URL = f"{BASE_URL}/dc-biz-activity/applet/ginsengTask/getUserSignInfo"
ADD_TASK_RECORD_URL = f"{BASE_URL}/dc-biz-activity/applet/gameTask/addTaskRecord"

GET_COUPON_TOP_LIST_URL = f"{BASE_URL}/api-mini-site/mini/member/coupon/getCouponTopList"
GET_COUPON_URL = f"{CRM_BASE}/coupon/getCoupon.do"

DAILY_SIGN_TASK_ID = "1654433159972143106"

BROWSE_TASKS = [
    {
        "id": "1808427725927809027",
        "name": "浏览拼团活动",
        "url": "https://dcapi.dslbuy.com/api-mini-site/mini/content/activity/page",
        "params": {"pageNo": "1638012745377009704"},
    },
    {
        "id": "1808427725927809026",
        "name": "浏览全球购",
        "url": "https://dcapi.dslbuy.com/api-mini-site/mini/content/activity/page",
        "params": {"pageNo": "1816016892253638658"},
    },
    {
        "id": "1911677832062554113",
        "name": "浏览健康科普",
        "url": "https://dcapi.dslbuy.com/api-mini-site/mini/member/healthScore/checkHealthScoreOrg",
        "params": {"storeNo": "1017013258"},
    },
]

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
    print("╔" + "═" * 50 + "╗")
    print("║ 🌿 大参林健康小程序人参游戏（YYB Go版）         ║")
    print(f"║ 🕒 启动时间: {now_text():<32}║")
    print(f"║ 🔢 账号数量: {len(SERVERS):<34}║")
    print("╚" + "═" * 50 + "╝")


def log_account_header(index: int, total: int, server: str) -> None:
    print()
    print("┌" + "─" * 50 + "┐")
    print(f"│ 🧩 账号 {index} / {total:<37}│")
    print(f"│ 🌍 来源 {server:<40}│")
    print("└" + "─" * 50 + "┘")


# ============ YYB Server 交互 ============

def parse_yyb_go_entry(raw_value):
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


def get_code(server_entry: str) -> str | None:
    parsed_server, ref = parse_yyb_go_entry(server_entry)
    if not parsed_server or not ref:
        return None
    url = f"http://{parsed_server}/wxapp/getCode"
    print(f"[{parsed_server}] 请求YYB Go获取code：{url}")
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
            print(f"[{parsed_server}] 获取code成功")
            return code
        else:
            print(f"[{parsed_server}] 获取code失败: {str(data)[:200]}")
            return None
    except Exception as exc:
        print(f"[{parsed_server}] 获取code异常: {exc}")
        return None


# ============ 代理系统（可选） ============

_persistent_session = None

def get_persistent_session() -> requests.Session:
    global _persistent_session
    if _persistent_session is None:
        _persistent_session = requests.Session()
        _persistent_session.trust_env = False
    return _persistent_session

def reset_persistent_session():
    global _persistent_session
    _persistent_session = None

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
    print(f"🛠️ [代理] 生成 {scheme.upper()} 代理 {host}:{port}")
    return {"http": proxy_url, "https": proxy_url}


def validate_proxy(proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    if not proxies:
        return False, ""
    try:
        ip_services = [
            ("https://api.ipify.org?format=json", "json", "ip"),
            ("https://ipapi.co/json/", "json", "ip"),
            ("https://api.ip.sb/ip", "text", None),
        ]
        ip = "未知"
        for url, response_type, key in ip_services:
            try:
                response = requests.get(url, proxies=proxies, timeout=5)
                if response.status_code == 200:
                    if response_type == "json":
                        data = response.json()
                        ip = data.get(key, "未知")
                    elif response_type == "text":
                        ip = response.text.strip()
                    if ip and ip != "未知":
                        print(f"✅ [代理] 验证成功，出口 IP: {ip}")
                        return True, ip
            except Exception:
                continue
        print(f"⚠️ [代理] 所有IP查询服务均失败，出口 IP: {ip}")
        return True, ip
    except Exception as exc:
        print(f"⚠️ [代理] 验证失败: {exc}")
    return False, ""


def get_valid_proxy(account_name: str) -> Tuple[Dict[str, str] | None, str]:
    if not PROXY_API:
        return None, ""
    print(f"🌐 [代理] {account_name} 正在获取品赞代理...")
    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=8)
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
            sleep(0.5)
    print("⚠️ [代理] 获取失败，使用直连")
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
            print(f"⚠️ [代理] {server} 代理请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("🔁 [兜底] 切换直连重试")
    try:
        session = direct_session()
        return session.request(method, url, **kwargs)
    except Exception as exc:
        print(f"⚠️ [请求] {server} 直连请求失败: {exc}")
        raise


# ============ 业务接口 ============

def md5_sign(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest().lower()


def common_headers() -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Referer": f"https://servicewechat.com/{APPID}/993/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "dc-version": "release",
    }


def extract_mini_token(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    candidates = [
        data.get("token"), data.get("mini_token"),
        data.get("accessToken"), data.get("access_token"), data.get("jwt"),
    ]
    inner = data.get("data")
    if isinstance(inner, dict):
        candidates.extend([
            inner.get("token"), inner.get("mini_token"),
            inner.get("accessToken"), inner.get("access_token"), inner.get("jwt"),
        ])
    for item in candidates:
        if item and item != "null":
            return str(item)
    return None


def extract_mobile(data: Dict[str, Any]) -> str | None:
    if not isinstance(data, dict):
        return None
    candidates = [
        data.get("mobile"), data.get("phone"),
        data.get("phoneNumber"), data.get("user_phone"),
    ]
    inner = data.get("data")
    if isinstance(inner, dict):
        candidates.extend([
            inner.get("mobile"), inner.get("phone"),
            inner.get("phoneNumber"), inner.get("user_phone"),
            inner.get("userInfo", {}).get("mobile") if isinstance(inner.get("userInfo"), dict) else None,
        ])
    for item in candidates:
        if item and item != "null" and str(item).isdigit():
            return str(item)
    return None


def login_by_code(server: str, code: str, proxies: Dict[str, str] | None) -> Tuple[str | None, Dict[str, Any] | None]:
    try:
        print("🔐 [登录] 使用 code 换 mini_token")
        response = request_with_proxy(
            "POST", LOGIN_URL,
            headers=common_headers(),
            json={"mini_token": "", "storeNo": STORE_NO, "code": code},
            proxies=proxies, server=server,
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:800]}
        mini_token = extract_mini_token(data)
        if mini_token:
            print(f"✅ [登录] mini_token 获取成功: {mask(mini_token)}")
            return mini_token, data
        print(f"❌ [登录] 未识别 mini_token 字段: {json_preview(data)}")
        return None, data
    except Exception as exc:
        print(f"❌ [登录] 请求异常: {exc}")
        return None, None


def api_get(server: str, url: str, mini_token: str, proxies: Dict[str, str] | None) -> Dict[str, Any]:
    response = request_with_proxy("GET", url, headers=common_headers(), proxies=proxies, server=server)
    try:
        return response.json()
    except Exception:
        return {"resp_code": "-1", "resp_msg": f"JSON解析失败: {response.text[:300]}"}


def api_post(server: str, url: str, mini_token: str, proxies: Dict[str, str] | None, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = request_with_proxy("POST", url, headers=common_headers(), json=payload, proxies=proxies, server=server)
    try:
        return response.json()
    except Exception:
        return {"resp_code": "-1", "resp_msg": f"JSON解析失败: {response.text[:300]}"}


# ============ 积分商城签到 ============

def get_integral_sign_info(server: str, mini_token: str, proxies: Dict[str, str] | None) -> Tuple[bool, Any]:
    try:
        url = f"{INTEGRAL_SIGN_BASE}/integralmall/signTemp/getByUser.do"
        headers = common_headers()
        params = {"mini_token": mini_token, "type": 1}
        response = request_with_proxy("GET", url, headers=headers, params=params, proxies=proxies, server=server)
        if response and response.status_code == 200:
            try:
                data = response.json()
                if data.get("status") == 200:
                    result = data.get("data", {}).get("result", {})
                    return True, result
                else:
                    print(f"⚠️ [积分签到] 获取签到信息失败: status={data.get('status')}, message={data.get('message')}")
            except Exception as exc:
                print(f"⚠️ [积分签到] 解析响应失败: {exc}")
        return False, None
    except Exception as exc:
        print(f"⚠️ [积分签到] 获取签到信息异常: {exc}")
        return False, None


def check_integral_signed_today(sign_info: Any) -> bool:
    if not sign_info:
        return False
    user_sign = sign_info.get("userSign", {})
    sign_date = user_sign.get("signDate")
    if not sign_date:
        return False
    try:
        if str(sign_date).isdigit():
            date_obj = datetime.fromtimestamp(int(sign_date) / 1000)
        else:
            date_obj = datetime.strptime(sign_date, "%Y-%m-%d")
        return date_obj.date() == datetime.now().date()
    except Exception:
        return False


def update_integral_form_id(server: str, mini_token: str, proxies: Dict[str, str] | None) -> bool:
    try:
        url = f"{INTEGRAL_SIGN_BASE}/integralmall/userSign/updateFormId.do"
        headers = common_headers()
        data = {"remind": False}
        response = request_with_proxy("POST", url, headers=headers, json=data, proxies=proxies, server=server)
        return response is not None and response.status_code == 200
    except Exception:
        return False


def do_integral_sign(server: str, mini_token: str, mobile: str, proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    try:
        update_integral_form_id(server, mini_token, proxies)
        timestamp = int(time.time())
        sign = md5_sign(f"{mobile}{timestamp}{INTEGRAL_SIGN_SALT}")
        url = f"{INTEGRAL_SIGN_BASE}/integralmall/userSign/sign.do?mobile={mobile}&timestamp={timestamp}&sign={sign}&storeNo=1017013258&type=1&mini_token={mini_token}"
        headers = common_headers()
        headers.pop("Content-Type", None)
        response = request_with_proxy("GET", url, headers=headers, proxies=proxies, server=server)
        if response and response.status_code == 200:
            try:
                result = response.json()
                if result.get("status") == 200:
                    data = result.get("data", {})
                    integral = data.get("integral", "0")
                    succession_day = data.get("successionDay", 0)
                    if integral and integral != "0":
                        return True, f"签到成功，+{integral}积分"
                    elif succession_day > 0:
                        return True, f"签到成功，连续签到{succession_day}天"
                    else:
                        return True, "签到成功"
                else:
                    msg = result.get("message", result.get("resp_msg", ""))
                    if "今日已签到" in msg or "已签到" in msg or "重复签到" in msg or "已经签到" in msg:
                        return True, "今日已签到"
                    if result.get("status") == 403:
                        time.sleep(2)
                        success, sign_info = get_integral_sign_info(server, mini_token, proxies)
                        if success and sign_info:
                            user_sign = sign_info.get("userSign", {})
                            sign_date = user_sign.get("signDate")
                            if sign_date:
                                try:
                                    if str(sign_date).isdigit():
                                        date_obj = datetime.fromtimestamp(int(sign_date) / 1000)
                                    else:
                                        date_obj = datetime.strptime(str(sign_date), "%Y-%m-%d")
                                    if date_obj.date() == datetime.now().date():
                                        sign_day = user_sign.get("signDay", user_sign.get("successionDay", 0))
                                        return True, f"今日已签到，连续签到{sign_day}天"
                                except Exception:
                                    pass
                        return False, "签到失败（403错误，可能已签到或受限）"
                    return False, msg
            except Exception as exc:
                return False, f"签到响应解析异常: {exc}"
        return False, "签到请求失败"
    except Exception as exc:
        return False, f"签到异常: {exc}"


def process_integral_sign(server: str, mini_token: str, user_info: Dict[str, Any], proxies: Dict[str, str] | None) -> Dict[str, Any]:
    result = {"success": False, "message": "", "integral": 0}
    try:
        mobile = user_info.get("phone") or user_info.get("mobile", "")
        if not mobile:
            result["message"] = "未获取到手机号，无法签到"
            return result
        success, sign_info = get_integral_sign_info(server, mini_token, proxies)
        if not success:
            result["message"] = "获取签到信息失败"
            return result
        if check_integral_signed_today(sign_info):
            user_sign = sign_info.get("userSign", {})
            sign_day = user_sign.get("signDay", user_sign.get("successionDay", 0))
            result["success"] = True
            result["message"] = f"今日已签到，连续签到{sign_day}天"
            return result
        sign_success, sign_msg = do_integral_sign(server, mini_token, mobile, proxies)
        result["success"] = sign_success
        result["message"] = sign_msg
        if sign_success:
            time.sleep(1)
            _, updated_sign_info = get_integral_sign_info(server, mini_token, proxies)
            if updated_sign_info:
                user_sign = updated_sign_info.get("userSign", {})
                sign_day = user_sign.get("signDay", user_sign.get("successionDay", 0))
                if "已签到" not in sign_msg:
                    result["message"] += f"，连续签到{sign_day}天"
    except Exception as exc:
        result["message"] = f"签到处理异常: {exc}"
    return result


# ============ 优惠券领取 ============

def claim_coupons(server: str, mini_token: str, proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    try:
        print("🎁 [优惠券] 开始领取优惠券...")
        coupon_list_url = f"{GET_COUPON_TOP_LIST_URL}?longStoreNo=1017013258&type=1&mini_token={mini_token}"
        coupon_list_resp = request_with_proxy("GET", coupon_list_url, headers=common_headers(), proxies=proxies, server=server)
        if not coupon_list_resp or coupon_list_resp.status_code != 200:
            return False, "获取优惠券列表失败"
        coupon_list_data = coupon_list_resp.json()
        if coupon_list_data.get("resp_code") != "0000":
            return False, f"获取优惠券列表失败: {coupon_list_data.get('resp_msg')}"
        coupons = coupon_list_data.get("datas", {}).get("list", [])
        if not coupons:
            return True, "暂无可用优惠券"
        unclaimed = [c for c in coupons if c.get("couponStatus") == "未领取" or c.get("userOwn") == 0]
        if not unclaimed:
            return True, "所有优惠券已领取"
        claimed_count = 0
        failed_count = 0
        for i, coupon in enumerate(unclaimed, 1):
            rule_code = coupon["ruleCode"]
            rule_name = coupon["ruleName"]
            claim_url = f"{GET_COUPON_URL}?ruleCode={rule_code}&relationId=null&storeNo=1017013258&addActivityReward=true&type=1&mini_token={mini_token}"
            headers = common_headers()
            headers.pop("Content-Type", None)
            claim_resp = request_with_proxy("GET", claim_url, headers=headers, proxies=proxies, server=server)
            if claim_resp and claim_resp.status_code == 200:
                claim_data = claim_resp.json()
                if claim_data.get("status") == 200:
                    claimed_count += 1
                else:
                    failed_count += 1
            else:
                failed_count += 1
            if i < len(unclaimed):
                sleep(1)
        result_msg = f"领取成功 {claimed_count} 个优惠券"
        if failed_count > 0:
            result_msg += f"，失败 {failed_count} 个"
        return True, result_msg
    except Exception as exc:
        return False, f"领取优惠券异常: {exc}"


# ============ 账号执行 ============

def run_account(index: int, total: int, server_entry: str) -> Dict[str, Any]:
    parsed_server, wxid = parse_yyb_go_entry(server_entry)
    result = {
        "server": parsed_server or server_entry,
        "wxid": mask(wxid),
        "success": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "miniToken": "-",
        "levelInfo": "-",
        "finalLevelInfo": "-",
        "signDripMsg": "-",
        "wateringMsg": "-",
        "browseTasksMsg": "-",
        "integralSignMsg": "-",
        "couponClaimMsg": "-",
        "dripNum": 0,
        "finalDripNum": 0,
        "dripDetails": [],
        "error": "",
    }

    log_account_header(index, total, parsed_server or server_entry)

    proxies, proxy_ip = get_valid_proxy(str(parsed_server))
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    if proxies:
        sleep(0.5)
    else:
        sleep(1)

    delay = random.randint(1, 3)
    print(f"⏳ [延迟] 启动延迟 {delay}s")
    sleep(delay)

    code = get_code(server_entry)
    if not code:
        result["error"] = "获取 code 失败"
        return result

    mini_token, raw_login = login_by_code(parsed_server, code, proxies)
    if not mini_token:
        result["error"] = f"登录失败: {json_preview(raw_login)}"
        return result

    result["miniToken"] = mask(mini_token)

    mobile = extract_mobile(raw_login) or ""
    if mobile:
        print(f"📱 [用户] 手机号: {mask(mobile)}")
    else:
        print(f"⚠️ [用户] 未获取到手机号")

    try:
        # 等级信息
        level_info_resp = api_get(
            parsed_server,
            f"{USER_LEVEL_INFO_URL}?mini_token={mini_token}&activityId={ACTIVITY_ID}",
            mini_token, proxies,
        )
        if level_info_resp.get("resp_code") == "0000":
            datas = level_info_resp.get("datas", {})
            level = datas.get("level", 0)
            level_name = datas.get("levelName", "未知")
            drip_total = to_int(datas.get("dripTotal"))
            watering_times = to_int(datas.get("wateringTimes"))
            tips = datas.get("tips", "")
            result["dripNum"] = drip_total
            result["levelInfo"] = f"等级{level}({level_name}) 水滴{drip_total} 浇水{watering_times}次"
            print(f"✅ [等级] {result['levelInfo']}")
            print(f"💡 [提示] {tips}")
        else:
            result["levelInfo"] = level_info_resp.get("resp_msg") or "获取等级信息失败"
            print(f"⚠️ [等级] {result['levelInfo']}")

        sleep(2)

        # 积分商城签到
        print("🎁 [积分] 开始积分商城签到...")
        user_info = {"phone": mobile, "mobile": mobile}
        integral_sign_result = process_integral_sign(parsed_server, mini_token, user_info, proxies)
        if integral_sign_result["success"]:
            print(f"✅ [积分] {integral_sign_result['message']}")
        else:
            print(f"⚠️ [积分] {integral_sign_result['message']}")
        result["integralSignMsg"] = integral_sign_result["message"]

        sleep(2)

        # 优惠券领取
        print("🎁 [优惠券] 开始领取优惠券...")
        coupon_claim_result = claim_coupons(parsed_server, mini_token, proxies)
        if coupon_claim_result[0]:
            print(f"✅ [优惠券] {coupon_claim_result[1]}")
        else:
            print(f"⚠️ [优惠券] {coupon_claim_result[1]}")
        result["couponClaimMsg"] = coupon_claim_result[1]

        sleep(2)

        # 签到任务
        print("🔍 [签到] 获取任务列表...")
        user_tasks_resp = api_get(
            parsed_server,
            f"{USER_TASKS_URL}?mini_token={mini_token}&activityId={ACTIVITY_ID}",
            mini_token, proxies,
        )

        current_sign_task_id = DAILY_SIGN_TASK_ID
        if user_tasks_resp.get("resp_code") == "0000":
            tasks = user_tasks_resp.get("datas", {}).get("userTaskInfos", [])
            if tasks:
                for task in tasks:
                    task_name = task.get("showTaskName", "")
                    task_type = task.get("taskType", "")
                    task_id = task.get("taskId", "")
                    if task_type == 6 or "签到" in task_name:
                        current_sign_task_id = task_id
                        print(f"🎯 [签到] 找到签到任务: {task_name} (ID: {task_id})")
                        break

        # 检查今日签到状态
        drip_water_resp = api_get(
            parsed_server,
            f"{USER_DRIP_WATER_URL}?mini_token={mini_token}&activityId={ACTIVITY_ID}&pageNo=1&pageSize=20",
            mini_token, proxies,
        )

        has_today_sign_record = False
        if drip_water_resp.get("resp_code") == "0000":
            results_list = drip_water_resp.get("datas", {}).get("results", [])
            today_str = datetime.now().strftime("%Y-%m-%d")
            for record in results_list:
                if today_str in record.get("recordTime", "") and "签到" in record.get("waterName", ""):
                    has_today_sign_record = True
                    print(f"✅ [签到] 今日已签到")
                    break

        if not has_today_sign_record:
            print("🎯 [签到] 开始执行每日签到...")
            sign_success = False
            sign_msg = "签到失败"
            for attempt in range(1, 4):
                try:
                    sign_task_resp = api_post(
                        parsed_server,
                        f"{ADD_TASK_RECORD_URL}?mini_token={mini_token}",
                        mini_token, proxies,
                        {"activityId": ACTIVITY_ID, "taskId": current_sign_task_id, "storeNo": STORE_NO, "mini_token": mini_token},
                    )
                    if sign_task_resp and sign_task_resp.get("resp_code") == "0000":
                        datas = sign_task_resp.get("datas")
                        if datas and isinstance(datas, dict):
                            award_num = datas.get("awardNum", 0)
                            if award_num > 0:
                                result["signDripMsg"] = f"签到成功，+{award_num}水滴"
                                sign_success = True
                                sign_msg = result["signDripMsg"]
                                print(f"✅ [签到] 第 {attempt} 次签到成功，奖励 {award_num} 水滴")
                                break
                        # datas为null或award为0，检查水滴明细确认
                        sleep(2)
                        check_resp = api_get(
                            parsed_server,
                            f"{USER_DRIP_WATER_URL}?mini_token={mini_token}&activityId={ACTIVITY_ID}&pageNo=1&pageSize=20",
                            mini_token, proxies,
                        )
                        if check_resp.get("resp_code") == "0000":
                            for record in check_resp.get("datas", {}).get("results", []):
                                if today_str in record.get("recordTime", "") and "签到" in record.get("waterName", ""):
                                    drip_num = record.get("dripNum", 0)
                                    result["signDripMsg"] = f"签到成功，+{drip_num}水滴"
                                    sign_success = True
                                    sign_msg = result["signDripMsg"]
                                    print(f"✅ [签到] 水滴明细确认签到成功")
                                    break
                        if sign_success:
                            break
                    else:
                        error_msg = sign_task_resp.get('resp_msg') if sign_task_resp else "响应为空"
                        print(f"⚠️ [签到] 第 {attempt} 次签到失败：{error_msg}")
                except Exception as exc:
                    print(f"❌ [签到] 第 {attempt} 次签到异常: {exc}")
                if attempt < 3:
                    sleep(3)
            if not sign_success:
                result["signDripMsg"] = sign_msg
        else:
            result["signDripMsg"] = "今日已签到"

        sleep(2)

        # 水滴收集
        print("🎯 [水滴] 开始执行水滴收集...")
        total_collected_drip = 0
        for loop_num in range(1, 3):
            new_drip_resp = api_get(
                parsed_server,
                f"{USER_NEW_DRIP_URL}?mini_token={mini_token}&activityId={ACTIVITY_ID}",
                mini_token, proxies,
            )
            if new_drip_resp.get("resp_code") == "0000":
                new_drip_list = new_drip_resp.get("datas", [])
                if new_drip_list:
                    loop_total_drip = sum(to_int(item.get("dripNum", 0)) for item in new_drip_list)
                    all_drip_record_ids = []
                    for drip_item in new_drip_list:
                        drip_record_ids = drip_item.get("dripRecordIds", [])
                        all_drip_record_ids.extend(drip_record_ids)
                    if all_drip_record_ids:
                        get_drip_resp = api_post(
                            parsed_server,
                            f"{GET_DRIP_URL}?mini_token={mini_token}",
                            mini_token, proxies,
                            {"dripRecordIds": all_drip_record_ids, "mini_token": mini_token},
                        )
                        if get_drip_resp.get("resp_code") == "0000":
                            total_collected_drip += loop_total_drip
                            print(f"✅ [水滴] 第 {loop_num} 次成功领取 {loop_total_drip} 水滴")
            if loop_num < 2:
                sleep(3)

        if total_collected_drip > 0:
            result["signDripMsg"] += f"，领取{total_collected_drip}水滴"

        sleep(2)

        # 浇水
        print("🔍 [浇水] 检查当前水滴数量...")
        current_level_info_resp = api_get(
            parsed_server,
            f"{USER_LEVEL_INFO_URL}?mini_token={mini_token}&activityId={ACTIVITY_ID}",
            mini_token, proxies,
        )
        current_drip_total = 0
        if current_level_info_resp.get("resp_code") == "0000":
            current_drip_total = to_int(current_level_info_resp.get("datas", {}).get("dripTotal"))
            print(f"💧 [浇水] 当前水滴数量: {current_drip_total}")

        watering_count = 0
        upgrade_happened = False
        while current_drip_total >= 20:
            watering_count += 1
            watering_resp = api_post(
                parsed_server,
                f"{WATERING_URL}?mini_token={mini_token}",
                mini_token, proxies,
                {"activityId": ACTIVITY_ID, "dripNum": 20, "storeNo": STORE_NO, "mini_token": mini_token},
            )
            if watering_resp.get("resp_code") == "0000":
                datas = watering_resp.get("datas", {})
                upgrade = datas.get("upgrade", False)
                if upgrade:
                    upgrade_happened = True
                    print(f"🎉 [浇水] 第 {watering_count} 次浇水成功，人参升级")
                else:
                    print(f"✅ [浇水] 第 {watering_count} 次浇水成功")
                current_drip_total -= 20
                if current_drip_total >= 20:
                    sleep(2)
            else:
                print(f"⚠️ [浇水] 第 {watering_count} 次浇水失败：{watering_resp.get('resp_msg')}")
                break

        if watering_count > 0:
            result["wateringMsg"] = f"浇水{watering_count}次" + ("，人参升级" if upgrade_happened else "成功")
        else:
            result["wateringMsg"] = f"水滴不足20，当前{current_drip_total}，跳过浇水"
            print(f"⏭️ [浇水] {result['wateringMsg']}")

        sleep(2)

        # 浏览任务
        user_tasks_resp = api_get(
            parsed_server,
            f"{USER_TASKS_URL}?activityId={ACTIVITY_ID}&storeNo={STORE_NO}&type=1&mini_token={mini_token}",
            mini_token, proxies,
        )
        browse_task_results = []
        if user_tasks_resp.get("resp_code") == "0000":
            user_task_infos = user_tasks_resp.get("datas", {}).get("userTaskInfos", [])
            for task in BROWSE_TASKS:
                for task_info in user_task_infos:
                    if task_info.get("taskId") == task["id"]:
                        complete_num = to_int(task_info.get("completeNum", 0))
                        time_drip_num = to_int(task_info.get("timeDripNum", 0))
                        show_task_name = task_info.get("showTaskName", task["name"])
                        if complete_num < time_drip_num:
                            try:
                                params = task["params"].copy()
                                params["mini_token"] = mini_token
                                url = f"{task['url']}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
                                request_with_proxy("GET", url, headers=common_headers(), proxies=proxies, server=parsed_server)
                                sleep(2)
                                add_task_resp = api_post(
                                    parsed_server,
                                    f"{ADD_TASK_RECORD_URL}?mini_token={mini_token}",
                                    mini_token, proxies,
                                    {"activityId": ACTIVITY_ID, "taskId": task["id"], "storeNo": STORE_NO, "mini_token": mini_token},
                                )
                                if add_task_resp.get("resp_code") == "0000":
                                    print(f"✅ [浏览] {show_task_name} 任务添加成功")
                                sleep(3)
                                browse_task_results.append(show_task_name)
                            except Exception as exc:
                                print(f"⚠️ [浏览] {show_task_name} 失败: {exc}")
                        else:
                            print(f"✅ [浏览] {show_task_name} 今日已完成")
                        break
            if browse_task_results:
                result["browseTasksMsg"] = f"完成浏览: {', '.join(browse_task_results)}"
            else:
                result["browseTasksMsg"] = "所有浏览任务已完成"
        else:
            result["browseTasksMsg"] = "获取任务列表失败"

        # 浏览任务后收集水滴
        if browse_task_results:
            sleep(5)
            for loop_num in range(1, 3):
                new_drip_after = api_get(
                    parsed_server,
                    f"{USER_NEW_DRIP_URL}?mini_token={mini_token}&activityId={ACTIVITY_ID}",
                    mini_token, proxies,
                )
                if new_drip_after.get("resp_code") == "0000":
                    new_drip_list_after = new_drip_after.get("datas", [])
                    if new_drip_list_after:
                        all_ids = []
                        for item in new_drip_list_after:
                            all_ids.extend(item.get("dripRecordIds", []))
                        if all_ids:
                            api_post(
                                parsed_server,
                                f"{GET_DRIP_URL}?mini_token={mini_token}",
                                mini_token, proxies,
                                {"dripRecordIds": all_ids, "mini_token": mini_token},
                            )
                if loop_num < 2:
                    sleep(3)

        sleep(2)

        # 最终等级信息
        final_level_info_resp = api_get(
            parsed_server,
            f"{USER_LEVEL_INFO_URL}?mini_token={mini_token}&activityId={ACTIVITY_ID}",
            mini_token, proxies,
        )
        if final_level_info_resp.get("resp_code") == "0000":
            datas = final_level_info_resp.get("datas", {})
            level = datas.get("level", 0)
            level_name = datas.get("levelName", "未知")
            drip_total = to_int(datas.get("dripTotal"))
            watering_times = to_int(datas.get("wateringTimes"))
            result["finalDripNum"] = drip_total
            result["finalLevelInfo"] = f"等级{level}({level_name}) 水滴{drip_total} 浇水{watering_times}次"
            drip_change = drip_total - result["dripNum"]
            if drip_change > 0:
                print(f"✅ [最终] {result['finalLevelInfo']} (水滴+{drip_change})")
            else:
                print(f"✅ [最终] {result['finalLevelInfo']}")
        else:
            result["finalLevelInfo"] = "获取最终等级信息失败"

        # 水滴明细
        drip_water_resp = api_get(
            parsed_server,
            f"{USER_DRIP_WATER_URL}?mini_token={mini_token}&activityId={ACTIVITY_ID}&pageNo=1&pageSize=10",
            mini_token, proxies,
        )
        if drip_water_resp.get("resp_code") == "0000":
            results_list = drip_water_resp.get("datas", {}).get("results", [])
            if results_list:
                result["dripDetails"] = []
                print(f"📋 [明细] 最近{len(results_list)}条水滴记录：")
                for item in results_list[:5]:
                    result["dripDetails"].append({
                        "name": item.get("waterName", "未知"),
                        "time": item.get("recordTime", ""),
                        "num": item.get("dripNum", 0),
                    })

        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        print(f"❌ [账号] 执行失败: {exc}")
        return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count
    total_drip = sum(item.get("finalDripNum", 0) for item in results)

    lines = [f"🌿 大参林健康任务结果", "━" * 30]
    lines.append(f"✅ {success_count}成功 / ❌ {fail_count}失败 / 💧 总水滴{total_drip}")
    lines.append("")

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"
        lines.append(f"{icon} 账号{idx} ({res.get('wxid', '-')})")
        lines.append(f"  初始: {res['levelInfo']}")
        lines.append(f"  最终: {res['finalLevelInfo']}")
        lines.append(f"  积分签到: {res.get('integralSignMsg', '-')}")
        lines.append(f"  优惠券: {res.get('couponClaimMsg', '-')}")
        lines.append(f"  水滴签到: {res['signDripMsg']}")
        lines.append(f"  浏览: {res.get('browseTasksMsg', '-')}")
        lines.append(f"  浇水: {res['wateringMsg']}")
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
            print(f"❌ [主程序] 执行异常: {exc}")
            _, wxid = parse_yyb_go_entry(server_entry)
            results.append({
                "server": server_entry, "wxid": mask(wxid),
                "success": False, "error": traceback.format_exc().strip(),
                "levelInfo": "-", "finalLevelInfo": "-",
                "signDripMsg": "-", "wateringMsg": "-", "browseTasksMsg": "-",
                "integralSignMsg": "-", "couponClaimMsg": "-",
                "dripNum": 0, "finalDripNum": 0, "dripDetails": [],
                "proxyStatus": "-", "proxyIp": "-", "miniToken": "-",
            })

        if index < len(SERVERS):
            print("⏳ [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count
    total_drip = sum(item.get("finalDripNum", 0) for item in results)

    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🏁 大参林健康任务执行完成                      ║")
    print(f"║ ✅ 成功: {success_count:<39}║")
    print(f"║ ❌ 失败: {fail_count:<39}║")
    print(f"║ 💧 总水滴: {total_drip:<38}║")
    print(f"║ 🕒 结束时间: {now_text():<32}║")
    print("╚" + "═" * 50 + "╝")

    # 青龙通知
    if notify:
        notify.send(APP_NAME, build_notify(results))


if __name__ == "__main__":
    main()
