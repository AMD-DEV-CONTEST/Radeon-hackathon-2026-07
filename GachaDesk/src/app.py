import os
import json
import logging
import tempfile
import requests
import numpy as np
import imageio
import gradio as gr
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urljoin, urlparse, urlunparse

# 尝试加载 .env 文件（需要 pip install python-dotenv）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==========================================
# 配置区（从环境变量读取）
# ==========================================
MODELSCOPE_TOKEN = os.getenv("MODELSCOPE_API_TOKEN", "")
# 文生图应用
TEXT2IMG_BASE_URL = "https://studio-xihuyisheng-qwen-image-2512-amd-mi308x.api-inference.modelscope.net"
# 图生图应用
IMG2IMG_BASE_URL = "https://studio-xihuyisheng-qwen-image-edit-2511-amd-mi308x.api-inference.modelscope.net"
# 图生视频应用（MCP 入口：{URL}/gradio_api/mcp/）
IMG2VIDEO_BASE_URL = "https://studio-xihuyisheng-wan2-2-14b-i2v-lora-amd-mi308x.api-inference.modelscope.net"
# 图生视频默认参数（对应远程 /config 中 id=18/19/22/23/24/16）
IMG2VIDEO_MODEL = "Wan-AI/Wan2.2-I2V-A14B-Diffusers"   # 主模型
IMG2VIDEO_LORA = "LightX2V (4步极速生成 LoRA)"          # 加速 LoRA（4步出片）
IMG2VIDEO_RESOLUTION = "768x432"                        # 分辨率（可选 1280x720/832x480/768x432）
IMG2VIDEO_FRAMES = "81"                                 # 总帧数（可选 81/121，固定16FPS）
IMG2VIDEO_WATERMARK = ""                                # 水印文字，留空不添加
IMG2VIDEO_NEGATIVE_PROMPT = "暴力，变形，扭曲，崩坏，模糊，水印，鬼影, 扭曲的脸,多余肢体, 多余角色"

# 图生图默认参数（对应远程 /config 中 id=25/26/27/28）
IMG2IMG_RESOLUTION = "1664x928"   # 仅支持 16:9
IMG2IMG_STEPS = 4
IMG2IMG_CFG = 1.5

# 默认负向提示词
DEFAULT_NEGATIVE_PROMPT = "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲。"

# 默认 CFG 与随机种子（与远程应用 /config 中 id=24/26 默认值一致）
DEFAULT_CFG = 4.0
DEFAULT_SEED = -1

# 尺寸选项（与远程应用 /config 中 id=21 的 dropdown 完全一致）
SIZE_OPTIONS = [
    "1:1 正方形 (1328×1328)",
    "16:9 横屏 (1664×928)",
    "9:16 竖屏 (928×1664)",
    "4:3 横屏 (1472×1140)",
    "3:4 竖屏 (1140×1472)",
    "3:2 横屏 (1584×1056)",
    "2:3 竖屏 (1056×1584)",
]
# 远程应用默认尺寸
DEFAULT_SIZE = "16:9 横屏 (1664×928)"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("TextToImage")


