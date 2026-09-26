#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JD_WSCK 转换：把 wskey 转成可用 pt_key Cookie，并写回青龙环境变量。

来源：逆向 hhaijdapp APK 得到公开转换接口
  POST https://wskey.djun97.top/convert
  body: {"wsck": "pin=jd_xxx;wskey=AAxxxxx;"}
  resp: {"success":true,"message":"JD_WSCK转换成功",
         "cookie":"pt_key=app_openxxx;pt_pin=jd_xxx;","token_key":"AAxxxxx"}

用法（青龙内）：
  1) 在青龙新建环境变量 JD_WSCK，值格式：pin=jd_xxx;wskey=AAxxxxx;
  2) 本脚本读取 JD_WSCK -> 调接口转换 -> 把得到的 cookie 写回同名 pin 的 JD_COOKIE
  3) 配合定时任务每天跑，cookie 永不过期

也可命令行直接跑：
  python3 wsck_convert.py --wsck "pin=jd_xxx;wskey=AAxxx;" --write
"""
import os
import re
import sys
import json
import time
import sqlite3
import urllib.request
import urllib.error

CONVERT_URL = "https://wskey.djun97.top/convert"
BATCH_URL = "https://wskey.djun97.top/convert/batch"
QL_DB = os.environ.get(
    "QL_DB", "/root/docker/ql/data/db/database.sqlite"
)


def http_post_json(url, payload, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def convert_one(wsck):
    """wsck: 'pin=xxx;wskey=yyy;' -> dict"""
    r = http_post_json(CONVERT_URL, {"wsck": wsck})
    return r


def ql_get_envs(db=QL_DB):
    """返回 [(id, name, value), ...]"""
    if not os.path.exists(db):
        print(f"[warn] 数据库不存在: {db}")
        return []
    con = sqlite3.connect(db)
    try:
        cur = con.execute("SELECT id,name,value FROM Envs")
        return cur.fetchall()
    finally:
        con.close()


def ql_set_value(env_id, value, db=QL_DB):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = f"{db}.bak_wsck_{ts}"
    try:
        import shutil
        shutil.copy2(db, bak)
        print(f"[backup] {bak}")
    except Exception as e:
        print(f"[warn] 备份失败: {e}")
    con = sqlite3.connect(db)
    try:
        con.execute("UPDATE Envs SET value=? WHERE id=?", (value, env_id))
        con.commit()
        return True
    finally:
        con.close()


def main():
    wsck = None
    do_write = False
    # 命令行参数
    if "--wsck" in sys.argv:
        wsck = sys.argv[sys.argv.index("--wsck") + 1]
    if "--write" in sys.argv:
        do_write = True

    targets = []
    if wsck:
        targets.append(("cli", wsck))
    else:
        # 从青龙环境变量读 JD_WSCK
        envs = ql_get_envs()
        for _id, name, value in envs:
            if name == "JD_WSCK" and value:
                targets.append((_id, value.strip()))
        if not targets:
            print("[info] 未找到 JD_WSCK 环境变量，也未传 --wsck，退出")
            return 0

    for src, wsck_str in targets:
        m = re.search(r"pin=([^;\s]+)", wsck_str)
        pin = m.group(1) if m else "?"
        print(f"\n=== 转换 {pin} ===")
        try:
            r = convert_one(wsck_str)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            print(f"[fail] HTTP {e.code}: {body[:300]}")
            continue
        except Exception as e:
            print(f"[fail] {e}")
            continue

        if not r.get("success"):
            print(f"[fail] {r.get('message') or r}")
            continue

        cookie = r.get("cookie", "")
        print(f"[ok] {r.get('message')}")
        print(f"[cookie] {cookie}")
        if r.get("token_key"):
            print(f"[token_key] {r['token_key'][:16]}...")

        if not do_write or not cookie:
            continue

        # 找到同 pin 的 JD_COOKIE 写回
        envs = ql_get_envs()
        hit = None
        for _id, name, value in envs:
            if name == "JD_COOKIE" and value and f"pt_pin={pin}" in value:
                hit = _id
                break
        if hit is None:
            print(f"[warn] 青龙中未找到 pt_pin={pin} 的 JD_COOKIE，跳过写入")
            continue
        if ql_set_value(hit, cookie):
            print(f"[WRITE_OK] 已写入 JD_COOKIE id={hit} pin={pin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
