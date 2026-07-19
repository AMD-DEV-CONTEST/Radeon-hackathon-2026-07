# vte/core/sampler.py

import numpy as np
from typing import Optional, List

def stable_softmax(logits: np.ndarray) -> np.ndarray:
    """Softmax numericamente estavel para evitar overflow com FP32 logits"""
    # Subtrai o maximo para evitar overflow no exp()
    logits_shifted = logits - np.max(logits)
    exp_logits = np.exp(logits_shifted)
    return exp_logits / np.sum(exp_logits)

# Penalidade de repetição por FREQUÊNCIA, não só presença -- achado real
# (2026-07, geração longa no Qwen3.5): o desconto multiplicativo fixo (uma
# vez por token único, não importa quantas vezes ele já repetiu) nunca
# escala o suficiente pra quebrar um ciclo persistente. Medido sem nenhum
# repetition_penalty numa história longa: o modelo entra num ciclo curto de
# ~8 tokens ("Okay, I need to write. *\n" repetindo) por volta do token
# ~500-600 -- e o GAP entre o token campeão e o segundo colocado NÃO
# explode perto do colapso (fica entre 1-6 logits do início ao fim,
# refutando a hipótese de "confiança numérica explodindo"/saturação do
# estado). É um ciclo de baixa margem: cada um dos ~8 tokens do ciclo
# continua com confiança só moderada, então um desconto que ESCALA com
# quantas vezes o token já saiu deveria bastar pra quebrá-lo -- e basta,
# ver diag_qwen35_logit_confidence.py / diag_qwen35_repetition_fix.py.
#
# Janela deslizante (não a geração inteira): uma palavra comum ("o", "de")
# usada 50x ao longo de uma história de 1000 tokens é normal, não um loop --
# só READ RECENTE importa pra detectar um ciclo de verdade. Expoente com teto
# (REPETITION_COUNT_CAP): sem isso, uma palavra genuinamente repetida muitas
# vezes na janela vira um fator absurdo (ex. 1.3^50) em vez de só "penalizado
# o bastante pra perder pra qualquer alternativa plausível".
REPETITION_WINDOW = 512
REPETITION_COUNT_CAP = 10


