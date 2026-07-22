# vte/core/speculative.py
"""Especulação decode: um draft model pequeno propõe K tokens, o target
verifica todos em lote usando o caminho de prefill em lote (WMMA GEMM +
atenção tree-reduction desta mesma sessão), aceitando o maior prefixo
que bate com o que o target teria previsto sozinho.

Gate 2/3 revisado e medido nesta sessão (ver docs/LIMITATIONS.md,
"Roadmap"): a tentativa anterior deste projeto (RX 7600 e W7900,
pré-sessão) mediu verify em lote como 4.48x mais caro que decode
sequencial, usando gemv_q4k puro (cada linha do lote relê o peso
inteiro, sem reaproveitamento). Reaberto porque o kernel que faltava
(`gemm_q4k_wmma`, peso residente em LDS) já existe, construído por
outro motivo (prefill em lote) -- remedido aqui e a razão caiu pra
0.92-1.24x (K=5..16, produção real via `execute_prefill`, incluindo o
custo do LM Head eager por posição). Verify deixou de ser uma
penalidade.

APENAS GREEDY por enquanto (temperature=0). Amostragem estocástica
especulativa é um algoritmo genuinamente diferente (aceitação
probabilística, não argmax-match) e fica para depois deste caminho
estar validado.
"""
import ctypes

import numpy as np

from vte.bridge.memory import MemoryRegion
from vte.core.model import VTEModel


