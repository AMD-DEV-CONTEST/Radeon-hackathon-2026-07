# -*- coding: utf-8 -*-
"""通用 OCR 工具：识别透明PNG验证码。用法: python ocr_captcha.py <png> """
import sys, os, subprocess, cv2, numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXE = "C:/Program Files/Tesseract-OCR/tesseract.exe"

def alpha_to_white(img_rgba):
    a = img_rgba[:, :, 3]
    comp = np.full((a.shape[0], a.shape[1]), 255, np.uint8)
    comp[a > 10] = 0
    return comp

def ocr(img, psm="7", whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"):
    cv2.imwrite("_ocr_tmp.png", img)
    cfg = ["--psm", psm]
    if whitelist:
        cfg += ["-c", "tessedit_char_whitelist=" + whitelist]
    r = subprocess.run([EXE, "_ocr_tmp.png", "stdout", "-l", "eng"] + cfg,
                       capture_output=True, text=True)
    return r.stdout.strip()

def main():
    path = sys.argv[1]
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        print("cannot read", path); return
    gray = alpha_to_white(img) if img.shape[2] == 4 else img
    results = {}
    # 多种预处理
    big_c = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    big_n = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    med = cv2.resize(cv2.medianBlur(gray, 3), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    for name, im in [("cubic", big_c), ("nearest", big_n), ("median", med)]:
        for psm in ["7", "8", "13"]:
            t = ocr(im, psm)
            results[f"{name}/psm{psm}"] = t
    # 统计最高频
    from collections import Counter
    c = Counter(results.values())
    best = c.most_common()
    for k, v in results.items():
        print(f"  {k}: [{v}]")
    print("=> most common:", best[0][0] if best else "")

if __name__ == "__main__":
    main()
