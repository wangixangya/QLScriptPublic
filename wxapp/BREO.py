#by:哆啦A梦
#入口:http://mx.qrurl.net/h5/wxa/link?sid=26407uif5Oq
#BREO变量填写wx_server里的openid/账号标识，多账号换行分割
#需要配置wx_server_url、wx_auth，用于获取wx.login code
#账号变量名:BREO
#new Env("BREO")
#cron 8 9,10,11 * * *


import requests
import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MINI_APP_ID = "wx61457400e4212cec"
WX_SERVER_URL = os.getenv("wx_server_url", "http://172.23.0.2:8000").rstrip("/")
WX_AUTH = os.getenv("wx_auth", "")
TOKEN_CACHE_PATH = Path(__file__).with_name("BREO_token_cache.json")
LOGIN_BASE = "https://breoplus.breo.cn/app/minic"
APP_BASE = "https://breoplus.breo.cn/breo-app"
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF"

session = requests.Session()

def read_token_cache():
    try:
        if not TOKEN_CACHE_PATH.exists():
            return {}
        return json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def write_token_cache(cache):
    try:
        TOKEN_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"⚠️ 写入token缓存失败: {e}")

def mask_token(token):
    if not token:
        return ""
    return f"{token[:6]}***{token[-6:]}"

def is_success(result):
    return result.get("success") is True or str(result.get("code")) in ("0000", "200", "200.0")

def is_token_error(message):
    text = str(message)
    return any(key in text for key in ["40101", "40102", "token", "登录", "授权", "过期", "失效"])

def wx_headers():
    return {
        "auth": WX_AUTH,
        "User-Agent": DEFAULT_UA,
        "Content-Type": "application/json",
    }

def app_headers(token=None):
    headers = {
        "User-Agent": DEFAULT_UA,
        "content-Type": "application/json",
        "Content-Type": "application/json",
        "deviceInfo": "{}",
        "Referer": "https://servicewechat.com/wx61457400e4212cec/390/page-frame.html",
    }
    if token:
        headers["token"] = token
    return headers

def breo_task_headers(token):
    return {
        "token": token,
        "device-type": "Xiaomi",
        "device-version": "10",
        "channel": "Breo",
        "version_code": "30201",
        "version": "3.2.1",
        "encrypt": "1",
        "Content-Type": "application/json; charset=UTF-8",
        "Referer": "https://servicewechat.com/wx61457400e4212cec/390/page-frame.html",
        "User-Agent": DEFAULT_UA,
    }

