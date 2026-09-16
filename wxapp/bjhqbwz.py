#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 北京环球度假区互动福利站 - 每日签到 (连续签到可获抽奖门票机会)
# 入口: 微信小程序「北京环球度假区互动福利站」-> 签到
# 说明: 通过 wx_server(smallcat) 用 openid 换取 wx.login code 自动登录, 完成每日签到。
#       连续签到达标后会获得抽奖机会, 但抽奖属于领奖动作, 本脚本不自动触发, 仅完成签到。
# 账号变量名:bjhqbwz  (填写 wx_server 中的 openid, 多账号用换行或 & 分割, 可选 #备注)
# 需要配置 wx_server_url、wx_auth, 用于获取 wx.login code
#new Env("北京环球签到")
#cron 15 9 * * *

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
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
MINI_APP_ID = "wx21f6790118783b83"
BASE_URL = "https://bmp.app.universalbeijingresort.com"
PATH_PREFIX = "/2026_ubr_yunyingqiu"                 # app.js 路径前缀 (小写)
ACTIVITY_CODE = "2026_UBR_YUNYINGQIU"                # app.js activityCode (大写)
# HTTP-Signatures 签名密钥 (客户端内置, 生产环境; 非 appsecret)
HMAC_USERNAME = "ubr-bmp"
HMAC_SECRET = "aK@AtX5#Ck5x"
SUCCESS_CODE = 200
SESSION_CODES = (401, 403)                           # 会话失效 -> 需重新登录
NEED_GOV_CODE = 60002                                # 需补充身份证/实名
NEED_CERT_CODE = 60003                               # 需完成实名认证
MEMBER_IDENTITIES = ("NORMAL_MEMBER", "ANNUAL_CARD_MEMBER")
# 「连续签到5天抽门票」玩法(Surprise5)开启时, 首签前需选一个抽奖奖池(小程序内
# 为二次确认弹窗)。本脚本按用户授权的 bjhqbwz_pool 自动选定一次(幂等: 已选过/无
# 门槛则不重复选); 若置空/none 则不自动选, 仅如实上报由用户在小程序内手动选。
POOL_GATE_HINT = "奖池"
# 奖池自动选择(用户授权): ticket1=指定日门票5折 / ticket2=门票+优速通套餐5折 /
# hotel=酒店5折。默认 ticket2(门票+优速通)。置空或 none/off 关闭自动选。
POOL_CHOICE = os.getenv("bjhqbwz_pool", "ticket2").strip().lower()
POOL_LABELS = {
    "ticket1": "指定日门票5折优惠券",
    "ticket2": "门票+环球优速通套餐5折优惠券",
    "hotel": "度假区酒店5折优惠券",
}
POOL_GATE_MSG = (
    "本期开启了『连续签到5天抽门票』玩法, 首次签到前需选择一个奖池"
    "(①指定日门票5折 ②门票+优速通套餐5折 ③酒店5折)。当前未启用自动选池"
    "(bjhqbwz_pool 为空), 请在小程序「北京环球度假区互动福利站」首页弹窗中"
    "选定奖池后再运行, 或设置环境变量 bjhqbwz_pool=ticket2 由脚本自动选定。"
)

# smallcat / wx_server 配置 (机密, 从环境变量读取, 绝不硬编码)
WX_SERVER_URL = os.getenv("wx_server_url", "http://172.23.0.2:8000").rstrip("/")
WX_AUTH = os.getenv("wx_auth", "")

TOKEN_CACHE_PATH = Path(__file__).with_name("bjhqbwz_token_cache.json")
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
        if not TOKEN_CACHE_PATH.exists():
            return {}
        return json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def write_token_cache(cache):
    try:
        TOKEN_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠️ 写入token缓存失败: {e}")


def get_cached_entity(account_id):
    return read_token_cache().get(account_id) or {}


def save_cached_entity(account_id, entity):
    cache = read_token_cache()
    cache[account_id] = {
        "token": entity.get("token"),
        "id": entity.get("id"),
        "uid": entity.get("uid"),
        "identity": entity.get("identity"),
        "identityCard": entity.get("identityCard"),
        "updatedAt": int(time.time()),
    }
    write_token_cache(cache)


def remove_cached_entity(account_id):
    cache = read_token_cache()
    if account_id in cache:
        del cache[account_id]
        write_token_cache(cache)


