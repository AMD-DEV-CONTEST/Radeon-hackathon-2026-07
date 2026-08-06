---
title: 库存与采购缺口规则
licenseId: lic-privateplate-synthetic-1
---

# 模糊库存

“半颗白菜”等 approximate 或 unknown 库存可以参与可行性判断，但不能伪装成可精确采购的克数。

exact 库存给出精确差额；approximate 给范围；unknown 标记需要确认。

# 采购单位

需要采购时，应按现实单位向上取整（例如一盒豆腐），而不是显示“购买 10g”。

# 不自动扣库存

生成计划或预览任务卡本身不得自动扣减库存。只有用户确认“本餐已按计划吃完”后，才在账本中扣库存并记录摄入。
