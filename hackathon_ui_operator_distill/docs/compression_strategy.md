# Compression Strategy

We do not compress OmniParser v2 directly for the 4 GB laptop first.

Instead:

```text
OmniParser v2 = teacher on cloud GPU
Tiny YOLO/ONNX = student on laptop
```

This is the practical version of the codiii-style idea:

- heavy model lives in the cloud/training phase
- local runtime keeps only the small useful parts
- lazy load models only when needed
- cache previous screen maps
- use structured OS APIs before vision models

## Teacher

OmniParser v2 produces:

- UI bounding boxes
- clickable/icon regions
- optional element descriptions

## Student

Train a tiny detector with these classes:

```text
button
input
checkbox
radio
dropdown
tab
menu
link
icon
```

Recommended first student:

```text
YOLOv8n
```

Export:

```text
ONNX dynamic quantized INT8
```

## Local Runtime Priority

```text
1. Windows UI Automation exact labels
2. OCR text search
3. Tiny UI detector
4. OpenCV visual rectangles
5. Ask user if confidence is low
```

## Memory Budget

Target local memory:

```text
Base scanner: below 250 MB
OCR loaded: below 800 MB if possible
Tiny ONNX model: usually below 200 MB
Full OmniParser: cloud only
```

