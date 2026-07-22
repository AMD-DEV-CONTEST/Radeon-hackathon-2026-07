# Challenge 07: Web UI 集成

**Estimated Time:** 45 minutes  
**Difficulty:** Medium

## Introduction

后端 Agent 系统已经就绪，现在需要构建用户界面，让非技术用户也能使用单据处理系统。

Gradio 是一个快速构建 ML 应用界面的框架，支持：
- 文本输入/输出
- 文件上传
- 实时响应
- 响应式布局

本挑战将构建 Web UI，提供友好的用户交互体验。

## Prerequisites

- Challenge 06 完成 (多 Agent 编排)

## Description

构建供应链单据处理系统的 Web 界面。您的目标是：

1. 使用 Gradio 构建主界面
2. 实现文件上传功能
3. 展示处理结果和校验报告
4. 支持对话式查询

界面应简洁直观，支持单据上传、处理状态展示、结果查看。

## Success Criteria

- [ ] Gradio 服务成功启动
- [ ] 支持上传 .txt 文件
- [ ] 上传后自动触发处理流程
- [ ] 展示提取的字段数据
- [ ] 展示校验结果（通过/失败）
- [ ] 支持简单的对话查询

## Hints

<details>
<summary>Hint 1 (broad)</summary>
Gradio 提供了 `gr.Interface` 和 `gr.Blocks` 两种创建界面的方式。对于复杂界面，推荐使用 `gr.Blocks`。
</details>

<details>
<summary>Hint 2 (more specific)</summary>
基础界面框架：
```python
import gradio as gr

def process_document(file):
    content = file.read().decode("utf-8")
    result = agent.process_document(content, file.name)
    return result

with gr.Blocks(title="Supply Chain DocAgent") as demo:
    gr.Markdown("# Supply Chain DocAgent")
    
    with gr.Row():
        file_input = gr.File(label="上传单据", type="binary")
        process_btn = gr.Button("处理")
    
    output = gr.JSON(label="处理结果")
    
    process_btn.click(process_document, inputs=file_input, outputs=output)

demo.launch(server_port=7860)
```
</details>

<details>
<summary>Hint 3 (almost there)</summary>
添加对话式查询功能：
```python
with gr.Blocks() as demo:
    # ... 文件上传部分 ...
    
    gr.Markdown("## 对话查询")
    chatbot = gr.Chatbot()
    msg = gr.Textbox(label="输入问题")
    
    def respond(message, chat_history):
        response = agent.query(message)
        chat_history.append((message, response))
        return "", chat_history
    
    msg.submit(respond, [msg, chatbot], [msg, chatbot])
```
</details>

## Learning Resources

- [Gradio 文档](https://www.gradio.app/docs/)
- [Gradio Blocks](https://www.gradio.app/guides/blocks-and-event-listeners)
- [Gradio Chatbot](https://www.gradio.app/components/chatbot/)

## Advanced Challenge (Optional)

实现高级 UI 功能：
- 添加处理进度条
- 实现多文件批量处理
- 导出处理报告为 PDF
