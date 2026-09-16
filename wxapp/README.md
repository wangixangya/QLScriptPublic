# YYB-Go 兼容版微信小程序脚本

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
