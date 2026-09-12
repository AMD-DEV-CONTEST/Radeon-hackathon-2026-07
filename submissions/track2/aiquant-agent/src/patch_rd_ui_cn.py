#!/usr/bin/env python3
"""
RD-Agent Streamlit UI 永久汉化补丁脚本
========================================
自动定位 aiquant 环境下 rdagent UI 源码路径，
批量替换所有硬编码英文文本为简体中文。

功能：
1. 自动定位 rdagent log/ui 源码目录
2. 批量替换英文文案为中文
3. 生成备份文件 *.ui.bak，支持一键还原
4. 仅修改展示文案，不动绘图/计算/数据逻辑

用法:
  python patch_rd_ui_cn.py          # 执行汉化
  python patch_rd_ui_cn.py --restore # 还原英文原版
  python patch_rd_ui_cn.py --status # 检查汉化状态
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path


# ── 中文翻译映射表 ────────────────────────────────────
# 格式: (匹配模式, 替换文本)
# 使用精确字符串替换，避免误伤变量名/代码逻辑

REPLACEMENTS: dict[str, dict[str, str]] = {
    # ═══════════════════════════════════════════════════
    # app.py - 主 UI 页面
    # ═══════════════════════════════════════════════════
    "app.py": {
        # 页面标题
        '"RD-Agent"': '"RD-Agent 控制台"',
        '"🎓"': '"📊"',
        
        # Sidebar
        '"Table of Content"': '"目录导航"',
        '"Control Panel"': '"控制面板"',
        '"Log Path"': '"日志路径"',
        '"Manual Input"': '"手动输入"',
        '"log path"': '"日志路径"',
        '"Select from `"': '"从 `"',
        '"**log path**"': '"**日志路径**"',
        '"All Loops"': '"加载全部"',
        '"Reset"': '"重置"',
        '"Next Loop"': '"下一轮"',
        '"Next Step"': '"下一步"',
        '"Config⚙️"': '"配置⚙️"',
        '"excluded log tags"': '"排除日志标签"',
        '"excluded log types"': '"排除日志类型"',
        '"debug"': '"调试"',
        '"Single Step Run"': '"单步运行"',
        '"Debug Info"': '"调试信息"',
        '"message id"': '"消息ID"',
        '"round"': '"轮次"',
        '"evolving round"': '"进化轮次"',
        
        # 导航标题
        '"RD-Agent🤖  [:grey[@GitHub]](https://github.com/microsoft/RD-Agent)"': 
            '"RD-Agent🤖  [:grey[@GitHub]](https://github.com/microsoft/RD-Agent)"',
        
        # Main header
        '"RD-Agent:<br>LLM-based autonomous evolving agents for industrial data-driven R&D"':
            '"RD-Agent：<br>基于大语言模型的工业级自主进化智能体，驱动数据研发自动化"',
        
        # Section headers
        '"Scenario Description📖"': '"场景描述📖"',
        '"Summary📊"': '"总览📊"',
        '"Metrics📈"': '"指标📈"',
        '"Hypotheses🏅"': '"假设🏅"',
        '"R&D Loops♾️"': '"研发循环♾️"',
        '"Research🔍"': '"研究🔍"',
        '"Research🔍 (reader)"': '"研究🔍（阅读模式）"',
        '"Development🛠️"': '"开发🛠️"',
        '"Development🛠️ (evolving coder)"': '"开发🛠️（进化编码器）"',
        '"Feedback📝"': '"反馈📝"',
        
        # Research section
        '"**Hypothesis💡**"': '"**研究假设💡**"',
        '"**Hypothesis**: {h.hypothesis}\\n- **Reason**: {h.reason}"':
            '"**假设内容**：{h.hypothesis}\\n- **推导依据**：{h.reason}"',
        
        # Factor tasks
        '"**Factor Tasks🚩**"': '"**因子任务🚩**"',
        '"**Model Tasks🚩**"': '"**模型任务🚩**"',
        '"**Description**":': '"**描述**":',
        '"**Factor Name**":': '"**因子名称**":',
        '"**Model Name**":': '"**模型名称**":',
        '"**Model Type**":': '"**模型类型**":',
        '"**Train Para**":': '"**训练参数**":',
        '"Formulation"': '"公式"',
        '"Variable | Description"': '"变量 | 描述"',
        
        # Hypothesis display
        '"hypothesis": "RD-Agent proposes the hypothesis"':
            '"hypothesis": "RD-Agent 提出的研究假设"',
        '"concise_justification": "because the reason"':
            '"concise_justification": "推导依据"',
        '"concise_observation": "based on the observation"':
            '"concise_observation": "基于的观察"',
        '"Knowledge": "Knowledge"': '"Knowledge": "实践知识"',
        
        # Metrics
        '"successful hypotheses"': '"仅成功假设"',
        '"download the metrics (csv)"': '"下载指标数据 (CSV)"',
        
        # Evolving
        '"**☑️ Evolving Status**"': '"**☑️ 进化状态**"',
        '"**🔄️Evolving Rounds**"': '"**🔄️ 进化轮次**"',
        '"**Workspace Path**"': '"**工作区路径**"',
        
        # Feedback
        '"**Config⚙️**"': '"**实验配置⚙️**"',
        '"**Returns📈**"': '"**收益曲线📈**"',
        '"**Hypothesis Feedback🔍**"': '"**假设评审反馈🔍**"',
        '"**Observations**: {h.observations}\\n- **Hypothesis Evaluation**: {h.hypothesis_evaluation}\\n- **New Hypothesis**: {h.new_hypothesis}\\n- **Decision**: {h.decision}\\n- **Reason**: {h.reason}"':
            '"**观察发现**：{h.observations}\\n- **假设评估**：{h.hypothesis_evaluation}\\n- **新假设**：{h.new_hypothesis}\\n- **决策**：{h.decision}\\n- **理由**：{h.reason}"',
        
        # RD-Agent proposes the hypothesis (in dict)
        '"RD-Agent proposes the hypothesis⬇️"': '"RD-Agent 提出的研究假设⬇️"',
        '"because the reason⬇️"': '"推导依据⬇️"',
        '"based on the observation⬇️"': '"基于的观察⬇️"',
        '"Knowledge⬇️ gained after practice"': '"实践后获得的知识⬇️"',
        
        # Tabs hint
        '"You can navigate through the tabs using ⬅️ ➡️ or by holding Shift and scrolling with the mouse wheel🖱️."':
            '"你可以使用 ⬅️ ➡️ 键切换标签页，或按住 Shift 键并用鼠标滚轮🖱️滚动浏览。"',
        
        # Task completion analysis
        '"Task Completion Analysis"': '"任务完成度分析"',
        '"🔄 Aggregate Completion Across All Loops"': '"🔄 全部循环汇总完成度"',
        '"Detailed Results by Loop"': '"各循环详细结果"',
        '"Summary:"': '"摘要："',
        '"After round 1:"': '"第1轮后："',
        '"After round 3:"': '"第3轮后："',
        '"After round 5:"': '"第5轮后："',
        '"After final round"': '"最终轮后"',
        '"No task completion data available."': '"暂无任务完成度数据。"',
        
        # Columns in analysis
        '"Total Tasks"': '"总任务数"',
        '"Passed (Round 1)"': '"通过 (第1轮)"',
        '"Passed (Round 3)"': '"通过 (第3轮)"',
        '"Passed (Round 5)"': '"通过 (第5轮)"',
        '"Passed (Final)"': '"通过 (最终)"',
        '"Evolving Round"': '"进化轮次"',
        '"Tasks Passed"': '"通过任务数"',
        '"Cumulative Passed"': '"累计通过数"',
        
        # Aggregate metrics
        '"📊 Overall Completion Progress:"': '"📊 总体完成进度："',
        '"After Round 1"': '"第1轮后"',
        '"After Round 3"': '"第3轮后"',
        '"After Round 5"': '"第5轮后"',
        '"Final Completion"': '"最终完成度"',
        
        # Toggle
        '"show analyse_task_competition"': '"显示任务完成度分析"',
        
        # Radio
        '"**Loops**"': '"**循环选择**"',
        
        # Footer
        '"Disclaimer"': '"免责声明"',
        '"*This content is AI-generated and may not be fully accurate or up-to-date; please verify with a professional for critical matters.*"':
            '"*本内容由AI生成，可能不完全准确或最新；关键事项请咨询专业人士核实。*"',
        
        # Messages
        '"No More Logs to Show!"': '"没有更多日志可显示！"',
        '"No Scenario Info detected"': '"未检测到场景信息"',
        '"Scenario Info detected"': '"已检测到场景信息"',
        '"Please Set Log Path!"': '"请设置日志路径！"',
        '"Unknown Scenario!"': '"未知场景！"',
        '"Error displaying workspace path"': '"显示工作区路径出错"',
        '"**Download Button Error**"': '"**下载按钮错误**"',
        
        # Expander labels
        '":green[**Exp Workspace**]"': '":green[**实验工作区**]"',
        '"**Download** submission.csv"': '"**下载** submission.csv"',
        
        # workspace output
        '"workspace"': '"工作区"',
    },
    
    # ═══════════════════════════════════════════════════
    # web.py - WebView 类
    # ═══════════════════════════════════════════════════
    "web.py": {
        # Hypothesis window
        '"#### **Hypothesis💡**"': '"#### **研究假设💡**"',
        '"**Hypothesis**: {h.hypothesis}\\n- **Reason**: {h.reason}"':
            '"**假设内容**：{h.hypothesis}\\n- **推导依据**：{h.reason}"',
        
        # Hypothesis feedback window
        '"#### **Hypothesis Feedback🔍**"': '"#### **假设评审反馈🔍**"',
        '"**Observations**: {h.observations}\\n- **Hypothesis Evaluation**: {h.hypothesis_evaluation}\\n- **New Hypothesis**: {h.new_hypothesis}\\n- **Decision**: {h.decision}\\n- **Reason**: {h.reason}"':
            '"**观察发现**：{h.observations}\\n- **假设评估**：{h.hypothesis_evaluation}\\n- **新假设**：{h.new_hypothesis}\\n- **决策**：{h.decision}\\n- **理由**：{h.reason}"',
        
        # Factor task window
        '"**Factor Name**"': '"**因子名称**"',
        '"**Description**"': '"**描述**"',
        '"Factor resources: {ft.factor_resources}"': '"因子资源: {ft.factor_resources}"',
        
        # Model task window
        '"**Model Name**"': '"**模型名称**"',
        '"**Model Type**"': '"**模型类型**"',
        
        # Factor feedback window
        '"### :blue[Factor Execution Feedback]"': '"### :blue[因子执行反馈]"',
        '"### :blue[Factor Code Feedback]"': '"### :blue[因子代码反馈]"',
        '"### :blue[Factor Value Feedback]"': '"### :blue[因子数值反馈]"',
        '"### :blue[Factor Final Feedback]"': '"### :blue[因子最终反馈]"',
        '"### :blue[Factor Final Decision]"': '"### :blue[因子最终决策]"',
        '"This implementation is {\'SUCCESS\' if fb.final_decision else \'FAIL\'}."':
            '"本轮实现结果为 {\'成功\' if fb.final_decision else \'失败\'}。"',
        
        # Model feedback window
        '"### :blue[Model Execution Feedback]"': '"### :blue[模型执行反馈]"',
        '"### :blue[Model Shape Feedback]"': '"### :blue[模型结构反馈]"',
        '"### :blue[Model Value Feedback]"': '"### :blue[模型数值反馈]"',
        '"### :blue[Model Code Feedback]"': '"### :blue[模型代码反馈]"',
        '"### :blue[Model Final Feedback]"': '"### :blue[模型最终反馈]"',
        '"### :blue[Model Final Decision]"': '"### :blue[模型最终决策]"',
        
        # Workspace window
        '"Factor Info"': '"因子信息"',
        '"Model Info"': '"模型信息"',
        
        # QlibFactorExp window
        '"**Factor Tasks**"': '"**因子任务**"',
        '"**Results**"': '"**回测结果**"',
        '"results table"': '"结果表格"',
        '"results chart"': '"结果图表"',
        '"Results are incomplete."': '"结果数据不完整。"',
        
        # QlibModelExp window
        '"**Model Tasks**"': '"**模型任务**"',
        
        # SimpleTraceWindow
        '"Factor Tasks"': '"因子任务"',
        '"Factor Workspaces"': '"因子工作区"',
        '"Factor Feedbacks"': '"因子反馈"',
        '"Model Tasks"': '"模型任务"',
        '"Model Workspaces"': '"模型工作区"',
        '"Model Feedbacks"': '"模型反馈"',
        
        # TraceObjWindow
        '"Trace History {id}"': '"追踪历史 {id}"',
        
        # EvolvingWindow
        '"**Factor Codes**"': '"**因子代码**"',
        '"**Model Codes**"': '"**模型代码**"',
        '"**Factor Feedbacks🔍**"': '"**因子反馈🔍**"',
        '"**Model Feedbacks🔍**"': '"**模型反馈🔍**"',
        
        # DevelopmentWindow
        '"Evolving Loops🔧"': '"进化循环🔧"',
        
        # FeedbackWindow
        '"**Returns📈**"': '"**收益曲线📈**"',
        
        # TraceWindow
        '"**Metrics📈**"': '"**指标📈**"',
        '"**Hypotheses🏅**"': '"**假设🏅**"',
        '"R&D Loops♾️"': '"研发循环♾️"',
    },
    
    # ═══════════════════════════════════════════════════
    # llm_st.py - LLM 调试页面
    # ═══════════════════════════════════════════════════
    "llm_st.py": {
        # Page title
        '"debug_llm"': '"调试LLM"',
        
        # Sidebar
        '"**Log Path**"': '"**日志路径**"',
        '"Refresh Data"': '"刷新数据"',
        
        # Chinese -> keep as is (already Chinese)
        # But some were already Chinese in the original
        
        # Loop navigation
        '"选择 Loop"': '"选择循环"',
        
        # Loading
        '"正在加载文件夹列表..."': '"正在加载文件夹列表..."',
        '"找到"': '"找到"',
        '"个文件夹"': '"个文件夹"',
        '"数据加载完成！耗时"': '"数据加载完成！耗时"',
        '"秒"': '"秒"',
        '"加载数据失败"': '"加载数据失败"',
        '"正在加载数据文件"': '"正在加载数据文件"',
        '"正在处理 Loop"': '"正在处理循环"',
        '"当前 Loop 数据处理完成！"': '"当前循环数据处理完成！"',
        
        # Expander labels
        '"Exp in :violet[**"': '"实验在 :violet[**"',
    },
    
    # ═══════════════════════════════════════════════════
    # ds_summary.py - 数据科学摘要页
    # ═══════════════════════════════════════════════════
    "ds_summary.py": {
        '"Show Curves"': '"显示曲线"',
        '"Show Curves (Lite)"': '"显示曲线（精简版）"',
        '"Show these folders"': '"显示这些文件夹"',
        '"Select MLE-Bench Competitions Level"': '"选择MLE-Bench竞赛级别"',
        '"Select Best"': '"选择最佳"',
        '"Ours vs Base"': '"基准对比"',
        '"Curves"': '"曲线"',
        '"**统计的比赛数目: :red["': '"**统计的比赛数目: :red["',
        '"Error occurred when show summary"': '"显示摘要时发生错误"',
        '"Distribution of Total Loops"': '"总循环数分布"',
        
        # Column names
        '"Select"': '"选择"',
        '"Competition"': '"竞赛"',
        '"Total Loops"': '"总循环数"',
        
        # Warnings
        '"Loop {k}\'s valid scores index are not unique, only the last one will be kept to show."':
            '"循环 {k} 的验证分数索引不唯一，仅保留最后一个显示。"',
        '"summary.pkl not found in **{lf}**\\n\\nRun:`dotenv run -- python rdagent/log/mle_summary.py grade_summary --log_folder={lf} --hours=<>`"':
            '"在 **{lf}** 中未找到 summary.pkl\\n\\n请运行：`dotenv run -- python rdagent/log/mle_summary.py grade_summary --log_folder={lf} --hours=<>`"',
    },
    
    # ═══════════════════════════════════════════════════
    # ds_trace.py - 数据科学追踪页
    # ═══════════════════════════════════════════════════
    "ds_trace.py": {
        # Sidebar
        '"**Show LLM Log**"': '"**显示LLM日志**"',
        '"*Show stdout*"': '"*显示标准输出*"',
        '"*Show save workspace*"': '"*显示保存工作区*"',
        '"Summary"': '"总览"',
        '"Exp Gen"': '"实验生成"',
        '"Coding"': '"编码"',
        '"Running"': '"运行"',
        '"Feedback"': '"反馈"',
        '"Record"': '"记录"',
        '"SOTA Experiment"': '"最佳实验"',
        
        # Headers
        '"Exp Gen"': '"实验生成"',
        '"💡 Hypothesis"': '"💡 研究假设"',
        '"📋 pending_tasks"': '"📋 待处理任务"',
        '"📁 Exp Workspace"': '"📁 实验工作区"',
        '"codes"': '"代码"',
        '"evolving feedback"': '"进化反馈"',
        '"No evolving."': '"无进化数据。"',
        
        # Tabs
        '"execution"': '"执行"',
        '"return_checking"': '"返回检查"',
        '"code"': '"代码"',
        '"others"': '"其他"',
        
        # Coding
        '"Exp Workspace (coding final)"': '"实验工作区（编码最终版）"',
        
        # Running
        '"Exp Workspace (running final)"': '"实验工作区（运行最终版）"',
        '"Result"': '"结果"',
        '"MLE Submission Score"': '"MLE提交分数"',
        '"no submission to score"': '"无提交数据"',
        
        # Feedback
        '"**SOTA Exp Hypothesis**"': '"**最佳实验假设**"',
        '"**Exp Workspace**"': '"**实验工作区**"',
        '"No SOTA experiment."': '"无最佳实验。"',
        
        # Summary
        '"Show trace DAG"': '"显示追踪DAG"',
        '"Only Success"': '"仅成功"',
        '"LLM Calls"': '"LLM调用次数"',
        '"LLM Filter Calls"': '"LLM过滤调用"',
        '"Timeouts (C)"': '"超时（编码）"',
        '"Timeouts (R)"': '"超时（运行）"',
        '"Trace DAG"': '"追踪DAG"',
        '"Hypotheses Table"': '"假设表格"',
        '"Scores Curve"': '"分数曲线"',
        '"Component Statistics"': '"组件统计"',
        '"Time Statistics"': '"时间统计"',
        '"COST Curve"': '"费用曲线"',
        '"COST($) per Loop & Cumulative COST($)"': '"每轮费用 & 累计费用"',
        '"COST($) per Loop"': '"每轮费用"',
        '"Cumulative COST($)"': '"累计费用"',
        '"Timeline"': '"时间线"',
        
        # Column names in summary
        '"Root N"': '"根节点"',
        '"Parent N"': '"父节点"',
        '"Component"': '"组件"',
        '"Hypothesis"': '"假设"',
        '"Reason"': '"原因"',
        '"Others"': '"其他"',
        '"Run Score (valid)"': '"验证分数"',
        '"Run Score (test)"': '"测试分数"',
        '"e-loops(c)"': '"进化轮(编码)"',
        '"e-loops(r)"': '"进化轮(运行)"',
        '"COST($)"': '"费用($)"',
        '"Time"': '"耗时"',
        
        # Stats
        '"Loop Num"': '"循环数"',
        '"Valid Loop"': '"有效循环"',
        '"Success Loop"': '"成功循环"',
        '"Valid Rate"': '"有效率"',
        '"Success Rate"': '"成功率"',
        '"Avg e-loops(c)"': '"平均进化轮(编码)"',
        
        # Tasks
        '"**Factor Tasks**"': '"**因子任务**"',
        '"**Model Tasks**"': '"**模型任务**"',
        
        # Misc
        '"Please Set: {stdout_path}"': '"请设置: {stdout_path}"',
        '"No files in :blue["': '"无文件在 :blue["',
        
        # Workspace popover
        '"**Diff with {cmp_name}**"': '"**与 {cmp_name} 的差异**"',
        '"📂Files in :blue["': '"📂文件在 :blue["',
        
        # Save files
        '"### Save All Files to Folder"': '"### 保存所有文件到文件夹"',
        '"Enter target folder path:"': '"输入目标文件夹路径："',
        '"Save Files"': '"保存文件"',
        '"Please enter a valid folder path."': '"请输入有效的文件夹路径。"',
        '"All files saved to: {target_folder}"': '"所有文件已保存到: {target_folder}"',
        
        # Other
        '"Error"': '"错误"',
        '"No settings found."': '"未找到配置。"',
        '"Loading folder list..."': '"加载文件夹列表..."',
        '"Please select a log path first!"': '"请先选择日志路径！"',
        '"Select from :blue[**{state.log_folder.absolute()}**]"': '"从 :blue[**{state.log_folder.absolute()}**] 选择"',
        '"Select :blue[**one log folder**]"': '"选择 :blue[**一个日志文件夹**]"',
        
        # Exception
        '":red[**Exception**]": {fb.exception}"': '":red[**异常**]": {fb.exception}"',
        
        # SOTA
        '":orange[trace.**sota_exp_to_submit**]"': '":orange[追踪.**待提交最佳实验**]"',
        '":orange[trace.**sota_experiment()**]"': '":orange[追踪.**最佳实验()**]"',
        
        # Loop stdout
        '"Loop {loop_id} stdout"': '"循环 {loop_id} 标准输出"',
    },
    
    # ═══════════════════════════════════════════════════
    # dsapp.py - 数据科学应用入口
    # ═══════════════════════════════════════════════════
    "dsapp.py": {
        '"Summary"': '"总览"',
        '"Trace"': '"追踪"',
        '"Aide"': '"助手"',
        '"Pages"': '"页面"',
        '"Settings"': '"设置"',
        '"**Log Folders**(split by \';\')"': '"**日志文件夹**（用\';\'分隔）"',
        '"Confirm"': '"确认"',
    },
    
    # ═══════════════════════════════════════════════════
    # ds_user_interact.py - 用户交互页面
    # ═══════════════════════════════════════════════════
    "ds_user_interact.py": {
        '"Contextual Information:"': '"上下文信息："',
        '"Competition scenario:"': '"竞赛场景："',
        '"Former attempts summary:"': '"先前尝试摘要："',
        '"Current SOTA code"': '"当前最佳代码"',
        '"Hypothesis candidates:"': '"候选假设："',
        '"Decisions to make:"': '"待决策事项："',
        '"Please modify the fields below and submit to provide your feedback."':
            '"请修改以下字段并提交以提供您的反馈。"',
        '"Target hypothesis: (you can copy from candidates)"':
            '"目标假设：（可从候选中复制）"',
        '"Target task description:"':
            '"目标任务描述："',
        '"Former user instructions, you can modify or delete the content to remove certain instruction."':
            '"先前的用户指令，您可以修改或删除内容以移除特定指令。"',
        '"Former user instruction"': '"先前的用户指令"',
        '"Add new user instruction"': '"添加新的用户指令"',
        '"Submit"': '"提交"',
        '"Approve without changes"': '"无需修改直接批准"',
        '"Your feedback has been submitted. Thank you!"':
            '"您的反馈已提交。谢谢！"',
        '"Extend expiration by 60s"': '"延长有效期60秒"',
        '"Please select a session from the sidebar."':
            '"请从侧边栏选择一个会话。"',
        '"R&D-Agent User Interaction Portal"': '"研发Agent用户交互门户"',
        '"Active Sessions"': '"活跃会话"',
        '"Click a session to view:"': '"点击会话查看："',
        '"No active sessions available. Please wait."':
            '"暂无活跃会话，请稍候。"',
        '"✅ means picked as target hypothesis"':
            '"✅ 表示被选为目标假设"',
    },
    
    # ═══════════════════════════════════════════════════
    # aide.py - AIDE 追踪页
    # ═══════════════════════════════════════════════════
    "aide.py": {
        '"AIDE trace"': '"AIDE 追踪"',
        '"Select Journal"': '"选择日志"',
        '"Parent ({p[\'metric\'][\'value\']}) Analysis"': '"父节点 ({p[\'metric\'][\'value\']}) 分析"',
        '"Child ({t[\'metric\'][\'value\']}) Plan"': '"子节点 ({t[\'metric\'][\'value\']}) 计划"',
        '"Diff"': '"差异"',
    },
}


def find_ui_dir() -> Path:
    """自动定位 rdagent UI 源码目录"""
    # 尝试从当前 conda 环境查找
    prefix = os.path.dirname(os.path.dirname(sys.executable))
    candidates = [
        Path(prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages" / "rdagent" / "log" / "ui",
    ]
    
    # 也尝试直接搜索
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import rdagent.log.ui; print(rdagent.log.ui.__path__[0])"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            candidates.insert(0, Path(result.stdout.strip()))
    except Exception:
        pass
    
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    
    # fallback: 使用已知路径
    fallback = Path("/opt/anaconda3/envs/aiquant/lib/python3.10/site-packages/rdagent/log/ui")
    if fallback.exists():
        return fallback
    
    raise FileNotFoundError(
        "无法定位 rdagent UI 源码目录。请确保 rdagent 已安装在当前 conda 环境中。\n"
        f"已尝试路径: {candidates}"
    )


def patch_file(filepath: Path, replacements: dict[str, str], backup: bool = True) -> int:
    """
    对单个文件执行文本替换。
    返回替换次数。
    """
    if not filepath.exists():
        print(f"  [跳过] 文件不存在: {filepath}")
        return 0
    
    content = filepath.read_text(encoding="utf-8")
    original = content
    count = 0
    
    for old, new in replacements.items():
        if old in content:
            content = content.replace(old, new)
            count += 1
    
    if content != original:
        if backup:
            backup_path = filepath.with_suffix(filepath.suffix + ".bak")
            if not backup_path.exists():
                shutil.copy2(filepath, backup_path)
                print(f"  [备份] {backup_path.name}")
        filepath.write_text(content, encoding="utf-8")
    
    return count


def restore_file(filepath: Path) -> bool:
    """从 .bak 文件还原"""
    backup_path = filepath.with_suffix(filepath.suffix + ".bak")
    if backup_path.exists():
        shutil.copy2(backup_path, filepath)
        backup_path.unlink()
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="RD-Agent UI 永久汉化补丁")
    parser.add_argument("--restore", action="store_true", help="还原英文原版")
    parser.add_argument("--status", action="store_true", help="检查汉化状态")
    parser.add_argument("--force", action="store_true", help="强制重新汉化（覆盖已有备份）")
    args = parser.parse_args()
    
    ui_dir = find_ui_dir()
    print(f"UI 源码目录: {ui_dir}")
    
    if args.restore:
        print("\n🔄 正在还原英文原版...")
        for filename in REPLACEMENTS:
            filepath = ui_dir / filename
            if restore_file(filepath):
                print(f"  [还原] {filename}")
        print("✅ 还原完成")
        return
    
    if args.status:
        print("\n📋 汉化状态检查:")
        all_patched = True
        for filename in REPLACEMENTS:
            filepath = ui_dir / filename
            backup_path = filepath.with_suffix(filepath.suffix + ".bak")
            if backup_path.exists():
                print(f"  ✅ {filename} — 已汉化（有备份）")
            else:
                print(f"  ⬜ {filename} — 未汉化")
                all_patched = False
        if all_patched:
            print("\n✅ 所有文件已汉化")
        else:
            print("\n⚠️ 部分文件未汉化，请执行 patch_rd_ui_cn.py 进行汉化")
        return
    
    # 执行汉化
    print("\n🔧 正在执行汉化...")
    total_count = 0
    
    for filename, replacements in REPLACEMENTS.items():
        filepath = ui_dir / filename
        backup_path = filepath.with_suffix(filepath.suffix + ".bak")
        
        # 如果已有备份且不是强制模式，跳过
        if backup_path.exists() and not args.force:
            print(f"  [跳过] {filename} — 已有备份（使用 --force 强制重新汉化）")
            continue
        
        count = patch_file(filepath, replacements, backup=not backup_path.exists())
        if count > 0:
            print(f"  ✅ {filename} — {count} 处替换")
            total_count += count
        else:
            print(f"  ⬜ {filename} — 无匹配内容")
    
    print(f"\n✅ 汉化完成，共替换 {total_count} 处文本")
    print("💡 提示: 使用 --restore 可还原英文原版")
    print(f"   备份文件位于: {ui_dir}/*.bak")


if __name__ == "__main__":
    main()