# ---------------------------------------------------------------------------
# smallcat: openid -> wx.login code
# ---------------------------------------------------------------------------
def get_wx_code(account_id):
    if not WX_AUTH:
        raise RuntimeError("缺少 wx_auth, 无法从 wx_server 获取 code")
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "auth": WX_AUTH}
    body = json.dumps({"appid": MINI_APP_ID, "openid": account_id})
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
# 北京环球 API (复刻 599C3084...js 的 HTTP-Signatures 签名)
# ---------------------------------------------------------------------------
def sign_headers(body_str, token=None, user_id=None):
    """复刻请求签名: digest=SHA-256(base64), 签名串 hmac-sha1(base64)。"""
    x_date = formatdate(usegmt=True)  # 对应 JS new Date().toUTCString()
    digest = "SHA-256=" + base64.b64encode(
        hashlib.sha256(body_str.encode("utf-8")).digest()
    ).decode("ascii")
    signing_string = f"x-date: {x_date}\ndigest: {digest}"
    signature = base64.b64encode(
        hmac.new(HMAC_SECRET.encode("utf-8"), signing_string.encode("utf-8"),
                 hashlib.sha1).digest()
    ).decode("ascii")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-date": x_date,
        "Digest": digest,
        "Authorization": (
            f'hmac username="{HMAC_USERNAME}", algorithm="hmac-sha1", '
            f'headers="x-date digest", signature="{signature}"'
        ),
        "User-Agent": DEFAULT_UA,
        "Referer": f"https://servicewechat.com/{MINI_APP_ID}/0/page-frame.html",
    }
    if token is not None:
        headers["ArrowAuthorization"] = token or ""
        headers["userId"] = str(user_id if user_id is not None else "")
    return headers


def api_post(path, body, token=None, user_id=None):
    """POST 业务接口: body 序列化后同时用于签名与请求体 (必须一致)。"""
    body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    headers = sign_headers(body_str, token=token, user_id=user_id)
    resp = session.post(f"{BASE_URL}{path}", data=body_str.encode("utf-8"),
                        headers=headers, timeout=30)
    # 会话失效时服务端是用 HTTP 401/403 表达的, 不是 JSON 信封里的 code。
    # raise_for_status() 会在 run_account 的重登重放分支之前就把它抛成异常
    # (实测缓存 token 过期后直接报 "401 Client Error", 整个账号失败),
    # 所以这里把它翻译成带 code 的信封, 交给调用方去重登。
    if resp.status_code in SESSION_CODES:
        try:
            data = resp.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data["code"] = resp.status_code
        return data
    resp.raise_for_status()
    return resp.json()


def envelope_entity(resp):
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict) and isinstance(data.get("entity"), dict):
        return data["entity"]
    if isinstance(resp, dict) and isinstance(resp.get("entity"), dict):
        return resp["entity"]
    return {}


def resp_code(resp):
    for k in ("code", "status"):
        v = (resp or {}).get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return -1


# ---------------------------------------------------------------------------
# 登录 / 会话
# ---------------------------------------------------------------------------
def is_member(entity):
    """源码: uid 非空 <=> 已完成手机号授权注册的会员 (isAuth/hasPhone 均以 uid 判定)。"""
    return bool(entity) and str(entity.get("id", "-1")) != "-1" and bool(entity.get("uid"))


def login(account_id):
    """wx.login code -> user/login (postNoAuth, 无 ArrowAuthorization) -> entity。

    源码逻辑: 200 时若 data.entity.id 存在则为会员实体, 否则视为未注册
    (NONMEMBER, id=-1)。未注册用户需在小程序内经手机号授权 (wechatLogin) 注册,
    属于手机号 PII 前置条件, 本脚本不自动触发, 仅识别并如实上报。
    """
    code = get_wx_code(account_id)
    body = {"code": code, "registerSource": "", "activityCode": ACTIVITY_CODE}
    # 登录接口 postNoAuth: 仍签名, 但不带 ArrowAuthorization/userId
    resp = api_post(f"{PATH_PREFIX}/ubr/user/login", body)
    if resp_code(resp) != SUCCESS_CODE:
        raise RuntimeError(f"登录失败: {resp.get('message') or resp.get('msg') or resp}")
    entity = envelope_entity(resp)
    if not entity or str(entity.get("id", "-1")) == "-1":
        entity = {"id": "-1", "uid": "", "identity": "NONMEMBER"}
    return entity


def get_entity_for_account(account_id, index, force=False):
    if not force:
        cached = get_cached_entity(account_id)
        if cached.get("token") and is_member(cached):
            print(f"账号 {index} 使用缓存 token: {mask(cached.get('token'))}")
            return cached
    entity = login(account_id)
    if is_member(entity):
        save_cached_entity(account_id, entity)
        print(f"账号 {index} code 登录成功: 会员 {mask(entity.get('token'))}")
    else:
        remove_cached_entity(account_id)
        print(f"账号 {index} code 登录成功: 未注册会员 (NONMEMBER)")
    return entity


# ---------------------------------------------------------------------------
# 签到业务
# ---------------------------------------------------------------------------
def activity_detail(token, user_id):
    return api_post(f"{PATH_PREFIX}/business/activityRecord/detail",
                    {"userId": user_id, "activityCode": ACTIVITY_CODE,
                     "prePrizeIds": []}, token=token, user_id=user_id)


