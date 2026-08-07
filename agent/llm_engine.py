import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline, BitsAndBytesConfig

class ROCmLLMEngine:
    def __init__(self, model_name: str, quantization: str = "4bit"):
        print(f"Loading LLM {model_name} with {quantization} quantization...")
        
        # In PyTorch, ROCm is treated as CUDA for the backend API.
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")
        
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        
        # Configure Quantization for consumer AMD GPUs
        bnb_config = None
        if quantization == "4bit":
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4"
            )
        elif quantization == "8bit":
            bnb_config = BitsAndBytesConfig(
                load_in_8bit=True
            )
        
        # Load model with quantization config
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=bnb_config,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
            device_map="auto" if self.device == "cuda" else None
        )
        
        if quantization == "none" and self.device == "cuda":
            if getattr(self.model, 'device', type('obj', (object,), {'type': 'cpu'})).type != 'cuda':
                 try:
                     self.model.to(self.device)
                 except Exception:
                     pass

        self.generator = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
        )
        
    def generate(self, prompt: str, max_new_tokens: int = 512) -> str:
        try:
            # Generate output
            outputs = self.generator(
                prompt,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=0.6,
                top_p=0.9,
                pad_token_id=self.tokenizer.eos_token_id,
                return_full_text=False
            )
            generated_text = outputs[0]['generated_text']
            
            # Extract just the new generated part
            response = generated_text.strip()
            return response
        except Exception as e:
            return f"Error during generation: {str(e)}"
