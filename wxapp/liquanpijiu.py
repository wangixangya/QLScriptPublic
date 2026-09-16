#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 漓泉啤酒生态营地 - 每日签到得积分
# 入口: 微信小程序「漓泉啤酒生态营地」-> 会员中心 -> 每日签到
# 说明: 通过 wx_server(smallcat) 用 openid 换取 wx.login code, 复刻小程序的
#       会员静默登录 (mbr/members/wxLogin/{code}) 拿到 Token, 再完成每日签到。
# 接口契约 (来自小程序主包 common/vendor.js 反编译):
#   登录  GET  /api/mbr/members/wxLogin/{code}?appId=<appid>
#            -> errcode==0 且 data.b2cMemberId/openid 存在; data.token 为会话凭证
#   鉴权  请求头 Token: <token>   (响应拦截器: errcode||code, 200 成功, 401 会话失效)
#   状态  GET  /api/b2c/member/sign/task/list  -> data.signRes.{sign, signNum,
#            taskSignDtoList[{signTime, signStatus}]}   sign==true / 今日行
#            signStatus=="sign" 即今日已签 (幂等预检依据)
#   签到  POST /api/b2c/member/sign/task  body {}  -> code==200, data.signRes.sign==true
#   积分  GET  /api/b2c/member/pointsAndCouponCardNumAndShopCardInfo?unionId=<unionId>
#            -> data.MemberCouponShopPointsVo.pointsNum   (仅用于上报余额)
# 账号变量名:lqpj   (填写 wx_server 中的 openid, 多账号用换行或 & 分割, 可选 #备注)
# 需要配置 wx_server_url、wx_auth, 用于获取 wx.login code
#new Env("漓泉啤酒签到")
#cron 30 9 * * *

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from notify import send
except Exception:
    def send(title, content):
        print(f"\n===== {title} =====\n{content}")

# ---------------------------------------------------------------------------
# 常量 (均来自小程序反编译源码, 非机密)
# ---------------------------------------------------------------------------
MINI_APP_ID = "wx08dabaec2783f4e9"
BASE_URL = "https://api.mbr.liquan.com/api"          # vendor.js api_HOST
SUCCESS_CODE = 200
SESSION_INVALID_CODE = 401                            # 拦截器: 清 token 并重新登录
SIGNED = "sign"                                       # taskSignDtoList[].signStatus

# smallcat / wx_server 配置 (机密, 从环境变量读取, 绝不硬编码)
WX_SERVER_URL = os.getenv("wx_server_url", "http://172.23.0.2:8000").rstrip("/")
WX_AUTH = os.getenv("wx_auth", "")

TOKEN_CACHE_PATH = Path(__file__).with_name("liquanpijiu_token_cache.json")
DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G9910 Build/TP1A.220624.014) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36 "
    "MicroMessenger/8.0.49.2600(0x28003137) NetType/WIFI Language/zh_CN "
    "miniProgram/" + MINI_APP_ID
)

session = requests.Session()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def bj_now():
    return datetime.now(timezone(timedelta(hours=8)))


def mask(value):
    if not value:
        return ""
    value = str(value)
    if len(value) <= 12:
        return value[:2] + "***"
    return f"{value[:6]}***{value[-4:]}"


def read_token_cache():
    try:
        if TOKEN_CACHE_PATH.exists():
            return json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def write_token_cache(cache):
    try:
        TOKEN_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"⚠️ 写入token缓存失败: {e}")


def get_cached_session(openid):
    return read_token_cache().get(openid) or {}


def save_cached_session(openid, token, union_id):
    cache = read_token_cache()
    cache[openid] = {"token": token, "unionId": union_id,
                     "updatedAt": int(time.time())}
    write_token_cache(cache)


def remove_cached_session(openid):
    cache = read_token_cache()
    if openid in cache:
        del cache[openid]
        write_token_cache(cache)


