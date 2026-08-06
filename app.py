import torch
from diffusers import AutoPipelineForText2Image
import gradio as gr

# Use a small, fast model — good for demo + works on CPU fallback too
MODEL_ID = "stabilityai/sdxl-turbo"  # fast, 1-4 steps, great for demos

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32

print(f"Loading model on {device}...")
pipe = AutoPipelineForText2Image.from_pretrained(
    MODEL_ID,
    torch_dtype=dtype,
    variant="fp16" if device == "cuda" else None,
)
pipe = pipe.to(device)

def generate(prompt, steps, guidance):
    image = pipe(
        prompt=prompt,
        num_inference_steps=int(steps),
        guidance_scale=guidance,
    ).images[0]
    return image

with gr.Blocks(title="Text-to-Image Studio") as demo:
    gr.Markdown("# 🎨 Text-to-Image Studio\nMultimodal AI — AMD Radeon / ROCm accelerated")
    with gr.Row():
        with gr.Column():
            prompt = gr.Textbox(label="Prompt", placeholder="a cyberpunk city at sunset, digital art")
            steps = gr.Slider(1, 8, value=2, step=1, label="Inference Steps")
            guidance = gr.Slider(0.0, 5.0, value=0.0, step=0.5, label="Guidance Scale")
            btn = gr.Button("Generate", variant="primary")
        with gr.Column():
            output = gr.Image(label="Generated Image")
    btn.click(fn=generate, inputs=[prompt, steps, guidance], outputs=output)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True)