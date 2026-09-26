import cv2, numpy as np, sys, re

COLORS = ['灰色','灰','红色','红','粉色','粉','蓝色','蓝','深蓝','绿色','绿','橙色','橙','紫色','紫','黄色','黄','黑色','黑','白色','白']
SHAPES = ['圆形','圆','三角形','三角','方形','正方形','星形','星','梯形','梯','椭圆','菱形']

def ocr_hint(img_path, scan_from=180, scan_to=720):
    """多横条扫描 OCR, 投票选最佳题目文本"""
    import ddddocr
    ocr = ddddocr.DdddOcr(show_ad=False)
    img = cv2.imread(img_path)
    if img is None: return ''
    h, w = img.shape[:2]
    best = []
    for y in range(scan_from, min(h, scan_to), 18):
        strip = img[y:y+42, 30:min(w,490)]
        if strip.size == 0: continue
        cv2.imwrite('/tmp/jdlogin/_ocr.png', strip)
        with open('/tmp/jdlogin/_ocr.png','rb') as f: b=f.read()
        try: t = ocr.classification(b)
        except Exception: continue
        if not t: continue
        # 评分: 含"请点击"/"点击" + 含"重叠" + 长度
        score = 0
        if '请点击' in t: score += 5
        elif '点击' in t: score += 3
        if '重叠' in t: score += 3
        score += min(len(t), 25) / 10.0
        if score > 3: best.append((score, y, t))
    if not best: return ''
    best.sort(reverse=True)
    return best[0][2]

def fuzzy_find(text, words):
    """模糊匹配: 允许 OCR 个别字错(用首字或包含关系)"""
    for wd in words:
        if wd in text: return wd
    # 单字匹配(如'灰','黄')
    for wd in words:
        if len(wd) == 1 and wd in text: return wd
    return None

def parse(hint):
    m = re.search(r'不[与和]?(.*?)重叠', hint)
    seg = m.group(1) if m else hint
    color = fuzzy_find(seg, COLORS)
    shape = fuzzy_find(seg, SHAPES)
    neg = ('不与' in hint) or ('不和' in hint) or ('不与' in hint)
    return color, shape, neg

if __name__ == '__main__':
    p = sys.argv[1] if len(sys.argv)>1 else '/tmp/jdlogin/frame.png'
    hint = ocr_hint(p)
    print('HINT=%s' % hint)
    c, s, n = parse(hint)
    print('COLOR=%s SHAPE=%s NEG=%s' % (c, s, n))