# ---------------------------------------------------------------------------
# smallcat: openid -> wx.login code
# ---------------------------------------------------------------------------
def get_wx_code(openid):
    if not WX_AUTH:
        raise RuntimeError("缺少 wx_auth, 无法从 wx_server 获取 code")
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "auth": WX_AUTH}
    body = json.dumps({"appid": MINI_APP_ID, "openid": openid})
    last_msg = ""
    for attempt in range(4):
        if attempt:
            # smallcat 偶发 "获取失败"(会话抖动), 刷新会话后间隔重试
            try:
                session.post(f"{WX_SERVER_URL}/wx/refresh", data=body,
                             headers=headers, timeout=30)
            except Exception:
                pass
            time.sleep(3)
        resp = session.post(f"{WX_SERVER_URL}/wx/code", data=body,
                            headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("status") is False:
            last_msg = data.get("message") or "获取失败"
            continue
        code = data.get("code") or (data.get("data") or {}).get("code")
        if code:
            return code
        last_msg = "wx_server 未返回 code"
    raise RuntimeError(f"wx_server 获取 code 失败(已重试): {last_msg}")


# ---------------------------------------------------------------------------
# 漓泉会员 API
# ---------------------------------------------------------------------------
def api_headers(token=None):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": DEFAULT_UA,
        "Referer": f"https://servicewechat.com/{MINI_APP_ID}/0/page-frame.html",
    }
    if token:
        headers["Token"] = token            # 请求拦截器: headers.Token = 本地 token
    return headers


def api_get(path, token=None, params=None):
    resp = session.get(f"{BASE_URL}{path}", params=params or {},
                       headers=api_headers(token), timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_post(path, body, token=None):
    resp = session.post(f"{BASE_URL}{path}",
                        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                        headers=api_headers(token), timeout=30)
    resp.raise_for_status()
    return resp.json()


def resp_code(resp):
    """拦截器口径: errcode 优先, 否则 code。"""
    node = resp if isinstance(resp, dict) else {}
    for key in ("errcode", "code"):
        v = node.get(key)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return -1


def resp_msg(resp):
    node = resp if isinstance(resp, dict) else {}
    for key in ("errmsg", "message", "msg"):
        v = node.get(key)
        if v:
            return str(v)
    data = node.get("data")
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    return ""


# ---------------------------------------------------------------------------
# 登录 / 会话
# ---------------------------------------------------------------------------
def login(openid):
    """wx.login code -> wxLogin -> (token, unionId)。code 放在 URL 路径中。"""
    code = get_wx_code(openid)
    resp = api_get(f"/mbr/members/wxLogin/{code}", params={"appId": MINI_APP_ID})
    if resp_code(resp) != 0:
        raise RuntimeError(f"登录失败: {resp_msg(resp) or resp_code(resp)}")
    data = resp.get("data") or {}
    token = data.get("token")
    union_id = data.get("unionid") or (data.get("wxUserInfo") or {}).get("unionId")
    if not (token and data.get("b2cMemberId")):
        raise RuntimeError("登录响应缺少 token/b2cMemberId, 需在小程序内登录一次后重试")
    return token, union_id


def obtain_session(openid, index, force=False):
    if force:
        remove_cached_session(openid)
    else:
        cached = get_cached_session(openid)
        if cached.get("token"):
            print(f"账号 {index} 使用缓存 token: {mask(cached['token'])}")
            return cached["token"], cached.get("unionId")
    token, union_id = login(openid)
    save_cached_session(openid, token, union_id)
    print(f"账号 {index} 静默登录成功: {mask(token)}")
    return token, union_id


# ---------------------------------------------------------------------------
# 签到业务
# ---------------------------------------------------------------------------
def sign_state(token):
    return api_get("/b2c/member/sign/task/list", token=token)


def do_sign(token):
    return api_post("/b2c/member/sign/task", {}, token=token)


def points_balance(token, union_id):
    """仅读取积分余额用于上报, 失败返回 None (不影响签到结论)。"""
    if not union_id:
        return None
    try:
        resp = api_get("/b2c/member/pointsAndCouponCardNumAndShopCardInfo",
                       token=token, params={"unionId": union_id})
        if resp_code(resp) != SUCCESS_CODE:
            return None
        vo = (resp.get("data") or {}).get("MemberCouponShopPointsVo") or {}
        return vo.get("pointsNum")
    except Exception:
        return None


def sign_res(resp):
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict) and isinstance(data.get("signRes"), dict):
        return data["signRes"]
    return {}


