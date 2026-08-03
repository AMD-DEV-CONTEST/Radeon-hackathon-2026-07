## goal
把 ComfyUI 从一个本地工作流工具，封装成一个可被产品调用的多模态 AI 创作后端 

## 核心定位
stagePoster 
not 
```
Prompt → Image
```

而是:

```
Creative Brief
        |
        |
  AI Creative Pipeline
        |
        |
 ComfyUI Generation Engine
        |
        |
 Poster / Video / VJ Asset
```


1.verall Architecture, please read docs/architecture.m
2. api contract , read docs/api-contract.md

3. backend 始终保持 前端只接触api 接入层
4. asset read docs/asset-contract.md
5. job 任务 处理， read docs/job-lefecycle.md
6. errors  code read docs/errors-code.md
ComfyUI 永远只通过外部推理适配层进入系统。
中间不能互相穿透，否则后面工作流一换，整个系统会像散架的纸灯笼。
```
API 接入层
   ↓
应用编排层
   ↓
领域模型层
   ↓
基础设施层
   ↓
外部推理适配层
```

backend struct 

Frontend AI Mode
        │
        ▼
AI Session API
        │
        ▼
Design Agent
Qwen3.5-9B
        │
        ▼
PosterGoal + DesignPlan
        │
用户确认设计方案
        │
        ▼
Poster Service
        │
        ▼
GPU Coordinator
   ┌────┴─────┐
   │          │
Qwen Sleep  ComfyUI Generate
              │
          3 Candidates
              │
          用户选择
              │
          Composer
              │
          Final Poster
              │
   ComfyUI /free
              │
         Qwen Wake
              │
       Visual Critic
              │
              ▼
 ACCEPT / RECOMPOSE / REGENERATE
              │
              ▼
       Goal-Driven Loop
