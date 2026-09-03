const q = selector => document.querySelector(selector);

async function loadStatus() {
  try {
    const response = await fetch("/api/settings");
    const status = await response.json();
    const connected = Boolean(status.configured);
    q("#ai-status").classList.toggle("connected", connected);
    q("#ai-status").innerHTML = `<i></i>${connected ? `${status.provider_name} · ${status.model}` : "尚未连接模型"}`;
    q("#status-title").textContent = connected ? `${status.provider_name} / ${status.model}` : "尚未连接 AI 模型";
    q("#status-copy").textContent = connected ? "已经可以前往任务中心执行电脑任务。" : "先去模型中心选择服务商并完成连接。";
  } catch {
    q("#status-title").textContent = "无法读取本地服务";
    q("#status-copy").textContent = "请重新启动 AutoFlow 后再试。";
  }
}

loadStatus();
