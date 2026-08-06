"""Built-in Jinja2 Markdown templates."""

from __future__ import annotations

from jinja2 import Environment, StrictUndefined

INSPECTION_REPORT_TEMPLATE = """# BuildGuard 安全巡检报告

**生成时间：** {{ generated_at[:19].replace("T", " ") }}
**检测来源：** {{ sources | join("、") if sources else "未知" }}

---

## 一、AI 分析摘要

> *以下摘要由本地 AI 模型生成，供参考；规范引用以第三节为准。*

{{ summary }}

---

## 二、发现的问题与风险

{% for risk in risks %}
{% set sev = risk.severity %}
{% set sev_zh = {"critical": "严重", "high": "高", "normal": "中等", "low": "低"}.get(sev, sev) %}
{% set sev_icon = {"critical": "🔴", "high": "🟠", "normal": "🟡", "low": "🟢"}.get(sev, "") %}
### {{ loop.index }}. 风险等级：{{ sev_icon }} {{ sev_zh }}（评分 {{ "%.2f"|format(risk.score) }}）

{{ risk.summary }}

{% endfor %}
{% if not risks %}
暂无确定性风险评分。
{% endif %}

**检测明细：**

{% for finding in findings %}- {{ finding }}
{% else %}- 未发现可报告的缺陷或事件。{% endfor %}

---

## 三、相关规范依据

{% for citation in citations %}
**[{{ loop.index }}] {{ citation.statement.standard_name }}{% if citation.statement.article %} · {{ citation.statement.article }}{% endif %}{% if citation.statement.page %} 第 {{ citation.statement.page }} 页{% endif %}**

> {{ citation.statement.quoted_content }}

{% else %}
暂无通过一致性验证的规范引用。
{% endfor %}

---

## 四、整改建议

{% for recommendation in recommendations %}{{ loop.index }}. {{ recommendation }}
{% else %}请由现场负责人结合人工复核结果制定整改措施。{% endfor %}

---

## 五、现场证据

{% for item in visual_evidence %}
**检测目标：** {{ item.label }}　**置信度：** {{ "%.1f%%"|format(item.confidence * 100) }}
{% if item.visualization_path %}
![{{ item.label }}]({{ item.visualization_path }})
{% endif %}
{% if item.clip_path %}
**事件视频片段：** `{{ item.clip_path }}`
{% endif %}
{% else %}
未记录可视化证据文件。
{% endfor %}

---

## 六、人工复核

{{ human_review }}

---

*本报告由 BuildGuard 自动生成，须经现场授权人员复核后方可作为正式记录。*
"""


def render_markdown(context: dict[str, object]) -> str:
    """Render the configured report using strict variables."""
    environment = Environment(
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.from_string(INSPECTION_REPORT_TEMPLATE).render(**context).strip() + "\n"
