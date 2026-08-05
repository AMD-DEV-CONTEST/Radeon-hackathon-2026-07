# 交接日志 (2026-07-30)

## 当前状态
- 42 单元测试 + 6 集成测试通过
- Gradio UI 重新设计：3 Tab 布局 + emerald 主题
- Mock 模式：ComfyUI 不可用时自动生成占位内容
- ffmpeg 已安装，缺 PyTorch+ROCm/ComfyUI/模型

## 变更文件
- ui/components.py - UI 重设计（Tab布局+CSS）
- ui/handlers.py - Mock 模式（_check_comfyui/_mock_generate_frames/_mock_edit_frame/_mock_propagate）
- mock_comfyui.py - 独立 Mock 服务（备用）
- app.py - launch 容错

## 启动
cd /persistent/Radeon-hackathon-2026-07 && python app.py
ssh -R 80:127.0.0.1:7860 nokey@localhost.run  # 公网

## 节点ID
- wan21_i2v: 6=prompt 7=neg 15=image 16=i2v 17=ksampler 20=vhs
- sdxl_inpaint: 4=ckpt 6/7=clip 9/10=image 11=ksampler 12=vae 15=save

## 待办
1. git push + GitHub PR
2. GPU环境装 ComfyUI+模型
3. 更多 UI 反馈