def sign_in_record(token, user_id, month):
    return api_post(f"{PATH_PREFIX}/business/yunyingqiu/signInRecord",
                    {"userId": user_id, "activityCode": ACTIVITY_CODE,
                     "month": month}, token=token, user_id=user_id)


def complete_quest(token, user_id, quest_template_id):
    return api_post(f"{PATH_PREFIX}/business/activityRecord/completeQuest",
                    {"userId": user_id, "activityCode": ACTIVITY_CODE,
                     "questTemplateId": quest_template_id},
                    token=token, user_id=user_id)


def select_surprise5_pool(token, user_id, prize):
    """一次性选择「连续签到5天」抽奖奖池 (surprise5select)。

    复刻小程序确认弹窗的提交: POST /business/surpriseFivePhase/selectedPrize
    body {selectedPrize:[prize], userId}, 成功 code==200。prize ∈ ticket1/ticket2/hotel。
    仅在检测到奖池门槛且用户已授权(bjhqbwz_pool)时调用一次, 服务端按活动/期次判定,
    已选过则再次签到不会触发门槛, 故天然幂等。
    """
    return api_post(f"{PATH_PREFIX}/business/surpriseFivePhase/selectedPrize",
                    {"selectedPrize": [prize], "userId": user_id},
                    token=token, user_id=user_id)


def find_sign_in_template_id(detail_resp):
    entity = envelope_entity(detail_resp)
    for quest in entity.get("questList") or []:
        if quest.get("templateCode") == "SIGN_IN":
            return quest.get("templateId")
    return None


def already_signed_today(record_resp):
    entity = envelope_entity(record_resp)
    today = bj_now().strftime("%Y-%m-%d")
    for info in entity.get("signInInfos") or []:
        if info.get("day") == today and info.get("signIn"):
            return True
    return False


