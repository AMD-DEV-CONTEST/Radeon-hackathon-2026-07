#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专业CNC报价单XLSX生成器 - 含推理链和工艺分析
参考行业标准格式，支持XAI推理过程展示
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统
"""

import io
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
except ImportError:
    openpyxl = None


class QuoteXlsxGenerator:
    """专业CNC报价单XLSX生成器 - 含推理链"""
    
    def __init__(self, company_name: str = "CNC AI 工艺大脑"):
        self.company_name = company_name
        self.now = datetime.now()
        self.quote_id = f"QT-{self.now.strftime('%Y%m%d')}-{self.now.strftime('%H%M%S')}"
    
    def generate(self, quote_data: Dict[str, Any], 
                 reasoning_chain: Dict[str, Any] = None,
                 part_info: Dict[str, Any] = None) -> bytes:
        """生成专业报价单XLSX"""
        if openpyxl is None:
            raise ImportError("需要安装openpyxl: pip install openpyxl")
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "CNC报价单"
        
        # 设置列宽
        ws.column_dimensions['A'].width = 18
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 15
        ws.column_dimensions['D'].width = 12
        ws.column_dimensions['E'].width = 15
        ws.column_dimensions['F'].width = 15
        ws.column_dimensions['G'].width = 12
        ws.column_dimensions['H'].width = 15
        
        # 样式
        title_font = Font(size=16, bold=True, color="FFFFFF")
        title_fill = PatternFill(patternType="solid", fgColor="1F4E79")
        header_font = Font(size=10, bold=True)
        header_fill = PatternFill(patternType="solid", fgColor="D9E1F2")
        label_font = Font(size=10, bold=True)
        content_font = Font(size=10)
        money_font = Font(size=10)
        
        thin_border = Border(
            left=Side(style='thin', color='B4B4B4'),
            right=Side(style='thin', color='B4B4B4'),
            top=Side(style='thin', color='B4B4B4'),
            bottom=Side(style='thin', color='B4B4B4')
        )
        
        row = 1
        
        # === 标题 ===
        ws.merge_cells(f'A{row}:H{row}')
        cell = ws[f'A{row}']
        cell.value = "CNC 加工报价单"
        cell.font = title_font
        cell.fill = title_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[row].height = 40
        row += 1
        
        # 公司名
        ws.merge_cells(f'A{row}:H{row}')
        ws[f'A{row}'] = f"{self.company_name} | 智能报价 · 精密制造 · XAI可解释"
        ws[f'A{row}'].font = Font(size=10, color="666666", italic=True)
        ws[f'A{row}'].alignment = Alignment(horizontal='center')
        row += 2
        
        # === 报价信息 ===
        info_items = [
            ("报价单号:", self.quote_id, "客户:", quote_data.get('customer', '—')),
            ("报价日期:", self.now.strftime("%Y-%m-%d %H:%M"), "联系人:", quote_data.get('contact', '—')),
            ("有效期:", "7个工作日", "联系电话:", quote_data.get('phone', '—')),
        ]
        
        for label_l, value_l, label_r, value_r in info_items:
            ws[f'A{row}'] = label_l
            ws[f'A{row}'].font = label_font
            ws[f'B{row}'] = value_l
            ws[f'B{row}'].font = content_font
            ws[f'E{row}'] = label_r
            ws[f'E{row}'].font = label_font
            ws[f'F{row}'] = value_r
            ws[f'F{row}'].font = content_font
            row += 1
        
        row += 1
        
        # === 零件信息 ===
        ws.merge_cells(f'A{row}:H{row}')
        ws[f'A{row}'] = "■ 零件技术参数"
        ws[f'A{row}'].font = Font(size=11, bold=True, color="1F4E79")
        ws[f'A{row}'].fill = PatternFill(patternType="solid", fgColor="F2F7FB")
        row += 1
        
        material = quote_data.get('material', '—')
        material_code = quote_data.get('material_code', material)
        
        part_data = [
            ("材料牌号", material_code, "材料单价", f"¥{quote_data.get('material_price', 30)}/kg"),
            ("加工工艺", quote_data.get('process', 'CNC三轴'), 
             "工艺费率", f"{quote_data.get('hourly_rate', 120)}元/小时"),
            ("表面处理", quote_data.get('surface', '无'), "表面处理费", f"¥{quote_data.get('surface_cost', 0)}"),
            ("公差等级", quote_data.get('tolerance', 'IT8'), "精度系数", f"×{quote_data.get('tol_coef', 1.0)}"),
            ("零件形状", quote_data.get('shape', 'flat'), "单件重量", f"{quote_data.get('weight_kg', 0):.4f} kg"),
            ("批量数量", f"{quote_data.get('quantity', 1)} 件", "加工工时", f"{quote_data.get('machine_hours', 0):.2f} 小时"),
            ("交货周期", f"{quote_data.get('lead_time_days', 7)} 个工作日", "置信度", f"{quote_data.get('confidence', 0.95)*100:.1f}%"),
        ]
        
        for label1, value1, label2, value2 in part_data:
            ws[f'A{row}'] = label1
            ws[f'A{row}'].font = label_font
            ws[f'B{row}'] = value1
            ws[f'B{row}'].font = content_font
            ws[f'E{row}'] = label2
            ws[f'E{row}'].font = label_font
            ws[f'F{row}'] = value2
            ws[f'F{row}'].font = content_font
            
            for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
                ws[f'{col}{row}'].border = thin_border
            row += 1
        
        row += 1
        
        # === 费用明细 ===
        ws.merge_cells(f'A{row}:H{row}')
        ws[f'A{row}'] = "■ 成本明细 (Excel公式: N27 = (L24+M15+O6+L20)/(1-H27)*L27)"
        ws[f'A{row}'].font = Font(size=11, bold=True, color="1F4E79")
        ws[f'A{row}'].fill = PatternFill(patternType="solid", fgColor="F2F7FB")
        row += 1
        
        # 表头
        headers = ["费用项目", "公式代码", "计算说明", "金额(元)", "占比"]
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=row, column=col, value=header)
            cell.font = Font(size=10, bold=True, color="FFFFFF")
            cell.fill = PatternFill(patternType="solid", fgColor="2E75B6")
            cell.alignment = Alignment(horizontal='center')
        row += 1
        
        # 费用数据
        quantity = quote_data.get('quantity', 1)
        material_cost = quote_data.get('material_cost', 0)
        machining_cost = quote_data.get('machining_cost', 0)
        surface_cost = quote_data.get('surface_cost', 0)
        extra_fees = quote_data.get('extra_fees', 0)
        total_cost = quote_data.get('total_cost', material_cost + machining_cost + surface_cost + extra_fees)
        
        def calc_percent(cost):
            return f"{(cost/total_cost*100):.1f}%" if total_cost > 0 else "0%"
        
        cost_items = [
            ("材料费", "O6", f"重量({quote_data.get('weight_kg', 0):.3f}kg) × 单价({quote_data.get('material_price', 30)}元/kg)", 
             material_cost, calc_percent(material_cost)),
            ("加工费", "M15", f"基础费率({quote_data.get('hourly_rate', 120)}) × 工时({quote_data.get('machine_hours', 0):.2f}h)", 
             machining_cost, calc_percent(machining_cost)),
            ("表面处理费", "L20", self._get_surface_calc_desc(quote_data), 
             surface_cost, calc_percent(surface_cost)),
            ("其他费用", "L24", f"测量费({quote_data.get('measurement_fee', 0)}) + 夹具费({quote_data.get('jig_fee', 0)})", 
             extra_fees, calc_percent(extra_fees)),
        ]
        
        for item_name, formula_code, calc_desc, amount, percent in cost_items:
            ws.cell(row=row, column=1, value=item_name).font = label_font
            ws.cell(row=row, column=2, value=formula_code).font = Font(size=9, bold=True, color="2E75B6")
            ws.cell(row=row, column=3, value=calc_desc).font = Font(size=9)
            ws.cell(row=row, column=4, value=round(amount, 2)).font = money_font
            ws.cell(row=row, column=4).number_format = '#,##0.00'
            ws.cell(row=row, column=5, value=percent).font = Font(size=9, color="666666")
            
            for col in range(1, 6):
                ws.cell(row=row, column=col).border = thin_border
            row += 1
        
        # 小计
        ws.cell(row=row, column=1, value="成本小计").font = Font(size=10, bold=True)
        ws.cell(row=row, column=4, value=round(total_cost, 2)).font = Font(size=10, bold=True)
        ws.cell(row=row, column=4).number_format = '#,##0.00'
        ws.cell(row=row, column=5, value="100%").font = Font(size=9, bold=True)
        
        for col in range(1, 6):
            ws.cell(row=row, column=col).border = thin_border
            ws.cell(row=row, column=col).fill = PatternFill(patternType="solid", fgColor="E8ECF0")
        row += 2
        
        # === 汇总 ===
        profit_rate = quote_data.get('profit_rate', 0.30)
        discount = quote_data.get('discount', 1.0)
        final_price = quote_data.get('final_price', total_cost / (1 - profit_rate) * discount)
        unit_price = quote_data.get('unit_price', final_price / quantity)
        profit = quote_data.get('profit', final_price - total_cost)
        
        # 利润计算说明
        ws.merge_cells(f'A{row}:H{row}')
        ws[f'A{row}'] = f"利润计算: 成本({total_cost:.2f}) / (1 - 利润率({profit_rate*100:.0f}%)) × 折扣({discount})"
        ws[f'A{row}'].font = Font(size=9, color="666666", italic=True)
        row += 1
        
        # 单价
        ws.merge_cells(f'A{row}:D{row}')
        ws[f'A{row}'] = "单件含税价"
        ws[f'A{row}'].font = Font(size=11, bold=True, color="FFFFFF")
        ws[f'A{row}'].fill = PatternFill(patternType="solid", fgColor="2E75B6")
        ws[f'A{row}'].alignment = Alignment(horizontal='center', vertical='center')
        
        ws.merge_cells(f'E{row}:H{row}')
        ws[f'E{row}'] = f"¥{unit_price:,.2f}"
        ws[f'E{row}'].font = Font(size=14, bold=True, color="FFFFFF")
        ws[f'E{row}'].fill = PatternFill(patternType="solid", fgColor="2E75B6")
        ws[f'E{row}'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[row].height = 35
        row += 1
        
        # 总价
        ws.merge_cells(f'A{row}:D{row}')
        ws[f'A{row}'] = f"总价 ({quantity}件)"
        ws[f'A{row}'].font = Font(size=12, bold=True, color="FFFFFF")
        ws[f'A{row}'].fill = PatternFill(patternType="solid", fgColor="1F4E79")
        ws[f'A{row}'].alignment = Alignment(horizontal='center', vertical='center')
        
        ws.merge_cells(f'E{row}:H{row}')
        ws[f'E{row}'] = f"¥{final_price:,.2f}"
        ws[f'E{row}'].font = Font(size=18, bold=True, color="FFFFFF")
        ws[f'E{row}'].fill = PatternFill(patternType="solid", fgColor="1F4E79")
        ws[f'E{row}'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[row].height = 45
        row += 2
        
        # === 推理链摘要 ===
        if reasoning_chain and reasoning_chain.get('steps'):
            ws.merge_cells(f'A{row}:H{row}')
            ws[f'A{row}'] = "■ XAI推理过程摘要 (完整推理链见Sheet2)"
            ws[f'A{row}'].font = Font(size=11, bold=True, color="1F4E79")
            ws[f'A{row}'].fill = PatternFill(patternType="solid", fgColor="F2F7FB")
            row += 1
            
            # 关键步骤
            key_steps = [s for s in reasoning_chain.get('steps', []) 
                        if s.get('step_type') in ['calculation', 'conclusion', 'warning']]
            
            for step in key_steps[:6]:
                ws.merge_cells(f'A{row}:B{row}')
                ws[f'A{row}'] = step.get('title', '')
                ws[f'A{row}'].font = Font(size=9, bold=True)
                
                ws.merge_cells(f'C{row}:H{row}')
                ws[f'C{row}'] = step.get('description', '')[:100]
                ws[f'C{row}'].font = Font(size=9)
                row += 1
            
            # 置信度
            confidence = reasoning_chain.get('overall_confidence', 0.95)
            ws.merge_cells(f'A{row}:H{row}')
            ws[f'A{row}'] = f"整体置信度: {confidence*100:.1f}% | 推理步骤: {reasoning_chain.get('total_steps', 0)}步 | 耗时: {reasoning_chain.get('elapsed_ms', 0):.0f}ms"
            ws[f'A{row}'].font = Font(size=9, color="2E75B6", italic=True)
            ws[f'A{row}'].alignment = Alignment(horizontal='center')
            row += 2
        
        # === 备注 ===
        ws.merge_cells(f'A{row}:H{row}')
        ws[f'A{row}'] = "■ 备注说明"
        ws[f'A{row}'].font = Font(size=11, bold=True, color="1F4E79")
        ws[f'A{row}'].fill = PatternFill(patternType="solid", fgColor="F2F7FB")
        row += 1
        
        notes = [
            "1. 本报价单由CNC AI工艺大脑智能生成，采用XAI可解释AI技术",
            "2. 报价计算完全还原Excel手工报价公式: N27 = (L24+M15+O6+L20)/(1-H27)*L27",
            "3. 所有计算步骤均有完整推理链记录，可通过报价单号追溯",
            "4. 实际加工前请人工确认所有技术参数，本报价仅供参考",
            "5. 报价有效期为7个工作日，逾期请重新询价",
            f"6. 材料: {material_code} | 工艺: {quote_data.get('process', 'CNC三轴')} | 表面: {quote_data.get('surface', '无')}",
        ]
        
        for note in notes:
            ws.merge_cells(f'A{row}:H{row}')
            ws[f'A{row}'] = note
            ws[f'A{row}'].font = Font(size=9, color="666666")
            row += 1
        
        row += 1
        
        # === 页脚 ===
        ws.merge_cells(f'A{row}:H{row}')
        ws[f'A{row}'] = f"报价单号: {self.quote_id} | 生成时间: {self.now.strftime('%Y-%m-%d %H:%M:%S')} | 引擎: quote-v3.0 | {self.company_name}"
        ws[f'A{row}'].font = Font(size=8, color="999999")
        ws[f'A{row}'].alignment = Alignment(horizontal='center')
        
        # ===== Sheet 2: 推理链详情 =====
        if reasoning_chain and reasoning_chain.get('steps'):
            self._create_reasoning_sheet(wb, reasoning_chain)
        
        # 保存到BytesIO
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()
    
    def _create_reasoning_sheet(self, wb, reasoning_chain: Dict):
        """创建推理链详情Sheet"""
        ws = wb.create_sheet("推理链详情")
        
        # 列宽
        ws.column_dimensions['A'].width = 8
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 25
        ws.column_dimensions['D'].width = 50
        ws.column_dimensions['E'].width = 12
        ws.column_dimensions['F'].width = 20
        
        # 样式
        title_font = Font(size=16, bold=True, color="FFFFFF")
        title_fill = PatternFill(patternType="solid", fgColor="1F4E79")
        header_font = Font(size=10, bold=True, color="FFFFFF")
        header_fill = PatternFill(patternType="solid", fgColor="2E75B6")
        
        # 标题
        ws.merge_cells('A1:F1')
        ws['A1'] = "XAI推理链详情 - 可解释AI报价过程"
        ws['A1'].font = title_font
        ws['A1'].fill = title_fill
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 40
        
        # 基本信息
        ws['A3'] = "任务类型:"
        ws['B3'] = reasoning_chain.get('task_type', 'quote')
        ws['D3'] = "总步骤:"
        ws['E3'] = reasoning_chain.get('total_steps', 0)
        
        ws['A4'] = "整体置信度:"
        ws['B4'] = f"{reasoning_chain.get('overall_confidence', 0)*100:.1f}%"
        ws['D4'] = "耗时:"
        ws['E4'] = f"{reasoning_chain.get('elapsed_ms', 0):.0f}ms"
        
        # 表头
        row = 6
        headers = ["步骤", "类型", "标题", "描述", "置信度", "公式/来源"]
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=row, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
        
        # 步骤数据
        row = 7
        for step in reasoning_chain.get('steps', []):
            ws.cell(row=row, column=1, value=step.get('step_id', '')).alignment = Alignment(horizontal='center')
            ws.cell(row=row, column=2, value=step.get('step_type', '')).alignment = Alignment(horizontal='center')
            ws.cell(row=row, column=3, value=step.get('title', ''))
            ws.cell(row=row, column=4, value=step.get('description', ''))
            ws.cell(row=row, column=5, value=f"{step.get('confidence', 0)*100:.0f}%").alignment = Alignment(horizontal='center')
            ws.cell(row=row, column=6, value=step.get('formula', '') or step.get('source', ''))
            
            # 根据类型设置颜色
            step_type = step.get('step_type', '')
            if step_type == 'warning':
                for col in range(1, 7):
                    ws.cell(row=row, column=col).fill = PatternFill(patternType="solid", fgColor="FFF2CC")
            elif step_type == 'conclusion':
                for col in range(1, 7):
                    ws.cell(row=row, column=col).fill = PatternFill(patternType="solid", fgColor="E2EFDA")
            
            for col in range(1, 7):
                ws.cell(row=row, column=col).border = Border(
                    left=Side(style='thin', color='B4B4B4'),
                    right=Side(style='thin', color='B4B4B4'),
                    top=Side(style='thin', color='B4B4B4'),
                    bottom=Side(style='thin', color='B4B4B4')
                )
                ws.cell(row=row, column=col).font = Font(size=9)
            
            row += 1
        
        # 警告信息
        warnings = reasoning_chain.get('warnings', [])
        if warnings:
            row += 1
            ws.merge_cells(f'A{row}:F{row}')
            ws[f'A{row}'] = "⚠️ 警告信息"
            ws[f'A{row}'].font = Font(size=10, bold=True, color="BF8F00")
            
            row += 1
            for warning in warnings:
                ws.merge_cells(f'A{row}:F{row}')
                ws[f'A{row}'] = f"• {warning}"
                ws[f'A{row}'].font = Font(size=9, color="C00000")
                row += 1
    
    def _get_surface_calc_desc(self, quote_data: Dict) -> str:
        """获取表面处理计算说明"""
        surface = quote_data.get('surface', '无')
        if surface in ('无', 'none', None):
            return "无表面处理"
        pricing_mode = quote_data.get('pricing_mode', 'by_quantity')
        if pricing_mode == 'by_weight':
            return f"重量({quote_data.get('weight_kg', 0):.3f}kg) × 费率"
        return f"单价 × 数量({quote_data.get('quantity', 1)})"


def generate_quote_xlsx(quote_data: Dict[str, Any], 
                        reasoning_chain: Dict[str, Any] = None,
                        part_info: Dict[str, Any] = None) -> bytes:
    """便捷函数：生成专业报价单XLSX"""
    generator = QuoteXlsxGenerator()
    return generator.generate(quote_data, reasoning_chain, part_info)


# 测试代码
if __name__ == "__main__":
    # 测试数据
    test_quote = {
        "material": "AL6061",
        "material_code": "AL6061",
        "material_price": 30,
        "quantity": 10,
        "unit_price": 125.50,
        "final_price": 1255.00,
        "weight_kg": 0.35,
        "surface": "阳极氧化",
        "surface_cost": 25,
        "lead_time_days": 7,
        "tolerance": "IT8",
        "process": "CNC三轴",
        "machine_hours": 2.5,
        "hourly_rate": 120,
        "material_cost": 10.5,
        "machining_cost": 300,
        "extra_fees": 50,
        "total_cost": 385.5,
        "final_price": 550.71,
        "profit": 165.21,
        "profit_rate": 0.3,
        "discount": 1.0,
        "tol_coef": 1.0,
        "rough_coef": 1.0,
        "roughness": "Ra1.6",
        "shape": "flat",
        "measurement_fee": 0,
        "jig_fee": 0,
        "tool_fee": 0,
        "pricing_mode": "by_quantity",
        "confidence": 0.95,
    }
    
    # 测试推理链
    test_reasoning = {
        "task_type": "quote",
        "total_steps": 10,
        "elapsed_ms": 45,
        "overall_confidence": 0.95,
        "steps": [
            {"step_id": 1, "step_type": "input_parse", "title": "输入解析", "description": "解析用户输入参数", "confidence": 1.0},
            {"step_id": 2, "step_type": "calculation", "title": "材料成本(O6)", "description": "0.35kg × 30元/kg = 10.50元", "confidence": 1.0, "formula": "Excel O6"},
            {"step_id": 3, "step_type": "calculation", "title": "加工成本(M15)", "description": "120 × 1.0 × 2.5 × 1.0 × 1.0 = 300元", "confidence": 1.0, "formula": "Excel M15"},
            {"step_id": 4, "step_type": "conclusion", "title": "报价结论", "description": "6061铝合金 × 10件 = 550.71元", "confidence": 0.95},
        ],
        "warnings": ["利润率偏低，建议复核"],
    }
    
    xlsx_bytes = generate_quote_xlsx(test_quote, test_reasoning)
    
    test_path = Path("test_professional_quote.xlsx")
    test_path.write_bytes(xlsx_bytes)
    print(f"专业报价单已生成: {test_path.absolute()}")
    print(f"文件大小: {len(xlsx_bytes)} bytes")