class Sampler:
    """Estrategias de sampling em CPU via Numpy.

    Otimizacao (medida): a versao anterior rodava argsort/softmax/cumsum
    sobre o vocabulario inteiro (151936 elementos) mesmo depois do top_k
    ja ter marcado quase tudo como -inf -- 9.4ms/tok medidos, o maior
    componente isolado do tempo por token em producao (maior que as 28
    camadas do modelo na GPU). Esta versao filtra para o subconjunto do
    top_k (tipicamente ~50 elementos) ANTES de ordenar/softmax/amostrar,
    e vetoriza o repetition penalty (era um loop Python puro sobre os
    tokens gerados). Resultado bit-exato preservado no caminho greedy
    (temperature<=0); nos demais casos a distribuicao de probabilidade
    final e matematicamente identica -- so o RNG consome numeros aleatorios
    em ordem diferente por operar sobre um array menor.
    """

    @staticmethod
    def sample(
        logits: np.ndarray,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 50,
        repetition_penalty: float = 1.1,
        generated_tokens: Optional[List[int]] = None,
        ignore_tokens: Optional[set] = None
    ) -> int:
        """
        Amostra o proximo token da distribuicao de logits.
        """
        logits = logits.copy()

        # 1. Repetition penalty por FREQUÊNCIA (vetorizado -- sem loop Python
        # por token), escalando com quantas vezes o token apareceu na janela
        # recente -- não um desconto fixo de presença/ausência (ver
        # REPETITION_WINDOW/REPETITION_COUNT_CAP acima para o porquê). Com
        # count=1 (token visto uma única vez, o caso comum), o expoente é 1
        # e o resultado é IDÊNTICO ao desconto fixo de antes -- só escala de
        # verdade quando um token realmente repete muito na janela recente.
        if generated_tokens and repetition_penalty != 1.0:
            unique_ids, counts = Sampler.compute_repetition_ids(generated_tokens, len(logits), ignore_tokens)
            if unique_ids.size > 0:
                vals = logits[unique_ids]
                eff_penalty = repetition_penalty ** counts
                logits[unique_ids] = np.where(vals > 0, vals / eff_penalty, vals * eff_penalty)

        # Se a temperature for 0, é um argmax (greedy decode) deterministico
        if temperature <= 0.0:
            return int(np.argmax(logits))

        # 2. Temperature scaling
        if temperature != 1.0:
            logits = logits / temperature

        # 3. Top-k: reduz para os candidatos plausiveis ANTES de qualquer
        # ordenacao/softmax/amostragem -- np.argpartition e O(n) (particao
        # parcial), nao O(n log n) como uma ordenacao completa, e todo o
        # trabalho pesado a seguir passa a operar sobre ~top_k elementos
        # em vez do vocabulario inteiro.
        if top_k > 0:
            top_k = min(top_k, len(logits))
            top_indices = np.argpartition(logits, -top_k)[-top_k:]
        else:
            top_indices = np.arange(len(logits))

        candidate_logits = logits[top_indices]

        # 4. Top-p (nucleus) filtering -- agora sobre o subconjunto pequeno
        if 0.0 < top_p < 1.0:
            order = np.argsort(candidate_logits)[::-1]
            sorted_logits = candidate_logits[order]

            cumulative_probs = np.cumsum(stable_softmax(sorted_logits))

            remove_mask = cumulative_probs > top_p
            # Mantém pelo menos o token mais provável
            remove_mask[1:] = remove_mask[:-1]
            remove_mask[0] = False

            keep_order = order[~remove_mask]
            final_indices = top_indices[keep_order]
        else:
            final_indices = top_indices

        # 5. Softmax e sampling -- so sobre os candidatos finais
        final_logits = logits[final_indices]
        probs = stable_softmax(final_logits)

        # Ocasionalmente fp32 precision issues fazem a sum = 0.9999999
        probs = probs / np.sum(probs)

        chosen = np.random.choice(len(probs), p=probs)

        return int(final_indices[chosen])

    @staticmethod
    def compute_repetition_ids(
        generated_tokens: List[int],
        vocab_size: int,
        ignore_tokens: Optional[set] = None,
    ):
        """Extrai os ids UNICOS (ordenados por np.unique) e contagens
        (capadas) da janela de repeticao recente -- exatamente o
        subconjunto que sample() penaliza. Fatorado pra fora de sample()
        (que agora chama isto) pra ser reaproveitado por
        pick_greedy_from_gpu_candidates() sem risco de as duas janelas
        divergirem -- ESSENCIAL pra corretude do caminho de leitura
        reduzida de logits (ver topk_reduce_greedy.hip.template): o
        conjunto de exclusao passado ao kernel e este MESMO conjunto,
        entao qualquer divergencia aqui quebraria a garantia de que nenhum
        vencedor pos-penalidade fica de fora dos candidatos lidos da GPU.
        """
        if not generated_tokens:
            return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
        window = generated_tokens[-REPETITION_WINDOW:]
        token_ids_arr = np.asarray(window, dtype=np.int64)
        token_ids_arr = token_ids_arr[token_ids_arr < vocab_size]
        if ignore_tokens and token_ids_arr.size > 0:
            mask = np.isin(token_ids_arr, list(ignore_tokens), invert=True)
            token_ids_arr = token_ids_arr[mask]
        if token_ids_arr.size == 0:
            return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
        unique_ids, counts = np.unique(token_ids_arr, return_counts=True)
        counts = np.minimum(counts, REPETITION_COUNT_CAP).astype(np.float64)
        return unique_ids, counts

    @staticmethod
    def pick_greedy_from_gpu_candidates(
        group_values: np.ndarray,
        group_indices: np.ndarray,
        gathered_values: np.ndarray,
        unique_ids: np.ndarray,
        counts: np.ndarray,
        repetition_penalty: float,
    ) -> int:
        """Reconstroi o argmax greedy (temperature<=0) pos-penalidade a
        partir dos candidatos reduzidos de topk_reduce_greedy_kernel, sem
        precisar do array de logits completo (151936 elementos).

        Corretude: a penalidade de repeticao so DIMINUI logits (nunca
        aumenta) -- ver o comentario do kernel para o raciocinio completo.
        O vencedor final e sempre um dos dois grupos abaixo, ambos
        calculados aqui com o valor EXATO (nao aproximado):
          (a) o melhor candidato NAO excluido de cada grupo de thread
              (group_values/group_indices) -- nenhum destes pode ter sido
              afetado pela penalidade, entao seu valor bruto ja E o valor
              final;
          (b) um token da janela de repeticao (gathered_values), com a
              MESMA formula de penalidade de sample().

        Desempate: EXATO, nao aproximado -- empates de valor NAO sao raros
        aqui (achado real, ao validar): os logits saem da GPU em FP16
        (~11 bits de mantissa), entao e bem comum dois ou mais dos 151936
        tokens compartilharem o MESMO valor apos a quantizacao, mesmo tendo
        vindo de um calculo FP32 diferente internamente. np.argmax() sobre
        o array completo sempre resolve empates pegando o MENOR indice de
        vocabulario -- cada thread do kernel reporta so o SEU proprio
        melhor candidato (1 por grupo de ~148 elementos), entao um empate
        que atravessa grupos DIFERENTES precisa ser resolvido explicitamente
        pelo menor indice aqui, ou o resultado diverge do caminho original
        (foi exatamente isto que causou uma divergencia de token real numa
        seed de validacao, ver tools/validate_topk_logits_readback.py).
        """
        max_group_val = float(group_values.max())
        tied_mask = group_values == max_group_val
        best_non_window_val = max_group_val
        best_non_window_token = int(group_indices[tied_mask].min())

        if unique_ids.size == 0:
            return best_non_window_token

        # vals fica em float32 (mesmo dtype do array `logits` original em
        # sample()) -- np.where(vals / eff_penalty, ...) promove pra float64
        # internamente (eff_penalty vem de counts:float64), EXATAMENTE como
        # em sample(), mas lá o resultado é gravado de volta em
        # logits[unique_ids] (float32), o que trunca implicitamente. Sem
        # esse .astype(np.float32) aqui, a comparação final ficaria em
        # float64 plena -- precisão mais alta que o caminho original, o que
        # pode escolher um vencedor DIFERENTE numa quase-empate (achado real:
        # foi exatamente isto que causou uma divergência de token numa
        # geração de 300 tokens durante a validação).
        vals = gathered_values[:unique_ids.size]
        eff_penalty = repetition_penalty ** counts
        penalized = np.where(vals > 0, vals / eff_penalty, vals * eff_penalty).astype(np.float32)
        # unique_ids ja vem ordenado (np.unique) -- argmax pega a primeira
        # ocorrencia do maximo, que aqui ja e o menor indice entre empates
        # DENTRO da janela.
        best_window_pos = int(np.argmax(penalized))
        best_window_val = float(penalized[best_window_pos])
        best_window_token = int(unique_ids[best_window_pos])

        if best_window_val > best_non_window_val:
            return best_window_token
        if best_window_val == best_non_window_val:
            # Empate ATRAVESSANDO janela/nao-janela -- mesmo desempate por
            # menor indice que np.argmax aplicaria sobre o array completo.
            return min(best_window_token, best_non_window_token)
        return best_non_window_token
