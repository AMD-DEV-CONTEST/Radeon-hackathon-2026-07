#!/usr/bin/env python3
"""Export Bundler — STEP + 标准报价单XLSX + 图纸 → ZIP
支持XAI推理链展示的专业报价单
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统"""
import os, json, zipfile, io
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

EXPORT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

def create_bundle(task_id: str, files: list, quote_data: dict = None, 
                  metadata: dict = None, reasoning_chain: dict = None) -> dict:
    """创建交付ZIP包
    
    Args:
        task_id: 任务ID
        files: [{"path": "/abs/path", "name": "display_name.step"}, ...]
        quote_data: 报价JSON
        metadata: 任务元数据
        reasoning_chain: XAI推理链数据 (可选)
    
    Returns:
        {"zip_file", "zip_url", "size_kb", "files_count"}
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. 加源文件
        for f in files:
            if os.path.exists(f["path"]):
                zf.write(f["path"], f["name"])
        
        # 2. 生成专业报价单XLSX (含推理链)
        if quote_data:
            try:
                from src.runtime.quote_xlsx_generator import generate_quote_xlsx
                
                # 生成专业报价单
                xlsx_bytes = generate_quote_xlsx(
                    quote_data=quote_data,
                    reasoning_chain=reasoning_chain,
                    part_info=metadata
                )
                zf.writestr("CNC报价单.xlsx", xlsx_bytes)
                
                # 同时生成推理链JSON (方便追溯)
                if reasoning_chain:
                    zf.writestr("推理链详情.json", 
                               json.dumps(reasoning_chain, ensure_ascii=False, indent=2))
                    
            except Exception as e:
                # 如果XLSX生成失败，回退到CSV格式
                print(f"[WARN] XLSX生成失败，回退到CSV: {e}")
                import traceback
                traceback.print_exc()
                print(f"[DEBUG] quote_data keys: {list(quote_data.keys()) if quote_data else 'None'}")
                print(f"[DEBUG] reasoning_chain: {reasoning_chain is not None}")
                
                csv_lines = [
                    "项目,值",
                    f"材料,{quote_data.get('material', '-')}",
                    f"数量,{quote_data.get('quantity', '-')}",
                    f"表面处理,{quote_data.get('surface_treatment', quote_data.get('surface', '无'))}",
                    f"单件重量(kg),{quote_data.get('weight_kg', '-')}",
                    f"单件价格,{quote_data.get('unit_price', '-')}",
                    f"总价,{quote_data.get('final_price', quote_data.get('total_price', '-'))}",
                    f"生成时间,{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ]
                zf.writestr("报价明细.csv", "\n".join(csv_lines))
        
        # 3. 加元数据
        if metadata:
            zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        
        # 4. 加免责声明和说明
        disclaimer = generate_disclaimer(quote_data, reasoning_chain)
        zf.writestr("README.txt", disclaimer)
    
    # 保存
    zip_name = f"bundle_{task_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = EXPORT_DIR / zip_name
    zip_path.write_bytes(buf.getvalue())
    
    # 计算文件数量
    files_count = len(files)
    if quote_data:
        files_count += 1  # XLSX
        if reasoning_chain:
            files_count += 1  # 推理链JSON
    files_count += 1  # README
    
    return {
        "zip_file": str(zip_path),
        "zip_url": f"/api/download/{zip_name}",
        "size_kb": round(len(buf.getvalue()) / 1024, 1),
        "files_count": files_count,
        "has_reasoning": reasoning_chain is not None,
    }


def generate_disclaimer(quote_data: dict = None, reasoning_chain: dict = None) -> str:
    """生成免责声明和说明"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    lines = [
        "=" * 60,
        "CNC AI 工艺大脑 - 智能报价系统",
        "=" * 60,
        "",
        "【免责声明】",
        "1. 此报价由CNC AI工艺大脑智能生成，仅供参考",
        "2. 报价计算完全还原Excel手工报价公式",
        "3. 实际加工前请人工确认所有技术参数",
        "4. 报价有效期为7个工作日，逾期请重新询价",
        "",
        "【技术说明】",
        "• 报价引擎: quote-v3.0 (Excel还原)",
        "• 公式: N27 = (L24+M15+O6+L20)/(1-H27)*L27",
        "• 采用XAI可解释AI技术，所有计算步骤可追溯",
        "",
    ]
    
    if quote_data:
        lines.extend([
            "【报价摘要】",
            f"• 材料: {quote_data.get('material', '—')}",
            f"• 数量: {quote_data.get('quantity', '—')} 件",
            f"• 单价: ¥{quote_data.get('unit_price', '—')}",
            f"• 总价: ¥{quote_data.get('final_price', quote_data.get('total_price', '—'))}",
            f"• 工艺: {quote_data.get('process', 'CNC三轴')}",
            f"• 表面处理: {quote_data.get('surface', quote_data.get('surface_treatment', '无'))}",
            "",
        ])
    
    if reasoning_chain:
        confidence = reasoning_chain.get('overall_confidence', 0)
        steps_count = reasoning_chain.get('total_steps', 0)
        elapsed = reasoning_chain.get('elapsed_ms', 0)
        
        lines.extend([
            "【推理链信息】",
            f"• 置信度: {confidence*100:.1f}%",
            f"• 推理步骤: {steps_count}步",
            f"• 计算耗时: {elapsed:.0f}ms",
            f"• 详细推理链请查看: 推理链详情.json",
            "",
        ])
        
        # 添加警告信息
        warnings = reasoning_chain.get('warnings', [])
        if warnings:
            lines.extend([
                "【⚠️ 警告信息】",
            ])
            for warning in warnings:
                lines.append(f"• {warning}")
            lines.append("")
    
    lines.extend([
        "【文件清单】",
        "• *.step - CAD源文件",
        "• CNC报价单.xlsx - 专业报价单 (含推理链)",
        "• 推理链详情.json - XAI推理过程记录",
        "• metadata.json - 任务元数据",
        "• README.txt - 本说明文件",
        "",
        f"生成时间: {now}",
        "作者: timo.cao | 生成: 大帅教练系统",
        "=" * 60,
    ])
    
    return "\n".join(lines)


def create_bundle_with_reasoning(task_id: str, files: list, quote_params: dict,
                                  metadata: dict = None) -> dict:
    """创建带推理链的交付ZIP包
    
    这个函数会自动调用quote_with_reasoning()生成带推理链的报价
    
    Args:
        task_id: 任务ID
        files: 文件列表
        quote_params: 报价参数 (会传递给quote_adapter)
        metadata: 任务元数据
    
    Returns:
        打包结果
    """
    from src.runtime.quote_adapter import get_quote_adapter
    
    quote_adapter = get_quote_adapter()
    
    # 使用quote_with_reasoning获取带推理链的报价
    quote_result = quote_adapter.quote_with_reasoning(quote_params)
    
    # 提取推理链
    reasoning_chain = quote_result.pop('reasoning_chain', None)
    quote_result.pop('reasoning_chain_id', None)
    
    # 调用标准打包函数
    return create_bundle(
        task_id=task_id,
        files=files,
        quote_data=quote_result,
        metadata=metadata,
        reasoning_chain=reasoning_chain
    )
