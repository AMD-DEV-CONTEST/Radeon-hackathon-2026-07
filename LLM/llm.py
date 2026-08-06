import os
from dotenv import load_dotenv

load_dotenv()

class LLM:
    def __init__(self):
        """ route = os.getenv("ROUTE") or ""
        if route == "":
            raise ValueError("ROUTE is not set in the environment variables. Acceptable values are 'LOCAL' or 'REMOTE'.")
        
        if route.upper() == "LOCAL":
            from LLM.llm_local import LLM_Local
            self.llm = LLM_Local()
        elif route.upper() == "REMOTE":
            from LLM.llm_remote import LLM_Remote
            self.llm = LLM_Remote()
        else:
            raise ValueError("Invalid ROUTE value. Acceptable values are 'LOCAL' or 'REMOTE'.") """

        from LLM.llm_local import LLM_Local
        self.llm = LLM_Local()

    def generate(self, prompt, system_instruction: str = "You are a helpful assistant.", number_of_attempts: int = 2, temperature: float = 0.0, max_tokens: int = 16384) -> str:
        if isinstance(prompt, list):
            extracted_prompt = ""
            extracted_system = system_instruction
            
            for message in prompt:
                if hasattr(message, 'type'):
                    if message.type == 'system':
                        extracted_system = message.content
                    elif message.type in ['human', 'user']:
                        extracted_prompt += message.content + "\n"
            
            prompt = extracted_prompt.strip()
            system_instruction = extracted_system

        print("Made LLM call with prompt:", prompt, "\n\n")

        ans = self.llm.generate(prompt = prompt, system_instruction = system_instruction, number_of_attempts = number_of_attempts, temperature = temperature, max_tokens = max_tokens)

        print("LLM call returned:", ans, "\n\n")

        return ans