#!/usr/bin/env python3
"""Generate project documentation PDF using HTML conversion."""

import subprocess
import os

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
@page { size: A4; margin: 2cm; }
body { font-family: sans-serif; font-size: 11pt; line-height: 1.6; color: #333; }
h1 { color: #ED1C24; font-size: 24pt; border-bottom: 2px solid #ED1C24; padding-bottom: 10px; }
h2 { color: #ED1C24; font-size: 16pt; margin-top: 20px; }
h3 { color: #555; font-size: 13pt; }
table { border-collapse: collapse; width: 100%; margin: 15px 0; }
th { background-color: #ED1C24; color: white; padding: 8px; text-align: left; }
td { border: 1px solid #ddd; padding: 6px; }
tr:nth-child(even) { background-color: #f9f9f9; }
.cover { text-align: center; padding-top: 100px; }
.cover h1 { font-size: 32pt; border: none; }
.cover .subtitle { font-size: 14pt; color: #666; margin: 20px 0; }
.section { page-break-inside: avoid; }
ul { margin: 10px 0; }
li { margin: 5px 0; }
</style>
</head>
<body>

<div class="cover">
<h1>InventoryDoc Agent</h1>
<div class="subtitle">库存盘点智能审计系统</div>
<p>基于 AMD Radeon GPU + ROCm 的本地私有 AI Agent</p>
<br><br>
<p><strong>提交赛道：</strong>赛道二 — 私有 AI Agent 开发与本地部署</p>
<p><strong>团队成员：</strong>开发团队</p>
<p><strong>GitHub：</strong>dev-team</p>
<p><strong>联系邮箱：</strong>developer@example.com</p>
<br><br>
<p style="color: #ED1C24; font-weight: bold;">AMD AI DevMaster 黑客松 2026</p>
</div>

<div class="section">
<h1>1. 项目概述</h1>
<p>InventoryDoc Agent 是一个基于 AMD Radeon GPU + ROCm 的本地私有 AI Agent，专为企业库存盘点差异分析设计。上传 10 份盘点数据，10 分钟自动生成可直接上会的调账材料，净差异 98.99 万元精准定位。</p>

<h2>1.1 解决的核心问题</h2>
<p>企业仓储盘点是库存管理的核心环节，但盘点差异分析长期依赖人工，存在以下痛点：</p>
<ul>
<li><strong>数据分散：</strong>10+ 份文件（CSV/XLSX/TXT），编码不统一，需人工逐个打开、格式转换</li>
<li><strong>噪音干扰：</strong>NOISE 干扰数据、异常记录、不适用文件混杂，误用导致分析结果失真</li>
<li><strong>分析耗时：</strong>从数据清洗到出具报告需 2-3 天，管理层会议延迟，追责不及时</li>
<li><strong>容易出错：</strong>基准选错、成本用售价、数字不一致，追责依据不可信</li>
</ul>

<h2>1.2 目标用户</h2>
<ul>
<li>仓储管理层：需要可上会讨论的盘点差异分析材料</li>
<li>库存控制专员：需要从数据清洗到报告生成的全流程自动化</li>
<li>财务部门：需要准确的差异金额和财务影响估算</li>
</ul>
</div>

<div class="section">
<h1>2. 核心能力</h1>

<h2>2.1 三大差异化卖点</h2>
<table>
<tr><th>创新点</th><th>说明</th><th>竞品对比</th></tr>
<tr><td><strong>噪音自动识别</strong></td><td>自动识别 3 类噪音：NOISE 干扰、异常记录、不适用文件</td><td>无此能力</td></tr>
<tr><td><strong>三维基准论证</strong></td><td>编码体系/时间窗口/数据粒度三维对比，自动选对基准</td><td>依赖人工经验</td></tr>
<tr><td><strong>日志关联三分类</strong></td><td>按净变动量比对，精准区分完全/部分/无关联</td><td>简单匹配</td></tr>
</table>

<h2>2.2 五项核心能力（满足赛道要求）</h2>
<ul>
<li><strong>本地知识检索（RAG）</strong>— 多文件向量索引，支持跨文件语义搜索</li>
<li><strong>工具调用</strong> — Excel 读写、差异计算、报告生成等 10+ 工具</li>
<li><strong>多步骤任务规划</strong> — 10 步确定性工作流，自动完成全流程分析</li>
<li><strong>本地多轮记忆</strong> — 跨文件一致性记忆，确保分析结果可追溯</li>
<li><strong>质量校验</strong> — 7 条 must_check_points 自动验证，防止常见错误</li>
</ul>
</div>

<div class="section">
<h1>3. 10 步工作流</h1>
<table>
<tr><th>步骤</th><th>名称</th><th>关键逻辑</th></tr>
<tr><td>Step 1</td><td>多格式文件加载</td><td>支持 CSV/XLSX/TXT，自动编码检测</td></tr>
<tr><td>Step 2</td><td>智能噪音识别</td><td>NOISE/异常/噪音文件自动过滤</td></tr>
<tr><td>Step 3</td><td>基准选择三维论证</td><td>编码体系/时间窗口/数据粒度对比</td></tr>
<tr><td>Step 4</td><td>扫描日志清洗</td><td>NOISE 过滤 + 时间窗口提取</td></tr>
<tr><td>Step 5</td><td>盘点结果加载</td><td>以复盘数为准，确保数据准确</td></tr>
<tr><td>Step 6</td><td>差异金额计算</td><td>成本单价匹配 + 缺失值估算</td></tr>
<tr><td>Step 7</td><td>日志关联三分类</td><td>完全/部分/无关联精准区分</td></tr>
<tr><td>Step 8</td><td>库位状态校验</td><td>启用/停用/维修中状态验证</td></tr>
<tr><td>Step 9</td><td>品类维度分析</td><td>差异率降序 + 异常品类识别</td></tr>
<tr><td>Step 10</td><td>交付物生成</td><td>Excel 4 sheets + MD 报告</td></tr>
</table>
<p><strong>质量校验：</strong>7 条 must_check_points 自动验证，确保分析结果准确可靠。</p>
</div>

<div class="section">
<h1>4. 技术架构</h1>

<h2>4.1 系统架构</h2>
<p>系统采用分层架构设计，从上到下依次为：</p>
<ul>
<li><strong>用户界面层：</strong>Gradio Web UI，提供 4 个功能标签页</li>
<li><strong>Agent 核心层：</strong>LangChain + 10 步工作流编排</li>
<li><strong>RAG 引擎层：</strong>多格式文件加载、向量索引、噪音检测</li>
<li><strong>工具层：</strong>Excel 读写、差异计算、报告生成</li>
<li><strong>推理层：</strong>vLLM + ROCm，AMD GPU 加速</li>
</ul>

<h2>4.2 核心模块</h2>
<table>
<tr><th>模块</th><th>文件</th><th>功能</th></tr>
<tr><td>Agent Core</td><td>src/agent.py</td><td>10 步工作流编排</td></tr>
<tr><td>RAG Engine</td><td>src/rag.py</td><td>多格式文件加载和索引</td></tr>
<tr><td>Noise Detector</td><td>src/noise_detector.py</td><td>智能噪音识别</td></tr>
<tr><td>Tools</td><td>src/tools.py</td><td>Excel 读写/计算/报告生成</td></tr>
<tr><td>Memory</td><td>src/memory.py</td><td>跨文件一致性记忆</td></tr>
<tr><td>Quality Checker</td><td>src/quality_checker.py</td><td>7 条质量校验</td></tr>
<tr><td>UI</td><td>src/ui.py</td><td>Gradio Web 界面</td></tr>
</table>
</div>

<div class="section">
<h1>5. AMD GPU 适配与优化</h1>

<h2>5.1 平台概述</h2>
<p>本项目基于 AMD Radeon GPU + ROCm 开源软件栈构建，实现完全本地化的 AI Agent 部署。核心推理过程全部在 AMD GPU 上执行，不依赖任何云端 API。</p>

<table>
<tr><th>组件</th><th>技术选型</th><th>说明</th></tr>
<tr><td>GPU 硬件</td><td>AMD Radeon RX 7900 XTX</td><td>24GB VRAM，支持 FP16/BF16</td></tr>
<tr><td>推理引擎</td><td>vLLM 0.6+</td><td>高性能 LLM 推理框架</td></tr>
<tr><td>深度学习框架</td><td>PyTorch 2.4+ ROCm</td><td>AMD GPU 原生支持</td></tr>
<tr><td>嵌入模型</td><td>BAAI/bge-small-en-v1.5</td><td>轻量级嵌入，GPU 加速</td></tr>
<tr><td>向量数据库</td><td>ChromaDB</td><td>本地向量存储</td></tr>
</table>

<h2>5.2 性能优化策略</h2>
<table>
<tr><th>优化技术</th><th>说明</th><th>效果</th></tr>
<tr><td>FP16 混合精度</td><td>使用 float16 进行推理</td><td>显存占用降低 50%</td></tr>
<tr><td>Continuous Batching</td><td>vLLM 动态批处理</td><td>吞吐量提升 2-4 倍</td></tr>
<tr><td>PagedAttention</td><td>vLLM 内存管理</td><td>支持更大 batch size</td></tr>
<tr><td>GPU 加速向量检索</td><td>嵌入计算在 GPU 上</td><td>检索延迟降低 60%</td></tr>
</table>

<h2>5.3 为什么选择 AMD ROCm</h2>
<table>
<tr><th>维度</th><th>AMD ROCm</th><th>NVIDIA CUDA</th></tr>
<tr><td>开源性</td><td>完全开源</td><td>闭源</td></tr>
<tr><td>成本</td><td>硬件成本更低</td><td>高端 GPU 昂贵</td></tr>
<tr><td>企业部署</td><td>无供应商锁定</td><td>依赖 NVIDIA</td></tr>
<tr><td>大模型支持</td><td>vLLM 原生支持</td><td>vLLM 原生支持</td></tr>
</table>
</div>

<div class="section">
<h1>6. 测试验证</h1>

<h2>6.1 Ground Truth 验证</h2>
<p>使用某供应链真实盘点数据测试，全部指标与人工分析一致：</p>

<table>
<tr><th>指标</th><th>Agent 输出</th><th>人工验证</th><th>状态</th></tr>
<tr><td>SKU 总数</td><td>528</td><td>528</td><td>通过</td></tr>
<tr><td>系统库存总计</td><td>21,144 件</td><td>21,144 件</td><td>通过</td></tr>
<tr><td>净差异</td><td>-971 件</td><td>-971 件</td><td>通过</td></tr>
<tr><td>总体差异率</td><td>4.6%</td><td>4.6%</td><td>通过</td></tr>
<tr><td>净差异金额</td><td>-989,900.97 元</td><td>-989,900.97 元</td><td>通过</td></tr>
<tr><td>日志关联三分类</td><td>14/21/124</td><td>14/21/124</td><td>通过</td></tr>
<tr><td>质量校验</td><td>7/7 通过</td><td>全部通过</td><td>通过</td></tr>
</table>

<h2>6.2 业务价值</h2>
<table>
<tr><th>指标</th><th>人工分析</th><th>Agent</th><th>提升</th></tr>
<tr><td>分析耗时</td><td>2-3 天</td><td>10 分钟</td><td>99%</td></tr>
<tr><td>准确率</td><td>依赖经验</td><td>与 Ground Truth 一致</td><td>—</td></tr>
<tr><td>可审计性</td><td>无</td><td>7 条质量校验</td><td>—</td></tr>
</table>
</div>

<div class="section">
<h1>7. 应用场景</h1>
<table>
<tr><th>场景</th><th>说明</th></tr>
<tr><td>企业库存盘点</td><td>月度/季度循环盘点差异分析</td></tr>
<tr><td>仓库调账</td><td>管理层会议前的调账材料准备</td></tr>
<tr><td>审计配合</td><td>提供可追溯的差异分析证据</td></tr>
<tr><td>库存优化</td><td>基于差异数据优化库存管理策略</td></tr>
</table>

<h1>8. 未来计划</h1>
<ul>
<li>支持更多数据格式（PDF 扫描件、数据库直连）</li>
<li>增加可视化图表（差异分布、趋势分析）</li>
<li>支持多仓库对比分析</li>
<li>接入企业 ERP 系统自动取数</li>
</ul>
</div>

<div class="section">
<h1>9. 团队信息</h1>
<table>
<tr><th>角色</th><th>姓名</th><th>职责</th></tr>
<tr><td>开发者</td><td>——</td><td>场景定义、产品设计、Agent 开发、数据处理、系统集成</td></tr>
</table>

<h1>10. 联系方式</h1>
<ul>
<li>GitHub：private repository</li>
<li>邮箱：developer@example.com</li>
</ul>
</div>

</body>
</html>
"""

def generate_pdf():
    # Write HTML file
    html_path = "/app/docs/project_report.html"
    pdf_path = "/app/docs/InventoryDoc_Agent_项目说明文档.pdf"
    
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(HTML_CONTENT)
    
    print(f"HTML file created: {html_path}")
    
    # Try to convert to PDF using weasyprint
    try:
        from weasyprint import HTML
        HTML(filename=html_path).write_pdf(pdf_path)
        print(f"PDF generated successfully: {pdf_path}")
        return pdf_path
    except Exception as e:
        print(f"WeasyPrint failed: {e}")
        
        # Fallback: try using wkhtmltopdf
        try:
            result = subprocess.run(
                ["wkhtmltopdf", "--encoding", "utf-8", html_path, pdf_path],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"PDF generated with wkhtmltopdf: {pdf_path}")
                return pdf_path
            else:
                print(f"wkhtmltopdf failed: {result.stderr}")
        except FileNotFoundError:
            print("wkhtmltopdf not found")
        
        print("Could not generate PDF. HTML file is available at:", html_path)
        return html_path

if __name__ == "__main__":
    generate_pdf()
