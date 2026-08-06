# 单 seed 演示跑：完全复用原版 prompt/参数，仅出 1 张
import os, time
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
import torch
from diffusers import StableDiffusionXLPipeline, EulerAncestralDiscreteScheduler

pipe = StableDiffusionXLPipeline.from_pretrained(
    'cagliostrolab/animagine-xl-4.0', torch_dtype=torch.float16, use_safetensors=True
).to('cuda')
pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)

PROMPT = ('1girl, solo, chibi, cat girl, cat ears, fang, pink hair, '
    'crossed arms, pout, blush stickers, sticker, thick outline, white border, '
    'flat color, vivid colors, pastel green background, simple background, upper body, '
    'masterpiece, high score, great score, absurdres')
NEG = ('lowres, bad anatomy, bad hands, extra digits, fewer digits, cropped, '
    'worst quality, low quality, low score, bad score, average score, '
    'signature, watermark, jpeg artifacts, blurry, 3d, realistic, gradient background')

seed = 20260728
g = torch.Generator('cuda').manual_seed(seed)
t0 = time.time()
img = pipe(prompt=PROMPT, negative_prompt=NEG,
    num_inference_steps=28, guidance_scale=5.5,
    width=1024, height=1024, generator=g).images[0]
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_pvc_out = '/workspace'
_out_dir = _pvc_out if os.path.isdir(_pvc_out) else os.path.join(_PROJECT_ROOT, 'output')
os.makedirs(_out_dir, exist_ok=True)
_out_path = os.path.join(_out_dir, 'run_one_20260728.png')
img.save(_out_path)
print(f'DONE seed {seed} in {time.time()-t0:.1f}s -> {_out_path}')
