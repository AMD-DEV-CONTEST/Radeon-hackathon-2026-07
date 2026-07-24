# Supply Chain DocAgent 演示视频脚本

## 视频时长：4分钟
## 赛道：Track 2 - Private AI Agent Development & Local Deployment

---

## 场景1：开场介绍（0:00-0:30）

### 画面内容：
- 显示项目标题幻灯片
- 团队名称和成员

### 配音/字幕：
```
"Hello, we are cyslmsolomon team.

Today we present Supply Chain DocAgent - 
a private AI Agent for supply chain document processing 
running on AMD Radeon GPU with ROCm."
```

---

## 场景2：环境展示（0:30-1:00）

### 命令行操作：

```bash
# 1. 展示AMD GPU信息
rocm-smi

# 2. 展示ROCm环境
python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'ROCm available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"

# 3. 展示项目目录
ls -la
```

### 配音/字幕：
```
"Our system runs on AMD Radeon GPU with ROCm software stack.
As you can see, PyTorch is properly configured with ROCm support,
and the GPU is ready for inference."
```

---

## 场景3：系统启动（1:00-1:30）

### 命令行操作：

```bash
# 激活虚拟环境
source venv/bin/activate

# 启动Agent系统
python -m src.agent
```

### 画面内容：
- 终端显示系统启动日志
- 显示Gradio Web UI启动信息
- 浏览器自动打开 http://localhost:7860

### 配音/字幕：
```
"Let's start the Supply Chain DocAgent system.
The multi-agent orchestrator is initializing...
RAG engine is loading document templates...
Web UI is now ready at localhost:7860"
```

---

## 场景4：功能演示 - 采购订单处理（1:30-2:30）

### Web UI操作：

1. **上传采购订单（PO）**
   - 点击上传按钮
   - 选择 `data/sample_docs/po_sample.txt`
   - 点击"Process Document"

2. **展示处理过程**
   - Classify Agent识别单据类型
   - Extract Agent提取关键字段
   - 校验结果展示

3. **显示提取结果**
   - 物料编码、数量、单价
   - 供应商信息
   - 交货日期

### 配音/字幕：
```
"Now let's process a purchase order document.

Step 1: The Classify Agent identifies this as a Purchase Order.
Step 2: The Extract Agent pulls out key information:
  - Material Code: AMD-GPU-7900
  - Quantity: 50 units
  - Unit Price: $999
  - Supplier: TechSupply Inc.

Step 3: Validation Agent checks the data..."
```

---

## 场景5：三单校验演示（2:30-3:15）

### Web UI操作：

1. **上传送货单**
   - 选择 `data/sample_docs/delivery_sample.txt`
   - 点击"Process Document"

2. **上传发票**
   - 选择 `data/sample_docs/invoice_sample.txt`
   - 点击"Process Document"

3. **展示交叉校验结果**
   - 显示PO vs 送货单对比
   - 显示PO vs 发票对比
   - 标记任何差异

### 配音/字幕：
```
"Now let's process the delivery note and invoice 
to perform three-way matching.

The Validate Agent is comparing:
- Purchase Order vs Delivery Note
- Purchase Order vs Invoice

Result: All quantities match (50 units).
Price variance: $0 - PASS
Total amount: $49,950 - MATCHED

Document validation: PASSED ✓"
```

---

## 场景6：异常处理演示（3:15-3:45）

### Web UI操作：

1. **展示异常单据**
   - 上传一个有差异的单据（可准备测试数据）
   - 展示异常检测结果

2. **展示异常分类**
   - 数量差异
   - 价格异常
   - 推送给对应负责人

### 配音/字幕：
```
"When a document has discrepancies,
the Exception Agent automatically:
1. Classifies the anomaly type
2. Calculates the variance
3. Routes to the appropriate approver

Here we see a quantity mismatch detected:
- Ordered: 50 units
- Delivered: 45 units
- Variance: -10%

Status: PENDING APPROVAL"
```

---

## 场景7：GPU性能展示（3:45-3:55）

### 命令行操作：

```bash
# 展示推理性能
python -c "
import time
import torch
from src.rag import RAGEngine

# 初始化RAG引擎
rag = RAGEngine()

# 测试查询性能
start = time.time()
results = rag.query('采购订单模板')
end = time.time()

print(f'RAG Query Time: {(end-start)*1000:.2f}ms')
print(f'GPU Memory Used: {torch.cuda.memory_allocated()/1024**3:.2f} GB')
"
```

### 配音/字幕：
```
"Running on AMD Radeon GPU with ROCm,
our system achieves fast inference times.
RAG queries complete in under 100ms,
enabling real-time document processing."
```

---

## 场景8：总结（3:55-4:00）

### 画面内容：
- 显示项目关键特性列表
- 显示联系方式

### 配音/字幕：
```
"Supply Chain DocAgent delivers:
✓ Multi-Agent collaboration
✓ AMD GPU acceleration
✓ Complete privacy protection
✓ Real-world business value

Thank you for watching!"
```

---

## 录制注意事项：

1. **屏幕录制设置**
   - 分辨率：1920x1080
   - 帧率：30fps
   - 录制整个屏幕或浏览器窗口

2. **命令行准备**
   - 字体大小：至少14pt，确保清晰可读
   - 终端背景：深色主题
   - 提前测试所有命令

3. **Web UI准备**
   - 清除浏览器缓存
   - 关闭不必要的标签页
   - 准备好示例文件

4. **视频编辑**
   - 添加字幕（英文）
   - 适当放大关键区域
   - 添加转场效果

5. **AMD GPU展示**
   - 使用 `rocm-smi` 而不是 `nvidia-smi`
   - 展示ROCm相关信息
   - 确保GPU使用率可见

## 示例文件准备：

确保以下文件存在于 `data/sample_docs/` 目录：
- `po_sample.txt` - 采购订单样本
- `delivery_sample.txt` - 送货单样本
- `invoice_sample.txt` - 发票样本