def signed_today(res):
    """今日已签: signRes.sign 为真, 或今日日期行 signStatus == 'sign'。"""
    if res.get("sign") is True:
        return True
    today = bj_now().strftime("%Y-%m-%d")
    for row in res.get("taskSignDtoList") or []:
        if row.get("signTime") == today and row.get("signStatus") == SIGNED:
            return True
    return False


def fmt_num(value):
    """服务端 signNum 为浮点(1.0), 展示成整数更自然。"""
    try:
        f = float(value)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(value)


def run_account(openid, index):
    lines = [f"【账号 {index}】"]

    token, union_id = obtain_session(openid, index)

    # 读取签到状态 (首个鉴权调用); 会话失效则强制重登重试一次
    state = sign_state(token)
    if resp_code(state) == SESSION_INVALID_CODE:
        print(f"账号 {index} 会话失效, 重新登录...")
        token, union_id = obtain_session(openid, index, force=True)
        state = sign_state(token)

    scode = resp_code(state)
    if scode != SUCCESS_CODE:
        msg = resp_msg(state) or f"获取签到状态失败 code={scode}"
        print(f"❌ 账号 {index} {msg}")
        lines.append(f"❌ {msg}")
        return "\n".join(lines), False

    res = sign_res(state)

    # 幂等预检: 今日已签则不再提交
    if signed_today(res):
        msg = f"今日已签到, 无需重复 (本周已签 {fmt_num(res.get('signNum'))} 天)"
        print(f"✅ 账号 {index} {msg}")
        lines.append(f"✅ {msg}")
        pts = points_balance(token, union_id)
        if pts is not None:
            lines.append(f"当前积分: {pts}")
            print(f"账号 {index} 当前积分: {pts}")
        return "\n".join(lines), True

    # 执行一次签到
    result = do_sign(token)
    rcode = resp_code(result)
    if rcode == SESSION_INVALID_CODE:
        print(f"账号 {index} 会话失效, 重新登录后重试签到...")
        token, union_id = obtain_session(openid, index, force=True)
        result = do_sign(token)
        rcode = resp_code(result)

    if rcode != SUCCESS_CODE:
        msg = resp_msg(result) or f"签到失败 code={rcode}"
        print(f"❌ 账号 {index} {msg}")
        lines.append(f"❌ {msg}")
        return "\n".join(lines), False

    res = sign_res(result)
    if not signed_today(res) and res.get("sign") is not True:
        msg = resp_msg(result) or "签到接口返回成功但未标记已签, 请稍后重试"
        print(f"⚠️ 账号 {index} {msg}")
        lines.append(f"⚠️ {msg}")
        return "\n".join(lines), False

    msg = f"签到成功, 本周已签 {fmt_num(res.get('signNum'))} 天"
    print(f"🎉 账号 {index} {msg}")
    lines.append(f"🎉 {msg}")

    pts = points_balance(token, union_id)
    if pts is not None:
        lines.append(f"当前积分: {pts}")
        print(f"账号 {index} 当前积分: {pts}")
    return "\n".join(lines), True


def main():
    raw = os.getenv("lqpj", "")
    entries = [x.strip() for x in raw.replace("&", "\n").splitlines() if x.strip()]

    if not entries:
        print("❌ 未检测到账号信息(环境变量 lqpj), 退出。")
        return
    if not WX_AUTH:
        print("❌ 未配置 wx_auth, 无法获取 code, 退出。")
        return

    print("=============== 漓泉啤酒 签到开始 ===============")
    summaries = []
    ok_count = 0
    for i, entry in enumerate(entries, 1):
        parts = entry.split("#", 1)
        openid = parts[0].strip()
        remark = parts[1].strip() if len(parts) > 1 else ""
        print(f"\n-------------- 账号 {i}{('/' + remark) if remark else ''} --------------")
        try:
            summary, ok = run_account(openid, i)
            summaries.append(summary)
            ok_count += 1 if ok else 0
        except Exception as e:
            print(f"❌ 账号 {i} 执行异常: {e}")
            summaries.append(f"【账号 {i}】\n❌ 执行异常: {e}")
        time.sleep(1)

    print("\n=============== 漓泉啤酒 签到结束 ===============")
    title = f"漓泉啤酒签到 {ok_count}/{len(entries)} 成功"
    try:
        send(title, "\n\n".join(summaries))
    except Exception as e:
        print(f"⚠️ 通知发送失败: {e}")



