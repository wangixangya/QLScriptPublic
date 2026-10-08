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
    
    with open(dst_file, 'w', encoding='utf-8') as f:
        f.write(content)
    return dst_file

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
