import gradio as gr

def hello(name):
    return f"Hello {name}!"

with gr.Blocks() as demo:
    gr.Markdown("# Share Test")
    name = gr.Textbox(label="Name")
    greet = gr.Textbox(label="Greeting")
    name.change(fn=hello, inputs=name, outputs=greet)

demo.queue()
demo.launch(share=True, ssr_mode=False)