# ==========================================
# ModelScope API 客户端
# ==========================================
class ModelScopeImageClient:
    """封装对 ModelScope 创空间 Gradio API 的调用"""

    def __init__(self, base_url, token):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://modelscope.cn"
        })

    def discover_api(self):
        """探测 API 端点：返回 (mode, api_name, api_prefix)"""
        resp = self.session.get(urljoin(self.base_url, "/config"))
        if resp.status_code == 200:
            cfg = resp.json()
            api_prefix = cfg.get("api_prefix", "")
            for dep in cfg.get("dependencies", []):
                if dep.get("backend_fn") and dep.get("api_name"):
                    return "call", dep.get("api_name"), api_prefix
        raise Exception("无法探测到有效的 API 端点")

    def submit_task(self, mode, api_name, api_prefix, payload):
        """提交文生图任务，返回 event_id"""
        url = urljoin(self.base_url, f"{api_prefix}/{mode}/{api_name}")
        resp = self.session.post(url, json={"data": payload})
        if resp.status_code == 200 and "event_id" in resp.json():
            return resp.json()["event_id"]
        raise Exception(f"任务提交失败: {resp.text}")

    def listen_sse(self, api_name, event_id, api_prefix):
        """监听 SSE 流。返回 (image_data, log_text) 或状态字符串"""
        url = urljoin(self.base_url, f"{api_prefix}/call/{api_name}/{event_id}")
        with self.session.get(url, stream=True, headers={"Accept": "text/event-stream"}) as resp:
            if resp.status_code != 200:
                return None
            final_image = None
            log_text = ""
            current_event = "message"
            for line in resp.iter_lines():
                if not line:
                    continue
                decoded = line.decode('utf-8')
                if decoded.startswith("event:"):
                    current_event = decoded[6:].strip()
                    continue
                if decoded.startswith("data:"):
                    data_str = decoded[5:].strip()
                    if data_str == "null":
                        continue
                    try:
                        data_json = json.loads(data_str)
                        # 排队检测：拒绝排队
                        if isinstance(data_json, dict) and data_json.get("msg") == "estimation":
                            if data_json.get("rank", 0) > 0:
                                return "QUEUE_ABORTED"
                        # 通用输出解析：第一个元素为图片，第二个元素（若存在）为日志
                        if isinstance(data_json, list) and data_json:
                            if isinstance(data_json[0], dict) and "url" in data_json[0]:
                                final_image = data_json[0]
                            if len(data_json) >= 2 and isinstance(data_json[1], str):
                                log_text = data_json[1]
                    except json.JSONDecodeError:
                        pass
            return (final_image, log_text)

    def download_image(self, image_data):
        """通过 API 网关下载图片到本地临时文件，返回路径"""
        if not image_data or "url" not in image_data:
            return None
        # 通用：把图片 URL 的 host 替换为当前应用 API 网关 host（鉴权用）
        parsed = urlparse(image_data["url"])
        api_host = urlparse(self.base_url).netloc
        if parsed.netloc != api_host:
            img_url = urlunparse(parsed._replace(netloc=api_host))
        else:
            img_url = image_data["url"]
        img_resp = self.session.get(img_url, headers={"Referer": "https://modelscope.cn/"})
        if img_resp.status_code == 200:
            tmp_path = os.path.join(
                tempfile.gettempdir(),
                image_data.get("orig_name", "output.png")
            )
            with open(tmp_path, "wb") as f:
                f.write(img_resp.content)
            return tmp_path
        return None

    def upload_image(self, image_path):
        """上传本地图片到远程 Gradio 服务，返回服务端 path 字符串"""
        with open(image_path, "rb") as f:
            resp = self.session.post(
                urljoin(self.base_url, "/gradio_api/upload"),
                files={"files": (os.path.basename(image_path), f, "image/webp")},
            )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0]
        raise Exception(f"图片上传失败: {resp.text}")


# ==========================================
# 文生图主函数
# ==========================================
def generate_image(prompt, size, steps):
    """Gradio 回调：调用远程 API 生成图片，返回 (图片路径, 状态信息, 运行日志)"""
    if not MODELSCOPE_TOKEN:
        return None, "❌ 请先在 .env 中配置 MODELSCOPE_API_TOKEN", ""
    if not prompt.strip():
        return None, "❌ 请输入正向提示词", ""

    try:
        client = ModelScopeImageClient(TEXT2IMG_BASE_URL, MODELSCOPE_TOKEN)
        mode, api_name, api_prefix = client.discover_api()
        logger.info(f"API 端点: {api_name}")

        payload = [
            prompt,
            DEFAULT_NEGATIVE_PROMPT,  # 负向提示词使用默认值
            size,
            int(steps),
            DEFAULT_CFG,              # CFG 使用默认值
            DEFAULT_SEED,             # 种子使用默认值（-1 随机）
        ]
        event_id = client.submit_task(mode, api_name, api_prefix, payload)
        logger.info(f"任务已提交，event_id={event_id}")

        result = client.listen_sse(api_name, event_id, api_prefix)

        if result == "QUEUE_ABORTED":
            return None, "⚠️ 当前排队人数较多，请稍后重试", ""
        if not result or not result[0] or "url" not in result[0]:
            return None, "⚠️ 未能获取到图片", result[1] if result else ""

        img_path = client.download_image(result[0])
        log_text = result[1]
        if img_path:
            return img_path, "✅ 图片生成成功！", log_text
        return None, "❌ 图片下载失败", log_text
    except Exception as e:
        logger.error(f"生成失败: {e}", exc_info=True)
        return None, f"❌ 生成失败: {str(e)}", ""


