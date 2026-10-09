/**
 * yyb-ua — 统一 User-Agent 库
 * 来源: https://www.lanren-tools.com/user-agent/ (懒人工具 UA 大全)
 *
 * 用法 (青龙 / yyb_wxapp 脚本):
 *   const UA = require('yyb-ua');
 *   headers: { 'User-Agent': UA.wx() }              // 随机微信 UA
 *   headers: { 'User-Agent': UA.wxMini() }          // 微信小程序 UA
 *   headers: { 'User-Agent': UA.wxAndroid() }       // 指定安卓微信
 *   headers: { 'User-Agent': UA.pick() }            // 全场景随机
 *   headers: { 'User-Agent': UA.chrome() }          // 桌面 Chrome
 *   UA.all.wxAndroid                                // 取某个分类数组
 */

// ============ 微信 Android (含主流机型) ============
const wxAndroid = [
  // 微信 8.0.40 - 华为 Mate60 Pro 鸿蒙4.0 WIFI
  'Mozilla/5.0 (Linux; Android 12; HarmonyOS 4.0; ALN-AL80 Build/HUAWEIALN-AL80; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 XWEB/1169 MMWEBSDK/20230901 MicroMessenger/8.0.40.2420(0x28002853) NetType/WIFI Language/zh_CN ABI/arm64',
  // 微信 8.0.40 - 小米14 Android14 WIFI
  'Mozilla/5.0 (Linux; Android 14; MI 14 Build/UN1A.231005.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36 XWEB/1169 MMWEBSDK/20230901 MicroMessenger/8.0.40.2420(0x28002853) NetType/WIFI Language/zh_CN ABI/arm64',
  // 微信 8.0.40 - vivo X100 Android14 5G
  'Mozilla/5.0 (Linux; Android 14; V2318A Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36 XWEB/1169 MMWEBSDK/20230901 MicroMessenger/8.0.40.2420(0x28002853) NetType/5G Language/zh_CN ABI/arm64',
  // 微信 8.0.40 - OPPO Find X7 Android14 WIFI
  'Mozilla/5.0 (Linux; Android 14; PHK110 Build/UKQ1.230924.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36 XWEB/1169 MMWEBSDK/20230901 MicroMessenger/8.0.40.2420(0x28002853) NetType/WIFI Language/zh_CN ABI/arm64',
  // 微信 8.0.40 - 荣耀 Magic6 Android14 5G
  'Mozilla/5.0 (Linux; Android 14; BVL-AN16 Build/HONORBVL-AN16; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36 XWEB/1169 MMWEBSDK/20230901 MicroMessenger/8.0.40.2420(0x28002853) NetType/5G Language/zh_CN ABI/arm64',
  // 微信 8.0.40 - 三星 S24 Android14 WIFI
  'Mozilla/5.0 (Linux; Android 14; SM-S9210 Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36 XWEB/1169 MMWEBSDK/20230901 MicroMessenger/8.0.40.2420(0x28002853) NetType/WIFI Language/zh_CN ABI/arm64',
  // 微信 6.6.1 经典 - 小米6 WIFI (老接口兼容)
  'Mozilla/5.0 (Linux; Android 7.1.1; MI 6 Build/NMF26X; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/57.0.2987.132 MQQBrowser/6.2 TBS/043807 Mobile Safari/537.36 MicroMessenger/6.6.1.1220(0x26060135) NetType/WIFI Language/zh_CN',
  // 微信 6.6.1 经典 - HUAWEI TAG-AL00 4G
  'Mozilla/5.0 (Linux; Android 5.1; HUAWEI TAG-AL00 Build/HUAWEITAG-AL00; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.49 Mobile MQQBrowser/6.2 TBS/043622 Safari/537.36 MicroMessenger/6.6.1.1220(0x26060135) NetType/4G Language/zh_CN',
];

// ============ 微信小程序 ============
const wxMini = [
  // 小米14 Android14 小程序 5G
  'Mozilla/5.0 (Linux; Android 14; MI 14 Build/UN1A.231005.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36 XWEB/1169 MMWEBSDK/20230901 MicroMessenger/8.0.40.2420(0x28002853) NetType/5G Language/zh_CN miniProgram ABI/arm64',
  // 小米6 小程序
  'Mozilla/5.0 (Linux; Android 7.1.1; MI 6 Build/NMF26X; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/57.0.2987.132 MQQBrowser/6.2 TBS/043807 Mobile Safari/537.36 MicroMessenger/6.6.1.1220(0x26060135) NetType/4G Language/zh_CN miniProgram',
  // 通用小程序兜底
  'Mozilla/5.0 MicroMessenger MiniProgram',
];

// ============ 微信 iOS ============
const wxIos = [
  // iPhone15 Pro iOS17 微信8.0.40 WIFI
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40(0x18002820) NetType/WIFI Language/zh_CN',
  // iPhone14 iOS16.5 微信8.0.39 5G
  'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.39(0x18002720) NetType/5G Language/zh_CN',
  // iPad Pro iOS17 微信8.0.40 WIFI
  'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40(0x18002820) NetType/WIFI Language/zh_CN',
  // iPhone iOS 11_2_2 微信6.6.1 (老接口兼容)
  'Mozilla/5.0 (iPhone; CPU iPhone OS 11_2_2 like Mac OS X) AppleWebKit/604.4.7 (KHTML, like Gecko) Mobile/15C202 MicroMessenger/6.6.1 NetType/4G Language/zh_CN',
];

// ============ 支付宝小程序/内置浏览器 ============
const alipay = [
  'Mozilla/5.0 (Linux; Android 13; SM-G9980 Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/107.0.5304.105 Mobile Safari/537.36 AlipayDefined(nt:4G,ws:360|0|3.0) AliApp(AP/10.2.90.9000) AlipayClient/10.2.90.9000 Language/zh-Hans useStatusBar/true isMp/true',
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 AliApp(AP/10.2.90.9000) AlipayClient/10.2.90.9000 Language/zh-Hans isMp/true',
];

// ============ 桌面浏览器 ============
const desktop = [
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
];

// ============ 移动浏览器(非微信) ============
const mobile = [
  'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36',
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
  'Mozilla/5.0 (Linux; Android 13; SM-G9980 Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/107.0.5304.105 Mobile Safari/537.36 UCBrowser/15.0.0.1000',
  'Mozilla/5.0 (Linux; Android 12; HarmonyOS 4.0; HLK-AL10 Build/HUAWEIHLK-AL10; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36',
];

const all = { wxAndroid, wxMini, wxIos, alipay, desktop, mobile };

function _rand(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

const UA = {
  all,
  /** 随机微信 UA(安卓+iOS 混合) */
  wx: () => _rand([...wxAndroid, ...wxIos]),
  /** 微信小程序 UA */
  wxMini: () => _rand(wxMini),
  /** 微信安卓 UA */
  wxAndroid: () => _rand(wxAndroid),
  /** 微信 iOS UA */
  wxIos: () => _rand(wxIos),
  /** 支付宝 UA */
  alipay: () => _rand(alipay),
  /** 桌面浏览器 UA */
  desktop: () => _rand(desktop),
  /** 指定桌面 Chrome */
  chrome: () => desktop[0],
  /** 移动浏览器 UA(非微信) */
  mobile: () => _rand(mobile),
  /** 全场景随机 */
  pick: () => _rand([...wxAndroid, ...wxIos, ...wxMini, ...desktop, ...mobile]),
  /** 从指定分类取: UA.get('wxAndroid') */
  get: (cat) => _rand(all[cat] || wxAndroid),
};

module.exports = UA;
