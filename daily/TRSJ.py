#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 甜润世界
# cron: 5 9,12,20 * * *
"""
Author: anonymous
Date: 2026.08.08
Description: 甜润世界小程序签到
Cron: 5 9,12,20 * * *
------------------------------------------
甜润世界小程序签到 v1.1.0

功能：自动执行甜润世界小程序签到、种植石斛，支持多账号执行。

配置说明：
1. 微信 code 服务（YYB Go 取码服务，格式同铛铛一下.py）：
   YYB_SERVER                YYB Go 服务地址，格式：地址@微信账号标识，多账号换行分隔
   - 请求：POST http://{server}/wxapp/getCode  body: {"ref":"<账号标识>","app_id":"wx210e40a77dbe7a27"}
   - 响应：{"code":0,"data":{"result":{"code":"<微信login code>"}}}

2. 品赞代理（可选，业务请求优先走代理，失败直连兜底）：
   PROXY_API                                          品赞代理提取 API
   PROXY_TYPE                                         http / socks5，默认 http（socks5 需 pip install requests[socks]）

3. PushPlus 推送（可选）：
   PLUSPLUS_TOKEN                                     PushPlus token，不填则不推送
------------------------------------------
"""
import os
import re
import sys
import time
import json
import random
import requests
from datetime import datetime
import urllib3

# Windows 控制台默认 GBK 无法编码 emoji/特殊字符，强制 stdout/stderr 为 UTF-8
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import unquote, urlparse, parse_qs, quote as url_encode

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

APPID = "wx210e40a77dbe7a27"
BASE = "https://m.ahzyssl.com"
UA = "Mozilla/5.0 (Linux; Android 14; PJE110) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36 MiniProgramEnv/android"
LOGIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541c1a) XWEB/25297 miniProgram/wx210e40a77dbe7a27"

BASE_HEADERS = {
    "Host": "m.ahzyssl.com",
    "Connection": "keep-alive",
    "charset": "utf-8",
    "User-Agent": UA,
    "Referer": f"https://servicewechat.com/{APPID}/page-frame.html",
}

# ========== YYB Go 取码服务配置（格式同铛铛一下.py）==========
_YYB_SERVER_RAW = os.getenv("YYB_SERVER", "").strip()
CODE_SERVERS = [line.strip() for line in _YYB_SERVER_RAW.splitlines() if line.strip()]

# ========== 品赞代理 + PushPlus 配置（参考铛铛一下.py）==========
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()

PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

if not CODE_SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识，多账号换行分隔）")
    exit(1)
print(f"✅ 读取到 {len(CODE_SERVERS)} 个 code 服务（账号）")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def direct_session() -> requests.Session:
    """创建不走系统代理的会话（用于获取代理 IP 与本地 code 服务请求）。"""
    session = requests.Session()
    session.trust_env = False
    session.verify = False
    return session


def parse_proxy_response(text: Any) -> Optional[Dict[str, Any]]:
    """解析品赞代理 API 返回的 JSON，兼容多种响应格式（参考铛铛一下.py）。"""
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

    # 纯文本格式 host:port[:user[:pass]]
    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            try:
                return {
                    "host": parts[0],
                    "port": int(parts[1]),
                    "username": parts[2] if len(parts) > 2 else "",
                    "password": parts[3] if len(parts) > 3 else "",
                }
            except (ValueError, IndexError):
                pass

    return None


