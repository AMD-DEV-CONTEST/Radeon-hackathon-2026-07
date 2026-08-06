"""
Supervisor Agent

Coordinates all monitoring tools and the LLM.
"""
#Dashboard
from utils.dashboard import one_line_snapshot
from utils.dashboard import show_dashboard
from config.settings import DEBUG

from llm.loader import load_model
from llm.inference import generate_response

# Memory
from tools.memory_tool import get_memory_status
from tools.memory_health_tool import evaluate_memory_health

# GPU
from tools.gpu_tool import get_gpu_status
from tools.health_tool import evaluate_gpu_health

# CPU
from tools.cpu_tool import get_cpu_status
from tools.cpu_health_tool import evaluate_cpu_health

# Disk
from tools.disk_tool import get_disk_status
from tools.disk_health_tool import evaluate_disk_health

# Network
from tools.network_tool import get_network_status
from tools.network_health_tool import evaluate_network_health

# Classifier
#from tools.question_classifier import classify_question

#Intent Classifier
from utils.intent_classifier import classify_intent
from utils.question_type import question_type

# Overall System Health
from tools.system_health_tool import evaluate_system_health

# Classifier
from tools.insight_tool import generate_insights

# Recommedation 
from tools.recommendation_tool import generate_recommendations

# Report Formatter
from utils.report_formatter import format_system_report

#Context builder
from utils.context_builder import build_context

# Diagnosis tool
from tools.diagnosis_tool import generate_diagnosis

# Rule Response Tool
from tools.rule_response_tool import generate_rule_response


BOLD = "\033[1m"
CYAN = "\033[96m"
RESET = "\033[0m"

class SupervisorAgent:

    def __init__(self):
        self.tokenizer, self.model = load_model()

    def process(self, question):

        # -----------------------------
        # Collect GPU Metrics
        # -----------------------------
        gpu = get_gpu_status()

        # Evaluate GPU Health
        gpu_health = evaluate_gpu_health(gpu)

        # -----------------------------
        # Collect CPU Metrics
        # -----------------------------
        cpu = get_cpu_status()

        # Evaluate CPU Health
        cpu_health = evaluate_cpu_health(cpu)
        
        # Collect Memory Metrics
        memory = get_memory_status()

        # Evaluate Memory Health
        memory_health = evaluate_memory_health(memory)
        
        # Collect Disk Metrics
        disk = get_disk_status()
        
        # Evaluate Disk Health
        disk_health = evaluate_disk_health(disk)

        # Collect Network Metrics
        network = get_network_status() 
        
        # Evaluate Network Health
        network_health = evaluate_network_health(network)


        #print(f"{BOLD}{CYAN}Question{RESET}")
        #print("──────────────────────────────────────────────────────────────────────────────")
        #print(question)
        print()

        # Evaluate Overall System Health
        system_health = evaluate_system_health(
            gpu_health,
            cpu_health,
            memory_health,
            disk_health,
            network_health
        )
        
        # Perform the diagnosis
        diagnosis = generate_diagnosis(
            gpu,
            gpu_health,
            cpu,
            cpu_health,
            memory,
            memory_health,
            disk,
            disk_health,
            network,
            network_health,
            system_health
        )
        
        recommendations = generate_recommendations(
            diagnosis
        )
        insights = generate_insights(
            gpu,
            cpu,
            memory,
            disk,
            network
        )
        # -----------------------------
        # Build System Report
        # -----------------------------
        report = format_system_report(
             gpu,
             gpu_health,

             cpu,
             cpu_health,

             memory,
             memory_health,

             disk,
             disk_health,

             network,
             network_health,

             system_health,
             diagnosis,
             recommendations,
             insights
        )
       
        # -----------------------------
        # Determine Question Route
        # -----------------------------
        route = question_type(question)

        # -----------------------------
        # Determine Component Intent
        # -----------------------------
        intent = classify_intent(question)

        # -----------------------------
        # Rule-Based Questions
        # -----------------------------
        if route == "rule":

            rule_response = generate_rule_response(
                intent,
                gpu,
                gpu_health,
                cpu,
                cpu_health,
                memory,
                memory_health,
                disk,
                disk_health,
                network,
                network_health,
                system_health,
            )

            if rule_response is not None:
                #print("\nQuestion")
                #print("────────────────────────────────────────")
                #print(question)
                print()
                return rule_response

        # -----------------------------
        # LLM Questions
        # -----------------------------
        context = build_context(
            report,
            intent
        )

        if DEBUG:
            print("\n================ CONTEXT SENT TO LLM ================\n")
            print(context)
            print("\n=====================================================\n")

        #print("\nQuestion")
        #print("────────────────────────────────────────")
        #print(question)
        print()
        return generate_response(
            self.model,
            self.tokenizer,
            context,
            question,
            intent,
            gpu,
            gpu_health,
            cpu,
            cpu_health,
            memory,
            memory_health,
            disk,
            disk_health,
            network,
            network_health,
            system_health,
        )