def run_account(account_id, index):
    lines = [f"【账号 {index}】"]

    entity = get_entity_for_account(account_id, index)

    # 前置条件: 未注册会员 (无手机号授权) 无法签到; 如实上报, 不自动触发手机号授权
    if not is_member(entity):
        msg = "该账号尚未注册, 需先在小程序「北京环球度假区互动福利站→签到」完成手机号授权注册后才能签到"
        print(f"⚠️ 账号 {index} {msg}")
        lines.append(f"⚠️ {msg}")
        return "\n".join(lines), False

    token = entity.get("token")
    user_id = entity.get("id")
    if not token:
        msg = "登录未返回会话凭证 (token), 需在小程序内重新登录一次以生成会话后再运行"
        print(f"⚠️ 账号 {index} {msg}")
        lines.append(f"⚠️ {msg}")
        return "\n".join(lines), False

    # 拉取任务详情 (首个鉴权调用); 会话失效则强制重登重试一次
    detail = activity_detail(token, user_id)
    if resp_code(detail) in SESSION_CODES:
        print(f"账号 {index} 会话失效, 重新登录...")
        remove_cached_entity(account_id)
        entity = get_entity_for_account(account_id, index, force=True)
        token, user_id = entity.get("token"), entity.get("id")
        detail = activity_detail(token, user_id)

    dcode = resp_code(detail)
    if dcode in (NEED_GOV_CODE, NEED_CERT_CODE):
        msg = "需先在小程序内完成实名/身份证信息后才能签到"
        print(f"⚠️ 账号 {index} {msg} (code={dcode})")
        lines.append(f"⚠️ {msg}")
        return "\n".join(lines), False
    if dcode != SUCCESS_CODE:
        msg = detail.get("message") or detail.get("msg") or f"获取活动详情失败 code={dcode}"
        print(f"❌ 账号 {index} {msg}")
        lines.append(f"❌ {msg}")
        return "\n".join(lines), False

    template_id = find_sign_in_template_id(detail)
    if not template_id:
        msg = "未找到签到任务(SIGN_IN), 活动可能已结束"
        print(f"⚠️ 账号 {index} {msg}")
        lines.append(f"⚠️ {msg}")
        return "\n".join(lines), False

    # 幂等预检: 今日是否已签到
    month = bj_now().strftime("%Y-%m")
    try:
        record = sign_in_record(token, user_id, month)
        if resp_code(record) == SUCCESS_CODE and already_signed_today(record):
            msg = "今日已签到, 无需重复"
            print(f"✅ 账号 {index} {msg}")
            lines.append(f"✅ {msg}")
            return "\n".join(lines), True
    except Exception as e:
        print(f"账号 {index} 签到记录预检失败(忽略, 继续签到): {e}")

    result = complete_quest(token, user_id, template_id)
    rcode = resp_code(result)

    # 奖池门槛: 首签前需选一个抽奖奖池。按用户授权(bjhqbwz_pool)自动选定一次后重试;
    # 未授权(置空)则如实上报, 由用户在小程序内手动选。选池是一次性动作, 不触发抽奖。
    if rcode != SUCCESS_CODE and POOL_GATE_HINT in (result.get("message") or result.get("msg") or ""):
        if POOL_CHOICE in POOL_LABELS:
            label = POOL_LABELS[POOL_CHOICE]
            print(f"账号 {index} 检测到奖池门槛, 按授权自动选定奖池「{label}」...")
            sel = select_surprise5_pool(token, user_id, POOL_CHOICE)
            if resp_code(sel) == SUCCESS_CODE:
                print(f"账号 {index} 奖池已选定「{label}」, 重试签到...")
                lines.append(f"已选定奖池「{label}」")
                result = complete_quest(token, user_id, template_id)
                rcode = resp_code(result)
            else:
                smsg = sel.get("message") or sel.get("msg") or f"code={resp_code(sel)}"
                print(f"⚠️ 账号 {index} 选择奖池失败: {smsg}")
                lines.append(f"⚠️ 选择奖池失败({smsg})。{POOL_GATE_MSG}")
                return "\n".join(lines), False
        else:
            print(f"⚠️ 账号 {index} {POOL_GATE_MSG}")
            lines.append(f"⚠️ {POOL_GATE_MSG}")
            return "\n".join(lines), False

    if rcode in (NEED_GOV_CODE, NEED_CERT_CODE):
        msg = "需先在小程序内完成实名/身份证信息后才能签到"
        print(f"⚠️ 账号 {index} {msg} (code={rcode})")
        lines.append(f"⚠️ {msg}")
        return "\n".join(lines), False
    if rcode != SUCCESS_CODE:
        raw_msg = result.get("message") or result.get("msg") or ""
        if POOL_GATE_HINT in raw_msg:            # 选池后仍报门槛(异常), 转为可读上报
            print(f"⚠️ 账号 {index} {POOL_GATE_MSG}")
            lines.append(f"⚠️ {POOL_GATE_MSG}")
            return "\n".join(lines), False
        msg = raw_msg or f"签到失败 code={rcode}"
        print(f"❌ 账号 {index} {msg}")
        lines.append(f"❌ {msg}")
        return "\n".join(lines), False

    rentity = envelope_entity(result)
    total = rentity.get("signInTotal")
    chances = rentity.get("chanceList") or []
    msg = "签到成功"
    if total is not None:
        msg += f", 连续签到 {total} 天"
    if chances:
        msg += f", 获得 {len(chances)} 次抽奖机会(请在小程序内手动抽奖)"
    print(f"🎉 账号 {index} {msg}")
    lines.append(f"🎉 {msg}")
    return "\n".join(lines), True


def main():
    raw = os.getenv("bjhqbwz", "")
    accounts = [x.strip() for x in raw.replace("&", "\n").splitlines() if x.strip()]

    if not accounts:
        print("❌ 未检测到账号信息(环境变量 bjhqbwz), 退出。")
        return
    if not WX_AUTH:
        print("❌ 未配置 wx_auth, 无法获取 code, 退出。")
        return

    print("=============== 北京环球 签到开始 ===============")
    summaries = []
    ok_count = 0
    for i, entry in enumerate(accounts, 1):
        parts = entry.split("#", 1)
        account = parts[0].strip()
        remark = parts[1].strip() if len(parts) > 1 else ""
        print(f"\n-------------- 账号 {i}{('/' + remark) if remark else ''} --------------")
        try:
            summary, ok = run_account(account, i)
            summaries.append(summary)
            ok_count += 1 if ok else 0
        except Exception as e:
            print(f"❌ 账号 {i} 执行异常: {e}")
            summaries.append(f"【账号 {i}】\n❌ 执行异常: {e}")
        time.sleep(1)

    print("\n=============== 北京环球 签到结束 ===============")
    title = f"北京环球签到 {ok_count}/{len(accounts)} 成功"
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
    _yyb_os.environ["bjhqbwz"] = "\n".join(_yyb_accts)

# === end YYB 兼容层 ===


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
    _yyb_os.environ["bjhqbwz"] = "\n".join(_yyb_accts)

# === end YYB 兼容层 ===

if __name__ == "__main__":
    main()


# ============================================================
# YYB-Go 兼容层 (auto-appended)
# ============================================================
import os as _yyb_os
import json as _yyb_json

_YWB_SERVER = "172.23.0.2:8000"

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


# ============================================================
# YYB-Go 兼容层 (auto-appended)
# ============================================================
import os as _yyb_os
import json as _yyb_json

_YWB_SERVER = "172.23.0.2:8000"

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
