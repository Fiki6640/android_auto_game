#!/usr/bin/env python3
"""用 OpenCV 从截图中裁剪按钮 —— 输入坐标直接出模板"""

import sys, os
import cv2
import numpy as np

def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

if len(sys.argv) < 5:
    print("用法: python crop_template.py <截图> <x1> <y1> <x2> <y2> [输出名]")
    print("  x1,y1 = 按钮左上角,  x2,y2 = 按钮右下角")
    sys.exit(1)

src = sys.argv[1]
x1, y1, x2, y2 = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
out = sys.argv[6] if len(sys.argv) > 6 else f"templates/cropped_{x1}_{y1}_{x2}_{y2}.png"

img = imread_cn(src)
if img is None:
    print(f"无法读取: {src}")
    sys.exit(1)

h, w = img.shape[:2]
x1, y1 = max(0, x1), max(0, y1)
x2, y2 = min(w, x2), min(h, y2)

crop = img[y1:y2, x1:x2]
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
cv2.imencode('.png', crop)[1].tofile(out)

print(f"已保存: {out}  ({x2-x1}x{y2-y1})")
print(f"匹配测试: python bot.py --test {src} {out}")
