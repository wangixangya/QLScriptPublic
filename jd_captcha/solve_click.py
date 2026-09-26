import cv2, numpy as np, sys, re

# 颜色候选(用于目标图形假设轮换)
COLOR_DEFS = {
    'gray':  lambda H,S,V: ((S<50)&(V>60)&(V<210)),
    'red':   lambda H,S,V: (((H<12)|(H>170))&(S>70)&(V>60)),
    'pink':  lambda H,S,V: ((H>=140)&(H<=170)&(S>35)&(V>140)),
    'blue':  lambda H,S,V: ((H>=95)&(H<=140)&(S>55)&(V>50)),
    'green': lambda H,S,V: ((H>=40)&(H<=85)&(S>55)&(V>50)),
    'orange':lambda H,S,V: ((H>=10)&(H<=32)&(S>80)&(V>120)),
    'purple':lambda H,S,V: ((H>=130)&(H<=168)&(S>55)&(V>50)),
    'yellow':lambda H,S,V: ((H>=22)&(H<=42)&(S>70)&(V>150)),
}
COLOR_CN = {'灰':'gray','灰色':'gray','红':'red','红色':'red','粉':'pink','粉色':'pink',
            '蓝':'blue','蓝色':'blue','绿':'green','绿色':'green','橙':'orange','橙色':'orange',
            '紫':'purple','紫色':'purple','黄':'yellow','黄色':'yellow'}

def blobs(mask, min_area=180):
    num, labels, stats, cents = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    out=[]
    for i in range(1,num):
        x,y,w,h,a = stats[i]
        if a<min_area: continue
        if w<10 or h<10: continue
        out.append({'bbox':(int(x),int(y),int(w),int(h)),'center':(int(cents[i][0]),int(cents[i][1])),'area':int(a),'mask':(labels==i)})
    return out

def solve(path, hint, box=None):
    img = cv2.imread(path)
    if img is None: print('POINTS='); return []
    offx, offy = 0,0
    if box and box[2]>20:
        x,y,w,h = box
        x=max(0,x); y=max(0,y)
        img = img[y:min(img.shape[0],y+h), x:min(img.shape[1],x+w)]
        offx, offy = x, y
    cv2.imwrite('/tmp/jdlogin/try_crop.png', img)
    h,w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H,S,V = hsv[:,:,0], hsv[:,:,1], hsv[:,:,2]

    # 解析题目
    neg = ('不与' in hint) or ('不和' in hint) or ('不' in hint and '重叠' in hint)
    tgt = None
    m = re.search(r'不[与和]?(.*?)重叠', hint)
    seg = m.group(1) if m else hint
    for k,v in COLOR_CN.items():
        if k in seg: tgt = v; break
    print('# hint=%s neg=%s target=%s' % (hint, neg, tgt))

    # 非背景图形(候选可点对象)
    bg = ((S<55)&(V>175)).astype(np.uint8)*255
    nonbg = cv2.bitwise_not(bg)
    nonbg = cv2.morphologyEx(nonbg, cv2.MORPH_OPEN, np.ones((3,3),np.uint8))
    nonbg = cv2.morphologyEx(nonbg, cv2.MORPH_CLOSE, np.ones((5,5),np.uint8))

    # 只取验证码图区域(去掉页面其他元素): 用较大连通域
    cands = blobs(nonbg, min_area=300)
    # 过滤掉太宽/太高的(页面元素)
    cands = [c for c in cands if c['bbox'][2] < w*0.6 and c['bbox'][3] < h*0.5]
    print('# cands=%d' % len(cands))
    if not cands: print('POINTS='); return []

    # 目标 mask
    order = [tgt] if tgt else []
    order += [c for c in COLOR_DEFS if c != tgt]

    best = None
    for tname in order:
        try:
            tmask = COLOR_DEFS[tname](H,S,V).astype(np.uint8)*255
        except Exception:
            continue
        tmask = cv2.morphologyEx(tmask, cv2.MORPH_OPEN, np.ones((5,5),np.uint8))
        tmask = cv2.morphologyEx(tmask, cv2.MORPH_CLOSE, np.ones((9,9),np.uint8))
        if (tmask>0).sum() < 200: continue
        sel=[]; ratios=[]
        for c in cands:
            x,y,bw,bh = c['bbox']
            pad=3
            x0=max(0,x-pad); y0=max(0,y-pad); x1=min(w,x+bw+pad); y1=min(h,y+bh+pad)
            reg = tmask[y0:y1, x0:x1]
            ratio = float((reg>0).sum())/max(1,reg.size)
            ratios.append(ratio)
            overlap = ratio > 0.04
            should = (not overlap) if neg else overlap
            if should: sel.append((c['center'][0]+offx, c['center'][1]+offy))
        # 评价: 选中数量在 1..len-1 之间较合理, 且比例区分明显
        if 0 < len(sel) < len(cands):
            spread = max(ratios) - min(ratios) if ratios else 0
            # OCR 指定了颜色时, 优先采用(加权), 避免评分选错目标
            score = spread + (100.0 if (tgt and tname == tgt) else 0.0)
            if best is None or score > best[0]:
                best = (score, tname, sel)
        print('#   try %s -> sel=%d' % (tname, len(sel)))

    if not best:
        print('POINTS='); return []
    print('# chosen target=%s selected=%d' % (best[1], len(best[2])))
    vis = img.copy()
    for c in cands:
        x,y,bw,bh = c['bbox']
        cv2.rectangle(vis,(x,y),(x+bw,y+bh),(0,255,0),2)
    cv2.imwrite('/tmp/jdlogin/try_solved.png', vis)
    print('POINTS=' + ';'.join('%d,%d' % p for p in best[2]))
    return best[2]

if __name__ == '__main__':
    p = sys.argv[1] if len(sys.argv)>1 else '/tmp/jdlogin/try_1.png'
    hint = sys.argv[2] if len(sys.argv)>2 else ''
    box = None
    if len(sys.argv)>3 and sys.argv[3]!='0,0,0,0':
        box=[int(v) for v in sys.argv[3].split(',')]
    solve(p, hint, box)
