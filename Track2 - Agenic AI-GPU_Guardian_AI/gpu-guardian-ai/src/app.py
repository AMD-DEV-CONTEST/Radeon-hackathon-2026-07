import gradio as gr

from agents.supervisor import SupervisorAgent

from tools.gpu_tool import get_gpu_status
from tools.cpu_tool import get_cpu_status
from tools.memory_tool import get_memory_status
from tools.disk_tool import get_disk_status
from tools.network_tool import get_network_status

from tools.health_tool import evaluate_gpu_health
from tools.cpu_health_tool import evaluate_cpu_health
from tools.memory_health_tool import evaluate_memory_health
from tools.disk_health_tool import evaluate_disk_health
from tools.network_health_tool import evaluate_network_health
from tools.system_health_tool import evaluate_system_health


agent = SupervisorAgent()


def refresh_dashboard():

    gpu = get_gpu_status()
    cpu = get_cpu_status()
    memory = get_memory_status()
    disk = get_disk_status()
    network = get_network_status()

    gpu_health = evaluate_gpu_health(gpu)
    cpu_health = evaluate_cpu_health(cpu)
    memory_health = evaluate_memory_health(memory)
    disk_health = evaluate_disk_health(disk)
    network_health = evaluate_network_health(network)

    overall = evaluate_system_health(
        gpu_health,
        cpu_health,
        memory_health,
        disk_health,
        network_health,
    )

    return (
        overall["overall"],
        f"{gpu['gpu_usage']} %",
        f"{cpu['cpu_usage']} %",
        f"{memory['memory_usage']} %",
        f"{disk['disk_usage']} %",
        network_health["overall"],
    )


def ask_ai(question):
    return agent.process(question)


with gr.Blocks(title="GPU Guardian AI") as demo:

    gr.Markdown("# GPU Guardian AI")
    gr.Markdown("### AMD ROCm Intelligent System Monitor")

    overall = gr.Textbox(label="Overall Health")

    with gr.Row():
        gpu = gr.Textbox(label="GPU Usage")
        cpu = gr.Textbox(label="CPU Usage")
        memory = gr.Textbox(label="Memory Usage")
        disk = gr.Textbox(label="Disk Usage")
        network = gr.Textbox(label="Network")

    refresh = gr.Button("Refresh Now")

    question = gr.Textbox(
        label="Ask GPU Guardian",
        placeholder="Why is my GPU idle?"
    )

    answer = gr.Textbox(
        label="AI Response",
        lines=10
    )

    refresh.click(
        fn=refresh_dashboard,
        outputs=[
            overall,
            gpu,
            cpu,
            memory,
            disk,
            network,
        ],
    )

    question.submit(
        fn=ask_ai,
        inputs=question,
        outputs=answer,
    )

    demo.load(
        fn=refresh_dashboard,
        outputs=[
            overall,
            gpu,
            cpu,
            memory,
            disk,
            network,
        ],
    )

    timer = gr.Timer(value=300)

    timer.tick(
        fn=refresh_dashboard,
        outputs=[
            overall,
            gpu,
            cpu,
            memory,
            disk,
            network,
        ],
    )
demo.launch(
    server_name="0.0.0.0",
    server_port=7860,
    share=True
)
