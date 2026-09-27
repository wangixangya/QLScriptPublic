# 京东登录工具（原生体验版）

## jd_login_*.apk（改造版京东登录 App）
- 来源: hhaijdapp-android-1.2.7.apk（逆向后改造）
- 原版会把 wskey 发到 robot.djun97.top（第三方，泄露账号）→ 已改成只回传本地
- 改造方式: apktool 解码 smali，把 robot.djun97.top / wskey.djun97.top 全部
  替换为自有接收端地址，apktool 重打包 + uber-apk-signer 签 v1+v2+v3
- 回传路径: POST /api/Doraemon/bigNai/wskey/service，body {wskey,pin,full_ck,callback_id}
- 包名: top.djun97.jd（与原版相同，安装前需卸载原版）

### 三个变体
- jd_login_local.apk  : 回传 http://192.168.5.22:8899（手机连家里 WiFi 用）
- jd_login_public.apk : 回传 https://<cloudflared隧道>.trycloudflare.com（任意网络，含流量）
- jd_login_signed.apk : 同 local 的全签名版

> 公网隧道域名重启会变，用 public 版前确认隧道在线。

## jd_cookie_server.js（接收端，仅本机）
- node 服务，监听 8899，只写本地青龙 database.sqlite，不发任何第三方
- 路由: / (录入页), /recv, /api/Doraemon/bigNai/wskey/service, /set
- 收到凭证后写入/新建 JD_COOKIE 环境变量，自动备份旧库
- 启动: node jd_cookie_server.js (需设置 QL_DB=/root/docker/ql/data/db/database.sqlite)

## 安全提醒
- 原版 hhaijdapp 把账号凭证发第三方，绝不要用原版
- 本改造版凭证只进你自己 N100 的青龙，青龙在本机 docker