# === YYB-Go 兼容层 ===
import os as _yyb_os
import json as _yyb_json
_YWB_SERVER = "172.23.0.2:8000"

def _yyb_accounts():
    result = []
    for line in _yyb_os.getenv("YYB_SERVER", "").splitlines():
        line = line.strip()
        if not line or "@" not in line:
            continue
        endpoint, ref = (p.strip() for p in line.split("@", 1))
        if endpoint and ref:
            if not endpoint.startswith(("http://", "https://")):
                endpoint = "http://" + endpoint
            result.append(endpoint.rstrip("/") + "@" + ref)
    return result

def _yyb_parts(server):
    v = str(server).strip()
    if "@" not in v:
        return v.rstrip("/"), ""
    return v.rsplit("@", 1)[0].rstrip("/"), v.rsplit("@", 1)[1]

def _yyb_appid(args, kwargs):
    a = kwargs.get("appid") or kwargs.get("app_id")
    if not a:
        a = globals().get("APPID") or globals().get("APP_ID") or globals().get("MINI_APP_ID")
        if not a:
            for k in dir():
                if isinstance(k, str) and "APPID" in k.upper() and k.isupper():
                    a = globals().get(k, "")
                    break
    if isinstance(a, (list, tuple)):
        a = a[0] if a else ""
    return str(a) if a else ""

def _yyb_json_req(server, path, appid, payload=None):
    import requests
    ep, ref = _yyb_parts(server)
    if not ep or not ref or not appid:
        raise RuntimeError("YYB 参数不完整")
    h = {}
    k = _yyb_os.getenv("YYB_API_KEY", "").strip()
    if k:
        h["Authorization"] = "Bearer " + k
    b = {"ref": ref, "app_id": str(appid)}
    if payload:
        b.update(payload)
    r = requests.post(ep + path, json=b, headers=h, timeout=30)
    try:
        b = r.json()
    except ValueError as e:
        raise RuntimeError("YYB 返回非 JSON") from e
    if r.status_code >= 400:
        raise RuntimeError(str(b.get("message") or b.get("msg") or b))
    return b

def _yyb_find_code(v):
    if isinstance(v, dict):
        c = v.get("code")
        if isinstance(c, str) and c not in ("", "null", "invalid"):
            return c
        for ch in v.values():
            f = _yyb_find_code(ch)
            if f:
                return f
    elif isinstance(v, list):
        for ch in v:
            f = _yyb_find_code(ch)
            if f:
                return f
    return None

def _yyb_get_code(server, *args, **kwargs):
    b = _yyb_json_req(server, "/wxapp/getCode", _yyb_appid(args, kwargs))
    c = _yyb_find_code(b)
    if not c:
        raise RuntimeError(str(b.get("msg") or b.get("message") or "YYB 未返回 code"))
    return str(c)

# 包装原取码函数
for _fn in ("get_wx_code", "get_code", "smallcat"):
    if _fn in globals():
        _orig = globals()[_fn]

        def _make_wrapper(orig):
            def wrapper(server, *args, **kwargs):
                if "@" in str(server):
                    return _yyb_get_code(server, *args, **kwargs)
                return orig(server, *args, **kwargs)
            return wrapper

        globals()[_fn] = _make_wrapper(_orig)

# 注入账号到环境变量
_yyb_accts = _yyb_accounts()
if _yyb_accts:
    _yyb_os.environ["lqpj"] = "\n".join(_yyb_accts)

# === end YYB 兼容层 ===

