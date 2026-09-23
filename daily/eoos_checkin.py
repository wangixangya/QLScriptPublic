# -*- coding: utf-8 -*-
"""
name: EOOS Emby 签到
cron: 30 8,20 * * *
"""

"""
EOOS Emby 管理站每日签到脚本
站点: https://eoos.top
验证方式: Cap.js PoW (SHA-256 工作量证明)
签到流程: 登录 → 查状态 → 获取challenge → 算PoW → redeem → 签到

环境变量:
  EOOS_ACCOUNTS - 多账号配置，& 分隔多账号，每个格式: 用户名#密码
                  示例: user1#password1&user2#password2
  EOOS_USER     - 单账号用户名（兼容旧配置）
  EOOS_PASS     - 单账号密码（兼容旧配置）
"""

import os
import sys
import json
import time
import hashlib
import requests
from datetime import datetime

SITE_URL = "https://eoos.top"

def load_accounts():
    """加载账号列表，支持多账号(&分隔)和单账号(EOOS_USER/EOOS_PASS)"""
    accounts_str = os.getenv("EOOS_ACCOUNTS", "")
    accounts = []
    if accounts_str:
        for item in accounts_str.split("&"):
            item = item.strip()
            if not item:
                continue
            if "#" in item:
                user, pwd = item.split("#", 1)
                accounts.append((user.strip(), pwd.strip()))
    # 兼容单账号模式
    if not accounts:
        user = os.getenv("EOOS_USER", "")
        pwd = os.getenv("EOOS_PASS", "")
        if user and pwd:
            accounts.append((user, pwd))
    return accounts

HEADERS = {
    "Content-Type": "application/json",
    "Origin": SITE_URL,
    "Referer": f"{SITE_URL}/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def fnv1a_hash(s):
    """FNV-1a 32-bit hash (cap.js d function)"""
    h = 2166136261
    for c in s:
        h ^= ord(c)
        h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) & 0xFFFFFFFF
    return h


def cap_d(prefix, length):
    """cap.js d() function: deterministic hex string from prefix"""
    seed = fnv1a_hash(prefix)
    s = ""
    state = seed
    while len(s) < length:
        # xorshift32
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= (state >> 17) & 0xFFFFFFFF
        state ^= (state << 5) & 0xFFFFFFFF
        s += format(state, '08x')
    return s[:length]


def login(session, username, password):
    resp = session.post(
        f"{SITE_URL}/api/auth/login",
        headers=HEADERS,
        json={"userName": username, "password": password},
        timeout=15,
    )
    data = resp.json()
    if "token" not in data:
        raise Exception(f"登录失败: {data.get('message', resp.text)}")
    token = data["token"]
    user = data.get("user", {})
    log(f"[{username}] 登录成功 | 余额: {user.get('rCoin', '?')} RCoin")
    return token


def get_checkin_status(session, token):
    resp = session.get(
        f"{SITE_URL}/api/checkin/status",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        timeout=15,
    )
    data = resp.json()
    if data.get("hasCheckedInToday"):
        log(f"今日已签到，获得 {data.get('amount', '?')} {data.get('currencyUnit', 'RCoin')}")
        return True
    return False


def get_challenge(session, token):
    """获取 Cap PoW challenge"""
    resp = session.post(
        f"{SITE_URL}/api/cap/challenge",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        json={"action": "checkin"},
        timeout=15,
    )
    return resp.json()


def solve_pow(salt, target):
    """解 PoW: 找 nonce 使 SHA256(salt + nonce_str) 前段匹配 target hex
    
    cap.js 算法:
    - target 是 hex 字符串 (如 "4a3f")
    - o = 4 * target.length  (总 bits)
    - a = o // 8  (完整字节数)
    - l = o % 8   (剩余 bits)
    - hash = SHA256(salt + str(nonce))
    - 检查 hash 前 a 字节 == target 前 a 字节
    - 如果 l > 0，检查 hash[a] 的前 l 位 == target[a] 的前 l 位
    """
    target_bytes = bytes.fromhex(target if len(target) % 2 == 0 else target + "0")
    full_bytes = len(target) * 4 // 8  # 完整匹配字节数
    rem_bits = (len(target) * 4) % 8   # 剩余 bits
    
    if rem_bits > 0:
        mask = (0xFF << (8 - rem_bits)) & 0xFF
    else:
        mask = 0
    
    for nonce in range(0, 50000000):
        data = f"{salt}{nonce}"
        h = hashlib.sha256(data.encode()).digest()
        
        match = True
        for i in range(full_bytes):
            if h[i] != target_bytes[i]:
                match = False
                break
        
        if match and rem_bits > 0:
            if (h[full_bytes] & mask) != (target_bytes[full_bytes] & mask):
                match = False
        
        if match:
            return nonce
        
        if nonce % 1000000 == 0 and nonce > 0:
            log(f"  PoW 计算中... 已尝试 {nonce}")
    
    return None