class SpeculativeDecoder:
    """Requer target e draft com o MESMO tokenizer/vocabulário (o draft
    propõe ids de token que são comparados diretamente contra o argmax
    do target -- vocabulários diferentes tornam a comparação sem
    sentido). Llama 3.1 8B (target) + Llama 3.2 1B (draft) confirmado
    compatível nesta sessão: vocab_size=128256 em ambos."""

    def __init__(self, target: VTEModel, draft: VTEModel, K: int = 5):
        if target.lm_head.vocab_size != draft.lm_head.vocab_size:
            raise ValueError(
                f"Target e draft precisam do MESMO vocab_size "
                f"(target={target.lm_head.vocab_size}, draft={draft.lm_head.vocab_size})."
            )
        self.target = target
        self.draft = draft
        self.K = K

        # Esquenta (captura) o grafo de prefill em lote do TARGET com
        # chunk_size=K AGORA, antes que carregar/usar o draft mexa nos
        # registros globais de peso cru (RAW_Q4K_WEIGHTS etc, estado de
        # MÓDULO -- ver VTEModel._activate_raw_registries) e corrompa
        # silenciosamente as decisões de dispatch dessa captura.
        self.target._activate_raw_registries()
        self._verify_executor = self.target._ensure_batched_prefill_executor(chunk_size=K)
        if self._verify_executor is None:
            raise RuntimeError(
                "_ensure_batched_prefill_executor(chunk_size=K) retornou None -- "
                "algum guard rejeitou (VTE_BATCHED_PREFILL não ligado, arquitetura "
                "GDN, ou VRAM insuficiente). Especulação precisa desse caminho."
            )

        # Otimização (2026-07, segunda sessão): a versão original chamava
        # LMHead.compute_logits() posição a posição dentro do loop de
        # aceitação, cada chamada com seu próprio hip.synchronize()+D2H
        # (o buffer de saída é ÚNICO e reaproveitado -- precisa ler antes
        # de lançar a próxima). Medido: 2.67x mais LENTO que decode normal
        # (29.86 vs 79.80 tok/s), causa raiz em ~11 round-trips pequenos
        # Host-Device por rodada, não no kernel (que já mede barato, ver
        # docstring do módulo). Fix: um buffer de scratch com K linhas
        # (não 1), K lançamentos do MESMO kernel de LM head em sequência
        # no stream SEM sincronizar entre eles (cada um escreve numa
        # linha DIFERENTE, sem risco de um sobrescrever o outro antes de
        # ser lido), só 1 sync+D2H no final cobrindo todo o lote. Perde a
        # saída antecipada no primeiro desacordo (agora sempre computa os
        # K), troca aceitável pelo Gate já medido (verify em lote é
        # barato mesmo comparado a decode sequencial).
        lm_head = self.target.lm_head
        vocab_size = lm_head.vocab_size
        self._verify_logits_scratch = self.target._allocator.allocate(
            size=K * vocab_size * 2, tag="speculative_verify_logits_batch",
            region=MemoryRegion.SCRATCH,
        )
        # Mesma resolução de peso (tied-embeddings-aware) e logit_scale de
        # LMHead.compute_logits() -- resolvida uma vez aqui (não muda
        # entre chamadas) em vez de repetir a cada lançamento.
        lm_head_name = 'output.weight'
        lm_head_ptr = self.target.tensor_mapping.get(lm_head_name)
        if lm_head_ptr is None:
            lm_head_ptr = self.target.tensor_mapping.get('token_embd.weight')
        self._target_lm_head_weight_ptr = lm_head_ptr.ptr if hasattr(lm_head_ptr, 'ptr') else lm_head_ptr
        logit_scale = self.target.metadata.get('logit_scale', 1.0) or 1.0
        self._target_logit_mul = ctypes.c_float(1.0 / logit_scale)
        if lm_head._kernel_info is None:
            raise RuntimeError(
                "LMHead do target não está capturado no grafo (kernel_info None) -- "
                "o lançamento em lote customizado precisa do kernel já resolvido."
            )
        self._target_lm_head_kernel = lm_head._kernel_info['kernel']

    def _read_logits_ptr(self, ptr: int) -> np.ndarray:
        buf = bytearray(self.target.lm_head.vocab_size * 2)
        self.target._hip.safe_memcpy_device_to_host(
            buf, ctypes.c_void_p(ptr), tag="speculative_logits_output_d2h"
        )
        return np.frombuffer(bytes(buf), dtype=np.float16).astype(np.float32)

    def _target_decode_logits(self) -> np.ndarray:
        """Logits do TARGET na posição mais recente do seu grafo de
        decode normal (mesmo caminho de sempre, _read_logits() em
        model.py, reimplementado aqui pra não depender do loop de
        generate())."""
        self.target._activate_raw_registries()
        hidden_ptr = self.target.tensor_mapping.get('output_norm.output')
        hidden_val = hidden_ptr.ptr if hasattr(hidden_ptr, 'ptr') else hidden_ptr
        ptr = self.target.lm_head.compute_logits(hidden_val, seq_len=1)
        return self._read_logits_ptr(ptr)

    def _draft_decode_logits(self) -> np.ndarray:
        self.draft._activate_raw_registries()
        hidden_ptr = self.draft.tensor_mapping.get('output_norm.output')
        hidden_val = hidden_ptr.ptr if hasattr(hidden_ptr, 'ptr') else hidden_ptr
        ptr = self.draft.lm_head.compute_logits(hidden_val, seq_len=1)
        buf = bytearray(self.draft.lm_head.vocab_size * 2)
        self.draft._hip.safe_memcpy_device_to_host(
            buf, ctypes.c_void_p(ptr), tag="speculative_logits_output_d2h"
        )
        return np.frombuffer(bytes(buf), dtype=np.float16).astype(np.float32)

    def _target_verify_logits_batch(self, K: int) -> np.ndarray:
        """Logits do TARGET nas K posições do ÚLTIMO replay de verify
        (execute_prefill), TODAS de uma vez -- K lançamentos do kernel
        de LM head em sequência no mesmo stream, sem sincronizar entre
        eles (cada um escreve numa linha diferente do scratch, sem
        hazard de dado), só 1 sync+D2H no final. Substitui
        _target_verify_logits_at() chamado K vezes (a versão antiga,
        ~11 round-trips Host-Device/rodada, medida 2.67x mais lenta que
        decode normal -- ver docstring do módulo). Retorna array
        [K, vocab_size] fp32."""
        self.target._activate_raw_registries()
        hidden_ptr = self._verify_executor.tensor_mapping.get('output_norm.output')
        hidden_val = hidden_ptr.ptr if hasattr(hidden_ptr, 'ptr') else hidden_ptr
        hidden_size = self.target.lm_head.hidden_size
        vocab_size = self.target.lm_head.vocab_size

        for i in range(K):
            row_hidden_ptr = hidden_val + i * hidden_size * 2  # fp16, linha i do chunk
            row_out_ptr = self._verify_logits_scratch.ptr + i * vocab_size * 2
            args = [
                ctypes.c_void_p(row_hidden_ptr),
                ctypes.c_void_p(self._target_lm_head_weight_ptr),
                ctypes.c_void_p(row_out_ptr),
                ctypes.c_int(1), ctypes.c_int(1),
                ctypes.c_int(hidden_size), ctypes.c_int(vocab_size),
                ctypes.c_void_p(0), ctypes.c_void_p(0),
                self._target_logit_mul,
            ]
            self.target._hip.launch_kernel(
                function=self._target_lm_head_kernel, args=args,
                grid=(vocab_size, 1, 1), block=(64, 1, 1),
                shared_mem=0, expected_args=10,
            )

        buf = bytearray(K * vocab_size * 2)
        self.target._hip.safe_memcpy_device_to_host(
            buf, ctypes.c_void_p(self._verify_logits_scratch.ptr),
            tag="speculative_verify_logits_batch_output_d2h",
        )
        return np.frombuffer(bytes(buf), dtype=np.float16).astype(np.float32).reshape(K, vocab_size)

    def generate(self, prompt: str, max_new_tokens: int = 100):
        """Greedy determinístico. Retorna (texto, stats) -- stats inclui
        taxa de aceitação média, pra validação e telemetria."""
        target_tok = self.target.tokenizer
        draft_tok = self.draft.tokenizer

        prompt_ids = target_tok.encode(prompt)
        prompt_ids_draft = draft_tok.encode(prompt)
        if prompt_ids != prompt_ids_draft:
            raise RuntimeError(
                "Tokenização do prompt divergiu entre target e draft -- "
                "tokenizers não são realmente compatíveis."
            )

        # Prefill sequencial do prompt em AMBOS os modelos (sem
        # especulação -- só decode se beneficia). Processa todas as
        # posições MENOS a última (mesma convenção de model.py::generate:
        # a última posição do prompt é processada abaixo, gerando os
        # logits "pré-rodada" pra prever o primeiro token novo).
        self.target._activate_raw_registries()
        for pos, tok in enumerate(prompt_ids[:-1]):
            self.target.executor.execute_decode(tok, kv_offset=pos)

        self.draft._activate_raw_registries()
        for pos, tok in enumerate(prompt_ids[:-1]):
            self.draft.executor.execute_decode(tok, kv_offset=pos)

        L = len(prompt_ids) - 1
        last_prompt_token = prompt_ids[-1]

        self.target._activate_raw_registries()
        self.target.executor.execute_decode(last_prompt_token, kv_offset=L)
        current_target_logits = self._target_decode_logits()

        self.draft._activate_raw_registries()
        self.draft.executor.execute_decode(last_prompt_token, kv_offset=L)

        L += 1  # próxima posição livre em ambos os caches

        stop_ids = target_tok.stop_token_ids
        generated_ids: list[int] = []
        acceptance_history: list[float] = []

        while len(generated_ids) < max_new_tokens:
            K = self.K

            # 1. Draft propõe K tokens, greedy, sequencial (ele é pequeno
            #    e rápido -- 260 tok/s medido -- não precisa de lote).
            self.draft._activate_raw_registries()
            draft_ids: list[int] = []
            for i in range(K):
                logits = self._draft_decode_logits()
                tok = int(np.argmax(logits))
                draft_ids.append(tok)
                # Roda o token proposto no PRÓPRIO draft pra gerar o
                # próximo (menos no último -- só roda se for usado
                # de fato como entrada da PRÓXIMA proposta).
                if i < K - 1:
                    self.draft.executor.execute_decode(tok, kv_offset=L + i)

            # 2. Target verifica os K tokens em lote (grafo de prefill
            #    em lote, chunk_size=K, escreve o KV cache de todas as
            #    K posições de uma vez).
            self.target._activate_raw_registries()
            self._verify_executor.execute_prefill(draft_ids, kv_offset=L)

            # 3. Target computa os K logits de verify TODOS de uma vez
            #    (1 sync+D2H pro lote inteiro, não K -- ver
            #    _target_verify_logits_batch). Aceitação/rejeição
            #    inteiramente em NumPy depois, sem nenhuma chamada de
            #    GPU adicional -- perde a saída antecipada no primeiro
            #    desacordo (sempre computa os K), troca aceitável pelo
            #    Gate já medido (verify em lote é barato).
            verify_logits = self._target_verify_logits_batch(K)  # [K, vocab_size]

            accepted_ids: list[int] = []
            check_logits = current_target_logits
            n_draft_accepted = 0
            mismatch = False
            for i in range(K):
                predicted = int(np.argmax(check_logits))
                if predicted == draft_ids[i]:
                    accepted_ids.append(draft_ids[i])
                    n_draft_accepted += 1
                    check_logits = verify_logits[i]  # logits após processar draft_ids[i] (posição L+i)
                else:
                    accepted_ids.append(predicted)  # token de bônus/substituição, correto por construção
                    mismatch = True
                    break

            if not mismatch:
                # Todos os K draft tokens aceitos -- 1 token extra além
                # deles, usando os logits já computados (posição K, a
                # distribuição que PREVIU o token de bônus).
                accepted_ids.append(int(np.argmax(check_logits)))

            # IMPORTANTE (bug real encontrado e corrigido antes de medir
            # qualquer coisa): check_logits em ambos os ramos é a
            # distribuição que PRODUZIU accepted_ids[-1] (o token de bônus
            # ou o token de substituição), não a distribuição que prevê o
            # token SEGUINTE a ele -- essa exige processar accepted_ids[-1]
            # pelo target de verdade (ele nunca foi rodado como entrada,
            # só "escolhido" pelo argmax). Sem este passo extra, a próxima
            # rodada prediria a partir do lugar errado silenciosamente.
            #
            # Efeito colateral necessário no caso de mismatch: a posição
            # L+len(accepted_ids)-1 no cache KV do target hoje contém K/V
            # do token REJEITADO (draft_ids[i], escrito pelo verify em
            # lote) -- rodar execute_decode aqui SOBRESCREVE essa entrada
            # com o token de substituição correto, na mesma chamada que já
            # precisávamos fazer pelos logits. Uma chamada, dois acertos.
            self.target._activate_raw_registries()
            last_pos = L + len(accepted_ids) - 1
            self.target.executor.execute_decode(accepted_ids[-1], kv_offset=last_pos)
            current_target_logits = self._target_decode_logits()

            acceptance_history.append(n_draft_accepted / K)
            generated_ids.extend(accepted_ids)

            # 4. Realinha o cache do DRAFT com o que foi realmente aceito.
            #    O draft já processou (via execute_decode) draft_ids[0..K-2]
            #    (nunca o último, ver loop acima) -- então já tem cache
            #    válido pra draft_ids[0 .. n_draft_accepted-1], SE
            #    n_draft_accepted-1 < K-1 (i.e., o mismatch aconteceu antes
            #    do último token proposto) ou se todos foram aceitos e
            #    n_draft_accepted-1 == K-1 (o draft rodou até K-2, falta
            #    ainda alimentar o (K-1)-ésimo e o token de bônus).
            self.draft._activate_raw_registries()
            # Quantas posições (a partir de L) o draft JÁ tem em cache:
            # ele processou tokens ATÉ o índice (n_draft_accepted-1) só se
            # esse índice for < K-1 (dentro do loop de proposta); o
            # (K-1)-ésimo nunca foi processado no draft mesmo se aceito.
            draft_cache_valid_upto = min(n_draft_accepted, K - 1)  # nº de tokens de draft_ids já no cache do draft
            for j, tok in enumerate(accepted_ids):
                if j < draft_cache_valid_upto:
                    continue  # já está no cache do draft
                self.draft.executor.execute_decode(tok, kv_offset=L + j)

            L += len(accepted_ids)

            if any(t in stop_ids for t in accepted_ids):
                # Corta no primeiro stop token, descarta o que vier depois.
                stop_pos = next(idx for idx, t in enumerate(accepted_ids) if t in stop_ids)
                cut = len(generated_ids) - len(accepted_ids) + stop_pos
                generated_ids = generated_ids[:cut]
                break

        # Uma rodada pode emitir até K+1 tokens de uma vez -- a última
        # rodada frequentemente ultrapassa max_new_tokens. Trunca pra
        # bater exatamente com o comportamento de generate() normal
        # (que para na contagem exata), sem o que a comparação byte-a-
        # byte falharia por texto extra no final, não por erro de lógica.
        generated_ids = generated_ids[:max_new_tokens]

        text = target_tok.decode(generated_ids)
        mean_acceptance = float(np.mean(acceptance_history)) if acceptance_history else 0.0
        stats = {
            "completion_tokens": len(generated_ids),
            "rounds": len(acceptance_history),
            "mean_acceptance_rate": mean_acceptance,
            "tokens_per_round": len(generated_ids) / max(len(acceptance_history), 1),
        }
        return text, stats
