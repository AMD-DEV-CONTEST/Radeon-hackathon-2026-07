import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="SparkFencer — AI 击剑训练视频分析系统")
    parser.add_argument("--video-path", required=True, help="输入视频文件路径")
    parser.add_argument("--corners", default=None,
                        help='剑道 4 角点（图像坐标）："x1,y1 x2,y2 x3,y3 x4,y4"，顺序：远左、远右、近右、近左')
    parser.add_argument("--piste-length", type=float, default=None,
                        help="标注角点覆盖的剑道长度（米），默认 14；只拍到部分剑道时按实际长度填写")
    parser.add_argument("--output-dir", default=None, help="输出目录，默认 outputs/<视频名>")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--stages", default="perception,analysis,evidence,agents,report",
                        help="要运行的阶段，逗号分隔：perception,analysis,evidence,agents,report")
    parser.add_argument("--skip-agents", action="store_true", help="跳过 AI Agent 验证，用规则模板生成报告")
    parser.add_argument("--agent-backend", choices=["claude", "local"], default=None,
                        help="覆盖 Agent 后端：claude（Anthropic API）或 local（OpenAI 兼容 VLM）")
    parser.add_argument("--pose-device", default=None,
                        help="姿态推理设备：auto(默认)/cpu/0；GPU 显存被占满时用 cpu 兜底")
    parser.add_argument("--max-events", type=int, default=None,
                        help="Agent 验证的最大事件数（覆盖 config，用于快速小范围验证）")
    parser.add_argument("--blade-detector", choices=["cv", "yolo"], default=None,
                        help="剑尖检测器：cv(线段检测) 或 yolo(微调模型)")
    parser.add_argument("--blade-filter", choices=["kalman", "ema", "none"], default=None,
                        help="剑尖滤波方式：kalman/ema/none(原始点)")
    parser.add_argument("--export-frame", action="store_true",
                        help="只导出第一帧（用于标注剑道角点）后退出")
    args = parser.parse_args()

    from fencing_analysis.piste.mapper import parse_corners_arg
    from fencing_analysis.pipeline import run_pipeline

    if args.export_frame:
        import cv2
        cap = cv2.VideoCapture(args.video_path)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            print(f"无法读取视频: {args.video_path}")
            sys.exit(1)
        video_name = os.path.splitext(os.path.basename(args.video_path))[0]
        out_dir = args.output_dir or os.path.join("outputs", video_name)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "first_frame.png")
        cv2.imwrite(path, frame)
        print(f"第一帧已导出: {path}")
        print('在图上确定剑道 4 角点后，用 --corners "x1,y1 x2,y2 x3,y3 x4,y4" 重新运行。')
        return

    corners = parse_corners_arg(args.corners) if args.corners else None
    stages = tuple(s.strip() for s in args.stages.split(",") if s.strip())

    config_path = args.config if os.path.exists(args.config) else None

    overrides = {}
    if args.piste_length is not None:
        overrides["piste"] = {"length": args.piste_length}
    if args.agent_backend:
        overrides["agents"] = {"backend": args.agent_backend}
    if args.pose_device:
        overrides["pose"] = {"device": args.pose_device}
    if args.max_events is not None:
        overrides["agents"] = {**overrides.get("agents", {}), "max_events_to_review": args.max_events}
    if args.blade_detector:
        overrides["blade"] = {**overrides.get("blade", {}), "detector": args.blade_detector}
    if args.blade_filter:
        overrides["blade"] = {**overrides.get("blade", {}), "filter": args.blade_filter}

    results = run_pipeline(
        args.video_path,
        corners=corners,
        output_dir=args.output_dir,
        config_path=config_path,
        config_overrides=overrides,
        stages=stages,
        skip_agents=args.skip_agents,
    )

    print("\n=== SparkFencer 完成 ===")
    for key, value in results.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
