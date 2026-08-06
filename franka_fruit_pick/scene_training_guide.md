# RationalVLA 场景特定训练和评估指南

## 概述

v6 prompt 已集成动态场景描述注入功能，支持4个场景 (A/B/C/D) 的特定训练和评估。

## 场景配置

| 场景 | 物体 | 任务类型 |
|------|------|----------|
| A | banana, lemon, plum, bowl | 水果拣选 |
| B | red_box, blue_box, red_block, blue_block, green_block | 颜色分类 |
| C | red_block, blue_block | 堆叠 |
| D | banana, lemon, plum, bowl, red_block, blue_block | 混合干扰 |

## 训练脚本使用

### 训练所有场景（默认）

```bash
python train_rationalvla_api.py --stage 1 --steps 2000
python train_rationalvla_api.py --stage 2 --steps 5000 --resume outputs/rationalvla/stage1/latest.pt
```

### 训练特定场景

```bash
# 场景 A - 水果拣选
python train_rationalvla_api.py --stage 1 --steps 2000 --scene-name A
python train_rationalvla_api.py --stage 2 --steps 5000 --scene-name A --resume outputs/rationalvla/stage1/latest.pt

# 场景 B - 颜色分类
python train_rationalvla_api.py --stage 1 --steps 2000 --scene-name B

# 场景 C - 堆叠
python train_rationalvla_api.py --stage 1 --steps 2000 --scene-name C

# 场景 D - 混合干扰
python train_rationalvla_api.py --stage 1 --steps 2000 --scene-name D
```

### 带轨迹数据的训练

```bash
python train_rationalvla_api.py --stage 2 --steps 5000 \
    --scene-name A \
    --trajectory-dirs /path/to/scene_A_trajectories \
    --resume outputs/rationalvla/stage1/latest.pt
```

## 评估脚本使用

### 单场景评估

```bash
# 评估场景 A
python eval_rationalvla_api.py --scene A

# 评估场景 B
python eval_rationalvla_api.py --scene B

# 评估所有场景
python eval_rationalvla_api.py
```

### 自定义检查点和数据集

```bash
python eval_rationalvla_api.py \
    --scene A \
    --checkpoint outputs/rationalvla/stage2/latest.pt \
    --dataset ../datasets/defect_instructions/defect_instructions_v2.jsonl
```

### 多场景批量评估

```bash
# 评估所有4个场景 + 所有场景合并
python eval_all_scenes.py

# 评估特定场景
python eval_all_scenes.py --scenes A B D

# 使用自定义检查点
python eval_all_scenes.py --checkpoint outputs/rationalvla/stage2_multiscene/latest.pt
```

## 输出结果

评估结果保存在 `outputs/rationalvla/eval_results_multi_scene.json`，包含：
- 每个场景的准确率
- 按缺陷维度分类的准确率
- 场景物体列表
- 样本数量

## 动态 Prompt 注入原理

1. **场景配置加载**：从 `scene_configs.py` 获取场景物体列表
2. **Prompt 生成**：在 `APIMLLM.__init__` 中动态生成 system prompt
3. **场景描述注入**：`SCENE: Table with {objects}` 格式
4. **API 分类**：API 根据场景物体列表判断指令是否有效

### Prompt 模板示例（场景 A）

```
You are a robot arm instruction classifier. Reply with ONLY '<ACT>' or '<REJ>'.

SCENE: Table with banana, lemon, plum, bowl

RULES:
- <ACT>: Object is in scene AND action is safe and possible
- <REJ>: Object NOT in scene OR unsafe OR impossible OR invalid color

INVALID COLORS: purple, neon, glowing, transparent, mirror, rainbow, invisible, holographic
INVALID OBJECTS (not in scene): cucumber, avocado, apple, pear, grape, pineapple, coconut, cherry, peach

EXAMPLES:
- 'pick the banana' -> <ACT>
- 'pick the cucumber' -> <REJ> (not in scene)
...
```

## API 测试

```bash
# 快速测试（10样本）
python test_api_reasoning_v6.py --max-samples 10

# 中等测试（50样本）
python test_api_reasoning_v6.py --max-samples 50

# 大规模测试（100样本）
python test_api_reasoning_v6.py --max-samples 100
```

## 场景注入测试

```bash
# 无 API 测试（验证场景描述生成）
python test_v6_scene_injection_simple.py

# 带 API 测试（验证完整流程）
python test_v6_scene_injection.py
```