def get_wx_code(account_id):
    if not WX_AUTH:
        raise RuntimeError("缺少wx_auth，无法从wx_server获取code")
    resp = session.post(
        f"{WX_SERVER_URL}/wx/code",
        json={"appid": MINI_APP_ID, "openid": account_id},
        headers=wx_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    code = data.get("code") or (data.get("data") or {}).get("code")
    if not code:
        raise RuntimeError(f"wx_server未返回code: {data}")
    return code

def login_with_code(account_id):
    code = get_wx_code(account_id)
    login_resp = session.get(
        f"{LOGIN_BASE}/login/{code}",
        headers=app_headers(),
        timeout=30,
    )
    login_resp.raise_for_status()
    login_data = login_resp.json()
    if str(login_data.get("code")) != "200" or not login_data.get("data"):
        raise RuntimeError(f"code登录失败: {login_data}")
    user_info = login_data["data"]
    uid = user_info.get("uid")
    open_id = user_info.get("openId")
    union_id = user_info.get("unionId")
    if not uid:
        raise RuntimeError(f"登录响应缺少uid: {login_data}")

    token_resp = session.post(
        f"{APP_BASE}/customer/loginByUid",
        json={"uid": uid, "openId": open_id, "unionId": union_id},
        headers=app_headers(),
        timeout=30,
    )
    token_resp.raise_for_status()
    token_data = token_resp.json()
    if not is_success(token_data) or not (token_data.get("result") or {}).get("token"):
        raise RuntimeError(f"业务token登录失败: {token_data}")
    return {
        "token": token_data["result"]["token"],
        "uid": uid,
        "openId": open_id,
        "unionId": union_id,
        "userInfo": user_info,
        "customer": token_data.get("result", {}),
        "updatedAt": int(time.time()),
    }

def get_cached_token(account_id):
    return read_token_cache().get(account_id)

def save_cached_token(account_id, auth_info):
    cache = read_token_cache()
    cache[account_id] = auth_info
    write_token_cache(cache)

def remove_cached_token(account_id):
    cache = read_token_cache()
    if account_id in cache:
        del cache[account_id]
        write_token_cache(cache)

def validate_token(token):
    try:
        resp = session.post(
            f"{APP_BASE}/getUserLevelInfoByUid",
            headers=app_headers(token),
            timeout=15,
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        if is_success(data):
            return True
        return not is_token_error(data)
    except Exception:
        return False

def get_token_for_account(account_id, index):
    cached = get_cached_token(account_id)
    if cached and cached.get("token"):
        print(f"账号 {index} 使用缓存token: {mask_token(cached['token'])}")
        if validate_token(cached["token"]):
            return cached["token"]
        print(f"账号 {index} 缓存token失效，重新登录")
        remove_cached_token(account_id)

    auth_info = login_with_code(account_id)
    save_cached_token(account_id, auth_info)
    user_info = auth_info.get("userInfo") or {}
    print(f"账号 {index} code登录成功: {user_info.get('nickname') or user_info.get('telephone') or auth_info.get('uid')}")
    return auth_info["token"]

def get_random_one_word():
    try:
        response = requests.get("https://uapis.cn/api/say")
        if response.status_code == 200:
            return response.text.strip()
        else:
            return "无法获取一言"
    except Exception as e:
        print(f"获取一言时出错: {e}")
        return "无法获取一言"

def get_proclamation():
    primary_url = "https://github.com/3288588344/toulu/raw/refs/heads/main/tl.txt"
    backup_url = "https://tfapi.cn/TL/tl.json"
    try:
        response = requests.get(primary_url, timeout=10)
        if response.status_code == 200:
            print("\n" + "=" * 50)
            print("📢 公告信息")
            print("=" * 35)
            print(response.text)
            print("=" * 35 + "\n")
            print("公告获取成功，开始执行任务...\n")
            return
    except requests.exceptions.RequestException as e:
        print(f"获取公告时发生错误: {e}, 尝试备用链接...")

    try:
        response = requests.get(backup_url, timeout=10)
        if response.status_code == 200:
            print("\n" + "=" * 50)
            print("📢 公告信息")
            print("=" * 35)
            print(response.text)
            print("=" * 35 + "\n")
            print("公告获取成功，开始执行任务...\n")
        else:
            print(f"⚠️ 获取公告失败，状态码: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ 获取公告时发生错误: {e}, 可能是网络问题或链接无效。")

def post_to_breo(token, content, title):
    url = "https://breoplus.breo.cn/breo-app/communityBaseInfo/releasePost"
    headers = breo_task_headers(token)
    data = {
        "anonymoused": 1,
        "content": content,
        "expressText": "",
        "images": [],
        "subTitle": "",
        "title": title,
        "topicText": ""
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                print("✅ 发帖成功！")
                print(f"帖子 ID: {result['result']['id']}")
                print(f"帖子标题: {result['result']['title']}")
                return result["result"]["id"]
            else:
                print(f"❌ 发帖失败，错误信息：{result.get('message', '未知错误')}")
                return None
        else:
            print(f"❌ 请求失败，状态码：{response.status_code}")
            return None
    except Exception as e:
        print(f"❌ 请求错误: {e}")
        return None

def collect_post(token, post_id):
    url = "https://breoplus.breo.cn/breo-app/communityBaseInfo/collect"
    headers = breo_task_headers(token)
    data = {
        "postId": post_id
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                print("✅ 收藏成功！")
                reward = result.get("result") or {}
                print(f"获得点数: {reward.get('point', 0)}")
                print(f"成长值: {reward.get('grow', 0)}")
            else:
                print(f"❌ 收藏失败，错误信息：{result.get('message', '未知错误')}")
        else:
            print(f"❌ 请求失败，状态码：{response.status_code}")
    except Exception as e:
        print(f"❌ 请求错误: {e}")

def comment_post(token, post_id):
    for _ in range(2):  # 评论2次
        comment_content = get_random_one_word()  # 使用随机一言作为评论内容
        url = "https://breoplus.breo.cn/breo-app/communityBaseInfo/comment"
        headers = breo_task_headers(token)
        data = {
            "anonymoused": 0,
            "commentText": comment_content,
            "postId": post_id
        }
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            if response.status_code == 200:
                result = response.json()
                if result.get("success", False):
                    print("✅ 评论成功！")
                    reward = result.get("result") or {}
                    root = reward.get("rootOutVO") or {}
                    print(f"评论内容: {root.get('commentText', comment_content)}")
                    print(f"获得点数: {reward.get('point', 0)}")
                    print(f"成长值: {reward.get('grow', 0)}")
                else:
                    print(f"❌ 评论失败，错误信息：{result.get('message', '未知错误')}")
            else:
                print(f"❌ 请求失败，状态码：{response.status_code}")
        except Exception as e:
            print(f"❌ 请求错误: {e}")
        time.sleep(1)  # 避免频繁请求

def browse_mall(token):
    url = "https://breoplus.breo.cn/breo-app/user/po-task-info/mall"
    headers = breo_task_headers(token)
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                print("✅ 浏览商城成功！")
                reward = result.get("result") or {}
                print(f"获得点数: {reward.get('point', 0)}")
                print(f"成长值: {reward.get('grow', 0)}")
            else:
                print(f"❌ 浏览商城失败，错误信息：{result.get('message', '未知错误')}")
        else:
            print(f"❌ 请求失败，状态码：{response.status_code}")
    except Exception as e:
        print(f"❌ 请求错误: {e}")

def punch_in(token):
    url = "https://breoplus.breo.cn/breo-app/user/po-task-info/punch"
    headers = breo_task_headers(token)
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                print("✅ 签到成功！")
                reward = result.get("result") or {}
                print(f"获得点数: {reward.get('point', 0)}")
                print(f"成长值: {reward.get('grow', 0)}")
            else:
                print(f"❌ 签到失败，错误信息：{result.get('message', '未知错误')}")
        else:
            print(f"❌ 请求失败，状态码：{response.status_code}")
    except Exception as e:
        print(f"❌ 请求错误: {e}")


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
    _yyb_os.environ["BREO"] = "\n".join(_yyb_accts)

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
    _yyb_os.environ["BREO"] = "\n".join(_yyb_accts)

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
    _yyb_os.environ["BREO"] = "\n".join(_yyb_accts)

# === end YYB 兼容层 ===

if __name__ == "__main__":
    # 获取公告
    #get_proclamation()

    # 从环境变量读取 wx_server 账号标识/openid
    accounts = [item.strip() for item in os.getenv("BREO", "").replace("&", "\n").splitlines() if item.strip()]

    if not accounts:
        print("❌ 未检测到 账号信息，退出脚本。")
    else:
        skip_community = os.getenv("BREO_SKIP_COMMUNITY", "").lower() in ("1", "true", "yes")
        print("=============== 开始执行任务 ===============")
        for i, account in enumerate(accounts, 1):
            print(f"\n-------------- 账号 {i} 开始 --------------")
            try:
                token = get_token_for_account(account, i)
            except Exception as e:
                print(f"❌ 账号 {i} 登录失败: {e}")
                continue

            print("🚀 正在签到...")
            punch_in(token)

            if skip_community:
                print("\n📝 已跳过发帖/收藏/评论任务")
            else:
                print("\n📝 正在发布帖子...")
                post_id = post_to_breo(token, "这是一个自动发布的帖子", "自动化测试")
                if post_id:
                    print("\n⭐ 正在收藏帖子...")
                    collect_post(token, post_id)

                    print("\n💬 正在评论帖子...")
                    comment_post(token, post_id)
                else:
                    print("❌ 发帖失败，跳过后续操作。")

            print("\n🛒 正在浏览商城...")
            browse_mall(token)

            print(f"-------------- 账号 {i} 结束 --------------")

        print("\n=============== 所有任务执行完毕 ===============")


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