if __name__ == "__main__":
    main()


# ============================================================
# YYB-Go 兼容层 (auto-appended)
# ============================================================
import os as _yyb_os
import json as _yyb_json

_YWB_SERVER = "yyb-go:8000"

def _yyb_accounts():
    result = []
    for line in _yyb_os.getenv("YYB_SERVER", "").splitlines():
        line = line.strip()
        if not line or "@" not in line or line == "[object Object]":
            continue
        endpoint, ref = (part.strip() for part in line.split("@", 1))
        if endpoint and ref:
            if not endpoint.startswith(("http://", "https://")):
                endpoint = "http://" + endpoint
            result.append(endpoint.rstrip("/") + "@" + ref)
    return result

def _yyb_parts(server):
    value = str(server).strip()
    if "@" not in value:
        return value.rstrip("/"), ""
    return value.rsplit("@", 1)[0].rstrip("/"), value.rsplit("@", 1)[1]

def _yyb_appid(args, kwargs):
    appid = kwargs.get("appid") or kwargs.get("app_id")
    if not appid and args and isinstance(args[0], str):
        appid = args[0]
    if not appid:
        appid = globals().get("APPID") or globals().get("APP_ID") or ""
    if isinstance(appid, (list, tuple)):
        appid = appid[0] if appid else ""
    return str(appid)

def _yyb_json_request(server, path, appid, payload=None):
    import requests
    endpoint, ref = _yyb_parts(server)
    if not endpoint or not ref or not appid:
        raise RuntimeError("YYB 参数不完整：需要 地址@账号ID 和 app_id")
    headers = {}
    api_key = _yyb_os.getenv("YYB_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    body = {"ref": ref, "app_id": str(appid)}
    if payload:
        body.update(payload)
    response = requests.post(
        endpoint + path,
        json=body,
        headers=headers,
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError("YYB 返回非 JSON") from exc
    if response.status_code >= 400:
        raise RuntimeError(str(body.get("message") or body.get("msg") or body))
    return body

def _yyb_find_code(value):
    if isinstance(value, dict):
        if value.get("code") not in (None, "", "null", "invalid") and isinstance(value.get("code"), str):
            return value["code"]
        for child in value.values():
            found = _yyb_find_code(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _yyb_find_code(child)
            if found:
                return found
    return None

def _yyb_code(server, *args, **kwargs):
    body = _yyb_json_request(server, "/wxapp/getCode", _yyb_appid(args, kwargs))
    code = _yyb_find_code(body)
    if not code:
        raise RuntimeError(str(body.get("msg") or body.get("message") or "YYB 未返回 wx.login code"))
    return str(code)

def _yyb_phone(server, *args, **kwargs):
    body = _yyb_json_request(server, "/wxapp/getPhoneNumber", _yyb_appid(args, kwargs))
    return body.get("result") or body.get("data") or body

# 自动替换原取码函数
if "get_wx_code" in globals():
    _yyb_original_get_wx_code = get_wx_code
    
    def get_wx_code(server, *args, **kwargs):
        if "@" in str(server):
            return _yyb_code(server, *args, **kwargs)
        return _yyb_original_get_wx_code(server, *args, **kwargs)

if "get_code" in globals() and "get_wx_code" not in globals():
    _yyb_original_get_code = get_code
    
    def get_code(server, *args, **kwargs):
        if "@" in str(server):
            return _yyb_code(server, *args, **kwargs)
        return _yyb_original_get_code(server, *args, **kwargs)

if "smallcat" in globals():
    _yyb_original_smallcat = smallcat
    
    def smallcat(server, *args, **kwargs):
        if "@" in str(server):
            return _yyb_code(server, *args, **kwargs)
        return _yyb_original_smallcat(server, *args, **kwargs)

# 替换 main 中的账号加载
if "main" in globals():
    _yyb_original_main = main
    
    def main():
        yyb_accts = _yyb_accounts()
        if yyb_accts:
            for line in yyb_accts:
                print("YYB-Go 账号: " + line)
        return _yyb_original_main()

# === end YYB compatibility layer ===