def build_proxy_dict(proxy_info: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """将代理信息转为 requests 可用的 proxies 字典（参考铛铛一下.py）。"""
    if not proxy_info:
        return None

    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info.get("username", "")
    password = proxy_info.get("password", "")

    auth = ""
    if username and password:
        auth = f"{url_encode(username)}:{url_encode(password)}@"

    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"

    print(f"🛠️ [代理] 生成 {scheme.upper()} 代理 {host}:{port}")

    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def validate_proxy(proxies: Optional[Dict[str, str]]) -> Tuple[bool, str]:
    """验证代理是否可用，返回 (是否可用, 出口IP)（参考铛铛一下.py）。"""
    if not proxies:
        return False, ""

    try:
        response = direct_session().get(PROXY_VALIDATE_URL, proxies=proxies, timeout=15)
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


def get_valid_proxy(account_name: str) -> Tuple[Optional[Dict[str, str]], str]:
    """获取品赞代理，验证失败或未配置时返回直连（参考铛铛一下.py）。"""
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
            time.sleep(2)

    print("⚠️ [代理] 获取失败，使用直连")
    return None, ""


def request_with_proxy(
    method: str,
    url: str,
    *,
    proxies: Optional[Dict[str, str]] = None,
    server: str = "",
    **kwargs,
) -> requests.Response:
    """业务请求优先走代理，代理失败自动直连兜底（参考铛铛一下.py）。"""
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

    return direct_session().request(method, url, **kwargs)


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


def get_code(entry: str) -> Optional[str]:
    """通过 YYB Go 取码服务获取微信小程序 login code。

    请求: POST http://{server}/wxapp/getCode  body: {"ref":"<ref>","app_id":"<APPID>"}
    返回: {"code":0,"data":{"result":{"code":"<微信login code>"}}}
    """
    server, ref = parse_yyb_entry(entry)
    if not server or not ref:
        return None

    url = f"http://{server}/wxapp/getCode"
    print(f"🔐 [授权] 请求 YYB Go 取码: {url}")

    try:
        response = direct_session().post(
            url, json={"ref": ref, "app_id": APPID}, timeout=20
        )
        data = response.json()
    except Exception as exc:
        print(f"❌ [授权] {entry} 获取 code 异常: {exc}")
        return None

    if data.get("code") != 0:
        print(f"❌ [授权] {entry} 取码失败: {json.dumps(data, ensure_ascii=False)[:400]}")
        return None

    code = ((data.get("data") or {}).get("result") or {}).get("code")
    if not code:
        print(f"❌ [授权] {entry} 返回无 code: {json.dumps(data, ensure_ascii=False)[:400]}")
        return None

    print(f"✅ [授权] {entry} 取码成功: {str(code)[:10]}... (len={len(str(code))})")
    return str(code)


def send_pushplus(title: str, content: str) -> None:
    """PushPlus 推送（参考铛铛一下.py，未配置 PLUSPLUS_TOKEN 则跳过）。"""
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


def code_login(server: str, proxies: Optional[Dict[str, str]] = None) -> Optional[str]:
    """小程序直登：code → applet_auth_token（data 字段即 ck）"""
    code = get_code(server)
    if not code:
        return None
    try:
        resp = request_with_proxy(
            "GET",
            f"{BASE}/wx/user/appletLogin",
            params={"code": code},
            headers={"User-Agent": LOGIN_UA},
            proxies=proxies,
            server=server,
        )
        data = resp.json()
        # 响应: {"code":200,"data":"<uuid token>"}，data 即 applet_auth_token
        if data.get("code") == 200 and data.get("data"):
            token = data["data"]
            print(f"✅ 登录成功，authToken: {str(token)[:8]}...")
            return token
        print(f"❌ 登录失败：{data.get('msg', '未知错误')}，状态码: {resp.status_code}")
        print(f"   响应体: {resp.text[:500]}")
        return None
    except Exception as e:
        print(f"❌ 登录异常: {e}")
        return None


def get_userinfo(ck: str, proxies: Optional[Dict[str, str]] = None) -> Optional[dict]:
    """用 applet_auth_token 查用户资料，验证 ck 是否有效"""
    return do_request(ck, f"{BASE}/applet/user/getUserBaseInfo", "验证ck-查资料", proxies=proxies)


def verify_ck(ck: str, proxies: Optional[Dict[str, str]] = None) -> bool:
    """验证 ck 是否有效（非 None 且能拿到用户资料）"""
    if not ck:
        return False
    data = get_userinfo(ck, proxies)
    if data and data.get("code") == 200 and data.get("data"):
        u = data["data"]
        print(f"✅ ck 有效: {u.get('userName', '?')}")
        return True
    print(f"❌ ck 无效或已过期: {str(data)[:120]}")
    return False


def get_ck(server: str, proxies: Optional[Dict[str, str]] = None) -> Optional[str]:
    """通过 code→ck 获取 applet_auth_token（code 来自本地 code 服务）"""
    ck = code_login(server, proxies)
    if ck and verify_ck(ck, proxies):
        return ck
    return None


def step(icon: str, desc: str, result: str = "") -> None:
    """统一子步骤打印：🟢 描述 → 结果"""
    if result:
        print(f"  {icon} {desc} → {result}")
    else:
        print(f"  {icon} {desc}")


def section(title: str, icon: str = "📌") -> None:
    """章节标题分隔条"""
    bar = "─" * 40
    print(f"\n{icon} {title}")
    print(f"  {bar}")


def do_request(auth_token: str, url: str, desc: str, method: str = "GET",
               proxies: Optional[Dict[str, str]] = None) -> Optional[dict]:
    headers = {**BASE_HEADERS, "Authorization": auth_token}
    try:
        resp = request_with_proxy(method, url, headers=headers, proxies=proxies)
        data = resp.json()
        msg = (data or {}).get("msg", "操作成功")
        step("🔹", desc, msg)
        return data
    except Exception as e:
        err_msg = str(e)
        step("⚠️", desc, f"失败: {err_msg}")
        return None


def sign_in_award(auth_token: str, proxies: Optional[Dict[str, str]] = None) -> list:
    """签到有奖"""
    section("签到有奖", "🎁")
    logs = []
    resp = do_request(auth_token, f"{BASE}/applet/user/signIn/getUserSignInLog", "查询签到有奖状态", proxies=proxies)
    if not resp or resp.get("code") != 200:
        logs.append("❌ 查询签到有奖状态失败")
        return logs
    today = datetime.now().strftime("%Y-%m-%d")
    sign_list = (resp.get("data") or {}).get("userSignInList") or []
    signed = any(
        (i.get("signInDate") == today and i.get("signInStatus") == 1)
        for i in sign_list
    )
    if signed:
        step("✅", "签到有奖", "今日已完成")
        logs.append("✅ 签到有奖：今日已完成")
    else:
        do_sign = do_request(auth_token, f"{BASE}/applet/user/signIn", "执行签到有奖", "POST", proxies=proxies)
        ok = bool(do_sign and do_sign.get("code") == 200)
        step("✅" if ok else "❌", "签到有奖", "成功" if ok else "失败")
        logs.append(("✅ 签到有奖成功" if ok else "❌ 签到有奖失败"))
    return logs


def plant_dendrobium(auth_token: str, proxies: Optional[Dict[str, str]] = None) -> tuple[list, bool]:
    """石斛播种（若尚未种植）"""
    section("石斛播种检查", "🌱")
    logs = []
    info = do_request(auth_token, f"{BASE}/applet/game/dendrobium/get", "查询石斛状态", proxies=proxies)
    if not info:
        step("❌", "查询石斛状态", "失败")
        logs.append("❌ 查询石斛状态失败")
        return logs, False
    # 未播种：code==500 且 msg 含"没有正在培养"
    if info.get("code") == 500 or "没有正在培养" in (info.get("msg") or ""):
        step("🟡", "石斛状态", "未种植，准备播种")
        sow = do_request(
            auth_token,
            f"{BASE}/applet/game/dendrobium/sowing?inviteUserId=sIH3CMTkxHnniqbPfy1B8g%3D%3D",
            "执行石斛播种",
            proxies=proxies,
        )
        if sow and sow.get("code") == 200:
            step("✅", "石斛播种", "成功")
            logs.append("✅ 石斛播种成功")
        else:
            step("❌", "石斛播种", "失败")
            logs.append("❌ 石斛播种失败")
            return logs, False
        # 播种后再次查询确认
        confirm = do_request(auth_token, f"{BASE}/applet/game/dendrobium/get", "确认石斛状态", proxies=proxies)
        planted = bool(confirm and confirm.get("code") == 200 and confirm.get("data"))
        return logs, planted
    # 已播种：code==200 且有 data
    if info.get("code") == 200 and info.get("data"):
        step("✅", "石斛状态", "已种植，跳过播种")
        logs.append("✅ 石斛已种植，跳过播种")
        return logs, True
    # 其他未知情况，保守当已种植处理（避免重复播种报错）
    step("⚠️", "石斛状态", "未知，按已种植处理")
    logs.append("⚠️ 石斛状态未知，按已种植处理")
    return logs, True


def dendrobium_sign(auth_token: str, proxies: Optional[Dict[str, str]] = None) -> list:
    """石斛签到"""
    section("石斛签到", "🌿")
    logs = []
    resp = do_request(auth_token, f"{BASE}/applet/game/dendrobium/signIn/getUserSignInLog", "查询石斛签到状态", proxies=proxies)
    if resp and (resp.get("data") or {}).get("todaySignInStatus"):
        logs.append("✅ 石斛签到：今日已完成")
    else:
        do_sign = do_request(auth_token, f"{BASE}/applet/game/dendrobium/signIn", "执行石斛签到", proxies=proxies)
        logs.append("✅ 石斛签到成功" if do_sign and do_sign.get("code") == 200 else "❌ 石斛签到失败")
    return logs


def _article_done_count(auth_token: str, proxies: Optional[Dict[str, str]] = None) -> int:
    """取推文任务(type=5)已完成次数：解析 task/list 的 schedule 'x/3'"""
    lst = do_request(auth_token, f"{BASE}/applet/game/dendrobium/task/list", "查询任务进度", proxies=proxies)
    if not lst or lst.get("code") != 200 or not lst.get("data"):
        return -1
    for t in lst["data"]:
        if t.get("type") == 5:
            sch = (t.get("schedule") or "0/3")
            try:
                done = int(str(sch).split("/")[0])
            except Exception:
                done = 0
            return done
    return 0


def browse_articles(auth_token: str, proxies: Optional[Dict[str, str]] = None) -> list:
    """推文浏览（每日3次，每次等30-40秒）"""
    section("推文浏览", "📖")
    logs = []

    before = _article_done_count(auth_token, proxies)
    if before < 0:
        logs.append("❌ 查询推文任务进度失败")
        return logs
    if before >= 3:
        step("✅", "推文", f"今日已完成（{before}/3），跳过")
        return ["✅ 今日推文已完成，跳过"]

    step("📊", "推文进度", f"当前 {before}/3，开始补满")
    done = before
    for i in range(before + 1, 4):
        sec = 30 + int(os.urandom(1)[0] % 11)
        step("⏳", f"第{i}次浏览", f"等待{sec}秒模拟阅读")
        time.sleep(sec)
        do_request(auth_token, f"{BASE}/applet/game/dendrobium/article/completeRead", f"第{i}次推文浏览", proxies=proxies)
        # 不依赖 msg，复查进度
        after = _article_done_count(auth_token, proxies)
        if after > done:
            done = after
            logs.append(f"✅ 第{i}次浏览成功（进度 {done}/3）")
        else:
            logs.append(f"🚫 第{i}次未推进进度（可能需真机阅读或额度已满），停止")
            break
        time.sleep(2)

    if done >= 3:
        logs.append("🎉 今日推文浏览已补满 3/3")
    else:
        logs.append(f"⚠️ 今日推文仅完成 {done}/3（接口未推进进度，可能需真机阅读）")
    return logs


def buy_fertilizer(auth_token: str, proxies: Optional[Dict[str, str]] = None) -> list:
    """徽宝买肥料"""
    section("徽宝买肥料", "🛒")
    logs = []

    # 1. 查积分
    user_info = do_request(auth_token, f"{BASE}/applet/game/dendrobium/getUserInfo", "查询积分", proxies=proxies)
    if not user_info or user_info.get("code") != 200:
        logs.append("❌ 查询积分失败")
        return logs
    integrate = (user_info.get("data") or {}).get("integrate", 0)
    step("💰", "当前徽宝", str(integrate))

    # 2. 查商品
    goods_resp = do_request(auth_token, f"{BASE}/applet/game/dendrobium/goods/list?type=1", "查询肥料商品", proxies=proxies)
    if not goods_resp or goods_resp.get("code") != 200 or not goods_resp.get("data"):
        logs.append("❌ 查询商品列表失败")
        return logs

    # 按价格降序，优先买贵的（200g > 100g）
    goods_list = sorted(goods_resp["data"], key=lambda x: x.get("price", 0), reverse=True)
    min_price = min((x.get("price", 0) for x in goods_list if x.get("price", 0) > 0), default=0)
    remain = integrate

    for item in goods_list:
        price = item.get("price", 0)
        if price <= 0:
            continue
        max_count = remain // price
        if max_count <= 0:
            continue
        goods_name = item.get("goodsName", "")
        goods_id = item.get("goodsId", "")
        step("🛍️", f"购买 {goods_name}", f"x{max_count} (共{max_count * price}徽宝)")
        for i in range(max_count):
            order = do_request(
                auth_token,
                f"{BASE}/applet/game/dendrobium/order/placeOrder?goodsId={goods_id}&goodsNum=1",
                f"买{goods_name} 第{i+1}次",
                proxies=proxies,
            )
            if order and order.get("code") == 200:
                remain -= price
            else:
                break
            time.sleep(1)

    spent = integrate - remain
    if spent == 0 and remain > 0 and min_price > 0:
        step("⚠️", "徽宝不足", f"当前 {remain} 徽宝，不足最低 {min_price} 徽宝，无法购买")
    step("💰", "购买结果", f"花费 {spent} 徽宝，剩余 {remain} 徽宝")
    logs.append(f"💰 共花费 {spent} 徽宝，剩余 {remain} 徽宝")
    return logs


def exhaust_fertilizer(auth_token: str, planted: bool = True,
                       proxies: Optional[Dict[str, str]] = None) -> list:
    """自动施肥（肥料<100g停止）"""
    section("自动施肥", "🌿")
    logs = []
    if not planted:
        step("⏭️", "施肥", "无培养中石斛，跳过")
        logs.append("⏭️ 没有正在培养中的石斛，跳过施肥")
        logs.append("🌿 共施肥0次")
        return logs
    count = 0
    while True:
        info = do_request(auth_token, f"{BASE}/applet/game/dendrobium/get", "查询肥料数量", proxies=proxies)
        if not info or info.get("code") != 200:
            # code==500 表示未种植，停止循环
            if info and info.get("code") == 500:
                logs.append("石斛已不在培养中，停止施肥")
            break
        val = (info.get("data") or {}).get("fertilizer", 0)
        if val < 100:
            logs.append(f"肥料剩余{val}g，停止")
            break
        do_request(auth_token, f"{BASE}/applet/game/dendrobium/fertilizer", f"施肥第{count+1}次", proxies=proxies)
        count += 1
        time.sleep(1)
    logs.append(f"共施肥{count}次")
    return logs


def run_account(server: str, index: int, total: int) -> dict:
    print(f"\n{'━' * 46}")
    print(f"  🍃 甜润世界 | 账号 {index}/{total} | {server}")
    print(f"  🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'━' * 46}")

    result = {
        "server": server,
        "ok": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "logs": [],
        "error": "",
    }

    proxies, proxy_ip = get_valid_proxy(server)
    result["proxyStatus"] = "使用品赞代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    time.sleep(PROXY_FETCH_INTERVAL)

    delay = random.randint(2, 6)
    print(f"⏳ [延迟] 启动延迟 {delay}s")
    time.sleep(delay)

    auth_token = get_ck(server, proxies)
    if not auth_token:
        result["error"] = "获取 ck 失败（code→ck 失败），跳过"
        print("❌ 获取 ck 失败（code→ck 失败），跳过")
        return result

    all_logs = []

    # 1. 签到有奖
    all_logs.extend(sign_in_award(auth_token, proxies))

    # 2. 石斛播种（未种植则播种，已种植跳过）→ 返回是否已在培养
    plant_logs, planted = plant_dendrobium(auth_token, proxies)
    all_logs.extend(plant_logs)

    # 3. 石斛签到（需先种植，否则会提示"请先种植石斛"）
    all_logs.extend(dendrobium_sign(auth_token, proxies))

    # 4. 推文浏览
    all_logs.extend(browse_articles(auth_token, proxies))

    # 5. 徽宝买肥料
    all_logs.extend(buy_fertilizer(auth_token, proxies))

    # 6. 自动施肥（未种植则跳过）
    all_logs.extend(exhaust_fertilizer(auth_token, planted, proxies))

    print(f"\n{'─' * 46}")
    print(f"  📋 本账号执行汇总")
    print(f"{'─' * 46}")
    for line in all_logs:
        print(f"  {line}")

    result["logs"] = all_logs
    result["ok"] = True
    return result


def build_notify(results: List[dict]) -> str:
    """组装 PushPlus 推送内容（参考铛铛一下.py）"""
    ok_count = sum(1 for item in results if item["ok"])
    fail_count = len(results) - ok_count

    content = f"""🍃 甜润世界小程序签到结果

━━━━━━━━━━━━━━━━━━━━
🏁 总结：{ok_count} 成功 / {fail_count} 失败
🕒 时间：{now_text()}
━━━━━━━━━━━━━━━━━━━━
"""

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["ok"] else "❌"

        content += f"""
🧩 账号 {idx}
🌍 来源：{res['server']}
🌐 代理：{res['proxyStatus']}
📡 出口IP：{res['proxyIp']}
{icon} 结果：{'成功' if res['ok'] else '失败'}
"""

        for line in res.get("logs", []):
            content += f"   {line}\n"

        if not res["ok"]:
            content += f"❌ 原因：{res['error']}\n"

        content += "━━━━━━━━━━━━━━━━━━━━\n"

    return content


if __name__ == "__main__":
    results = []
    for i, server in enumerate(CODE_SERVERS, 1):
        res = run_account(server, i, len(CODE_SERVERS))
        results.append(res)
        if i < len(CODE_SERVERS):
            time.sleep(5)

    summary = "\n".join(f"{r['server']}: {'✅' if r['ok'] else '❌'}" for r in results)
    print(f"\n{'━' * 46}")
    print(f"  🏁 运行结果汇总")
    print(f"{'━' * 46}")
    print(summary)

    send_pushplus("🍃 甜润世界签到完成", build_notify(results))