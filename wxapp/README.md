# YYB-Go 兼容版微信小程序脚本

基于以下来源合并改写，兼容 YYB-Go 协议服务：

- [smallfawn/QLScriptPublic](https://github.com/smallfawn/QLScriptPublic.git) — 原始脚本
- [SuperNaiBA/YYB-GO-Script](https://github.com/SuperNaiBA/YYB-GO-Script.git) — YYB-Go 适配版
- [lcmovie/YYB-GO-Script-i](https://github.com/lcmovie/YYB-GO-Script-i.git) — YYB-Go-Enhanced 适配版

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

## 目录结构
- `wxapp/` — 微信小程序脚本（JS/Python）
- `daily/` — 日常任务脚本
- `idp/` — 独立脚本（来自 lcmovie/YYB-GO-Script-i）
- `jd/` — 京东脚本
- `tools/` — 公共工具（env.js, sendNotify.js）