# ==========================================
# 图生图主函数
# ==========================================
def generate_img2img(input_image_path, prompt):
    """Gradio 回调：把主操作台图片通过图生图 API 编译，返回 (图片路径, 状态信息)"""
    if not MODELSCOPE_TOKEN:
        return None, "❌ 请先在 .env 中配置 MODELSCOPE_API_TOKEN"
    if not input_image_path:
        return None, "❌ 请先在主操作台上传图片"
    if not prompt.strip():
        return None, "❌ 请输入正向提示词"

    try:
        client = ModelScopeImageClient(IMG2IMG_BASE_URL, MODELSCOPE_TOKEN)
        mode, api_name, api_prefix = client.discover_api()
        logger.info(f"图生图 API 端点: {api_name}")

        # 1. 上传图片到远程服务，获取服务端 path
        uploaded_path = client.upload_image(input_image_path)
        logger.info(f"图片已上传: {uploaded_path}")

        # 2. 构造 payload（inputs=[5,6,7,25,26,27,28]）
        payload = [
            {"path": uploaded_path, "meta": {"_type": "gradio.FileData"}},
            prompt,
            DEFAULT_NEGATIVE_PROMPT,
            IMG2IMG_RESOLUTION,
            IMG2IMG_STEPS,
            IMG2IMG_CFG,
            DEFAULT_SEED,
        ]
        event_id = client.submit_task(mode, api_name, api_prefix, payload)
        logger.info(f"图生图任务已提交，event_id={event_id}")

        result = client.listen_sse(api_name, event_id, api_prefix)

        if result == "QUEUE_ABORTED":
            return None, "⚠️ 当前排队人数较多，请稍后重试"
        if not result or not result[0] or "url" not in result[0]:
            return None, "⚠️ 未能获取到图片"

        img_path = client.download_image(result[0])
        if img_path:
            return img_path, "✅ 图生图成功！"
        return None, "❌ 图片下载失败"
    except Exception as e:
        logger.error(f"图生图失败: {e}", exc_info=True)
        return None, f"❌ 图生图失败: {str(e)}"


# ==========================================
# 图生视频主函数
# ==========================================
def generate_img2video(input_image_path, prompt):
    """Gradio 回调：把分镜图片通过图生视频 API 生成视频，返回 (视频路径, 运行日志)"""
    if not MODELSCOPE_TOKEN:
        return None, "❌ 请先在 .env 中配置 MODELSCOPE_API_TOKEN"
    if not input_image_path:
        return None, "❌ 请先提供图片"
    if not prompt.strip():
        return None, "❌ 请输入正向提示词"

    try:
        client = ModelScopeImageClient(IMG2VIDEO_BASE_URL, MODELSCOPE_TOKEN)
        # 图生视频应用的端点固定（/config 中首个 dep 是 lambda，不能自动探测）
        mode, api_name, api_prefix = "call", "generate_video", "/gradio_api"
        logger.info(f"图生视频 API 端点: {api_name}")

        # 1. 上传图片到远程服务，获取服务端 path
        uploaded_path = client.upload_image(input_image_path)
        logger.info(f"图片已上传: {uploaded_path}")

        # 2. 构造 payload（inputs=[4,11,9,18,19,22,23,24,16]）
        payload = [
            {"path": uploaded_path, "meta": {"_type": "gradio.FileData"}},
            prompt,
            IMG2VIDEO_NEGATIVE_PROMPT,
            IMG2VIDEO_MODEL,
            IMG2VIDEO_LORA,
            IMG2VIDEO_RESOLUTION,
            IMG2VIDEO_FRAMES,
            DEFAULT_SEED,
            IMG2VIDEO_WATERMARK,
        ]
        event_id = client.submit_task(mode, api_name, api_prefix, payload)
        logger.info(f"图生视频任务已提交，event_id={event_id}")

        result = client.listen_sse(api_name, event_id, api_prefix)

        if result == "QUEUE_ABORTED":
            return None, "⚠️ 当前排队人数较多，请稍后重试"
        if not result or not result[0] or "url" not in result[0]:
            return None, "⚠️ 未能获取到视频"

        video_path = client.download_image(result[0])
        log_text = result[1]
        if video_path:
            return video_path, f"✅ 图生视频成功！\n{log_text}"
        return None, "❌ 视频下载失败"
    except Exception as e:
        logger.error(f"图生视频失败: {e}", exc_info=True)
        return None, f"❌ 图生视频失败: {str(e)}"


