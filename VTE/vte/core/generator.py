# vte/core/generator.py

import json
import numpy as np
import ctypes
from typing import Optional, List
from vte.core.model_config import ModelConfig
from vte.core.lm_head import LMHead
from vte.core.sampler import Sampler

class TextGenerator:
    """Loop autoregressivo para geração de texto"""
    
    def __init__(self, model, tokenizer, debug: bool = False):
        self.model = model
        self.tokenizer = tokenizer
        self.debug = debug
        
        self.config = ModelConfig(model)
        
        self.lm_head = LMHead(model, model._hip, model._allocator, tokenizer=tokenizer)
        self.sampler = Sampler()
        
        # Estado do KV cache (posição atual em cada camada)
        self.kv_cache_pos = 0
        self.generated_tokens = []
        
        # Lê o seq len maximo permitido do modelo para evitar overflow no cache
        self.max_seq_len = self.config.max_position_embeddings
    
    def _get_top_k_tokens(self, logits, k=5):
        """Helper para o debug"""
        top_indices = np.argsort(logits)[-k:][::-1]
        tokens_info = []
        for idx in top_indices:
            try:
                text = self.tokenizer.decode([idx])
            except Exception:
                text = "<UNK>"
            tokens_info.append(f"{idx} ({text}): {logits[idx]:.2f}")
        return ", ".join(tokens_info)

    def save_state(self, path: str):
        """Salva estado do gerador para resumir depois"""
        state = {
            'kv_cache_pos': self.kv_cache_pos,
            'generated_tokens': self.generated_tokens,
        }
        with open(path, 'w') as f:
            json.dump(state, f)
            
    def load_state(self, path: str):
        """Carrega estado salvo"""
        with open(path, 'r') as f:
            state = json.load(f)
        self.kv_cache_pos = state['kv_cache_pos']
        self.generated_tokens = state['generated_tokens']
        
    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 100,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 50,
        repetition_penalty: float = 1.1,
        stop_strings: Optional[List[str]] = None,
        stream: bool = False
    ) -> str:
        """
        Gera texto a partir de um prompt.
        """
        # 1. Tokeniza o prompt
        if hasattr(self.tokenizer, 'encode'):
            input_ids = self.tokenizer.encode(prompt)
            if hasattr(input_ids, 'ids'):  # tokenizers rust lib
                input_ids = input_ids.ids
        else:
            raise ValueError("Tokenizer must have an encode method.")
            
        self.generated_tokens = list(input_ids)
        
        print(f"Prompt: {len(input_ids)} tokens")
        print(f"Gerando até {max_new_tokens} tokens...")
        
        # 2. Fase de Prefill: processa todos os tokens do prompt
        print("Fase de Prefill...")
        self._prefill(input_ids)
        
        # 3. Fase de Decode: gera token por token
        print("Fase de Decode:")
        generated_text = ""
        prompt_len = len(input_ids)
        
        for i in range(max_new_tokens):
            if self.kv_cache_pos >= self.max_seq_len:
                print(f"\nLimite de KV Cache atingido ({self.max_seq_len}). Parando geração.")
                break
                
            # Gera próximo token
            next_token = self._decode_step(
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repetition_penalty=repetition_penalty,
                generated_tokens=self.generated_tokens,
                prompt_len=prompt_len
            )
            
            self.generated_tokens.append(next_token)
            self.kv_cache_pos += 1
            
            # Decodifica token (usando o método decode no tokenizer)
            new_text = self.tokenizer.decode(self.generated_tokens)
            
            # Se for BPE e remover espaços iniciais precisaremos fazer a diferença no texto inteiro
            new_piece = new_text[len(prompt + generated_text):]
            generated_text += new_piece
            
            if stream:
                print(new_piece, end="", flush=True)
            
            # Verifica stopping conditions
            if self._should_stop(self.generated_tokens, generated_text, stop_strings):
                break
        
        if stream:
            print()  # Nova linha final
        
        return generated_text
    
    def _prefill(self, input_ids: List[int]):
        """Processa todos os tokens do prompt de uma vez"""
        seq_len = len(input_ids)
        
        if seq_len >= self.max_seq_len:
            raise ValueError(f"Prompt length ({seq_len}) exceeds max_seq_len ({self.max_seq_len})")
        
        # O FallbackExecutor precisa de um input_ids no tensor mapping
        tokens_array = np.array(input_ids, dtype=np.int32)
        input_ids_ptr = self.model.tensor_mapping.get('input_ids')
            
        ptr_val = input_ids_ptr.ptr if hasattr(input_ids_ptr, 'ptr') else input_ids_ptr
        
        self.model._hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(ptr_val),
            tokens_array.tobytes(),
            "prefill_tokens"
        )
        
        # O prefill ignora o kv_cache_offset (trata como offset 0 inicial)
        # Para isso chamamos _prefill do executor, mas se quisermos usar execute_layer:
        for layer_idx in range(self.model.executor.num_layers):
            # Assumimos que o executor vai aceitar kv_cache_offset
            self.model.executor.execute_layer(layer_idx, seq_len=seq_len, kv_cache_offset=0)
        
        self.model._hip.synchronize()
        self.kv_cache_pos = seq_len
    
    def _decode_step(
        self,
        temperature: float,
        top_p: float,
        top_k: int,
        repetition_penalty: float,
        generated_tokens: List[int],
        prompt_len: int
    ) -> int:
        """Gera um único token"""
        last_token = generated_tokens[-1]
        
        token_array = np.array([last_token], dtype=np.int32)
        input_ids_ptr = self.model.tensor_mapping.get('input_ids')
        ptr_val = input_ids_ptr.ptr if hasattr(input_ids_ptr, 'ptr') else input_ids_ptr
        
        self.model._hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(ptr_val),
            token_array.tobytes(),
            "decode_token"
        )
        
        # Executa 28 camadas em modo decode (seq_len=1)
        for layer_idx in range(self.model.executor.num_layers):
            self.model.executor.execute_layer(
                layer_idx, 
                seq_len=1,
                kv_cache_offset=self.kv_cache_pos
            )
        
        self.model._hip.synchronize()
        
        # ========================================================================
        # DEBUG: O Sinal está morrendo nas camadas ou no LM Head?
        # ========================================================================
        hidden_ptr = self.model.tensor_mapping.get('blk.27.output')
        if hidden_ptr:
            ptr_v = hidden_ptr.ptr if hasattr(hidden_ptr, 'ptr') else hidden_ptr
            buffer = bytearray(1 * self.config.hidden_size * 2)  # seq_len=1, FP16
            self.model._hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(ptr_v), "output")
            hidden = np.frombuffer(buffer, dtype=np.float16)
            
            print(f"\n[Decode Step {self.kv_cache_pos}] blk.27.output:")
            print(f"   Mean: {np.mean(hidden):.6f} | Std: {np.std(hidden):.6f} | Max: {np.max(hidden):.6f}")
            
            if np.all(hidden == 0):
                print("   CRÍTICO: Hidden state final está ZERADO!")
                print("   Causa: O 'Argumento 11 nulo' está matando o sinal nas camadas de Attention/FFN.")
            else:
                print("   Hidden state tem valores válidos. O problema está no LM Head.")
        # ========================================================================
        # Computa logits
        last_hidden_ptr = self.model.tensor_mapping.get('output_norm.output')
        last_hidden_val = last_hidden_ptr.ptr if hasattr(last_hidden_ptr, 'ptr') else last_hidden_ptr
        
        logits_ptr = self.lm_head.compute_logits(last_hidden_val, seq_len=1)
        
        # Copia logits para CPU (LM head grava em FP16, mesmo tipo do matmul_kernel)
        logits_buffer = bytearray(self.lm_head.vocab_size * 2)
        self.model._hip.safe_memcpy_device_to_host(
            logits_buffer,
            ctypes.c_void_p(logits_ptr),
            "logits_d2h"
        )
        logits = np.frombuffer(logits_buffer, dtype=np.float16).astype(np.float32)
        
        # Debug opcional
        if self.debug:
            print(f"[Decode Step {self.kv_cache_pos}]")
            try:
                dec = self.tokenizer.decode([last_token])
            except Exception:
                dec = "<UNK>"
            print(f"  Input token: {last_token} ({dec})")
            print(f"  Logits range: [{np.min(logits):.3f}, {np.max(logits):.3f}]")
            print(f"  Top-5 tokens: {self._get_top_k_tokens(logits, k=5)}")
            
        # Sample próximo token
        next_token = self.sampler.sample(
            logits=logits,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            generated_tokens=generated_tokens[prompt_len:],
            ignore_tokens=set(self.tokenizer.special_tokens.values())
        )
        
        if self.debug:
            try:
                dec_out = self.tokenizer.decode([next_token])
            except Exception:
                dec_out = "<UNK>"
            print(f"  Sampled token: {next_token} ({dec_out})\n")
            
        self.kv_cache_pos += 1
        return next_token
    
    def _should_stop(
        self,
        generated_tokens: List[int],
        generated_text: str,
        stop_strings: Optional[List[str]]
    ) -> bool:
        """Verifica se deve parar a geração"""
        # EOS token fallback
        eos_token_id = getattr(self.tokenizer, 'eos_token_id', None)
        # OQwen2.5 usa 151643 ou 151645 como EOS, verifique tokenizer.
        if eos_token_id is not None and generated_tokens[-1] == eos_token_id:
            return True
            
        # Hardcoded EOS para Qwen se não mapeado:
        if generated_tokens[-1] in (151645, 151643):
            return True
        
        # Stop strings
        if stop_strings:
            for stop_str in stop_strings:
                if stop_str in generated_text:
                    return True
        
        return False
