# jd_captcha — 京东验证码自动识别 / 登录取 Cookie

在本机（无 GPU 的 N100）上，用 Playwright + 系统 Chromium + ddddocr / OpenCV
实现京东登录流程自动化：填账号密码 → 触发安全验证 → 自动识别验证码 → 取 `pt_key` / `pt_pin`，
可选直接写入青龙 `Envs` 表刷新 JD_COOKIE。

## 目录

| 文件 | 作用 |
|---|---|
| `jd_login.js` | 主脚本：密码登录 + 滑块/点选验证码处理 + 短信码等待 + 写青龙 |
| `jd_scan_login.js` | 备选：扫码登录（生成二维码 PNG，需人工扫） |
| `ocr_hint.py` | OCR 读验证码提示文字（多横条扫描投票，输出 `HINT=`） |
| `solve_click.py` | 点选题求解：解析题目颜色/否定语义 → 找候选图形 → 判断重叠 → 输出点击坐标 |
| `calc_slide.py` | 滑块题求解：原图缺口定位 → 输出 `DISTANCE=` |
| `collect_samples.js` | 样本采集（全类型），用于后续训练 |
| `collect_slide.js` | 滑块样本采集（只采滑块，存背景图原图） |

## 依赖

```bash
# Node
npm i playwright          # 或已有 node_modules
# 系统 Chromium（推荐，避免下载 playwright 自带 chromium）
apt install -y chromium   # 脚本用 executablePath: /usr/bin/chromium
# Python
pip3 install ddddocr opencv-python-headless numpy
```

> pip 若报 SOCKS / proxy 错：本机环境变量被 `socks5://127.0.0.1:7890` 污染且缺 pysocks，
> 用干净环境装：`env -i PATH=/usr/bin:/bin HOME=/root http_proxy=http://127.0.0.1:7890 pip3 install ...`

## 用法

### 1. 只取 Cookie（不写库）

```bash
JD_PHONE=手机号 JD_PWD=密码 node jd_login.js
# 成功输出: [COOKIE] pt_key=xxx; pt_pin=xxx;
```

### 2. 直接写入青龙

```bash
export QL_DB=/root/docker/ql/data/db/database.sqlite   # 青龙 sqlite 路径
export QL_ENV_ID=108                                    # 可选：指定 Envs.id
JD_PHONE=手机号 JD_PWD=密码 node jd_login.js
```

写入前自动 `cp` 备份 sqlite 到同目录 `.bak_jdlogin_<时间戳>`。

### 3. 遇到短信验证

脚本检测到短信页会打印 `[sms] 等待 /tmp/jdlogin/sms.txt`，
把收到的验证码写入该文件即可继续：

```bash
echo -n "123456" > /tmp/jdlogin/sms.txt
```

### 4. 扫码登录（备选）

```bash
node jd_scan_login.js     # 生成 /tmp/jdlogin/qrcode.png，京东 App 扫
```

## 已知原理与现状（重要）

- **验证码不在 iframe**：`page.frames()` 只有 1 个，DOM 里只有「安全验证 / 刷新 / 确定」，
  **提示文字是图片渲染的**，必须 OCR —— 这是 `ocr_hint.py` 存在的原因。
- **题型随机**：滑块 / 点选交替出现；点选题的目标颜色与形状每次都变
  （实测出现过：粉色星形、灰色圆形、粉色梯形、黄色…、"最小XX形"）。
  `solve_click.py` 用 OCR 读题 + 8 色 HSV 掩码 + 连通域重叠判断应对。
- **滑块**：背景图原图 320×240，页面显示 290×218（缩放 ~0.906），
  距离必须按 `dist_orig * dispW / natW` 换算，否则拖不到位（`calc_slide.py` 处理）。
- **成功率**：点选题因 OCR 颜色词误识（如"黄"识成"植"、"灰"识成"榷"）与
  重叠阈值敏感，实测通过率不高；滑块题相对可行。
- **风控**：连续自动化尝试会触发京东风控（表现为提交后页面停在登录页无任何弹窗）。
  **建议低频使用**；触发后需间隔一段时间，或改走扫码 / 手动取 Cookie。

## 手动取 Cookie（最可靠，推荐）

浏览器登录京东后 F12 → Console 执行：

```js
document.cookie.match(/pt_key=[^;]+|pt_pin=[^;]+/g).join('; ')
```

把结果交给脚本或手动写入青龙即可。

## 训练更好的识别模型

`collect_samples.js` / `collect_slide.js` 用于攒样本。
样本 + OCR 题目存于 `samples/`（`labels.csv`），可用于微调专用识别器 ——
当前实现是"规则 + ddddocr 预训练模型"，未做自有模型训练。
