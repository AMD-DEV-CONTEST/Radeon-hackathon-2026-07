#!/usr/bin/env python3
"""Generate project documentation PDF for AMD AI DevMaster Hackathon submission."""

from fpdf import FPDF
import os

class ProjectPDF(FPDF):
    def __init__(self):
        super().__init__()
        font_dir = os.environ.get("FONT_DIR", "/usr/share/fonts/truetype/noto")
        font_regular = os.path.join(font_dir, "NotoSansCJK-Regular.ttc")
        font_bold = os.path.join(font_dir, "NotoSansCJK-Bold.ttc")
        if not os.path.exists(font_regular):
            font_regular = os.path.join(font_dir, "NotoSansSC-Regular.ttf")
            font_bold = os.path.join(font_dir, "NotoSansSC-Bold.ttf")
        self.add_font("NotoSansSC", "", font_regular, uni=True)
        self.add_font("NotoSansSC", "B", font_bold, uni=True)
        
    def header(self):
        self.set_font("NotoSansSC", "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "AMD AI DevMaster 黑客松 | 赛道二：私有 AI Agent 开发与本地部署", align="C")
        self.ln(12)
        self.set_draw_color(237, 28, 36)  # AMD red
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)
    
    def footer(self):
        self.set_y(-15)
        self.set_font("NotoSansSC", "", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"InventoryDoc Agent - 第 {self.page_no()} 页", align="C")
    
    def chapter_title(self, title):
        self.set_font("NotoSansSC", "B", 14)
        self.set_text_color(237, 28, 36)  # AMD red
        self.cell(0, 10, title)
        self.ln(8)
        self.set_text_color(0, 0, 0)
    
    def section_title(self, title):
        self.set_font("NotoSansSC", "B", 12)
        self.set_text_color(50, 50, 50)
        self.cell(0, 8, title)
        self.ln(8)
        self.set_text_color(0, 0, 0)
    
    def body_text(self, text):
        self.set_font("NotoSansSC", "", 10)
        self.multi_cell(0, 6, text)
        self.ln(3)
    
    def bullet_point(self, text):
        self.set_font("NotoSansSC", "", 10)
        x = self.get_x()
        self.cell(5, 6, "•")
        self.multi_cell(0, 6, text)
        self.ln(1)
    
    def add_table(self, headers, data, col_widths=None):
        if col_widths is None:
            col_widths = [190 / len(headers)] * len(headers)
        
        # Header
        self.set_font("NotoSansSC", "B", 9)
        self.set_fill_color(237, 28, 36)
        self.set_text_color(255, 255, 255)
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 8, header, 1, 0, "C", True)
        self.ln()
        
        # Data
        self.set_font("NotoSansSC", "", 9)
        self.set_text_color(0, 0, 0)
        fill = False
        for row in data:
            if fill:
                self.set_fill_color(240, 240, 240)
            else:
                self.set_fill_color(255, 255, 255)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 7, str(cell), 1, 0, "C", True)
            self.ln()
            fill = not fill
        self.ln(5)


