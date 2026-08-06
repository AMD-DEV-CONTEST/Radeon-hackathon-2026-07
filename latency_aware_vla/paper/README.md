# Overleaf 使用说明

本目录可以整体上传到 Overleaf：

```text
paper/
  main.tex
  references.bib
  README.md
```

## 编译

Overleaf 设置：

- Compiler：pdfLaTeX
- Main document：`main.tex`
- TeX Live：默认最新版本

本地编译：

```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

## 填写规则

搜索全文中的 `TBD`。只允许用真实实验产物替换：

- 作者和联系方式；
- 精确软件版本；
- 训练步数和 batch size；
- 成功数/总数；
- 置信区间；
- throughput、jerk、boundary discontinuity；
- AMD VRAM、step time、inference latency；
- 团队成员贡献；
- 最终结论。

没有执行的实验应删除对应行或标为 `N/A`，不得填估计值。

## 推荐加入的图片

正式提交前可增加：

1. `figures/system.pdf`：Genesis → cameras/state → π0.5 → RTC queue → Franka；
2. `figures/success_vs_delay.pdf`：Sync/Async/RTC 成功率随延迟变化；
3. `figures/action_boundary.pdf`：同 seed 的 chunk boundary action 曲线；
4. `figures/amd_profile.pdf`：训练显存、step time、推理 P50/P95。

图片必须由脚本生成并保留原始 JSON。不要为了版面手动修改数据点。

## 定位

这是一份“顶会风格技术报告”，不是已经完成的顶会论文：

- 方法依据和实验协议按论文标准撰写；
- 结果部分保留显式占位符；
- 当前只有单任务仿真和小样本评估，不应声称达到顶会论文所需的实验广度；
- 对黑客马拉松而言，严谨、可复现、不过度宣称比伪造宏大结论更重要。

