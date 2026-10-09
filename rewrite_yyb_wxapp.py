#!/usr/bin/env python3
"""
批量改写 QLScriptPublic/wxapp/ 脚本为 YYB-Go 兼容版本
"""
import os, re, shutil, glob

SRC_DIR = "/root/QLScriptPublic/wxapp"
DST_DIR = "/root/yyb-go/scripts/yyb_wxapp"
YWB_SERVER = "yyb-go:8000"

def ensure_dirs():
    os.makedirs(DST_DIR, exist_ok=True)

def process_js(src_file):
    """改写 JS 脚本的 wcs.js 引用和端口"""
    dst_file = os.path.join(DST_DIR, os.path.basename(src_file))
    with open(src_file, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    # 修改默认 URL: 8787 -> 8000 yyb-go
    content = content.replace('http://192.168.31.196:8787', 'http://' + YWB_SERVER)
    content = content.replace('"8787"', '"8000"')

    # 部署目录是扁平的 (yyb_wxapp/), require 路径必须相对当前文件解析:
    #   ../wxapp/X  -> ./X   (wcs.js 等已拷贝到同级)
    #   ../tools/X  -> ./X   (env.js / sendNotify.js 同上)
    # 不改写会导致 Node 报 Cannot find module '../wxapp/wcs.js' (见 2026-09-17 植白说任务失败).
    content = re.sub(r'require\("\.\./wxapp/([^"]+)"\)', r'require("./\1")', content)
    content = re.sub(r'require\("\.\./tools/([^"]+)"\)', r'require("./\1")', content)

    # === YYB 依赖兜底注入 (幂等) ===
    # 上游脚本常漏 require path/fs，以及漏定义 readCache/writeCache，
    # 导致运行时 'path is not defined' / 'readCache is not defined'。
    # 每日同步会 rm -rf 整个 yyb_wxapp 再 cp，手动改容器文件会被覆盖，
    # 因此在此处(真源)注入，每次同步自动带正确依赖。
    content = fix_wx_endpoint(content)
    content = inject_dependency_shims(content)

    with open(dst_file, 'w', encoding='utf-8') as f:
        f.write(content)
    return dst_file


def fix_wx_endpoint(content):
    """把"调 /wx/getuserinfo 却从中取登录 code"的脚本改成 /wx/code。

    yyb-go 两个端点返回不同:
      /wx/code        -> data.result.code   (真正的微信登录 code)
      /wx/getuserinfo -> data.user_info     (只有用户信息, 不含 code)
    部分上游脚本调 getuserinfo 却要 code, 永远取不到 -> "获取code失败"。

    注意: 取码语句可能写在 ajax 调用之前(函数式 .then 写法),
    因此这里在全文件范围判定并替换, 不依赖局部位置。
    """
    uses_wx = ("/wx/getuserinfo" in content) or ("/wx/code" in content)
    if not uses_wx:
        return content

    # 该文件是否真的"取 code"(而非只要 user_info)
    takes_code = bool(re.search(r"\bconst\s+code\s*=|\blet\s+code\s*=|\bcode\s*\|\||result\.code", content))
    if not takes_code:
        return content
    # 已经能取到 result.code 的不动
    if "data?.data?.result?.code" in content or "result?.result?.code" in content:
        return content

    out = content.replace("/wx/getuserinfo", "/wx/code")
    # 取码路径: data.data?.code / data.data.code / data?.data?.code -> data?.data?.result?.code
    if "data?.data?.result?.code" in out:
        return out
    out = re.sub(r"(?<![?.\w])data\??\.data\??\.code\b", "data?.data?.result?.code || data?.data?.code", out)
    out = re.sub(r"(?<![?.\w])data\.code\b", "data?.data?.result?.code || data?.code", out, count=1)
    return out


def inject_dependency_shims(content):
    """为 JS 脚本幂等注入 ref 拦截器 / path,fs require / readCache,writeCache 兜底。

    注意: 每一项独立判断、独立幂等, 不允许"marker 存在就整体早退"——
    否则历史上注入过残缺 shim(如 cache 用了 path 却没 require)的文件将永远无法自愈。
    """
    dep_marker = "// === YYB dependency shim ==="
    ref_marker = "// === YYB ref auto-inject ==="

    additions = []   # 本次需要新增的代码片段

    # ---- 0) 取码请求缺 ref ----
    # yyb-go 后端升级后 /wx/code 与 /wx/getuserinfo 强制要求 body 带 ref(账号 token)。
    # 后端仅用 ref 选账号, openid 字段被忽略; 但多账号共用同一 endpoint,
    # 必须按每个 openid(=账号整行 server@ref) 里的 @ref 精确取, 否则串号。
    # 用 axios 拦截器统一补, 不改任何业务代码。
    uses_wx_ep = re.search(r'/wx/(?:code|getuserinfo)', content) is not None
    uses_axios = re.search(r'require\(\s*["\']axios["\']\s*\)', content) is not None
    already_sends_ref = bool(re.search(r'\bref\s*[:=]', content)) or ref_marker in content
    need_ref = uses_wx_ep and uses_axios and not already_sends_ref
    if need_ref:
        additions.append("""
// === YYB ref auto-inject ===
// yyb-go 后端 /wx/code 与 /wx/getuserinfo 要求 body 带 ref(账号 token)。
// openid 在 YYB 模式下是账号整行 "server@ref", 从 @ 后取 ref 精确注入(避免串号)。
try {
    const _yybAxios = require("axios");
    if (_yybAxios && _yybAxios.defaults && !_yybAxios.defaults.__yybRefPatched) {
        _yybAxios.defaults.__yybRefPatched = true;
        const _yybRefOf = (v) => {
            const s = String(v || "");
            const at = s.lastIndexOf("@");
            return at >= 0 ? s.slice(at + 1).trim() : "";
        };
        const _yybPatch = (cfg) => {
            try {
                const url = String((cfg && cfg.url) || "");
                if (url.indexOf("/wx/code") >= 0 || url.indexOf("/wx/getuserinfo") >= 0) {
                    const d = cfg.data;
                    if (d && typeof d === "object" && !d.ref) {
                        const ref = _yybRefOf(d.openid || d.openId || d.id || d.account);
                        if (ref) d.ref = ref;
                        // /wx/code 要求 app_id(下划线), 上游脚本普遍写成 appid
                        if (!d.app_id && (d.appid || d.appId)) d.app_id = d.appid || d.appId;
                    } else if (typeof d === "string" && d.indexOf("ref") < 0) {
                        const obj = JSON.parse(d);
                        const ref = _yybRefOf(obj.openid || obj.openId || obj.id || obj.account);
                        if (ref) { obj.ref = ref; cfg.data = JSON.stringify(obj); }
                        if (!obj.app_id && (obj.appid || obj.appId)) { obj.app_id = obj.appid || obj.appId; cfg.data = JSON.stringify(obj); }
                    }
                }
            } catch (e) {}
            return cfg;
        };
        if (_yybAxios.interceptors && _yybAxios.interceptors.request) {
            _yybAxios.interceptors.request.use(_yybPatch);
        }
        if (typeof _yybAxios.create === "function") {
            const _origCreate = _yybAxios.create.bind(_yybAxios);
            _yybAxios.create = function () {
                const inst = _origCreate.apply(null, arguments);
                try { if (inst.interceptors && inst.interceptors.request) inst.interceptors.request.use(_yybPatch); } catch (e) {}
                return inst;
            };
        }
    }
} catch (e) {}
// === end YYB ref auto-inject ===
""")

    # ---- 1) 缺 require path / fs ----
    # 注意: 注入的 cache shim 自身会用 path./fs., 因此这里必须先看"注入后"的需求。
    # 注意: 上游单/双引号混用, 且可能是 const fs = require('fs') 之外的声明方式,
    # 这里用"是否已声明该标识符"判定, 避免重复注入导致 SyntaxError。
    def _declared(name):
        return bool(re.search(r'(?:const|let|var)\s+' + name + r'\s*[=:]', content)) or bool(
            re.search(r'require\(\s*["\']' + name + r'["\']\s*\)', content))
    needs_path = bool(re.search(r'(?<![.\w])path\.', content)) and not _declared('path')
    needs_fs = bool(re.search(r'(?<![.\w])fs\.', content)) and not _declared('fs')

    # ---- 2) 调用 readCache/writeCache 但未定义 ----
    cache_func_re = re.compile(r'(?:function\s+(readCache|writeCache)|const\s+(readCache|writeCache)\s*=|(readCache|writeCache)\s*[:=]\s*function|require\(["\'][^"\']*cache[^"\']*["\']\))')
    uses_cache = bool(re.search(r'(?<![.\w])readCache\s*\(', content)) or bool(re.search(r'(?<![.\w])writeCache\s*\(', content))
    defined_cache = bool(cache_func_re.search(content))
    need_cache_shim = uses_cache and not defined_cache
    if need_cache_shim:
        needs_path = True   # cache shim 用 path.join / fs
        needs_fs = True

    dep_lines = []
    if need_cache_shim:
        # 关键: require 必须排在 cache 函数之前
        dep_lines.append('const path = require("path");')
        dep_lines.append('const fs = require("fs");')
        dep_lines.append("""
const _yybCacheFile = path.join(__dirname, "_yyb_cache.json");
function readCache() {
    try { return JSON.parse(fs.readFileSync(_yybCacheFile, "utf8")); }
    catch (e) { return {}; }
}
function writeCache(obj) {
    try { fs.writeFileSync(_yybCacheFile, JSON.stringify(obj, null, 2)); } catch (e) {}
}
""")
    else:
        if needs_path:
            dep_lines.append('const path = require("path");')
        if needs_fs:
            dep_lines.append('const fs = require("fs");')

    if dep_lines and dep_marker not in content:
        additions.append("\n" + dep_marker + "\n" + "\n".join(dep_lines) + "\n")

    if not additions:
        return content

    shim = "\n" + "\n".join(additions)
    # 插到文件顶部第一个 require 行之后 (require 必须在任何使用之前)
    first_req = re.search(r'require\(', content)
    if first_req:
        pos = content.find("\n", first_req.start())
        content = content[:pos + 1] + shim + content[pos + 1:]
    else:
        content = shim + content
    return content


def process_js_fallback(src_file):
    """为 JS 脚本添加 YYB_SERVER 回退"""
    dst_file = os.path.join(DST_DIR, os.path.basename(src_file))
    with open(dst_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # YYB 回退代码
    yyb_code = '\n// === YYB-Go 兼容层 ===\n'
    yyb_code += 'if (!$.userCount) {\n'
    yyb_code += '    const yybServers = (process.env.YYB_SERVER || "").split(/\\r?\\n/).map(s => s.trim()).filter(Boolean);\n'
    yyb_code += '    if (yybServers.length) {\n'
    yyb_code += '        $.userList = yybServers;\n'
    yyb_code += '        $.userCount = yybServers.length;\n'
    yyb_code += '        $.log("YYB-Go: 加载了 " + yybServers.length + " 个账号");\n'
    yyb_code += '    }\n'
    yyb_code += '}\n'
    
    # 在 $.checkEnv(ckName) 后注入（幂等：已注入则跳过）
    if "// === YYB-Go 兼容层 ===" in content:
        print(f"  已注入，跳过: {os.path.basename(src_file)}")
        return
    pattern = r'(\$\s*\.\s*checkEnv\([^)]+\);)'
    match = re.search(pattern, content)
    if match:
        insert_pos = match.end()
        content = content[:insert_pos] + yyb_code + content[insert_pos:]
    else:
        print(f"  未找到 checkEnv，跳过: {os.path.basename(src_file)}")
        return
    
    with open(dst_file, 'w', encoding='utf-8') as f:
        f.write(content)

def get_yyb_layer():
    """生成 Python YYB 兼容层代码"""
    server = YWB_SERVER
    return '''

# ============================================================
# YYB-Go 兼容层 (auto-appended)
# ============================================================
import os as _yyb_os
import json as _yyb_json

_YWB_SERVER = "%s"

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
''' % server

def process_python(src_file):
    """为 Python 脚本追加 YYB 兼容层"""
    dst_file = os.path.join(DST_DIR, os.path.basename(src_file))
    with open(src_file, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    layer = get_yyb_layer()
    with open(dst_file, 'w', encoding='utf-8') as f:
        f.write(content + layer)
    return dst_file

def main():
    ensure_dirs()
    
    # 1. Copy tools
    env_src = "/root/QLScriptPublic/tools/env.js"
    if os.path.exists(env_src):
        shutil.copy(env_src, os.path.join(DST_DIR, "env.js"))
        print("Copied env.js")
    
    notify_src = "/root/QLScriptPublic/sendNotify.js"
    if os.path.exists(notify_src):
        shutil.copy(notify_src, os.path.join(DST_DIR, "sendNotify.js"))
        print("Copied sendNotify.js")
    
    # 2. Process JS scripts
    js_files = sorted(glob.glob(os.path.join(SRC_DIR, "*.js")))
    js_files = [f for f in js_files if os.path.basename(f) != "wcs.js"]
    print("\nProcessing %d JS scripts..." % len(js_files))
    for js_file in js_files:
        try:
            process_js(js_file)
            process_js_fallback(js_file)
            print("  OK %s" % os.path.basename(js_file))
        except Exception as e:
            print("  FAIL %s: %s" % (os.path.basename(js_file), e))
    
    # 3. Process Python scripts
    py_files = sorted(glob.glob(os.path.join(SRC_DIR, "*.py")))
    print("\nProcessing %d Python scripts..." % len(py_files))
    for py_file in py_files:
        try:
            process_python(py_file)
            print("  OK %s" % os.path.basename(py_file))
        except Exception as e:
            print("  FAIL %s: %s" % (os.path.basename(py_file), e))
    
    # 4. Create README
    readme = """# YYB-Go 兼容版微信小程序脚本

基于 smallfawn/QLScriptPublic/wxapp 改写，兼容 YYB-Go 协议服务。

## 环境变量

### YYB_SERVER (必填)
格式: endpoint@ref, 每行一个账号
```
yyb-go:8000@openid1
yyb-go:8000@openid2
```

### YYB_API_KEY (可选)
协议接口鉴权密钥

### CODE_SERVER (可选, 旧版兼容)
不使用 YYB_SERVER 时生效

## 部署
青龙任务路径: task yyb_wxapp/脚本名.js
"""
    with open(os.path.join(DST_DIR, "README.md"), 'w', encoding='utf-8') as f:
        f.write(readme)
    
    print("\nDone! %d JS + %d Python scripts rewritten" % (len(js_files), len(py_files)))

if __name__ == "__main__":
    main()