def generate_pdf():
    pdf = ProjectPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    
    # Cover page
    pdf.add_page()
    pdf.ln(30)
    pdf.set_font("NotoSansSC", "B", 28)
    pdf.set_text_color(237, 28, 36)
    pdf.cell(0, 15, "InventoryDoc Agent", align="C")
    pdf.ln(20)
    pdf.set_font("NotoSansSC", "", 14)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, "库存盘点智能审计系统", align="C")
    pdf.ln(15)
    pdf.set_font("NotoSansSC", "", 12)
    pdf.cell(0, 8, "基于 AMD Radeon GPU + ROCm 的本地私有 AI Agent", align="C")
    pdf.ln(30)
    
    # Team info
    pdf.set_font("NotoSansSC", "", 11)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, "提交赛道：赛道二 — 私有 AI Agent 开发与本地部署", align="C")
    pdf.ln(8)
    pdf.cell(0, 8, "团队成员：开发团队", align="C")
    pdf.ln(8)
    pdf.cell(0, 8, "GitHub：dev-team", align="C")
    pdf.ln(8)
    pdf.cell(0, 8, "联系邮箱：developer@example.com", align="C")
    pdf.ln(20)
    
    # AMD logo placeholder
    pdf.set_font("NotoSansSC", "B", 10)
    pdf.set_text_color(237, 28, 36)
    pdf.cell(0, 8, "AMD AI DevMaster 黑客松 2026", align="C")
    
    # Page 2: Executive Summary
    pdf.add_page()
    pdf.chapter_title("1. 项目概述")
    pdf.body_text(
        "InventoryDoc Agent 是一个基于 AMD Radeon GPU + ROCm 的本地私有 AI Agent，"
        "专为企业库存盘点差异分析设计。上传 10 份盘点数据，10 分钟自动生成可直接上会的调账材料，"
        "净差异 98.99 万元精准定位。"
    )
    
    pdf.section_title("1.1 解决的核心问题")
    pdf.body_text(
        "企业仓储盘点是库存管理的核心环节，但盘点差异分析长期依赖人工，存在以下痛点："
    )
    pdf.bullet_point("数据分散：10+ 份文件（CSV/XLSX/TXT），编码不统一，需人工逐个打开、格式转换")
    pdf.bullet_point("噪音干扰：NOISE 干扰数据、异常记录、不适用文件混杂，误用导致分析结果失真")
    pdf.bullet_point("分析耗时：从数据清洗到出具报告需 2-3 天，管理层会议延迟，追责不及时")
    pdf.bullet_point("容易出错：基准选错、成本用售价、数字不一致，追责依据不可信")
    
    pdf.section_title("1.2 目标用户")
    pdf.bullet_point("仓储管理层：需要可上会讨论的盘点差异分析材料")
    pdf.bullet_point("库存控制专员：需要从数据清洗到报告生成的全流程自动化")
    pdf.bullet_point("财务部门：需要准确的差异金额和财务影响估算")
    
    # Page 3: Core Capabilities
    pdf.add_page()
    pdf.chapter_title("2. 核心能力")
    
    pdf.section_title("2.1 三大差异化卖点")
    pdf.add_table(
        ["创新点", "说明", "竞品对比"],
        [
            ["噪音自动识别", "自动识别 3 类噪音：NOISE 干扰、异常记录、不适用文件", "无此能力"],
            ["三维基准论证", "编码体系/时间窗口/数据粒度三维对比，自动选对基准", "依赖人工经验"],
            ["日志关联三分类", "按净变动量比对，精准区分完全/部分/无关联", "简单匹配"],
        ],
        [45, 95, 50]
    )
    
    pdf.section_title("2.2 五项核心能力（满足赛道要求）")
    pdf.bullet_point("本地知识检索（RAG）— 多文件向量索引，支持跨文件语义搜索")
    pdf.bullet_point("工具调用 — Excel 读写、差异计算、报告生成等 10+ 工具")
    pdf.bullet_point("多步骤任务规划 — 10 步确定性工作流，自动完成全流程分析")
    pdf.bullet_point("本地多轮记忆 — 跨文件一致性记忆，确保分析结果可追溯")
    pdf.bullet_point("质量校验 — 7 条 must_check_points 自动验证，防止常见错误")
    
    # Page 4: 10-Step Workflow
    pdf.add_page()
    pdf.chapter_title("3. 10 步工作流")
    
    steps = [
        ("Step 1", "多格式文件加载", "支持 CSV/XLSX/TXT，自动编码检测"),
        ("Step 2", "智能噪音识别", "NOISE/异常/噪音文件自动过滤"),
        ("Step 3", "基准选择三维论证", "编码体系/时间窗口/数据粒度对比"),
        ("Step 4", "扫描日志清洗", "NOISE 过滤 + 时间窗口提取"),
        ("Step 5", "盘点结果加载", "以复盘数为准，确保数据准确"),
        ("Step 6", "差异金额计算", "成本单价匹配 + 缺失值估算"),
        ("Step 7", "日志关联三分类", "完全/部分/无关联精准区分"),
        ("Step 8", "库位状态校验", "启用/停用/维修中状态验证"),
        ("Step 9", "品类维度分析", "差异率降序 + 异常品类识别"),
        ("Step 10", "交付物生成", "Excel 4 sheets + MD 报告"),
    ]
    
    pdf.add_table(
        ["步骤", "名称", "关键逻辑"],
        steps,
        [25, 55, 110]
    )
    
    pdf.body_text("质量校验：7 条 must_check_points 自动验证，确保分析结果准确可靠。")
    
    # Page 5: Technical Architecture
    pdf.add_page()
    pdf.chapter_title("4. 技术架构")
    
    pdf.section_title("4.1 系统架构")
    pdf.body_text(
        "系统采用分层架构设计，从上到下依次为：\n"
        "• 用户界面层：Gradio Web UI，提供 4 个功能标签页\n"
        "• Agent 核心层：LangChain + 10 步工作流编排\n"
        "• RAG 引擎层：多格式文件加载、向量索引、噪音检测\n"
        "• 工具层：Excel 读写、差异计算、报告生成\n"
        "• 推理层：vLLM + ROCm，AMD GPU 加速"
    )
    
    pdf.section_title("4.2 核心模块")
    pdf.add_table(
        ["模块", "文件", "功能"],
        [
            ["Agent Core", "src/agent.py", "10 步工作流编排"],
            ["RAG Engine", "src/rag.py", "多格式文件加载和索引"],
            ["Noise Detector", "src/noise_detector.py", "智能噪音识别"],
            ["Tools", "src/tools.py", "Excel 读写/计算/报告生成"],
            ["Memory", "src/memory.py", "跨文件一致性记忆"],
            ["Quality Checker", "src/quality_checker.py", "7 条质量校验"],
            ["UI", "src/ui.py", "Gradio Web 界面"],
        ],
        [40, 60, 90]
    )
    
    # Page 6: AMD GPU Optimization
    pdf.add_page()
    pdf.chapter_title("5. AMD GPU 适配与优化")
    
    pdf.section_title("5.1 平台概述")
    pdf.body_text(
        "本项目基于 AMD Radeon GPU + ROCm 开源软件栈构建，实现完全本地化的 AI Agent 部署。"
        "核心推理过程全部在 AMD GPU 上执行，不依赖任何云端 API。"
    )
    
    pdf.add_table(
        ["组件", "技术选型", "说明"],
        [
            ["GPU 硬件", "AMD Radeon RX 7900 XTX", "24GB VRAM，支持 FP16/BF16"],
            ["推理引擎", "vLLM 0.6+", "高性能 LLM 推理框架"],
            ["深度学习框架", "PyTorch 2.4+ ROCm", "AMD GPU 原生支持"],
            ["嵌入模型", "BAAI/bge-small-en-v1.5", "轻量级嵌入，GPU 加速"],
            ["向量数据库", "ChromaDB", "本地向量存储"],
        ],
        [40, 60, 90]
    )
    
    pdf.section_title("5.2 性能优化策略")
    pdf.add_table(
        ["优化技术", "说明", "效果"],
        [
            ["FP16 混合精度", "使用 float16 进行推理", "显存占用降低 50%"],
            ["Continuous Batching", "vLLM 动态批处理", "吞吐量提升 2-4 倍"],
            ["PagedAttention", "vLLM 内存管理", "支持更大 batch size"],
            ["GPU 加速向量检索", "嵌入计算在 GPU 上", "检索延迟降低 60%"],
        ],
        [50, 70, 70]
    )
    
    pdf.section_title("5.3 为什么选择 AMD ROCm")
    pdf.add_table(
        ["维度", "AMD ROCm", "NVIDIA CUDA"],
        [
            ["开源性", "完全开源", "闭源"],
            ["成本", "硬件成本更低", "高端 GPU 昂贵"],
            ["企业部署", "无供应商锁定", "依赖 NVIDIA"],
            ["大模型支持", "vLLM 原生支持", "vLLM 原生支持"],
        ],
        [50, 70, 70]
    )
    
    # Page 7: Testing & Validation
    pdf.add_page()
    pdf.chapter_title("6. 测试验证")
    
    pdf.section_title("6.1 Ground Truth 验证")
    pdf.body_text("使用某供应链真实盘点数据测试，全部指标与人工分析一致：")
    
    pdf.add_table(
        ["指标", "Agent 输出", "人工验证", "状态"],
        [
            ["SKU 总数", "528", "528", "通过"],
            ["系统库存总计", "21,144 件", "21,144 件", "通过"],
            ["净差异", "-971 件", "-971 件", "通过"],
            ["总体差异率", "4.6%", "4.6%", "通过"],
            ["净差异金额", "-989,900.97 元", "-989,900.97 元", "通过"],
            ["日志关联三分类", "14/21/124", "14/21/124", "通过"],
            ["质量校验", "7/7 通过", "全部通过", "通过"],
        ],
        [50, 50, 50, 40]
    )
    
    pdf.section_title("6.2 业务价值")
    pdf.add_table(
        ["指标", "人工分析", "Agent", "提升"],
        [
            ["分析耗时", "2-3 天", "10 分钟", "99%"],
            ["准确率", "依赖经验", "与 Ground Truth 一致", "—"],
            ["可审计性", "无", "7 条质量校验", "—"],
        ],
        [50, 50, 50, 40]
    )
    
    # Page 8: Application & Future
    pdf.add_page()
    pdf.chapter_title("7. 应用场景")
    
    pdf.add_table(
        ["场景", "说明"],
        [
            ["企业库存盘点", "月度/季度循环盘点差异分析"],
            ["仓库调账", "管理层会议前的调账材料准备"],
            ["审计配合", "提供可追溯的差异分析证据"],
            ["库存优化", "基于差异数据优化库存管理策略"],
        ],
        [60, 130]
    )
    
    pdf.chapter_title("8. 未来计划")
    pdf.bullet_point("支持更多数据格式（PDF 扫描件、数据库直连）")
    pdf.bullet_point("增加可视化图表（差异分布、趋势分析）")
    pdf.bullet_point("支持多仓库对比分析")
    pdf.bullet_point("接入企业 ERP 系统自动取数")
    
    # Page 9: Team & Contact
    pdf.add_page()
    pdf.chapter_title("9. 团队信息")
    
    pdf.add_table(
        ["角色", "姓名", "职责"],
        [
            ["开发者", "——", "场景定义、产品设计、Agent 开发、数据处理、系统集成"],
        ],
        [40, 50, 100]
    )
    
    pdf.ln(10)
    pdf.chapter_title("10. 联系方式")
    pdf.bullet_point("GitHub：private repository")
    pdf.bullet_point("邮箱：developer@example.com")
    
    # Save PDF
    output_path = "/app/docs/InventoryDoc_Agent_项目说明文档.pdf"
    pdf.output(output_path)
    print(f"PDF generated: {output_path}")
    return output_path


if __name__ == "__main__":
    generate_pdf()
