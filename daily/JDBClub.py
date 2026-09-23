#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 加多宝Club
# cron: 1 10,22 * * *

"""
加多宝Club小程序（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code（3次：登录/授权/手机验证）
  2. jscode 换 token + apitoken
  3. 手机号验证 + 会员注册
  4. 每日签到
  5. 每日任务（分享小程序、浏览商城）
  6. 宝藏星期五抽奖
  7. 查询积分/阅历
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

APP_NAME = "加多宝Club小程序"
APPID = "wx8371875e443e177f"
CLIENT_CODE = "CLI2113448692"

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

# 功能开关
ENABLE_LOTTERY = True

PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

BASE_URL = "https://api-mp.jdbchina.com"

LOGIN_URL = f"{BASE_URL}/geement.authjextra/api/v1/loginsession/2weichatmicroprogram"
NANOPROGRAM_AUTH_URL = f"{BASE_URL}/geement.authjextra/api/v1/common/nanoprogramauth"
GET_PHONE_URL = f"{BASE_URL}/geement.authjextra/api/v1/loginsession/2weichatmicroprogram/getuserphonenumberwithcheckid"
REGISTER_MEMBER_URL = f"{BASE_URL}/geement.usercenter/api/v1/user/informationvbyfiled"
USER_INFO_URL = f"{BASE_URL}/geement.usercenter/api/v1/user/information"

SIGNIN_LIST_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin?status=30&pageNum=1&pageSize=1"
SIGNIN_USERINFO_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin/userinfo"
SIGNIN_DO_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin/signbyuser"
SIGNIN_USERLOGS_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin/userlogs"

TASK_JOIN_URL = f"{BASE_URL}/geement.marketingplay/api/v1/task/join"

ACT_DETAIL_URL = f"{BASE_URL}/geement.actjextra/api/v1/act"
ACT_PRIZES_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/prizes"
ACT_CHECK_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/check"
ACT_LOTTERY_COUNT_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/lottery/data/todaycount"
ACT_LOTTERY_DO_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/data/pu"

SENIORITY_URL = f"{BASE_URL}/geement.usercenter/api/v1/user/seniority"
POINT_URL = f"{BASE_URL}/thirty.jdb/api/member/point/expire"

# 任务/活动 ID 兜底值
SHARE_TASK_ID_FALLBACK = "2508121123571"
BROWSE_TASK_ID_FALLBACK = "2508121124311"
ACT_CODE_FALLBACK = "ACT2508121127551"
SEN_CODE_FALLBACK = "SEN2508111752581"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541923) XWEB/20089"
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


def to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def log_title() -> None:
    print()
    print("+" + "=" * 50 + "+")
    print("| 🥤 加多宝Club小程序（YYB Go版）                  |")
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


def get_phone_code_yyb(server_entry: str) -> str | None:
    """通过 YYB Go 的 getPhoneNumber 接口获取手机号验证 code"""
    parsed_server, ref = parse_yyb_go_entry(server_entry)
    if not parsed_server or not ref:
        return None
    url = f"http://{parsed_server}/wxapp/getPhoneNumber"
    print(f"  [授权] 请求YYB Go获取手机号验证code")
    try:
        resp = requests.post(
            url,
            json={"ref": ref, "app_id": APPID},
            timeout=20,
            proxies={"http": None, "https": None},
        )
        data = resp.json()
        # getPhoneNumber 返回的是 encryptedData + iv，不是直接的 code
        # 加多宝需要的是微信的 phone code（用于后端解密），不是 getCode 的 jscode
        # YYB Go 的 getPhoneNumber 返回格式: {code:0, data:{openid, result:{code, encryptedData, iv}}}
        result = (((data.get("data") or {}).get("result") or {}))
        phone_code = result.get("code")
        if data.get("code") == 0 and phone_code:
            print(f"  [授权] 手机号验证code获取成功")
            return phone_code
        else:
            print(f"  [授权] 手机号验证code获取失败: {str(data)[:200]}")
            return None
    except Exception as exc:
        print(f"  [授权] 手机号验证code获取异常: {exc}")
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

def common_headers(token: str | None = None, apitoken: str | None = None) -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": f"https://servicewechat.com/{APPID}/45/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["unique_identity"] = token
        headers["apitoken"] = apitoken or token
    return headers


def login_by_code(server: str, login_code: str, auth_code: str, proxies: Dict[str, str] | None) -> Tuple[str | None, str | None, Dict[str, Any] | None]:
    """使用两个 jscode 换 token 和 apitoken"""
    try:
        # Step 1: 登录换 token
        print("  [登录] 使用 jscode 换 token")
        response = request_with_proxy(
            "POST", LOGIN_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "*/*",
                "xweb_xhr": "1",
                "Referer": f"https://servicewechat.com/{APPID}/45/page-frame.html",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            data={"jscode": login_code, "app_id": APPID, "client_code": CLIENT_CODE},
            proxies=proxies, server=server,
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:800]}

        token = data.get("data", {}).get("token")
        if not token:
            print(f"  [登录] token 获取失败: {json_preview(data)}")
            return None, None, data

        print(f"  [登录] token 获取成功: {mask(token)}")

        # Step 2: 换 apitoken
        apitoken = None
        try:
            print("  [登录] 使用第二个 jscode 换 apitoken")
            auth_resp = request_with_proxy(
                "GET", NANOPROGRAM_AUTH_URL,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "*/*",
                    "xweb_xhr": "1",
                    "Referer": f"https://servicewechat.com/{APPID}/45/page-frame.html",
                },
                params={"app_id": APPID, "client_code": CLIENT_CODE, "jscode": auth_code},
                proxies=proxies, server=server,
            )
            auth_data = auth_resp.json()
            apitoken = auth_data.get("data")
            if apitoken:
                print(f"  [登录] apitoken 获取成功: {mask(apitoken)}")
            else:
                print(f"  [登录] apitoken 获取失败，使用 token 替代")
                apitoken = token
        except Exception as exc:
            print(f"  [登录] apitoken 获取异常: {exc}，使用 token 替代")
            apitoken = token

        return token, apitoken, data

    except Exception as exc:
        print(f"  [登录] 请求异常: {exc}")
        return None, None, None


def api_get(server: str, url: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> Dict[str, Any]:
    response = request_with_proxy("GET", url, headers=common_headers(token, apitoken), proxies=proxies, server=server)
    try:
        return response.json()
    except Exception:
        return {"success": False, "msg": f"JSON解析失败: {response.text[:300]}"}


def api_post(server: str, url: str, token: str, apitoken: str, proxies: Dict[str, str] | None, payload: Dict[str, Any] | None = None, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    headers = common_headers(token, apitoken)
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        headers["Content-Type"] = "application/json"
    response = request_with_proxy(
        "POST", url, headers=headers,
        json=payload if payload is not None else None,
        data=data if data is not None else None,
        proxies=proxies, server=server,
    )
    try:
        return response.json()
    except Exception:
        return {"success": False, "msg": f"JSON解析失败: {response.text[:300]}"}


def check_and_register_member(server: str, token: str, apitoken: str, phone_code: str, proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    """手机号验证 + 会员注册"""
    info_resp = api_get(server, USER_INFO_URL, token, apitoken, proxies)
    if not info_resp.get("success"):
        return False, f"查询用户信息失败: {info_resp.get('msg', '未知错误')}"

    user_data = info_resp.get("data", {})
    member_info = user_data.get("extra_memberinfo", {})
    member_status = member_info.get("member_status", 0)
    phone = user_data.get("phone", "")

    if member_status == 1:
        memberdto = member_info.get("memberdto") or {}
        member_id = memberdto.get("m_id", "")
        print(f"  [会员] 已注册为会员 (ID: {member_id})")
        return True, f"已注册为会员 (ID: {member_id})"

    print("  [会员] 尚未注册为会员，尝试手机验证+注册...")

    check_id = None
    phone_number = phone

    if phone_code:
        print("  [会员] 使用手机验证 code 获取手机号...")
        phone_resp = api_post(
            server, GET_PHONE_URL, token, apitoken, proxies,
            data={"code": phone_code, "app_id": APPID, "client_code": CLIENT_CODE},
        )
        if phone_resp.get("success"):
            phone_data = phone_resp.get("data", {})
            check_id = phone_data.get("check_id")
            phone_number = phone_data.get("phone_number", phone)
            print(f"  [会员] 手机号验证成功")
        else:
            print(f"  [会员] 手机号验证失败: {phone_resp.get('msg', '')[:80]}")
    else:
        print("  [会员] 未获取手机验证 code，跳过手机验证")

    if check_id and phone_number:
        print("  [会员] 尝试注册会员...")
        reg_payload = {
            "custom_fields": [{"id": "phone", "field_valuestr": phone_number}],
            "register_member": True,
            "register_member_phonenumbercheckdto": {"system_checkid": check_id},
            "member_sourceinfo": {
                "source_key01": "jdbmember001",
                "source_key02": "加多宝小程序虚拟门店",
                "source_key03": "",
                "source_key04": "",
            },
        }
        reg_resp = api_post(server, REGISTER_MEMBER_URL, token, apitoken, proxies, payload=reg_payload)
        if reg_resp.get("success"):
            reg_data = reg_resp.get("data", {})
            reg_result = reg_data.get("register_member_result") or {}
            new_member_id = reg_result.get("member_id", "")
            print(f"  [会员] 注册成功! 会员ID: {new_member_id}")
            return True, f"注册成功 (ID: {new_member_id})"
        else:
            print(f"  [会员] 注册失败: {reg_resp.get('msg', '')}")
    else:
        print("  [会员] 缺少 check_id，无法完成注册")

    return False, "未注册为会员（缺少手机号验证）"


def do_signin(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    """每日签到"""
    signin_list = api_get(server, SIGNIN_LIST_URL, token, apitoken, proxies)
    if not signin_list.get("success"):
        return f"获取签到活动失败: {signin_list.get('msg', '未知错误')}"

    signin_data = signin_list.get("data", [])
    if not signin_data:
        return "暂无进行中的签到活动"

    activity_id = signin_data[0].get("activitydto", {}).get("id")
    if not activity_id:
        return "签到失败: API 未返回活动 ID"
    print(f"  [签到] 活动 ID: {activity_id}")

    userinfo_url = f"{SIGNIN_USERINFO_URL}?task_id={activity_id}"
    userinfo = api_get(server, userinfo_url, token, apitoken, proxies)

    total_days = 0
    already_signed = False
    if userinfo.get("success"):
        ud = userinfo.get("data", {})
        total_days = ud.get("total_signindays", 0)
        continuity_days = ud.get("continuity_signindays", 0)
        latest_time = str(ud.get("latest_signin_time", ""))
        print(f"  [签到] 累计 {total_days} 天，连续 {continuity_days} 天")
        today_str = datetime.now().strftime("%Y-%m-%d")
        if latest_time.startswith(today_str):
            already_signed = True

    if already_signed:
        print("  [签到] 今日已完成签到")
        _show_signin_rewards(server, token, apitoken, proxies, activity_id)
        return f"今日已签到 (累计{total_days}天)"

    resp = api_post(server, SIGNIN_DO_URL, token, apitoken, proxies, data={"task_id": activity_id})
    if resp.get("success"):
        print("  [签到] 签到成功!")
        sleep(1)
        _show_signin_rewards(server, token, apitoken, proxies, activity_id)
        userinfo2 = api_get(server, f"{SIGNIN_USERINFO_URL}?task_id={activity_id}", token, apitoken, proxies)
        if userinfo2.get("success"):
            total_days = userinfo2["data"].get("total_signindays", total_days + 1)
        return f"签到成功 (累计{total_days}天)"
    else:
        msg = resp.get("msg") or ""
        if "已完成签到" in msg or "已经签到" in msg:
            _show_signin_rewards(server, token, apitoken, proxies, activity_id)
            return f"今日已签到 (累计{total_days}天)"
        print(f"  [签到] 签到失败: {msg}")
        return f"签到失败: {msg}"


def _show_signin_rewards(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None, activity_id: str) -> None:
    logs_url = f"{SIGNIN_USERLOGS_URL}?task_id={activity_id}&pageNum=1&pageSize=7"
    logs_resp = api_get(server, logs_url, token, apitoken, proxies)
    if not logs_resp.get("success"):
        return
    today_str = datetime.now().strftime("%Y-%m-%d")
    for log in logs_resp.get("data", []):
        signin_date = str(log.get("signin_date", ""))
        if not signin_date.startswith(today_str):
            continue
        rc_str = log.get("reward_content", "")
        if not rc_str:
            continue
        try:
            rewards = json.loads(rc_str)
        except Exception:
            continue
        for reward in rewards:
            for detail in reward.get("rule_reward_details", []):
                name = detail.get("relationship_name", "未知")
                count = detail.get("reward_count", 0)
                print(f"  [签到] 获得奖励: {name} × {count}")


def do_task(server: str, task_id: str, task_name: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    """完成每日任务"""
    join_url = f"{TASK_JOIN_URL}?task_id={task_id}"
    resp = api_get(server, join_url, token, apitoken, proxies)

    if resp.get("success") and resp.get("data") == "成功":
        print(f"  [任务] {task_name}完成")
        return f"{task_name}: 成功"
    elif "已参" in (resp.get("msg") or ""):
        print(f"  [任务] {task_name}今日已完成")
        return f"{task_name}: 今日已完成"
    else:
        msg = resp.get("data") or resp.get("msg") or "任务失败"
        print(f"  [任务] {task_name}: {msg}")
        return f"{task_name}: {msg}"


def do_lottery(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    """宝藏星期五抽奖"""
    if not ENABLE_LOTTERY:
        return "抽奖已关闭"

    # 活动详情
    detail_url = f"{ACT_DETAIL_URL}?act_code={ACT_CODE_FALLBACK}"
    detail_resp = api_get(server, detail_url, token, apitoken, proxies)
    act_name = ACT_CODE_FALLBACK
    if detail_resp.get("success") and detail_resp.get("data"):
        actdto = detail_resp["data"][0].get("actdto", {}) if detail_resp["data"] else {}
        act_name = actdto.get("activity_name", ACT_CODE_FALLBACK)
        print(f"  [抽奖] 活动: {act_name}")

    # 检查活动状态
    check_url = f"{ACT_CHECK_URL}?act_code={ACT_CODE_FALLBACK}"
    check_resp = api_get(server, check_url, token, apitoken, proxies)
    if not check_resp.get("success"):
        return f"抽奖活动检查失败: {check_resp.get('msg', '未知错误')}"

    check_data = check_resp.get("data", {})
    act_status = check_data.get("act_status_full", 0)
    if act_status != 1 and act_status != 2:
        return f"活动「{act_name}」未在进行中 (状态: {act_status})"

    # 今日可抽奖次数
    count_url = f"{ACT_LOTTERY_COUNT_URL}?act_code={ACT_CODE_FALLBACK}"
    count_resp = api_get(server, count_url, token, apitoken, proxies)
    today_count = 0
    if count_resp.get("success"):
        today_count = count_resp.get("data", 0)
        print(f"  [抽奖] 今日已抽奖 {today_count} 次")

    max_per_day = check_data.get("user_max_scan_count_perday", 1)
    remaining = max(0, max_per_day - today_count)
    if remaining <= 0:
        return f"「{act_name}」今日抽奖次数已用完 ({today_count}/{max_per_day})"

    print(f"  [抽奖] 今日可抽奖 {remaining} 次")
    prize_list: List[str] = []
    for draw_index in range(1, remaining + 1):
        wait_time = random.randint(2, 5)
        print(f"  [抽奖] 第 {draw_index} 次抽奖前等待 {wait_time}s")
        sleep(wait_time)

        resp = api_post(server, ACT_LOTTERY_DO_URL, token, apitoken, proxies, data={"act_code": ACT_CODE_FALLBACK})
        if not resp.get("success"):
            msg = resp.get("msg") or "抽奖失败"
            prize_list.append(f"第{draw_index}次失败: {msg}")
            continue

        prize_data = resp.get("data")
        if isinstance(prize_data, dict):
            prize_name = prize_data.get("prize_name") or prize_data.get("prizeName") or "未知奖品"
            prize_level = prize_data.get("prize_level") or prize_data.get("prizeLevel") or ""
            prize_list.append(f"{prize_level} {prize_name}" if prize_level else prize_name)
            print(f"  [抽奖] 第 {draw_index} 次获得: {prize_level} {prize_name}" if prize_level else f"  [抽奖] 第 {draw_index} 次获得: {prize_name}")
        elif prize_data is True:
            prize_list.append(f"「{act_name}」参与成功")
        else:
            prize_list.append(str(prize_data))

    return "、".join(prize_list) if prize_list else "无抽奖机会"


def query_point(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    resp = api_get(server, POINT_URL, token, apitoken, proxies)
    if resp.get("success"):
        point = resp.get("data", {}).get("point", 0)
        print(f"  [积分] 当前积分: {point}")
        return str(point)
    else:
        msg = resp.get("msg") or "查询失败"
        print(f"  [积分] {msg}")
        return msg


def query_seniority(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    url = f"{SENIORITY_URL}?sencodes={SEN_CODE_FALLBACK}"
    resp = api_get(server, url, token, apitoken, proxies)
    if resp.get("success"):
        data_list = resp.get("data", [])
        if data_list:
            total = data_list[0].get("total_count", 0)
            used = data_list[0].get("used_count", 0)
            print(f"  [阅历] 总计 {total}，已使用 {used}")
            return f"总{total}/用{used}"
        return "暂无阅历数据"
    else:
        msg = resp.get("msg") or "查询失败"
        print(f"  [阅历] {msg}")
        return msg


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
        "memberMsg": "-",
        "signMsg": "-",
        "taskShareMsg": "-",
        "taskBrowseMsg": "-",
        "lotteryMsg": "-",
        "point": "-",
        "seniority": "-",
        "error": "",
    }

    log_account_header(index, total, parsed_server or server_entry)

    proxies, proxy_ip = get_valid_proxy(str(parsed_server))
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    delay = random.randint(2, 6)
    print(f"  [延迟] 启动延迟 {delay}s")
    sleep(delay)

    # 获取3个code：登录、授权、手机验证
    login_code = get_code(server_entry)
    if not login_code:
        result["error"] = "获取登录 code 失败"
        return result

    sleep(1)
    auth_code = get_code(server_entry)
    if not auth_code:
        result["error"] = "获取授权 code 失败"
        return result

    # 第3个code用 getPhoneNumber 接口
    sleep(1)
    phone_code = get_phone_code_yyb(server_entry)
    if phone_code:
        print("  [授权] 手机验证 code 获取成功")
    else:
        print("  [授权] 手机验证 code 获取失败，将跳过手机验证")

    # 登录
    token, apitoken, raw_login = login_by_code(parsed_server, login_code, auth_code, proxies)
    if not token:
        result["error"] = f"登录失败: {json_preview(raw_login)}"
        return result

    result["token"] = mask(token)

    try:
        # 会员注册
        member_ok, member_msg = check_and_register_member(parsed_server, token, apitoken, phone_code, proxies)
        result["memberMsg"] = member_msg

        sleep(random.randint(1, 3))

        # 签到
        result["signMsg"] = do_signin(parsed_server, token, apitoken, proxies)

        sleep(random.randint(1, 3))

        # 分享小程序任务
        result["taskShareMsg"] = do_task(parsed_server, SHARE_TASK_ID_FALLBACK, "分享小程序", token, apitoken, proxies)

        sleep(random.randint(1, 3))

        # 浏览商城任务
        result["taskBrowseMsg"] = do_task(parsed_server, BROWSE_TASK_ID_FALLBACK, "浏览商城", token, apitoken, proxies)

        sleep(random.randint(1, 3))

        # 抽奖
        result["lotteryMsg"] = do_lottery(parsed_server, token, apitoken, proxies)

        sleep(random.randint(1, 3))

        # 积分
        result["point"] = query_point(parsed_server, token, apitoken, proxies)

        # 阅历
        result["seniority"] = query_seniority(parsed_server, token, apitoken, proxies)

        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        print(f"  [账号] 执行失败: {exc}")
        return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    lines = [f"🥤 加多宝Club任务结果", "—" * 30]
    lines.append(f"✅ {success_count}成功 / ❌ {fail_count}失败")
    lines.append(f"🕒 {now_text()}")
    lines.append("")

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"
        lines.append(f"{icon} 账号{idx} ({res.get('wxid', '-')})")
        lines.append(f"  会员: {res['memberMsg']}")
        lines.append(f"  签到: {res['signMsg']}")
        lines.append(f"  分享: {res['taskShareMsg']}")
        lines.append(f"  浏览: {res['taskBrowseMsg']}")
        lines.append(f"  抽奖: {res['lotteryMsg']}")
        lines.append(f"  积分: {res['point']}")
        lines.append(f"  阅历: {res['seniority']}")
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
                "token": "-", "memberMsg": "-", "signMsg": "-",
                "taskShareMsg": "-", "taskBrowseMsg": "-",
                "lotteryMsg": "-", "point": "-", "seniority": "-",
                "proxyStatus": "-", "proxyIp": "-",
            })

        if index < len(SERVERS):
            print("  [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    print()
    print("+" + "=" * 50 + "+")
    print("| 🥤 加多宝Club任务执行完成                        |")
    print(f"| ✅ 成功: {success_count:<39}|")
    print(f"| ❌ 失败: {fail_count:<39}|")
    print(f"| 🕒 结束时间: {now_text():<32}|")
    print("+" + "=" * 50 + "+")

    if notify:
        notify.send(APP_NAME, build_notify(results))


if __name__ == "__main__":
    main()
