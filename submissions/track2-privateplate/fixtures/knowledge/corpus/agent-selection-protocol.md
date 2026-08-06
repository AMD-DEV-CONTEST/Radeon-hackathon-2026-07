---
title: Agent 选菜与 Domain 校验协议
licenseId: lic-privateplate-synthetic-1
---

# Agent 选菜协议

Domain 提供硬过滤候选菜事实，不综合打分、不选 bundle winner。

Agent 必须提交完整 selectedDishes、mealPortionScale 与 selectionReason；标准正餐的主菜/蛋白质、蔬菜/配菜、主食三类只是最低角色覆盖，不等于固定三道菜。Agent 根据人数、用户意图、预算和复杂度决定 1～12 道；用户要求“丰富一点”或“多一道蔬菜”时，可以提交多道同 role 菜。需要简单餐或一锅餐时，还要提交结构化 mealStructure。
Domain 只做 ID 校验、餐盘结构、份量换算、预算/绝对下限校验和采购缺口，不自动增加、删除或替换菜品。

remaining 只限制当前餐次的上限，不再作为第二个份量乘数。plannedIntake 用于营养账本，preparedBatch 在其上增加 5%～10% 备餐余量后用于采购和库存；备餐余量不计为已摄入。

同 role 的多道菜分享该 role 的家庭总份量，不能每道菜各算一整份。

修订时提交新的完整选菜列表，而不是让代码在拒绝项后偷偷换菜。
