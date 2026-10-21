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
    git merge -X ours upstream/main --no-edit 2>&1 || { git merge --abort 2>/dev/null; log "  上游合并冲突,已放弃本次合并(保留本地YYB适配)"; }

    # 1.5 京东净化：上游 smallfawn/QLScriptPublic 自带 jd/、jd_captcha/、qitoqito_psyduck/，
    #      每次 merge 都会回灌。这里强制清除，确保京东永不进本仓库。
    log "[1.5/6] 京东净化(防上游回灌)..."
    JD_HIT=0
    for jdpath in jd jd_captcha qitoqito_psyduck daily/JDCode.py daily/JDCodeLocal.py wxapp/jdcode.js wxapp/jdbclub.js wxapp/jdyj.js wxapp/jdkd.py; do
        if [ -e "$jdpath" ]; then rm -rf "$jdpath"; JD_HIT=1; fi
    done
    # 通配清除(含 cache/未跟踪)
    find . -path ./.git -prune -o -iname 'jd_task_*' -print -exec rm -f {} + 2>/dev/null
    find . -path ./.git -prune -o -iname '*psyduck*' -print -exec rm -rf {} + 2>/dev/null
    find . -path ./.git -prune -o -iname 'jd_cookie*' -print -exec rm -f {} + 2>/dev/null
    find . -path ./.git -prune -o -iname 'jd_ck_*' -print -exec rm -f {} + 2>/dev/null
    [ $JD_HIT -eq 1 ] && log "  上游京东文件已清除" || log "  无京东回灌"

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

    # 3c. /wx/code 响应形状修补：yyb-go 返回 {code:0,data:{result:{code}}}，
    #      上游脚本多按旧 wx_server 形状(status/data.code)解析，会误报"未返回code"
    log "[3c/6] /wx/code 响应形状修补..."
    (cd "$SCRIPT_DIR" && python3 patch_wxcode_shape.py) 2>&1 | tail -5
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        log "  /wx/code 形状修补失败"; FAILED=1
    fi

    JS_COUNT=$(ls "$DST_DIR"/*.js 2>/dev/null | wc -l)
    PY_COUNT=$(ls "$DST_DIR"/*.py 2>/dev/null | wc -l)

    # 4. 同步改写结果到 git 仓库
    log "[4/6] 同步到仓库..."
    cp -r "$DST_DIR"/* "$REPO/wxapp/" 2>/dev/null

    # 4.5 提交前守卫：任何京东文件企图进入暂存区则中止本次推送
    git add -A
    if git diff --cached --name-only | grep -qiE 'jd/|jd_captcha|qitoqito_psyduck|jdcode|jdbclub|jdyj|jdkd|jd_task_|jd_cookie|jd_ck_|psyduck'; then
        log "  ⛔ 检测到京东文件企图提交，已中止推送！详情："
        git diff --cached --name-only | grep -iE 'jd|psyduck' | sed 's/^/    /' | tee -a "$LOG"
        FAILED=1
    elif git diff --cached --quiet; then
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

    # 5c. 部署 yyb-ua 模块到 NODE_PATH(deps), 供脚本 require('yyb-ua')
    QL2_DEPS="/root/docker/ql2/data/deps"
    mkdir -p "$QL2_DEPS"
    if [ -f "$DST_DIR"/_lib/yyb-ua.js ]; then
        cp "$DST_DIR"/_lib/yyb-ua.js "$QL2_DEPS"/yyb-ua.js
        log "  yyb-ua 模块部署完成"
    fi

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
