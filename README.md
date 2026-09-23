# QLScriptPublic — 青龙面板脚本公共仓库

合并自以下来源，已去重并统一 YYB-Go 适配：

- [smallfawn/QLScriptPublic](https://github.com/smallfawn/QLScriptPublic.git) — 原始脚本
- [SuperNaiBA/YYB-GO-Script](https://github.com/SuperNaiBA/YYB-GO-Script.git) — YYB-Go 适配版
- [lcmovie/YYB-GO-Script-i](https://github.com/lcmovie/YYB-GO-Script-i.git) — YYB-Go-Enhanced 适配版

## 目录结构

| 目录 | 说明 |
|------|------|
| `wxapp/` | 微信小程序脚本（JS/Python），已统一 YYB-Go 适配 |
| `daily/` | 日常任务脚本 |
| `idp/` | 独立脚本（来自 lcmovie/YYB-GO-Script-i） |
| `jd/` | 京东脚本 |
| `tools/` | 公共工具（env.js, sendNotify.js） |
| `backup/` | 历史备份脚本 |

## 环境变量

### YYB_SERVER (必填)
格式: `endpoint@ref`，每行一个账号
```
yyb-go:8000@openid1
yyb-go:8000@openid2
```

### YYB_API_KEY (可选)
协议接口鉴权密钥

## 青龙面板拉库命令

```bash
ql repo https://github.com/wangixangya/QLScriptPublic.git
```

## 免责声明

这里的脚本只是自己学习 js 的一个实践，仅用于测试和学习研究，禁止用于商业用途，不能保证其合法性，准确性，完整性和有效性，请根据情况自行判断。

仓库内所有资源文件，禁止任何公众号、自媒体进行任何形式的转载、发布。

间接使用脚本的任何用户，包括但不限于建立 VPS 或在某些行为违反国家/地区法律或相关法规的情况下进行传播，对于由此引起的任何隐私泄漏或其他后果概不负责。

如果任何单位或个人认为该项目的脚本可能涉嫌侵犯其权利，则应及时通知并提供身份证明，所有权证明，我们将在收到认证文件后删除相关脚本。