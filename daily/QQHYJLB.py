#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 洽洽会员俱乐部
# cron: 25 9,21 * * *

"""
洽洽会员俱乐部小程序（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code
  2. code 换 Authorization token 和 uid
  3. 每日签到
  4. 浏览页面任务（每日 2 次，每次间隔 10s）
  5. 领取待领取奖励
  6. 查询积分余额
  7. 青龙 notify 推送

环境变量：
  YYB_SERVER        YYB Go 服务地址，格式：server@wxid，多账号换行分隔
  PROXY_API         品赞代理提取 API，可选
  PROXY_TYPE        http / socks5，默认 http
  QQFOOD_TENANT_ID  租户 ID，默认 1
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

APP_NAME = "洽洽会员俱乐部小程序"
APPID = "wxc72491b6cd007333"

TENANT_ID = os.getenv("QQFOOD_TENANT_ID", "1")

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

BASE_URL = "https://vip.qiaqiafood.com"
LOGIN_URL = f"{BASE_URL}/upms/wechat/login/code"

SIGN_URL = f"{BASE_URL}/vip/member/sign"
LIST_INTEGRAL_TASK_URL = f"{BASE_URL}/vip/member/listIntegralTask"
TASK_FINISHED_URL = f"{BASE_URL}/vip/member/taskFinished"
GET_VIP_EXT_INFO_URL = f"{BASE_URL}/vip/member/getVipExtInfo"
AWARD_SEARCH_URL = f"{BASE_URL}/award/center/search"
AWARD_RECEIVE_URL = f"{BASE_URL}/award/center/receive"
LOTTERY_LIST_URL = f"{BASE_URL}/activity/lottery/list"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541a1d) XWEB/19899"
)

VISIT_PAGE_WAIT_SECONDS = 10
VISIT_PAGE_DAILY_LIMIT = 2


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
    print("| 🥜 洽洽会员俱乐部（YYB Go版）                    |")
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
        "Referer": f"https://servicewechat.com/{APPID}/520/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["Authorization"] = token
    return headers


def api_post(
    server: str, url: str, token: str, uid: str,
    proxies: Dict[str, str] | None, extra_body: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    body = {"uid": uid, "tenantId": TENANT_ID}
    if extra_body:
        body.update(extra_body)
    response = request_with_proxy(
        "POST", url, headers=common_headers(token), json=body,
        proxies=proxies, server=server,
    )
    try:
        return response.json()
    except Exception:
        return {"success": False, "status": "-1", "msg": f"JSON解析失败: {response.text[:300]}"}


def login_by_code(server: str, code: str, proxies: Dict[str, str] | None) -> Tuple[str | None, str | None, Dict[str, Any] | None]:
    try:
        print("  [登录] 使用 code 换 token")
        body = {
            "code": code,
            "tenantId": TENANT_ID,
            "appId": APPID,
            "componentAppId": APPID,
        }
        response = request_with_proxy(
            "POST", LOGIN_URL, headers=common_headers(), json=body,
            proxies=proxies, server=server,
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:800]}

        inner = data.get("data")
        if not isinstance(inner, dict):
            print(f"  [登录] 响应格式异常: {json_preview(data)}")
            return None, None, data

        token = inner.get("token")
        uid = inner.get("loginId") or (inner.get("account") or {}).get("userId")

        if token and uid:
            print(f"  [登录] token 获取成功: {mask(token)}")
            print(f"  [登录] uid 获取成功: {uid}")
            return token, uid, data

        print(f"  [登录] 未识别 token/uid: {json_preview(data)}")
        return None, None, data
    except Exception as exc:
        print(f"  [登录] 请求异常: {exc}")
        return None, None, None


def do_sign(server: str, token: str, uid: str, proxies: Dict[str, str] | None) -> str:
    resp = api_post(server, SIGN_URL, token, uid, proxies, {"channel": ""})
    if resp.get("success") is True or resp.get("status") == "0":
        inner = resp.get("data") or {}
        days = inner.get("continueDays", "?")
        value = inner.get("value", 0)
        msg = f"签到成功，连续 {days} 天，获得 {value} 积分"
        print(f"  [签到] {msg}")
        return msg
    msg = resp.get("msg") or resp.get("message") or "签到失败"
    print(f"  [签到] {msg}")
    return msg


def do_visit_page(server: str, token: str, uid: str, proxies: Dict[str, str] | None) -> str:
    task_resp = api_post(server, LIST_INTEGRAL_TASK_URL, token, uid, proxies)
    task_list = task_resp.get("data") or []

    visit_task = None
    for task in task_list:
        if task.get("taskType") == "VISIT_PAGE":
            visit_task = task
            break

    if not visit_task:
        print("  [浏览] 未找到浏览页面任务")
        return "未找到浏览任务"

    finished_count = int(visit_task.get("finishedCount", 0))
    limit_value = int(visit_task.get("limitValue", VISIT_PAGE_DAILY_LIMIT))
    remaining = limit_value - finished_count

    if remaining <= 0:
        msg = f"今日浏览任务已完成 ({finished_count}/{limit_value})"
        print(f"  [浏览] {msg}")
        return msg

    print(f"  [浏览] 今日 {finished_count}/{limit_value}，还需完成 {remaining} 次")

    results: List[str] = []
    for i in range(1, remaining + 1):
        wait_time = random.randint(VISIT_PAGE_WAIT_SECONDS, VISIT_PAGE_WAIT_SECONDS + 5)
        print(f"  [浏览] 第 {i} 次，模拟等待 {wait_time}s...")
        sleep(wait_time)

        finish_resp = api_post(
            server, TASK_FINISHED_URL, token, uid, proxies,
            {"pointTaskType": "VISIT_PAGE"},
        )

        if finish_resp.get("success") is True or finish_resp.get("status") == "0":
            results.append(f"第{i}次浏览成功，+2积分")
            print(f"  [浏览] 第 {i} 次完成，+2积分")
        else:
            msg = finish_resp.get("msg") or finish_resp.get("message") or "浏览失败"
            results.append(f"第{i}次失败: {msg}")
            print(f"  [浏览] 第 {i} 次: {msg}")

        if i < remaining:
            gap = random.randint(3, 6)
            sleep(gap)

    return "、".join(results)


def do_receive_awards(server: str, token: str, uid: str, proxies: Dict[str, str] | None) -> str:
    search_resp = api_post(
        server, AWARD_SEARCH_URL, token, uid, proxies,
        {"page": 1, "pageSize": 10, "awardType": "", "awardStatus": "UNRECEIVED"},
    )
    awards = search_resp.get("data") or []
    if not awards:
        print("  [奖励] 没有待领取的奖励")
        return "暂无待领取奖励"

    received: List[str] = []
    for award in awards:
        award_id = award.get("id")
        award_title = award.get("awardTitle", "未知奖励")
        if not award_id:
            continue
        recv_resp = api_post(
            server, AWARD_RECEIVE_URL, token, uid, proxies,
            {"id": str(award_id)},
        )
        if recv_resp.get("success") is True or recv_resp.get("status") == "0":
            received.append(award_title)
            print(f"  [奖励] 领取成功: {award_title}")
        else:
            msg = recv_resp.get("msg") or recv_resp.get("message") or "领取失败"
            print(f"  [奖励] {award_title}: {msg}")

    if received:
        return f"已领取: {'、'.join(received)}"
    return "领取失败"


def do_check_lottery(server: str, token: str, uid: str, proxies: Dict[str, str] | None) -> str:
    resp = api_post(
        server, LOTTERY_LIST_URL, token, uid, proxies,
        {"page": 1, "pageSize": 3, "activityStatus": "UNDERWAY", "showPointsActivity": "T"},
    )
    lotteries = resp.get("data") or []
    if not lotteries:
        print("  [抽奖] 当前无进行中的抽奖活动")
        return "暂无抽奖活动"
    count = len(lotteries)
    msg = f"当前有 {count} 个抽奖活动"
    print(f"  [抽奖] {msg}")
    return msg


def do_check_points(server: str, token: str, uid: str, proxies: Dict[str, str] | None) -> str:
    resp = api_post(server, GET_VIP_EXT_INFO_URL, token, uid, proxies)
    inner = resp.get("data")
    if not isinstance(inner, dict):
        print(f"  [积分] 查询失败: {json_preview(resp)}")
        return "查询失败"
    point = inner.get("point", 0)
    total = inner.get("totalPoint", 0)
    level = inner.get("vipLevel", "?")
    continuous = inner.get("continuousSignDays", 0)
    msg = f"当前积分 {point}，累计 {total}，等级 {level}，连续签到 {continuous} 天"
    print(f"  [积分] {msg}")
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
        "uid": "-",
        "signMsg": "-",
        "visitMsg": "-",
        "awardMsg": "-",
        "lotteryMsg": "-",
        "pointMsg": "-",
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

    token, uid, raw_login = login_by_code(parsed_server, code, proxies)
    if not token or not uid:
        result["error"] = f"登录失败: {json_preview(raw_login)}"
        return result

    result["token"] = mask(token)
    result["uid"] = uid

    try:
        result["signMsg"] = do_sign(parsed_server, token, uid, proxies)
        result["visitMsg"] = do_visit_page(parsed_server, token, uid, proxies)
        result["awardMsg"] = do_receive_awards(parsed_server, token, uid, proxies)
        result["lotteryMsg"] = do_check_lottery(parsed_server, token, uid, proxies)
        result["pointMsg"] = do_check_points(parsed_server, token, uid, proxies)
        result["success"] = True
        return result
    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        print(f"  [账号] 执行失败: {exc}")
        return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    lines = [f"🥜 洽洽会员俱乐部任务结果", "—" * 30]
    lines.append(f"✅ {success_count}成功 / ❌ {fail_count}失败")
    lines.append(f"🕒 {now_text()}")
    lines.append("")

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"
        lines.append(f"{icon} 账号{idx} ({res.get('wxid', '-')})")
        lines.append(f"  签到: {res['signMsg']}")
        lines.append(f"  浏览: {res['visitMsg']}")
        lines.append(f"  奖励: {res['awardMsg']}")
        lines.append(f"  抽奖: {res['lotteryMsg']}")
        lines.append(f"  积分: {res['pointMsg']}")
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
                "token": "-", "uid": "-",
                "signMsg": "-", "visitMsg": "-",
                "awardMsg": "-", "lotteryMsg": "-",
                "pointMsg": "-",
                "proxyStatus": "-", "proxyIp": "-",
            })

        if index < len(SERVERS):
            print("  [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    print()
    print("+" + "=" * 50 + "+")
    print("| 🥜 洽洽会员俱乐部任务执行完成                    |")
    print(f"| ✅ 成功: {success_count:<39}|")
    print(f"| ❌ 失败: {fail_count:<39}|")
    print(f"| 🕒 结束时间: {now_text():<32}|")
    print("+" + "=" * 50 + "+")

    if notify:
        notify.send(APP_NAME, build_notify(results))


if __name__ == "__main__":
    main()
