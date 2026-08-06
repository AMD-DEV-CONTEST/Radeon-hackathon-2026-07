import { describe, expect, it } from "vitest";
import { humanizeProductText, prepareChatAnswer } from "./formatters";

describe("humanizeProductText HTML break normalization", () => {
  it("converts <br> markers to real newlines and strips markdown bold", () => {
    const raw =
      "详情如下：<br><br>【晚餐菜单】<br>1. **白菜豆腐煲**<br>2. 昨日米饭<br><br>【营养概览】";
    const out = humanizeProductText(raw);
    expect(out).not.toMatch(/<br/i);
    expect(out).not.toContain("**");
    expect(out).toContain("详情如下：\n\n【晚餐菜单】\n1. 白菜豆腐煲\n2. 昨日米饭\n\n【营养概览】");
  });

  it("lets compact answers split on former <br> lines", () => {
    const raw =
      "今晚安排好了。<br>【菜单】<br>1. 白菜豆腐煲<br>2. 昨日米饭<br>3. 香菇蒸蛋<br>4. 多余一行触发截断<br>5. 再一行<br>6. 还一行";
    const out = prepareChatAnswer(raw, { hasPlan: true, compact: true });
    expect(out).not.toMatch(/<br/i);
    expect(out.split("\n")[0]).toBe("今晚安排好了。");
    expect(out).toContain("（详情见右侧计划）");
  });
});
