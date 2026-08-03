StagePoster Creative Brief Schema v1.0

目标：定义前端提交什么，以及后端如何解释MVP 输出：竖版音乐活动海报核心原则：用户提交创作意图，Prompt 和模型参数由后端产生

1. Creative Brief 的定位

前端不能提交一段“最终模型 Prompt”作为唯一输入。

前端提交的是结构化需求：

活动事实
+ 演出者
+ 精确文案
+ 视觉风格
+ 素材绑定
+ 输出规格

后端把它转换成内部 Generation Plan。

Generation Plan 包含：

Workflow ID 和版本

Positive Prompt

Negative Prompt

素材预处理方案

图片条件控制方式

模型参数

排版模板

后处理方案

输出规格

Generation Plan 是后端内部对象，前端不需要知道其格式。

2. 生成和排版分层

模型负责：

背景

光影

氛围

构图

纹理

风格

人物融入

确定性排版负责：

Logo

活动名称

日期

时间

地点

票务信息

歌词摘录

页脚文字

最终流水线：

Creative Brief
      ↓
视觉生成
      ↓
确定性 Logo 和文字排版
      ↓
最终海报

不能让扩散模型自由重写日期、地点和 Logo。

3. 根结构

字段

类型

必填

说明

schema_version

string

是

当前为 1.0

event

object

是

活动信息

performers

array

是

演出者

copy

object

是

精确文案

style

object

是

视觉方向

asset_bindings

array

是

素材绑定

output

object

是

输出规格

rights_confirmed

boolean

是

使用权确认

notes

string

否

补充说明

不支持的 schema_version 必须拒绝。

4. Event

字段

必填

约束

用途

name

是

1 至 120 字符

Prompt 上下文和精确排版

date

是

YYYY-MM-DD

精确排版

start_time

否

HH:MM

精确排版

end_time

否

HH:MM

精确排版

venue

是

1 至 120 字符

精确排版

city

否

1 至 80 字符

Prompt 和排版

country

否

推荐国家代码

Prompt 上下文

event_type

否

枚举

Workflow 上下文

ticket_url

否

URL

后续二维码

age_restriction

否

最长 40 字符

页脚

支持：

concert
festival
club_night
album_release
community_event
other

活动事实不能由模型改写。

5. Performers

每个演出者包含：

字段

必填

说明

name

是

展示名称

role

是

headliner、support、guest、dj、other

display_order

否

展示顺序

genre

否

音乐风格

tagline

否

精确文案

asset_role

否

对应人物素材角色

MVP 建议：

1 个主演

最多 3 个辅助演出者

1 张主要人物图

多人物复杂组合由后端能力判断。

6. Copy

文案字段默认必须原样呈现。

字段

必填

限制

headline

是

最长 80 字符

subheadline

否

最长 120 字符

call_to_action

否

最长 60 字符

lyrics_excerpt

否

最长 280 字符

footer

否

最长 240 字符

language

是

推荐 BCP 47

allow_copy_assistance

否

默认 false

当：

allow_copy_assistance=false

后端不能修改文案。

当：

allow_copy_assistance=true

后端可以生成候选文案，但必须保留原文。

长歌词可以作为创意上下文，但最终只排版指定摘录。

7. Style

Style 由版本化风格预设和用户调整组成。

字段

必填

说明

preset_id

是

风格 ID

preset_version

是

风格版本

mood

否

情绪数组

palette

否

1 至 6 个颜色

layout_preset_id

是

排版模板

composition_notes

否

构图说明

texture

否

纹理方向

typography_tone

否

字体气质

prompt_hint

否

用户补充描述

avoid

否

避免内容

示例：

{
  "preset_id": "retro_japan_80s",
  "preset_version": "1",
  "mood": ["nostalgic", "energetic"],
  "palette": ["#E94F64", "#1C2841", "#F6D58A"],
  "layout_preset_id": "portrait_hero",
  "composition_notes": "Keep the performer dominant",
  "texture": ["film_grain", "screen_print"],
  "typography_tone": "editorial",
  "prompt_hint": "City-pop night atmosphere",
  "avoid": ["crowded_background", "illegible_face"]
}

风格预设由后端拥有

每个风格预设内部解析为：

Prompt 片段

Negative Prompt

兼容 Workflow

条件强度

推荐尺寸

