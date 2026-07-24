"""
屏幕录制脚本 - 使用 pyautogui
录制演示 GIF 并保存到 assets/ 目录
"""

import os
import sys
import time
from datetime import datetime

try:
    import pyautogui
except ImportError:
    print("请先安装 pyautogui: pip install pyautogui")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("请先安装 Pillow: pip install Pillow")
    sys.exit(1)


def record_screen(duration=60, fps=15, output_file="demo.gif"):
    """
    录制屏幕
    
    Args:
        duration: 录制时长（秒）
        fps: 帧率
        output_file: 输出文件名
    """
    print("=" * 50)
    print("屏幕录制工具")
    print("=" * 50)
    print(f"录制时长: {duration} 秒")
    print(f"帧率: {fps} fps")
    print(f"输出文件: {output_file}")
    print()
    
    # 创建 assets 目录
    assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
    os.makedirs(assets_dir, exist_ok=True)
    
    output_path = os.path.join(assets_dir, output_file)
    
    # 倒计时
    print("录制将在 3 秒后开始...")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    
    print("开始录制！请进行演示...")
    print("按 Ctrl+C 可提前停止录制")
    print()
    
    frames = []
    start_time = time.time()
    frame_count = 0
    
    try:
        while time.time() - start_time < duration:
            # 截取屏幕
            screenshot = pyautogui.screenshot()
            
            # 转换为 RGB（去掉 alpha 通道）
            screenshot = screenshot.convert('RGB')
            
            # 缩小尺寸以减小文件大小
            screenshot = screenshot.resize((1280, 720), Image.LANCZOS)
            
            frames.append(screenshot)
            frame_count += 1
            
            # 显示进度
            elapsed = time.time() - start_time
            remaining = duration - elapsed
            print(f"\r已录制: {elapsed:.1f}s / {duration}s | 帧数: {frame_count} | 剩余: {remaining:.1f}s", end="", flush=True)
            
            # 控制帧率
            time.sleep(1 / fps)
    
    except KeyboardInterrupt:
        print("\n\n录制已手动停止")
    
    if not frames:
        print("未录制到任何帧")
        return
    
    # 保存为 GIF
    print(f"\n\n正在保存 GIF ({len(frames)} 帧)...")
    
    # 使用 Pillow 保存 GIF
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / fps),  # 毫秒
        loop=0,  # 无限循环
        optimize=True,
    )
    
    file_size = os.path.getsize(output_path) / (1024 * 1024)
    
    print(f"\n录制完成！")
    print(f"文件: {output_path}")
    print(f"大小: {file_size:.2f} MB")
    print(f"帧数: {len(frames)}")
    print(f"时长: {len(frames) / fps:.1f} 秒")
    
    return output_path


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="录制演示 GIF")
    parser.add_argument("-d", "--duration", type=int, default=60, help="录制时长（秒），默认 60")
    parser.add_argument("-f", "--fps", type=int, default=15, help="帧率，默认 15")
    parser.add_argument("-o", "--output", type=str, default="demo.gif", help="输出文件名，默认 demo.gif")
    
    args = parser.parse_args()
    
    record_screen(args.duration, args.fps, args.output)


if __name__ == "__main__":
    main()
