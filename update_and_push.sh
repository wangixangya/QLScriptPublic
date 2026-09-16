#!/bin/bash
# 每日更新：拉上游 → YYB改写 → push fork → 部署青龙 → QQ通知
set -e

REPO="/root/QLScriptPublic"
FORK_URL="https://github.com/wangixangya/QLScriptPublic.git"
UPSTREAM_URL="https://github.com/smallfawn/QLScriptPublic.git"
SCRIPT_DIR="/root/yyb-go/scripts"
DST_DIR="/root/yyb-go/scripts/yyb_wxapp"
QL2_SCRIPTS="/root/docker/ql2/data/scripts/yyb_wxapp"
YYB_SERVER="172.23.0.2:8000"
QQ_TOKEN="sg_qq_token_2026"
QQ_USER="949194446"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
LOG="/tmp/update_qlscriptpub_$(date +%Y%m%d_%H%M%S).log"
RESULT=""
FAILED=0

log() { echo "[$TIMESTAMP] $1" | tee -a "$LOG"; }

send_qq() {
    local msg="$1"
    local payload="{\"user_id\":$QQ_USER,\"message\":{\"type\":\"text\",\"data\":{\"text\":\"$msg\"}}}"
    curl -s -m 10 -X POST "http://127.0.0.1:3000/send_private_msg" \
        -H "Content-Type: application/json" \
        -H "Authorization: $QQ_TOKEN" \
        -d "$payload" >/dev/null 2>&1
}

{
    log "========== QLScriptPublic 更新开始 =========="
    cd "$REPO"

    # 确保 upstream remote 存在
    git remote add upstream "$UPSTREAM_URL" 2>/dev/null || true

    # 1. 拉取上游
    log "[1/6] 拉取上游..."
    git fetch upstream main 2>&1
    UPSTREAM_HEAD=$(git rev-parse upstream/main)
    LOCAL_HEAD=$(git rev-parse origin/main)
    if [ "$UPSTREAM_HEAD" = "$LOCAL_HEAD" ]; then
        log "  上游无更新，跳过"
        send_qq "📋 QLScriptPublic 每日更新 $TIMESTAMP
上游无新提交，跳过。"
        exit 0
    fi
    git merge upstream/main --no-edit 2>&1
    log "  上游已合并: $(git rev-parse --short upstream/main)"

    # 2. JS 改写
    log "[2/6] JS 改写..."
    (cd "$SCRIPT_DIR" && python3 rewrite_yyb_wxapp.py) 2>&1 | tail -5
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        log "  改写失败"; FAILED=1
    fi

    # 3. Python 注入 YYB 兼容层
    log "[3/6] Python 注入 YYB 兼容层..."
    (cd "$SCRIPT_DIR" && python3 rebuild_python3.py) 2>&1 | tail -5
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        log "  Python 注入失败"; FAILED=1
    fi

    # 3b. JS 取码适配：给直接 axios.post /wx/getuserinfo 的脚本注入 YYB-Go 分支
    log "[3b/6] JS 取码适配..."
    (cd "$SCRIPT_DIR" && python3 patch_wx_getuserinfo_yyb.py) 2>&1 | tail -10
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        log "  JS 取码适配失败"; FAILED=1
    fi

    JS_COUNT=$(ls "$DST_DIR"/*.js 2>/dev/null | wc -l)
    PY_COUNT=$(ls "$DST_DIR"/*.py 2>/dev/null | wc -l)

    # 4. 同步改写结果到 git 仓库
    log "[4/6] 同步到仓库..."
    cp -r "$DST_DIR"/* "$REPO/wxapp/" 2>/dev/null
    git add -A
    if git diff --cached --quiet; then
        log "  无改动"
    else
        git commit -m "feat: auto-update $(date +%Y-%m-%d) YYB-Go rewrite" 2>&1
        git push origin main 2>&1
        log "  已推送至 fork"
    fi

    # 5. 部署到 qinglong2
    log "[5/6] 部署到 qinglong2..."
    rm -rf "$QL2_SCRIPTS"
    mkdir -p "$QL2_SCRIPTS"
    cp -r "$DST_DIR"/* "$QL2_SCRIPTS"/ 2>/dev/null
    if [ $? -ne 0 ]; then
        log "  部署失败"; FAILED=1
    else
        log "  部署完成: $JS_COUNT JS + $PY_COUNT Python"
    fi

    # 5b. 部署 tools 目录（env.js + sendNotify.js）
    QL2_TOOLS="/root/docker/ql2/data/scripts/tools"
    mkdir -p "$QL2_TOOLS"
    cp "$DST_DIR"/env.js "$QL2_TOOLS"/ 2>/dev/null
    cp "$DST_DIR"/sendNotify.js "$QL2_TOOLS"/ 2>/dev/null
    log "  tools 部署完成"

    # 6. 验证 YYB 连接
    log "[6/6] 验证 YYB 连接..."
    YYB_HEALTH=$(docker exec qinglong2 wget -qO- --timeout=5 "http://$YYB_SERVER/health" 2>/dev/null || echo "FAIL")
    if echo "$YYB_HEALTH" | grep -q '"ok":true'; then
        log "  qinglong2 → yyb-go 正常"
    else
        log "  YYB 连接失败: $YYB_HEALTH"; FAILED=1
    fi

    # QQ 通知
    if [ $FAILED -eq 0 ]; then
        send_qq "✅ QLScriptPublic 更新成功 $TIMESTAMP
改写: $JS_COUNT JS + $PY_COUNT Python
部署: qinglong2/15700
YYB: 正常"
    else
        send_qq "⚠️ QLScriptPublic 更新有异常 $TIMESTAMP
改写: $JS_COUNT JS + $PY_COUNT Python
详见: $LOG"
    fi

    log "QQ通知已发送"
    log "========== 更新结束 =========="
} > "$LOG" 2>&1

cat "$LOG"
