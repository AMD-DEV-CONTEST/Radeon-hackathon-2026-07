import os
import argparse
from agent.llm_engine import ROCmLLMEngine
from agent.memory import AgentMemory
from agent.tools import ToolExecutor

class SentinelDesk:
    def __init__(self, model_name: str, persona: str = "helpful", quantization: str = "4bit"):
        print(f"Initializing SentinelDesk with model {model_name}...")
        self.llm = ROCmLLMEngine(model_name, quantization=quantization)
        self.memory = AgentMemory(collection_name="sentinel_memory")
        self.tools = ToolExecutor()
        self.persona = persona
        
        # Save initial persona settings
        self.memory.add_interaction(
            user_input="Set persona",
            agent_response=f"Persona set to: {self.persona}",
            metadata={"type": "config"}
        )
        print("SentinelDesk Initialization Complete.")

    def process_input(self, user_prompt: str) -> str:
        # Retrieve relevant past context
        context = self.memory.get_relevant_context(user_prompt)
        context_str = "\n".join(context) if context else "No past context."
        
        # Safely truncate context to prevent context window overflow
        if len(context_str) > 1500:
            context_str = context_str[:1500] + "\n...[Context truncated]"

        # Check if a tool needs to be executed based on simple heuristic (can be expanded via LLM)
        tool_result = self.tools.parse_and_execute(user_prompt)
        
        system_msg = (
            f"You are a {self.persona} AI assistant named SentinelDesk. You have access to local system tools.\n"
            f"Past Context:\n{context_str}"
        )
        if tool_result:
            system_msg += f"\n\nTool Execution Result:\n{tool_result}"
            
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_prompt}
        ]
        
        prompt = self.llm.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        response = self.llm.generate(prompt)
        
        # Save interaction to memory
        self.memory.add_interaction(user_input=user_prompt, agent_response=response)
        
        return response

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SentinelDesk Autonomous Copilot")
    parser.add_argument("--model", type=str, default="meta-llama/Meta-Llama-3-8B-Instruct", help="HuggingFace model ID")
    parser.add_argument("--persona", type=str, default="helpful companion", help="Agent persona")
    parser.add_argument("--quantization", type=str, choices=["none", "8bit", "4bit"], default="4bit", help="Quantization level")
    args = parser.parse_args()

    agent = SentinelDesk(model_name=args.model, persona=args.persona, quantization=args.quantization)
    
    print("\n--- SentinelDesk is ready ---")
    print("Type 'exit' or 'quit' to stop.")
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.strip().lower() in ['exit', 'quit']:
                break
            response = agent.process_input(user_input)
            print(f"\nSentinelDesk: {response}")
        except KeyboardInterrupt:
            break