def solve_challenges(session, token, challenge_data):
    """解所有 challenge，返回 solutions 数组"""
    cap_token = challenge_data["token"]
    ch = challenge_data["challenge"]
    c = ch["c"]  # challenge 数量
    s = ch["s"]  # salt 长度
    d = ch["d"]  # target 长度
    
    log(f"PoW 参数: {c} challenges, salt_len={s}, target_len={d}")
    
    solutions = []
    for i in range(1, c + 1):
        salt = cap_d(f"{cap_token}{i}", s)
        target = cap_d(f"{cap_token}{i}d", d)
        
        log(f"  challenge {i}/{c}: target={target[:8]}...")
        nonce = solve_pow(salt, target)
        
        if nonce is None:
            raise Exception(f"challenge {i} PoW 求解失败")
        
        log(f"  challenge {i} 解出: nonce={nonce}")
        solutions.append(nonce)
    
    return solutions


def redeem(session, token, cap_token, solutions):
    """提交 PoW 解决方案，获取验证 token"""
    resp = session.post(
        f"{SITE_URL}/api/cap/redeem",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        json={"token": cap_token, "solutions": solutions},
        timeout=15,
    )
    return resp.json()


def do_checkin(session, token, verification_token):
    """执行签到"""
    resp = session.post(
        f"{SITE_URL}/api/checkin",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        json={"verificationToken": verification_token},
        timeout=15,
    )
    return resp.json()


def checkin_one(username, password):
    """单个账号签到流程"""
    session = requests.Session()
    try:
        token = login(session, username, password)

        if get_checkin_status(session, token):
            return True

        log(f"[{username}] 开始签到流程...")

        log(f"[{username}] 获取验证 challenge...")
        challenge_data = get_challenge(session, token)

        if "challenge" not in challenge_data:
            log(f"[{username}] ❌ 获取 challenge 失败: {challenge_data}")
            return False

        log(f"[{username}] 开始计算 PoW...")
        t0 = time.time()
        solutions = solve_challenges(session, token, challenge_data)
        elapsed = time.time() - t0
        log(f"[{username}] PoW 全部解出，耗时 {elapsed:.1f}s")

        log(f"[{username}] 提交验证...")
        redeem_result = redeem(session, token, challenge_data["token"], solutions)

        if not redeem_result.get("success"):
            log(f"[{username}] ❌ 验证失败: {redeem_result.get('error', redeem_result)}")
            return False

        verified_token = redeem_result.get("token", challenge_data["token"])
        log(f"[{username}] 验证通过，执行签到...")

        result = do_checkin(session, token, verified_token)

        if result.get("success"):
            amount = result.get("amount", "?")
            unit = result.get("currencyUnit", "RCoin")
            balance = result.get("balance", "")
            log(f"[{username}] ✅ 签到成功！获得 {amount} {unit}" + (f" | 余额: {balance}" if balance else ""))
            return True
        else:
            msg = result.get("message", "")
            if "已经签到" in msg:
                log(f"[{username}] 今日已签到: {msg}")
                return True
            log(f"[{username}] ❌ 签到失败: {msg}")
            return False

    except Exception as e:
        log(f"[{username}] ❌ 执行失败: {e}")
        return False


def main():
    accounts = load_accounts()
    if not accounts:
        print("❌ 请设置环境变量 EOOS_ACCOUNTS (格式: 用户名#密码&用户名#密码)")
        print("  或设置 EOOS_USER 和 EOOS_PASS")
        sys.exit(1)

    log(f"共 {len(accounts)} 个账号需要签到")
    success_count = 0
    for i, (user, pwd) in enumerate(accounts, 1):
        log(f"--- 账号 {i}/{len(accounts)}: {user} ---")
        if checkin_one(user, pwd):
            success_count += 1
        if i < len(accounts):
            time.sleep(2)

    log(f"签到完成: {success_count}/{len(accounts)} 成功")
    if success_count < len(accounts):
        sys.exit(1)


if __name__ == "__main__":
    main()
