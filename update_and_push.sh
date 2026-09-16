#!/bin/bash
# 每日更新脚本：拉上游 → YYB改写 → push fork → QQ通知
set -e

REPO="/root/QLScriptPublic"
FORK="https://github.com/wangixangya/QLScriptPublic.git"
UPSTREAM="https://github.com/smallfawn/QLScriptPublic.git"

# QQ 推送函数
send_qq() {
    local msg="$1"
    local result
    result=$(curl -s -m 10 -X POST http://172.17.0.1:3000/send_private_msg \
        -H "Authorization: Bearer sg_qq_token_2026" \
        -H "Content-Type: application/json" \
        -d "{\"user_id\":949194446,\"message\":\"$msg\"}" 2>/dev/null)
    echo "QQ推送: $result"
}

LOG="/tmp/update_qlscriptpub_$(date +%Y%m%d_%H%M%S).log"

{
    echo "=== $(date) 开始更新 QLScriptPublic ==="
    cd "$REPO"

    # 1. 拉取上游
    echo "[1/5] 拉取上游 smallfawn..."
    git fetch upstream main 2>&1
    UPSTREAM_HEAD=$(git rev-parse upstream/main)
    LOCAL_HEAD=$(git rev-parse origin/main)
    if [ "$UPSTREAM_HEAD" = "$LOCAL_HEAD" ]; then
        echo "  上游无更新，跳过"
        send_qq "📋 QLScriptPublic 每日更新\n上游无新提交，跳过。"
        exit 0
    fi
    git merge upstream/main --no-edit 2>&1
    echo "  上游已合并: $(git rev-parse --short upstream/main)"

    # 2. JS 改写
    echo "[2/5] JS 改写..."
    python3 /root/yyb-go/scripts/rewrite_yyb_wxapp.py 2>&1 | tail -5

    # 3. Python 注入 YYB 兼容层
    echo "[3/5] Python 注入 YYB 兼容层..."
    python3 /root/yyb-go/scripts/rebuild_python3.py 2>&1 | tail -5

    # 4. 提交并推送
    echo "[4/5] 提交推送..."
    git add -A
    if git diff --cached --quiet; then
        echo "  无改动"
    else
        git commit -m "feat: auto-update $(date +%Y-%m-%d) YYB-Go rewrite" 2>&1
        git push origin main 2>&1
    fi

    # 5. QQ 通知
    echo "[5/5] QQ 通知..."
    CHANGED=$(git diff --stat HEAD~1..HEAD -- wxapp/ 2>/dev/null | tail -1)
    send_qq "🎉 QLScriptPublic 每日更新完成\n$CHANGED\n已推送至 fork: wangxiangya/QLScriptPublic"

    echo "=== 更新完成 ==="
} > "$LOG" 2>&1

cat "$LOG"
