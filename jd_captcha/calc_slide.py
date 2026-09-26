import cv2, numpy as np, sys, json

def find_gap(img_path):
    """在背景图(原始尺寸)上找拼图缺口 -> 返回缺口中心x(原图坐标)"""
    img = cv2.imread(img_path)
    if img is None:
        return None, 0
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 缺口特征: 一块区域与周围不连续(明显亮或暗的块), 边缘强
    edges = cv2.Canny(gray, 50, 150)

    # 拼图块通常是"凸"形, 有明显的竖向边缘集中
    # 方法: 对每列统计边缘数, 缺口处会有两条强竖边(左右边界)
    colsum = edges.sum(axis=0).astype(float)
    # 平滑
    k = np.ones(7)/7
    sm = np.convolve(colsum, k, mode='same')

    # 排除最左(拼图块起始区通常不在最左) 和最右
    left = int(w*0.12)
    right = int(w*0.95)
    seg = sm[left:right]
    if len(seg)==0: return None, w
    peak = int(np.argmax(seg)) + left

    # 方法2: 找"平坦块"(缺口内部常是纯色/半透明, 边缘少) -> 用低边缘连续区
    inv = (edges==0).astype(np.uint8)
    colgap = inv[0:int(h*0.8), :].sum(axis=0)
    ks = np.ones(21)/21
    sm2 = np.convolve(colgap, ks, mode='same')
    seg2 = sm2[left:right]
    peak2 = int(np.argmax(seg2)) + left

    print('# orig_w=%d edge_peak=%d gap_peak=%d' % (w, peak, peak2))
    # 综合: 缺口通常在右半区, 取两者中更靠右且不为边缘的值
    cand = [p for p in (peak, peak2) if left < p < right]
    if not cand: return None, w
    gap_x = int(np.median(cand))
    return gap_x, w

if __name__ == '__main__':
    bg = sys.argv[1] if len(sys.argv)>1 else '/tmp/jdlogin/slide_bg.png'
    disp_w = float(sys.argv[2]) if len(sys.argv)>2 else 290.0
    btn_start = float(sys.argv[3]) if len(sys.argv)>3 else 0.0   # 滑块按钮起始x(页面坐标)
    gap_x, orig_w = find_gap(bg)
    if gap_x is None:
        print('DISTANCE=0')
    else:
        scale = disp_w / orig_w if orig_w else 1.0
        disp_gap = gap_x * scale
        dist = int(round(disp_gap - (btn_start - 105)))  # 105 = 背景图左边界x
        dist = max(5, min(int(disp_gap) , 280))
        print('# gap_x=%d orig_w=%d scale=%.3f disp_gap=%.1f' % (gap_x, orig_w, scale, disp_gap))
        print('DISTANCE=%d' % dist)