排版默认值

后处理参数

支持的素材组合

前端只保存：

preset_id
preset_version

不要把模型参数塞进前端。

8. Asset Bindings

素材上传后，通过语义角色绑定。

支持角色：

角色

素材类型

MVP

primary_artist

artist_image

必须

secondary_artist

artist_image

可选

event_logo

logo

可选

brand_logo

logo

可选

style_reference

style_reference

可选

background_reference

background_reference

可选

texture_reference

style_reference

可选

示例：

{
  "role": "primary_artist",
  "asset_id": "asset_01K...",
  "options": {
    "identity_strength": "high",
    "allow_crop": true
  }
}

规则：

素材必须属于当前 Project。

素材状态必须是 ready。

素材类型必须与角色兼容。

前端不得传服务器文件路径。

一个素材可在兼容情况下承担多个角色。

9. Output

字段

必填

约束

preset_id

是

后端支持的输出预设

candidate_count

是

1 至 4

format

是

MVP 为 png

include_clean_background

否

是否返回无文字底图

seed

否

固定或随机

safe_margin

否

standard 或 compact

quality_tier

否

draft、demo、high

推荐 MVP：

poster_2x3
1024 × 1536

开发阶段默认 1 张候选。

比赛演示可默认 2 张候选。

10. 完整示例

{
  "schema_version": "1.0",
  "event": {
    "name": "Tokyo Night Festival",
    "date": "2026-08-01",
    "start_time": "19:30",
    "venue": "Shibuya Stage",
    "city": "Tokyo",
    "event_type": "concert"
  },
  "performers": [
    {
      "name": "Neon Echo",
      "role": "headliner",
      "display_order": 1,
      "genre": ["city_pop", "electronic"],
      "asset_role": "primary_artist"
    }
  ],
  "copy": {
    "headline": "TOKYO NIGHT",
    "subheadline": "NEON ECHO LIVE",
    "call_to_action": "Tickets Available",
    "lyrics_excerpt": "Meet me under the city lights",
    "language": "en",
    "allow_copy_assistance": false
  },
  "style": {
    "preset_id": "retro_japan_80s",
    "preset_version": "1",
    "mood": ["nostalgic", "energetic"],
    "palette": ["#E94F64", "#1C2841", "#F6D58A"],
    "layout_preset_id": "portrait_hero",
    "composition_notes": "Keep the performer dominant",
    "texture": ["film_grain"],
    "typography_tone": "editorial",
    "prompt_hint": "City-pop night atmosphere",
    "avoid": ["crowded_background"]
  },
  "asset_bindings": [
    {
      "role": "primary_artist",
      "asset_id": "asset_artist"
    },
    {
      "role": "event_logo",
      "asset_id": "asset_logo"
    },
    {
      "role": "style_reference",
      "asset_id": "asset_style"
    }
  ],
  "output": {
    "preset_id": "poster_2x3",
    "candidate_count": 2,
    "format": "png",
    "include_clean_background": false,
    "quality_tier": "demo"
  },
  "rights_confirmed": true,
  "notes": "Prioritize the artist and keep the event information readable."
}

11. 校验层次

结构校验

必填字段

字段类型

字符长度

日期格式

数组数量

枚举值

引用校验

Project 是否存在

Asset 是否存在

Asset 是否属于 Project

Asset 是否 Ready

Asset 与绑定角色是否匹配

能力校验

风格版本是否存在

排版模板是否存在

输出规格是否存在

Workflow 是否支持该素材组合

当前 GPU 是否允许候选数量

权限与安全校验

用户是否确认素材使用权

文件格式是否合法

是否包含危险 SVG

请求是否触发安全限制

12. MVP 范围

包含：

音乐活动海报

一张主人物图

可选 Logo

可选风格参考图

可选背景参考图

版本化风格

确定性文案排版

1 至 4 张候选图

暂不包含：

视频

VJ 时间线

音频节拍分析

多人实时协作

用户自定义 ComfyUI Workflow

前端节点级参数控制

完整在线编辑器

13. 验收标准

前端无需理解 ComfyUI。

所有精确文案都有确定性排版策略。

每个素材都有明确语义角色。

风格可以版本化复现。

后端可在使用 GPU 前完成校验。

Mock 和真实生成接受同一份 Brief。

不支持的组合能给出明确错误。
