# -*- coding: utf-8 -*-
"""Run DeviationNet on a cockpit frame and print the estimated runway deviation.

Usage:
    python inference.py assets/sample_frames/frame_00.jpg [more images...]

Expected output on the bundled sample frames (CPU, onnxruntime):
    frame_00.jpg  cross-track +0.07 m   heading error +0.04 deg
    frame_01.jpg  cross-track +0.02 m   heading error -0.08 deg
    frame_02.jpg  cross-track -0.13 m   heading error +0.14 deg

The same ONNX file runs unmodified on AMD GPUs through MIGraphX
(measured 2110 frames/s, 0.47 ms/frame on a Radeon gfx906).
"""
import sys
import os

import cv2
import numpy as np
import onnxruntime as ort

SCALE_CROSS = 10.0   # net output * scale = meters (right of centerline positive)
SCALE_HERR = 5.0     # net output * scale = degrees (nose right of runway positive)
CROP_TOP_FRAC = 2.0 / 3.0


def preprocess(img):
    """Any 16:9 cockpit frame -> 1x3x180x480 float tensor."""
    img = cv2.resize(img, (480, 270), interpolation=cv2.INTER_AREA)
    img = img[: int(270 * CROP_TOP_FRAC)]        # drop instrument panel
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    x = img.astype(np.float32).transpose(2, 0, 1)[None] / 255.0 - 0.5
    return x


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    here = os.path.dirname(os.path.abspath(__file__))
    sess = ort.InferenceSession(os.path.join(here, "weights", "deviation.onnx"))
    inp = sess.get_inputs()[0].name
    for path in sys.argv[1:]:
        img = cv2.imread(path)
        if img is None:
            print(f"{path}: cannot read")
            continue
        c, h = sess.run(None, {inp: preprocess(img)})[0][0]
        print(f"{os.path.basename(path)}  "
              f"cross-track {c * SCALE_CROSS:+.2f} m   "
              f"heading error {h * SCALE_HERR:+.2f} deg")


if __name__ == "__main__":
    main()