# ==========================================
# 8图合片：把分镜台8张图按每图16帧拼接成视频
# ==========================================
# 字体候选列表：优先 Linux（Ubuntu/Debian 的 DejaVu），Windows 兜底
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Ubuntu/Debian 默认路径
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",  # 其他 Linux 的 DejaVu 路径
    "DejaVuSans.ttf",  # Linux 按名查找
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",  # CentOS/RHEL
    "LiberationSans-Regular.ttf",  # Linux Liberation 按名查找
    "arial.ttf",  # Windows
]
# 启动时探测一次可用的 TrueType 字体名
_RESOLVED_FONT = None
for _cand in _FONT_CANDIDATES:
    try:
        ImageFont.truetype(_cand, 20)
        _RESOLVED_FONT = _cand
        logger.info(f"水印字体已选用: {_cand}")
        break
    except Exception:
        continue
if not _RESOLVED_FONT:
    logger.warning("⚠️ 未找到 TrueType 字体，水印将使用默认位图字体（可能模糊）")


def add_watermark(frame_img, text):
    """在帧右下角添加水印文字（带黑色阴影提升可读性），返回 PIL.Image"""
    draw = ImageDraw.Draw(frame_img)
    # 字体大小按图片宽度自适应
    font_size = max(16, frame_img.width // 40)
    if _RESOLVED_FONT:
        try:
            font = ImageFont.truetype(_RESOLVED_FONT, font_size)
        except Exception:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()
    # 计算文字尺寸
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # 右下角留边距
    margin = max(10, frame_img.width // 80)
    x = frame_img.width - tw - margin
    y = frame_img.height - th - margin
    # 黑色阴影 + 白色文字
    draw.text((x + 2, y + 2), text, fill=(0, 0, 0), font=font)
    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    return frame_img


def get_video_last_frame(video_path):
    """读取视频最后一帧，保存为临时图片文件并返回路径，失败返回 None"""
    if not video_path or not isinstance(video_path, str) or not os.path.exists(video_path):
        return None, "❌ 视频文件不存在"
    try:
        reader = imageio.get_reader(video_path)
        frames = []
        for frame in reader:
            frames.append(frame)
        reader.close()
        if not frames:
            return None, "❌ 视频为空，无帧可提取"
        last_frame = frames[-1]
        # 确保是 RGB
        if len(last_frame.shape) == 3 and last_frame.shape[2] == 4:
            last_frame = last_frame[:, :, :3]
        img = Image.fromarray(last_frame)
        tmp_path = os.path.join(tempfile.gettempdir(), f"last_frame_{os.path.basename(video_path).split('.')[0]}.png")
        img.save(tmp_path)
        return tmp_path, f"✅ 已提取视频最后一帧（共{len(frames)}帧）"
    except Exception as e:
        logger.error(f"提取视频帧失败: {e}", exc_info=True)
        return None, f"❌ 提取帧失败: {str(e)}"


def merge_8_images_to_video(watermark, *images):
    """把8张图片按每张16帧拼接成视频，watermark 非空则在右下角加水印，返回 (视频路径, 状态信息)"""
    fps = 8
    frames_per_image = 16
    # 过滤有效图片
    valid_imgs = [img for img in images if img and isinstance(img, str) and os.path.exists(img)]
    if not valid_imgs:
        return None, "❌ 分镜台没有可用的图片"

    try:
        # 统一尺寸：以第一张图为基准
        base = Image.open(valid_imgs[0]).convert("RGB")
        w, h = base.size
        # libx264 要求宽高为偶数
        if w % 2: w -= 1
        if h % 2: h -= 1

        output_path = os.path.join(tempfile.gettempdir(), "storyboard_merged.mp4")
        writer = imageio.get_writer(output_path, fps=fps, codec="libx264",
                                    macro_block_size=1, quality=10)
        try:
            for img_path in valid_imgs:
                frame = Image.open(img_path).convert("RGB").resize((w, h))
                # 若设置了水印则绘制
                if watermark and watermark.strip():
                    frame = add_watermark(frame, watermark.strip())
                arr = np.array(frame)
                for _ in range(frames_per_image):
                    writer.append_data(arr)
        finally:
            writer.close()

        total = len(valid_imgs) * frames_per_image
        wm_tip = "（已加水印）" if (watermark and watermark.strip()) else "（无水印）"
        return output_path, f"✅ 合片完成：{len(valid_imgs)}张图 × {frames_per_image}帧 = {total}帧（{total/fps:.1f}秒）{wm_tip}"
    except Exception as e:
        logger.error(f"合片失败: {e}", exc_info=True)
        return None, f"❌ 合片失败: {str(e)}"


# ==========================================
# 8镜合片：把分镜台8个视频按顺序拼接成长视频
# ==========================================
def merge_8_videos_to_long(watermark, *videos):
    """Gradio 回调：把8个分镜视频顺序拼接成一个长视频（可选水印），返回 (视频路径, 状态信息)"""
    try:
        valid_videos = [v for v in videos if v and isinstance(v, str) and os.path.exists(v)]
        if not valid_videos:
            return None, "❌ 没有可用的分镜视频，请先在分镜台生成视频"

        logger.info(f"准备拼接 {len(valid_videos)} 个视频...")
        # fps 以第一个视频为准
        reader = imageio.get_reader(valid_videos[0])
        first_meta = reader.get_meta_data()
        fps = first_meta.get("fps", 16)
        reader.close()

        wm_text = watermark.strip() if isinstance(watermark, str) and watermark else ""

        output_path = os.path.join(tempfile.gettempdir(), "storyboard_videos_merged.mp4")
        writer = imageio.get_writer(output_path, fps=fps, codec="libx264",
                                    macro_block_size=1, quality=8)
        total_frames = 0
        try:
            for idx, vpath in enumerate(valid_videos):
                logger.info(f"正在处理第 {idx+1}/{len(valid_videos)} 个视频: {vpath}")
                reader = imageio.get_reader(vpath)
                for frame in reader:
                    # 确保帧是 RGB 格式（排除 RGBA 等）
                    if len(frame.shape) == 3 and frame.shape[2] == 4:
                        frame = frame[:, :, :3]  # 去掉 alpha 通道
                    # 若设置了水印则逐帧绘制
                    if wm_text:
                        frame = np.array(
                            add_watermark(Image.fromarray(frame), wm_text)
                        )
                    writer.append_data(frame)
                    total_frames += 1
                reader.close()
        finally:
            writer.close()

        wm_tip = "（已加水印）" if wm_text else "（无水印）"
        logger.info(f"✅ 8镜合片完成：{len(valid_videos)}个视频，共{total_frames}帧")
        return output_path, f"✅ 8镜合片完成：{len(valid_videos)}个视频拼接，共{total_frames}帧（{total_frames/fps:.1f}秒）{wm_tip}"
    except Exception as e:
        logger.error(f"8镜合片失败: {e}", exc_info=True)
        return None, f"❌ 8镜合片失败: {str(e)}"


# ==========================================
# Gradio 界面
# ==========================================
with gr.Blocks(title="视频工作台 / Video Workbench") as demo:
    gr.Markdown("# 🎨 视频工作台 / Video Workbench")
    gr.Markdown("#### 功能 / Features:文生图 + 图生图 + 图生视频 + 反向提示词 + 分镜 + 合片<br>Text-to-Image + Image-to-Image + Image-to-Video + Negative Prompt + Storyboard + Merging")
    gr.Markdown("""
    > **适用场景 / Application Scenarios**:
    > 🏫 **乡村助教课件 / Rural Teaching Aids** —— 为乡村教师快速生成配图素材,让课件生动直观;<br>Quickly generate illustration materials for rural teachers, making classes vivid and intuitive.
    > 👗 **女装宣传展示 / Fashion Showcase** —— 一键生成服装上身效果图与宣传短视频,低成本打造商品展示;<br>One-click generation of clothing on-body effects and promotional short videos, building product displays at low cost.
    > 🌄 **文旅风光推广 / Tourism Promotion** —— 生成景区意境图与分镜短片,助力乡村文旅宣传;<br>Generate scenic mood images and storyboard shorts to boost rural tourism marketing.
    > 🥬 **农产直播带货 / Agricultural Live Commerce** —— 为农产品制作精美海报与预告短片,提升带货转化;<br>Create beautiful posters and teaser clips for agricultural products to lift conversion rates.
    > 📱 **短视频素材库 / Short Video Material Library** —— 批量产出多分镜画面,快速合成创意短视频。<br>Batch-produce multi-shot frames and quickly compose creative short videos.
    """)

    # 主操作台：用户上传一张图片
    # 主操作台：用户上传一张图片
    with gr.Accordion("📂 主操作台", open=True):
        main_image = gr.Image(label="上传图片", type="filepath")
    
    with gr.Row():
        # 左侧：输入区（参数与远程应用 /config 中 id=5/21/23 对应）
        with gr.Column():
            prompt = gr.Textbox(label="正向提示词", placeholder="描述你想生成的画面...", lines=3)
            size = gr.Dropdown(choices=SIZE_OPTIONS, value=DEFAULT_SIZE, label="尺寸")
            # id=23：步数 10-100，默认 25
            steps = gr.Slider(minimum=10, maximum=100, value=25, step=1, label="推理步数")
            btn = gr.Button("文生图", variant="primary")
            # 图生图按钮：以主操作台图片为输入进行编译
            img2img_btn = gr.Button("图生图", variant="primary")

        # 右侧：输出区（对应远程 outputs=[19, 14]）
        with gr.Column():
            # 文生图结果图 + 推送按钮（推送至主操作台）
            with gr.Row():
                output_image = gr.Image(label="文生图结果图", type="filepath")
                push_text2img_btn = gr.Button("推送操作台", variant="secondary")
                push_sb1_btn = gr.Button("推送分镜1", variant="secondary")
            # 图生图结果图 + 推送按钮（推送至主操作台）
            with gr.Row():
                img2img_output = gr.Image(label="图生图结果图", type="filepath")
                push_img2img_btn = gr.Button("推送操作台", variant="secondary")
                push_sb2_btn = gr.Button("推送分镜2", variant="secondary")

            output_status = gr.Textbox(label="状态", interactive=False)
            output_log = gr.Textbox(label="运行日志", interactive=False, lines=8)

    btn.click(
        fn=generate_image,
        inputs=[prompt, size, steps],
        outputs=[output_image, output_status, output_log],
    )
    # 图生图：以主操作台图片 + 提示词为输入，结果输出到 img2img_output
    img2img_btn.click(
        fn=generate_img2img,
        inputs=[main_image, prompt],
        outputs=[img2img_output, output_status],
    )
    # 推送文生图结果到主操作台
    push_text2img_btn.click(fn=lambda img: img, inputs=[output_image], outputs=[main_image])
    # 推送图生图结果到主操作台
    push_img2img_btn.click(fn=lambda img: img, inputs=[img2img_output], outputs=[main_image])

    # 8 个分镜台（2 行 × 4 列），每个分镜台包含：图片、正向提示词、视频
    storyboard_images = []
    storyboard_prompts = []
    storyboard_videos = []
    storyboard_img2img_btns = []
    storyboard_img2video_btns = []
    storyboard_continue_btns = []  # 续帧按钮
    with gr.Accordion("🎬 分镜台", open=False):
        gr.Markdown("### 8 个分镜")
        for row_idx in range(2):
            with gr.Row():
                for col_idx in range(4):
                    idx = row_idx * 4 + col_idx + 1
                    with gr.Column():
                        gr.Markdown(f"**分镜 {idx}**")
                        storyboard_images.append(
                            gr.Image(label=f"图片{idx}", type="filepath")
                        )
                        storyboard_prompts.append(
                            gr.Textbox(label=f"提示词{idx}", lines=2)
                        )
                        storyboard_img2img_btns.append(
                            gr.Button(f"图生图{idx}", variant="secondary")
                        )
                        storyboard_img2video_btns.append(
                            gr.Button(f"图生视频{idx}", variant="secondary")
                        )
                        storyboard_videos.append(
                            gr.Video(label=f"视频{idx}")
                        )
                        # 续帧按钮：第8镜无下一镜，不显示
                        if idx < 8:
                            storyboard_continue_btns.append(
                                gr.Button(f"续帧{idx}→{idx+1}", variant="secondary")
                            )
                        else:
                            storyboard_continue_btns.append(None)

    # 每个分镜的图生图按钮：主操作台图片 + 本分镜提示词 → 生成本分镜图片
    for i in range(8):
        storyboard_img2img_btns[i].click(
            fn=generate_img2img,
            inputs=[main_image, storyboard_prompts[i]],
            outputs=[storyboard_images[i], output_log],
        )

    # 每个分镜的图生视频按钮：本分镜图片 + 本分镜提示词 → 生成本分镜视频
    for i in range(8):
        storyboard_img2video_btns[i].click(
            fn=generate_img2video,
            inputs=[storyboard_images[i], storyboard_prompts[i]],
            outputs=[storyboard_videos[i], output_log],
        )

    # 续帧按钮：本镜视频最后一帧 → 下一镜图片（共7个：1→2, 2→3, ... 7→8）
    for i in range(7):
        # 使用闭包捕获当前 i，避免 Python 延迟绑定陷阱
        def make_continue_fn(idx):
            def _fn(vpath):
                img_path, msg = get_video_last_frame(vpath)
                return img_path, msg
            return _fn
        storyboard_continue_btns[i].click(
            fn=make_continue_fn(i),
            inputs=[storyboard_videos[i]],
            outputs=[storyboard_images[i + 1], output_log],
        )

    # 推送文生图结果到分镜1
    push_sb1_btn.click(fn=lambda img: img, inputs=[output_image], outputs=[storyboard_images[0]])
    # 推送图生图结果到分镜2
    push_sb2_btn.click(fn=lambda img: img, inputs=[img2img_output], outputs=[storyboard_images[1]])

    # 合片区：把8个分镜的图片按每图16帧拼接成视频
    with gr.Accordion("🎞️ 合片区", open=False):
        with gr.Row():
            merge_btn = gr.Button("8图合片", variant="primary")
            merge_video_btn = gr.Button("8镜合片", variant="primary")

            watermark_input = gr.Textbox(
                label="水印内容（留空则不添加）",
                placeholder="",
                value="AI ART XIHUYISHENG AMD RADEON",
                scale=1,
            )
        merged_video = gr.Video(label="合片视频")

    # 合片：输入水印+8个分镜图片，输出到合片视频+运行日志
    merge_btn.click(
        fn=merge_8_images_to_video,
        inputs=[watermark_input] + storyboard_images,
        outputs=[merged_video, output_log],
    )

    # 8镜合片：把8个分镜视频顺序拼接成长视频（水印作为第一个输入）
    merge_video_btn.click(
        fn=merge_8_videos_to_long,
        inputs=[watermark_input] + storyboard_videos,
        outputs=[merged_video, output_log],
    )

    gr.Markdown("""
    **⚠️ 免责声明**：本工具仅供学习研究使用。用户需遵守法律法规及平台规范，严禁生成违法违规、有害信息、价值观导向不正、虚假信息或侵权内容。用户对生成内容负全部责任，开发者不对用户生成内容承担法律责任。
    """)


if __name__ == "__main__":
    demo.launch()
