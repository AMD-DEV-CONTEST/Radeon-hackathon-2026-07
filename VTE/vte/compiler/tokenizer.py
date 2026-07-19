import re
import json
import regex
from pathlib import Path
from typing import Dict, List, Optional
from jinja2 import Environment
from vte.bridge.logger import get_logger
from vte.compiler.text_normalizer import normalize
from vte.compiler.gguf_metadata import read_gguf_metadata

logger = get_logger(__name__)

_GPT2_PATTERN = re.compile(
    r"""'s|'t|'re|'ve|'m|'ll|'d| ?[^\W\d_]+| ?\d+| ?[^\s\w]+|\s+(?!\S)|\s+""",
    re.UNICODE,
)

# Pré-tokenizador "dbrx" do Granite -- confirmado em
# llama.cpp/src/llama-vocab.cpp: LLAMA_VOCAB_PRE_TYPE_DBRX cai no MESMO case
# que LLAMA_VOCAB_PRE_TYPE_SMAUG e usa a mesma regex do Llama3 (não uma regex
# própria do Dbrx, apesar do nome). Usa \p{L}/\p{N} (propriedades Unicode),
# por isso precisa do módulo `regex` (stdlib `re` não suporta \p{...}).
_DBRX_PATTERN = regex.compile(
    r"(?:'[sS]|'[tT]|'[rR][eE]|'[vV][eE]|'[mM]|'[lL][lL]|'[dD])"
    r"|[^\r\n\p{L}\p{N}]?\p{L}+"
    r"|\p{N}{1,3}"
    r"| ?[^\s\p{L}\p{N}]+[\r\n]*"
    r"|\s*[\r\n]+"
    r"|\s+(?!\S)"
    r"|\s+"
)

# Pré-tokenizador do Qwen3.5 -- transcrito EXATAMENTE de
# transformers/models/qwen3_5/tokenization_qwen3_5.py::PRETOKENIZE_REGEX
# (código-fonte real, instalado localmente nesta sessão), NÃO reaproveitado
# de _GPT2_PATTERN nem _DBRX_PATTERN por semelhança -- os três são
# parecidos mas não idênticos. Duas diferenças reais que importam:
# 1) letras incluem marcas de combinação Unicode (\p{L}\p{M}), DBRX/GPT2
#    não incluem \p{M};
# 2) dígitos são agrupados um de cada vez (\p{N}), não em blocos de 1-3
#    como o Llama3/DBRX (\p{N}{1,3}) -- reaproveitar _DBRX_PATTERN aqui
#    tokenizaria qualquer número de 2+ dígitos de forma diferente da real.
# Precisa do módulo `regex` (mesma razão do _DBRX_PATTERN: \p{...} não é
# suportado pelo `re` da stdlib).
_QWEN35_PATTERN = regex.compile(
    r"(?i:'s|'t|'re|'ve|'m|'ll|'d)"
    r"|[^\r\n\p{L}\p{N}]?[\p{L}\p{M}]+"
    r"|\p{N}"
    r"| ?[^\s\p{L}\p{M}\p{N}]+[\r\n]*"
    r"|\s*[\r\n]+"
    r"|\s+(?!\S)"
    r"|\s+"
)

_TOKENIZER_KEYS = {
    "tokenizer.ggml.tokens",
    "tokenizer.ggml.merges",
    "tokenizer.ggml.bos_token_id",
    "tokenizer.ggml.eos_token_id",
}


def _bytes_to_unicode() -> Dict[int, str]:
    """Mapa byte->unicode (GPT-2/tiktoken) para que todo byte tenha uma representação
    imprimível e reversível dentro do vocabulário BPE."""
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, (chr(c) for c in cs)))


def _get_pairs(word: tuple) -> set:
    pairs = set()
    prev = word[0]
    for ch in word[1:]:
        pairs.add((prev, ch))
        prev = ch
    return pairs


def _coerce_chat_messages(user_message, system: Optional[str], default_system: str) -> List[dict]:
    """Normaliza o primeiro argumento de `apply_chat_template` para uma lista
    de mensagens `{"role", "content"}`. Compatível com o uso atual (uma única
    string de usuário, comportamento inalterado) e com um histórico
    multi-turno completo já pronto (lista de mensagens, ex.: vindo de uma
    requisição OpenAI `chat/completions`) -- necessário para hosts externos
    (ex.: um servidor HTTP que embrulha VTEModel) que precisam repassar uma
    conversa inteira, não só a última mensagem do usuário."""
    if isinstance(user_message, list):
        messages = list(user_message)
        if not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system if system is not None else default_system})
        return messages
    return [
        {"role": "system", "content": system if system is not None else default_system},
        {"role": "user", "content": user_message},
    ]


def _strip_literal_special_tokens(messages: List[dict], special_tokens: Dict[str, int]) -> List[dict]:
    """Remove ocorrências literais dos tokens especiais deste tokenizer (ex.:
    "<|im_start|>", "<|im_end|>") do `content` de cada mensagem, antes de
    renderizar o chat template.

    Sem isto, uma mensagem vinda de um chamador externo (ex.: vte-server,
    que repassa `content` de requisições HTTP não confiáveis direto pra cá)
    poderia embutir um literal desses -- `encode()`/`_split_special_tokens`
    (mais abaixo) faz `re.split` sobre o texto JÁ RENDERIZADO inteiro, sem
    nenhuma forma de distinguir um marcador que o próprio template inseriu
    de um literal que veio de dentro do `content` de uma mensagem "user".
    Isso deixaria quem chama `apply_chat_template` com uma lista de
    mensagens externa forjar um limite de turno falso (ex.: um "system"
    extra depois do prompt de sistema real), sobrescrevendo instruções que
    um integrador downstream (ex.: quem embute o vte-server no próprio
    produto) esperava que fossem definitivas. Aplicado uniformemente a
    TODA mensagem (inclusive as inseridas internamente por
    `_coerce_chat_messages`), já que essas nunca contêm esses literais e a
    checagem é barata."""
    if not special_tokens:
        return messages
    pattern = re.compile("|".join(re.escape(t) for t in special_tokens))
    sanitized = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str) and pattern.search(content):
            m = {**m, "content": pattern.sub("", content)}
        sanitized.append(m)
    return sanitized


class QwenTokenizer:
    """
    Tokenizador BPE byte-level do Qwen2.5, reconstruído a partir do vocabulário
    e das regras de merge embutidas no próprio arquivo GGUF
    (`tokenizer.ggml.tokens` / `tokenizer.ggml.merges`).
    """

    def __init__(self, vocab_path: Optional[str] = None, gguf_path: Optional[str | Path] = None):
        self.vocab: Dict[str, int] = {}
        self.inv_vocab: Dict[int, str] = {}
        self.bpe_ranks: Dict[tuple, int] = {}
        self._bpe_cache: Dict[str, str] = {}

        self._byte_encoder = _bytes_to_unicode()
        self._byte_decoder = {v: k for k, v in self._byte_encoder.items()}

        self.special_tokens = {
            "<|endoftext|>": 151643,
            "<|im_start|>": 151644,
            "<|im_end|>": 151645,
        }
        self.bos_token_id: Optional[int] = None
        self.eos_token_id: Optional[int] = self.special_tokens["<|im_end|>"]
        self.vocab_size = 0

        if gguf_path is not None:
            self._load_from_gguf(Path(gguf_path))
        else:
            logger.warning(
                "QwenTokenizer sem gguf_path: usando vocabulário mínimo de fallback (não-funcional para produção)."
            )
            self._load_fallback_vocab()

    def _load_fallback_vocab(self):
        self.vocab.update(self.special_tokens)
        self.vocab["O"] = 100
        self.vocab[" V"] = 101
        self.vocab["TE"] = 102
        self._rebuild_inverse_vocab()

    def _load_from_gguf(self, gguf_path: Path):
        logger.info(f"Extraindo vocabulário BPE do GGUF: {gguf_path}")
        metadata = read_gguf_metadata(gguf_path, wanted_keys=_TOKENIZER_KEYS)

        tokens: List[str] = metadata.get("tokenizer.ggml.tokens", [])
        merges: List[str] = metadata.get("tokenizer.ggml.merges", [])

        if not tokens:
            logger.warning("GGUF não contém 'tokenizer.ggml.tokens'. Usando fallback mínimo.")
            self._load_fallback_vocab()
            return

        for token_id, token_str in enumerate(tokens):
            self.vocab[token_str] = token_id
        self._rebuild_inverse_vocab()
        self.vocab_size = len(tokens)

        for token_str, token_id in self.vocab.items():
            if token_str in ("<|endoftext|>", "<|im_start|>", "<|im_end|>"):
                self.special_tokens[token_str] = token_id

        self.eos_token_id = self.special_tokens.get("<|im_end|>", self.eos_token_id)

        bos_id = metadata.get("tokenizer.ggml.bos_token_id")
        if bos_id is not None:
            self.bos_token_id = bos_id

        for rank, merge_line in enumerate(merges):
            parts = merge_line.split(" ")
            if len(parts) == 2:
                self.bpe_ranks[(parts[0], parts[1])] = rank

        logger.info(
            f"Tokenizer BPE carregado: {len(tokens)} tokens, {len(self.bpe_ranks)} regras de merge."
        )

    def _rebuild_inverse_vocab(self):
        self.inv_vocab = {v: k for k, v in self.vocab.items()}

    def _bpe(self, token: str) -> str:
        if token in self._bpe_cache:
            return self._bpe_cache[token]

        word = tuple(token)
        pairs = _get_pairs(word)
        if not pairs:
            self._bpe_cache[token] = token
            return token

        while True:
            candidate = min(pairs, key=lambda p: self.bpe_ranks.get(p, float("inf")))
            if candidate not in self.bpe_ranks:
                break

            first, second = candidate
            new_word = []
            i = 0
            while i < len(word):
                try:
                    j = word.index(first, i)
                except ValueError:
                    new_word.extend(word[i:])
                    break
                new_word.extend(word[i:j])
                i = j
                if i < len(word) - 1 and word[i] == first and word[i + 1] == second:
                    new_word.append(first + second)
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1
            word = tuple(new_word)
            if len(word) == 1:
                break
            pairs = _get_pairs(word)

        result = " ".join(word)
        self._bpe_cache[token] = result
        return result

    def _split_special_tokens(self, text: str) -> List[str]:
        """Divide o texto em segmentos, isolando tokens especiais literais."""
        if not self.special_tokens:
            return [text]
        pattern = "(" + "|".join(re.escape(t) for t in self.special_tokens) + ")"
        return [seg for seg in re.split(pattern, text) if seg != ""]

    def encode(self, text: str) -> List[int]:
        """Codifica texto em IDs de token via BPE byte-level (algoritmo GPT-2/Qwen)."""
        text = normalize(text)
        token_ids: List[int] = []

        for segment in self._split_special_tokens(text):
            if segment in self.special_tokens:
                token_ids.append(self.special_tokens[segment])
                continue

            for match in _GPT2_PATTERN.finditer(segment):
                piece = match.group()
                byte_piece = "".join(self._byte_encoder[b] for b in piece.encode("utf-8"))

                for bpe_piece in self._bpe(byte_piece).split(" "):
                    tid = self.vocab.get(bpe_piece)
                    if tid is not None:
                        token_ids.append(tid)
                    else:
                        for ch in bpe_piece:
                            fallback_id = self.vocab.get(ch)
                            if fallback_id is not None:
                                token_ids.append(fallback_id)

        return token_ids

    def decode_bytes(self, token_ids: List[int]) -> bytes:
        """Decodifica IDs de token pros bytes UTF-8 crus, SEM decodificar pra
        str ainda -- usado pelo streaming (IncrementalUTF8Decoder, ver
        vte/core/incremental_decoder.py) pra não cortar caracteres multi-byte
        (emoji, acentos) no meio quando um token BPE só carrega metade dos
        bytes de um caractere."""
        pieces = []
        for tid in token_ids:
            if tid == self.eos_token_id:
                break
            piece = self.inv_vocab.get(tid)
            if piece is None:
                continue
            if piece in self.special_tokens:
                continue
            pieces.append(piece)

        text = "".join(pieces)
        return bytes(self._byte_decoder.get(ch, ord("?") & 0xFF) for ch in text)

    def decode(self, token_ids: List[int]) -> str:
        """Decodifica IDs de token de volta para texto UTF-8."""
        return self.decode_bytes(token_ids).decode("utf-8", errors="replace")

    DEFAULT_SYSTEM_PROMPT = (
        "You are Qwen, created by Alibaba Cloud. You are a helpful assistant. "
        "Always reply in the same language the user's message is written in "
        "(e.g. reply in Portuguese to a Portuguese message, in Spanish to a "
        "Spanish message) -- never switch to English unless the user wrote in "
        "English."
    )

    def apply_chat_template(self, user_message, system: str = None, enable_thinking: bool = False) -> str:
        """Formata uma mensagem (ou histórico completo) no chat template do
        Qwen2.5 (ChatML).

        Sem isto, o modelo Instruct recebe o texto cru e faz *completion*
        (continua o texto como um documento) em vez de responder como
        assistente -- é o que fazia um "oi" retornar texto incoerente de
        divagação. Os marcadores <|im_start|>/<|im_end|> são reconhecidos
        pelo encode() como tokens especiais (ver _split_special_tokens), e o
        <|im_end|> ao final da resposta é o eos_token_id, o que faz a geração
        parar sozinha no ponto certo.

        `user_message` aceita tanto uma string única (comportamento original,
        preservado) quanto uma lista de mensagens `{"role", "content"}`
        (histórico multi-turno completo) -- ver `_coerce_chat_messages`.

        `enable_thinking` não tem efeito aqui -- o ChatML do Qwen2.5 não tem
        um bloco <think>. O parâmetro só existe para manter a assinatura
        igual à de outros tokenizers (ver GraniteTokenizer.apply_chat_template
        e vte/core/thinking_scanner.py), pronta para um modelo que use isso
        de verdade (ex.: Qwen3.5) sem precisar mudar quem chama.
        """
        messages = _coerce_chat_messages(user_message, system, self.DEFAULT_SYSTEM_PROMPT)
        messages = _strip_literal_special_tokens(messages, self.special_tokens)
        rendered = "".join(
            f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages
        )
        return rendered + "<|im_start|>assistant\n"

    @property
    def stop_token_ids(self) -> set:
        """Tokens que encerram a geração (fim de turno do assistente)."""
        ids = {self.eos_token_id}
        eot = self.special_tokens.get("<|endoftext|>")
        if eot is not None:
            ids.add(eot)
        return {i for i in ids if i is not None}


class GraniteTokenizer:
    """
    Tokenizador BPE byte-level do Granite 4.1, reconstruído a partir do
    vocabulário/merges do próprio GGUF -- mesmo motor de merge BPE do
    QwenTokenizer (reaproveitado por atribuição direta abaixo, já que só usa
    `self.bpe_ranks`/`self._bpe_cache`, nada específico do Qwen), mas com
    pré-tokenizador, tokens especiais e chat template PRÓPRIOS do Granite
    (confirmados contra os bytes reais do GGUF, não adivinhados -- ver
    plano em curious-roaming-quasar.md). `QwenTokenizer` permanece intocado.
    """

    # Reaproveita o motor BPE genérico do QwenTokenizer -- funções puras de
    # instância (usam só self.bpe_ranks/self._bpe_cache/self.special_tokens),
    # sem nenhuma suposição de arquitetura.
    _bpe = QwenTokenizer._bpe
    _split_special_tokens = QwenTokenizer._split_special_tokens

    def __init__(self, vocab_path: Optional[str] = None, gguf_path: Optional[str | Path] = None):
        self.vocab: Dict[str, int] = {}
        self.inv_vocab: Dict[int, str] = {}
        self.bpe_ranks: Dict[tuple, int] = {}
        self._bpe_cache: Dict[str, str] = {}

        self._byte_encoder = _bytes_to_unicode()
        self._byte_decoder = {v: k for k, v in self._byte_encoder.items()}

        # IDs confirmados contra os bytes reais do GGUF (gguf.GGUFReader),
        # não a partir de documentação de terceiros: BOS e EOS são o MESMO
        # token (100257, "<|end_of_text|>") -- `tokenizer.ggml.add_bos_token`
        # é False neste GGUF, então nenhum BOS é prefixado por padrão.
        self.special_tokens = {
            "<|end_of_text|>": 100257,
            "<|start_of_role|>": 100264,
            "<|end_of_role|>": 100265,
            "<|pad|>": 100256,
            "<|unk|>": 100269,
        }
        self.bos_token_id: Optional[int] = 100257
        self.eos_token_id: Optional[int] = 100257
        self.vocab_size = 0
        self._chat_template_src: Optional[str] = None

        if gguf_path is not None:
            self._load_from_gguf(Path(gguf_path))
        else:
            logger.warning(
                "GraniteTokenizer sem gguf_path: usando vocabulário mínimo de fallback (não-funcional para produção)."
            )
            self._load_fallback_vocab()

    def _load_fallback_vocab(self):
        self.vocab.update(self.special_tokens)
        self._rebuild_inverse_vocab()

    def _load_from_gguf(self, gguf_path: Path):
        logger.info(f"[Granite] Extraindo vocabulário BPE do GGUF: {gguf_path}")
        metadata = read_gguf_metadata(gguf_path, wanted_keys=_TOKENIZER_KEYS | {"tokenizer.chat_template"})

        tokens: List[str] = metadata.get("tokenizer.ggml.tokens", [])
        merges: List[str] = metadata.get("tokenizer.ggml.merges", [])

        if not tokens:
            logger.warning("GGUF não contém 'tokenizer.ggml.tokens'. Usando fallback mínimo.")
            self._load_fallback_vocab()
            return

        for token_id, token_str in enumerate(tokens):
            self.vocab[token_str] = token_id
        self._rebuild_inverse_vocab()
        self.vocab_size = len(tokens)

        for token_str in list(self.special_tokens.keys()):
            real_id = self.vocab.get(token_str)
            if real_id is not None:
                self.special_tokens[token_str] = real_id

        bos_id = metadata.get("tokenizer.ggml.bos_token_id")
        eos_id = metadata.get("tokenizer.ggml.eos_token_id")
        if bos_id is not None:
            self.bos_token_id = bos_id
        if eos_id is not None:
            self.eos_token_id = eos_id

        for rank, merge_line in enumerate(merges):
            parts = merge_line.split(" ")
            if len(parts) == 2:
                self.bpe_ranks[(parts[0], parts[1])] = rank

        self._chat_template_src = metadata.get("tokenizer.chat_template")
        if not self._chat_template_src:
            logger.warning("GGUF não contém 'tokenizer.chat_template' -- apply_chat_template() falhará.")

        logger.info(
            f"[Granite] Tokenizer BPE carregado: {len(tokens)} tokens, {len(self.bpe_ranks)} regras de merge."
        )

    def _rebuild_inverse_vocab(self):
        self.inv_vocab = {v: k for k, v in self.vocab.items()}

    def encode(self, text: str) -> List[int]:
        """Codifica texto em IDs de token via BPE byte-level, usando o
        pré-tokenizador "dbrx" (idêntico ao do Llama3, ver `_DBRX_PATTERN`)
        em vez do padrão GPT2/Qwen."""
        text = normalize(text)
        token_ids: List[int] = []

        for segment in self._split_special_tokens(text):
            if segment in self.special_tokens:
                token_ids.append(self.special_tokens[segment])
                continue

            for match in _DBRX_PATTERN.finditer(segment):
                piece = match.group()
                byte_piece = "".join(self._byte_encoder[b] for b in piece.encode("utf-8"))

                for bpe_piece in self._bpe(byte_piece).split(" "):
                    tid = self.vocab.get(bpe_piece)
                    if tid is not None:
                        token_ids.append(tid)
                    else:
                        for ch in bpe_piece:
                            fallback_id = self.vocab.get(ch)
                            if fallback_id is not None:
                                token_ids.append(fallback_id)

        return token_ids

    def decode_bytes(self, token_ids: List[int]) -> bytes:
        """Decodifica IDs de token pros bytes UTF-8 crus, SEM decodificar pra
        str ainda -- usado pelo streaming (IncrementalUTF8Decoder, ver
        vte/core/incremental_decoder.py) pra não cortar caracteres multi-byte
        (emoji, acentos) no meio quando um token BPE só carrega metade dos
        bytes de um caractere."""
        pieces = []
        for tid in token_ids:
            if tid == self.eos_token_id:
                break
            piece = self.inv_vocab.get(tid)
            if piece is None:
                continue
            if piece in self.special_tokens:
                continue
            pieces.append(piece)

        text = "".join(pieces)
        return bytes(self._byte_decoder.get(ch, ord("?") & 0xFF) for ch in text)

    def decode(self, token_ids: List[int]) -> str:
        """Decodifica IDs de token de volta para texto UTF-8."""
        return self.decode_bytes(token_ids).decode("utf-8", errors="replace")

    DEFAULT_SYSTEM_PROMPT = (
        "You are Granite, developed by IBM. You are a helpful assistant. "
        "Always reply in the same language the user's message is written in "
        "(e.g. reply in Portuguese to a Portuguese message, in Spanish to a "
        "Spanish message) -- never switch to English unless the user wrote in "
        "English."
    )

    def apply_chat_template(self, user_message, system: str = None, enable_thinking: bool = False) -> str:
        """Renderiza o Jinja2 real embutido em `tokenizer.chat_template` do
        GGUF (não uma f-string aproximada) -- o template do Granite é bem
        mais complexo que o ChatML do Qwen (suporta tools/documents, que não
        usamos aqui, mas o template exige as variáveis existirem mesmo assim).

        `user_message` aceita tanto uma string única (comportamento original,
        preservado) quanto uma lista de mensagens `{"role", "content"}`
        (histórico multi-turno completo) -- ver `_coerce_chat_messages`.

        `<|end_of_text|>` (o EOS) é emitido pelo próprio template ao final de
        cada turno -- é ele que faz a geração parar sozinha, mesmo mecanismo
        do `<|im_end|>` do Qwen.

        `enable_thinking` é repassado ao render mesmo sem o template real do
        Granite referenciar isso hoje (Jinja2 simplesmente ignora uma
        variável de contexto não usada) -- é o mesmo hook exposto em
        QwenTokenizer, já pronto para um chat template que de fato tenha um
        bloco <think> condicional a essa flag (ex.: Qwen3.5, ver
        Model/"template  chat.txt").
        """
        if not self._chat_template_src:
            raise RuntimeError(
                "Chat template do Granite não carregado do GGUF (tokenizer.chat_template ausente)."
            )
        messages = _coerce_chat_messages(user_message, system, self.DEFAULT_SYSTEM_PROMPT)
        messages = _strip_literal_special_tokens(messages, self.special_tokens)

        env = Environment(trim_blocks=True, lstrip_blocks=True)
        env.filters["tojson"] = json.dumps
        template = env.from_string(self._chat_template_src)
        return template.render(
            messages=messages,
            add_generation_prompt=True,
            tools=None,
            documents=None,
            available_tools=None,
            enable_thinking=enable_thinking,
        )

    @property
    def stop_token_ids(self) -> set:
        """Tokens que encerram a geração (fim de turno do assistente)."""
        ids = {self.eos_token_id}
        eor = self.special_tokens.get("<|end_of_role|>")
        if eor is not None:
            ids.add(eor)
        return {i for i in ids if i is not None}


class Qwen3_5Tokenizer:
    """
    Tokenizador BPE byte-level do Qwen 3.5 2B, reconstruído a partir do
    vocabulário/merges do próprio GGUF -- mesmo motor de merge BPE do
    QwenTokenizer/GraniteTokenizer (reaproveitado por atribuição direta,
    igual GraniteTokenizer já faz), mas com pré-tokenizador PRÓPRIO
    (`_QWEN35_PATTERN`, ver comentário acima -- não é o mesmo do Qwen2.5
    apesar do nome parecido), tokens especiais e chat template do Qwen3.5
    (confirmados contra os bytes reais do GGUF e o `tokenization_qwen3_5.py`
    real instalado nesta sessão, não adivinhados). QwenTokenizer/
    GraniteTokenizer permanecem intocados.
    """

    _bpe = QwenTokenizer._bpe
    _split_special_tokens = QwenTokenizer._split_special_tokens

    def __init__(self, vocab_path: Optional[str] = None, gguf_path: Optional[str | Path] = None):
        self.vocab: Dict[str, int] = {}
        self.inv_vocab: Dict[int, str] = {}
        self.bpe_ranks: Dict[tuple, int] = {}
        self._bpe_cache: Dict[str, str] = {}

        self._byte_encoder = _bytes_to_unicode()
        self._byte_decoder = {v: k for k, v in self._byte_encoder.items()}

        # IDs confirmados no GGUF real (gguf.GGUFReader) e em
        # config.json/Tokenizer config.txt reais: EOS é <|endoftext|>
        # (248044), NÃO <|im_end|> (248046) -- mesmo padrão "EOS != fim de
        # turno visual" já visto no Qwen2.5 (que também usa <|endoftext|>
        # como EOS real, com <|im_end|> sendo só um marcador de formatação
        # do ChatML).
        self.special_tokens = {
            "<|endoftext|>": 248044,
            "<|im_start|>": 248045,
            "<|im_end|>": 248046,
            "<think>": 248068,
            "</think>": 248069,
        }
        self.bos_token_id: Optional[int] = None
        self.eos_token_id: Optional[int] = 248044
        self.vocab_size = 0
        self._chat_template_src: Optional[str] = None

        if gguf_path is not None:
            self._load_from_gguf(Path(gguf_path))
        else:
            logger.warning(
                "Qwen3_5Tokenizer sem gguf_path: usando vocabulário mínimo de fallback (não-funcional para produção)."
            )
            self._load_fallback_vocab()

    def _load_fallback_vocab(self):
        self.vocab.update(self.special_tokens)
        self._rebuild_inverse_vocab()

    def _load_from_gguf(self, gguf_path: Path):
        logger.info(f"[Qwen3.5] Extraindo vocabulário BPE do GGUF: {gguf_path}")
        metadata = read_gguf_metadata(gguf_path, wanted_keys=_TOKENIZER_KEYS | {"tokenizer.chat_template"})

        tokens: List[str] = metadata.get("tokenizer.ggml.tokens", [])
        merges: List[str] = metadata.get("tokenizer.ggml.merges", [])

        if not tokens:
            logger.warning("GGUF não contém 'tokenizer.ggml.tokens'. Usando fallback mínimo.")
            self._load_fallback_vocab()
            return

        for token_id, token_str in enumerate(tokens):
            self.vocab[token_str] = token_id
        self._rebuild_inverse_vocab()
        self.vocab_size = len(tokens)

        for token_str in list(self.special_tokens.keys()):
            real_id = self.vocab.get(token_str)
            if real_id is not None:
                self.special_tokens[token_str] = real_id

        bos_id = metadata.get("tokenizer.ggml.bos_token_id")
        eos_id = metadata.get("tokenizer.ggml.eos_token_id")
        if bos_id is not None:
            self.bos_token_id = bos_id
        if eos_id is not None:
            self.eos_token_id = eos_id

        for rank, merge_line in enumerate(merges):
            parts = merge_line.split(" ")
            if len(parts) == 2:
                self.bpe_ranks[(parts[0], parts[1])] = rank

        self._chat_template_src = metadata.get("tokenizer.chat_template")
        if not self._chat_template_src:
            logger.warning("GGUF não contém 'tokenizer.chat_template' -- apply_chat_template() falhará.")

        logger.info(
            f"[Qwen3.5] Tokenizer BPE carregado: {len(tokens)} tokens, {len(self.bpe_ranks)} regras de merge."
        )

    def _rebuild_inverse_vocab(self):
        self.inv_vocab = {v: k for k, v in self.vocab.items()}

    def encode(self, text: str) -> List[int]:
        """Codifica texto em IDs de token via BPE byte-level, usando o
        pré-tokenizador PRÓPRIO do Qwen3.5 (`_QWEN35_PATTERN`), não o do
        Qwen2.5 nem o do Granite."""
        text = normalize(text)
        token_ids: List[int] = []

        for segment in self._split_special_tokens(text):
            if segment in self.special_tokens:
                token_ids.append(self.special_tokens[segment])
                continue

            for match in _QWEN35_PATTERN.finditer(segment):
                piece = match.group()
                byte_piece = "".join(self._byte_encoder[b] for b in piece.encode("utf-8"))

                for bpe_piece in self._bpe(byte_piece).split(" "):
                    tid = self.vocab.get(bpe_piece)
                    if tid is not None:
                        token_ids.append(tid)
                    else:
                        for ch in bpe_piece:
                            fallback_id = self.vocab.get(ch)
                            if fallback_id is not None:
                                token_ids.append(fallback_id)

        return token_ids

    # Tokens especiais que precisam sobreviver ao decode() como texto
    # literal -- o ThinkingSectionScanner (vte/core/thinking_scanner.py)
    # detecta o bloco de pensamento procurando essas strings no stream JÁ
    # DECODIFICADO, não por token ID. Sem isso, <think>/</think> eram
    # descartados igual aos outros tokens especiais (im_start/im_end/eot),
    # o scanner nunca via a tag de fechamento, e o texto de "pensamento"
    # (rascunho associativo, propositalmente menos coerente/direto que a
    # resposta final) era exibido inteiro como se fosse a resposta -- bug
    # real encontrado ao investigar por que o Qwen3.5 parecia "não pensar"
    # e gerar texto degenerado.
    _LITERAL_SPECIAL_TOKENS = {"<think>", "</think>"}

    def decode_bytes(self, token_ids: List[int]) -> bytes:
        """Decodifica IDs de token pros bytes UTF-8 crus, SEM decodificar pra
        str ainda -- usado pelo streaming (IncrementalUTF8Decoder, ver
        vte/core/incremental_decoder.py) pra não cortar caracteres multi-byte
        (emoji, acentos) no meio quando um token BPE só carrega metade dos
        bytes de um caractere."""
        pieces = []  # cada item: (True, str_literal) ou (False, bpe_piece)
        for tid in token_ids:
            if tid == self.eos_token_id:
                break
            piece = self.inv_vocab.get(tid)
            if piece is None:
                continue
            if piece in self.special_tokens:
                if piece in self._LITERAL_SPECIAL_TOKENS:
                    pieces.append((True, piece))
                continue
            pieces.append((False, piece))

        out_bytes = bytearray()
        for is_literal, piece in pieces:
            if is_literal:
                out_bytes.extend(piece.encode("utf-8"))
                continue
            for ch in piece:
                b = self._byte_decoder.get(ch)
                if b is not None:
                    out_bytes.append(b)
        return bytes(out_bytes)

    def decode(self, token_ids: List[int]) -> str:
        """Decodifica IDs de token de volta para texto UTF-8."""
        return self.decode_bytes(token_ids).decode("utf-8", errors="replace")

    DEFAULT_SYSTEM_PROMPT = (
        "You are Qwen, created by Alibaba Cloud. You are a helpful assistant. "
        "Always reply in the same language the user's message is written in "
        "(e.g. reply in Portuguese to a Portuguese message, in Spanish to a "
        "Spanish message) -- never switch to English unless the user wrote in "
        "English."
    )

    def apply_chat_template(self, user_message, system: str = None, enable_thinking: bool = False) -> str:
        """Renderiza o Jinja2 real embutido em `tokenizer.chat_template` do
        GGUF -- mesmo mecanismo do GraniteTokenizer, mas o template do
        Qwen3.5 de fato usa `enable_thinking` (bloco condicional real: insere
        '<think>\\n' vazio pra pensar livremente, ou '<think>\\n\\n</think>\\n\\n'
        já fechado se enable_thinking for False -- ver Model/"template
        chat.txt"). `add_vision_id` é passado como False explicitamente
        (o template real referencia essa variável num bloco de imagem/vídeo
        que não usamos em texto puro).

        `user_message` aceita tanto uma string única (comportamento original,
        preservado) quanto uma lista de mensagens `{"role", "content"}`
        (histórico multi-turno completo) -- ver `_coerce_chat_messages`."""
        if not self._chat_template_src:
            raise RuntimeError(
                "Chat template do Qwen3.5 não carregado do GGUF (tokenizer.chat_template ausente)."
            )

        messages = _coerce_chat_messages(user_message, system, self.DEFAULT_SYSTEM_PROMPT)
        messages = _strip_literal_special_tokens(messages, self.special_tokens)

        env = Environment(trim_blocks=True, lstrip_blocks=True)
        env.filters["tojson"] = json.dumps
        template = env.from_string(self._chat_template_src)
        return template.render(
            messages=messages,
            add_generation_prompt=True,
            add_vision_id=False,
            tools=None,
            enable_thinking=enable_thinking,
        )

    @property
    def stop_token_ids(self) -> set:
        """Tokens que encerram a geração. `tokenizer.ggml.eos_token_id` real
        do GGUF é <|im_end|> (248046), não <|endoftext|> (248044) -- mesma
        situação já vista no QwenTokenizer (ChatML: <|im_end|> é o EOS
        "de fato" do chat, mas <|endoftext|> continua sendo um stop válido
        também). Mesmo padrão defensivo de lá: inclui os dois.

        `</think>` NÃO é um token de parada (o modelo continua gerando a
        resposta final depois dele) -- é só um marcador de seção que o
        ThinkingSectionScanner (vte/core/thinking_scanner.py) usa pra
        separar a UI, sem parar a geração."""
        ids = {self.eos_token_id}
        eot = self.special_tokens.get("<|endoftext|>")
        if eot is not None:
            ids.add(eot)
        return {i for i in ids if i is not None}


class LlamaTokenizer:
    """
    Tokenizador BPE byte-level do Llama 3.1, reconstruído a partir do
    vocabulário/merges do próprio GGUF -- mesmo motor de merge BPE do
    QwenTokenizer (reaproveitado por atribuição direta, como Granite/
    Qwen3.5 já fazem), pré-tokenizador `_DBRX_PATTERN` (é literalmente a
    regex do Llama3 -- ver comentário na definição do pattern, llama.cpp
    trata LLAMA_VOCAB_PRE_TYPE_DBRX/SMAUG/LLAMA3 como o mesmo case), e
    tokens especiais/chat template PRÓPRIOS do Llama 3.1 (confirmados
    contra os bytes reais de Model/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
    via gguf.GGUFReader, não adivinhados).
    """

    _bpe = QwenTokenizer._bpe
    _split_special_tokens = QwenTokenizer._split_special_tokens

    def __init__(self, vocab_path: Optional[str] = None, gguf_path: Optional[str | Path] = None):
        self.vocab: Dict[str, int] = {}
        self.inv_vocab: Dict[int, str] = {}
        self.bpe_ranks: Dict[tuple, int] = {}
        self._bpe_cache: Dict[str, str] = {}

        self._byte_encoder = _bytes_to_unicode()
        self._byte_decoder = {v: k for k, v in self._byte_encoder.items()}

        # IDs confirmados contra os bytes reais do GGUF -- sobrescritos pelos
        # valores reais do vocabulário logo abaixo em _load_from_gguf, este
        # dict só serve de fallback pro caso vocab_path/sem-GGUF.
        self.special_tokens = {
            "<|begin_of_text|>": 128000,
            "<|end_of_text|>": 128001,
            "<|start_header_id|>": 128006,
            "<|end_header_id|>": 128007,
            "<|eom_id|>": 128008,
            "<|eot_id|>": 128009,
            "<|python_tag|>": 128010,
        }
        # tokenizer.ggml.eos_token_id real do GGUF aponta para <|eot_id|>
        # (fim de turno do chat), não <|end_of_text|> -- mesma situação já
        # vista no ChatML do Qwen (o EOS "de fato" do chat é o marcador de
        # turno, não o EOS bruto de pré-treino). bos_token_id é
        # <|begin_of_text|>: o chat template deste GGUF referencia
        # `{{- bos_token }}` como variável Jinja (não como literal embutido),
        # então apply_chat_template precisa passá-la explicitamente no
        # render -- diferente de Granite/Qwen3.5, cujos templates não
        # referenciam bos_token.
        self.bos_token_id: Optional[int] = 128000
        self.eos_token_id: Optional[int] = 128009
        self.vocab_size = 0
        self._chat_template_src: Optional[str] = None

        if gguf_path is not None:
            self._load_from_gguf(Path(gguf_path))
        else:
            logger.warning(
                "LlamaTokenizer sem gguf_path: usando vocabulário mínimo de fallback (não-funcional para produção)."
            )
            self._load_fallback_vocab()

    def _load_fallback_vocab(self):
        self.vocab.update(self.special_tokens)
        self._rebuild_inverse_vocab()

    def _load_from_gguf(self, gguf_path: Path):
        logger.info(f"[Llama] Extraindo vocabulário BPE do GGUF: {gguf_path}")
        metadata = read_gguf_metadata(gguf_path, wanted_keys=_TOKENIZER_KEYS | {"tokenizer.chat_template"})

        tokens: List[str] = metadata.get("tokenizer.ggml.tokens", [])
        merges: List[str] = metadata.get("tokenizer.ggml.merges", [])

        if not tokens:
            logger.warning("GGUF não contém 'tokenizer.ggml.tokens'. Usando fallback mínimo.")
            self._load_fallback_vocab()
            return

        for token_id, token_str in enumerate(tokens):
            self.vocab[token_str] = token_id
        self._rebuild_inverse_vocab()
        self.vocab_size = len(tokens)

        for token_str in list(self.special_tokens.keys()):
            real_id = self.vocab.get(token_str)
            if real_id is not None:
                self.special_tokens[token_str] = real_id

        bos_id = metadata.get("tokenizer.ggml.bos_token_id")
        eos_id = metadata.get("tokenizer.ggml.eos_token_id")
        if bos_id is not None:
            self.bos_token_id = bos_id
        if eos_id is not None:
            self.eos_token_id = eos_id

        for rank, merge_line in enumerate(merges):
            parts = merge_line.split(" ")
            if len(parts) == 2:
                self.bpe_ranks[(parts[0], parts[1])] = rank

        self._chat_template_src = metadata.get("tokenizer.chat_template")
        if not self._chat_template_src:
            logger.warning("GGUF não contém 'tokenizer.chat_template' -- apply_chat_template() falhará.")

        logger.info(
            f"[Llama] Tokenizer BPE carregado: {len(tokens)} tokens, {len(self.bpe_ranks)} regras de merge."
        )

    def _rebuild_inverse_vocab(self):
        self.inv_vocab = {v: k for k, v in self.vocab.items()}

    def encode(self, text: str) -> List[int]:
        """Codifica texto em IDs de token via BPE byte-level, usando o
        pré-tokenizador "dbrx" (idêntico ao do Llama3, ver `_DBRX_PATTERN`)."""
        text = normalize(text)
        token_ids: List[int] = []

        for segment in self._split_special_tokens(text):
            if segment in self.special_tokens:
                token_ids.append(self.special_tokens[segment])
                continue

            for match in _DBRX_PATTERN.finditer(segment):
                piece = match.group()
                byte_piece = "".join(self._byte_encoder[b] for b in piece.encode("utf-8"))

                for bpe_piece in self._bpe(byte_piece).split(" "):
                    tid = self.vocab.get(bpe_piece)
                    if tid is not None:
                        token_ids.append(tid)
                    else:
                        for ch in bpe_piece:
                            fallback_id = self.vocab.get(ch)
                            if fallback_id is not None:
                                token_ids.append(fallback_id)

        return token_ids

    def decode_bytes(self, token_ids: List[int]) -> bytes:
        """Decodifica IDs de token pros bytes UTF-8 crus, SEM decodificar pra
        str ainda -- usado pelo streaming (IncrementalUTF8Decoder) pra não
        cortar caracteres multi-byte no meio."""
        pieces = []
        for tid in token_ids:
            if tid == self.eos_token_id:
                break
            piece = self.inv_vocab.get(tid)
            if piece is None:
                continue
            if piece in self.special_tokens:
                continue
            pieces.append(piece)

        text = "".join(pieces)
        return bytes(self._byte_decoder.get(ch, ord("?") & 0xFF) for ch in text)

    def decode(self, token_ids: List[int]) -> str:
        """Decodifica IDs de token de volta para texto UTF-8."""
        return self.decode_bytes(token_ids).decode("utf-8", errors="replace")

    DEFAULT_SYSTEM_PROMPT = (
        "You are a helpful assistant. Always reply in the same language the "
        "user's message is written in (e.g. reply in Portuguese to a "
        "Portuguese message, in Spanish to a Spanish message) -- never "
        "switch to English unless the user wrote in English."
    )

    def apply_chat_template(self, user_message, system: str = None, enable_thinking: bool = False) -> str:
        """Renderiza o Jinja2 real embutido em `tokenizer.chat_template` do
        GGUF. Diferença real em relação a Granite/Qwen3.5: o template do
        Llama 3.1 referencia `{{- bos_token }}` como variável (confirmado
        lendo o template real do GGUF), então precisa ser passada
        explicitamente no render -- sem isso, o Jinja2 renderiza a variável
        indefinida como string vazia (comportamento padrão do
        `Undefined`, não um erro), e `<|begin_of_text|>` simplesmente não
        apareceria no prompt.

        `enable_thinking` é aceito só por paridade de assinatura com os
        outros tokenizers (o template do Llama 3.1 não referencia essa
        variável -- Jinja2 ignora silenciosamente uma variável de contexto
        não usada)."""
        if not self._chat_template_src:
            raise RuntimeError(
                "Chat template do Llama não carregado do GGUF (tokenizer.chat_template ausente)."
            )

        messages = _coerce_chat_messages(user_message, system, self.DEFAULT_SYSTEM_PROMPT)
        messages = _strip_literal_special_tokens(messages, self.special_tokens)

        bos_token_str = self.inv_vocab.get(self.bos_token_id, "<|begin_of_text|>")

        env = Environment(trim_blocks=True, lstrip_blocks=True)
        env.filters["tojson"] = json.dumps
        template = env.from_string(self._chat_template_src)
        return template.render(
            messages=messages,
            add_generation_prompt=True,
            tools=None,
            bos_token=bos_token_str,
        )

    @property
    def stop_token_ids(self) -> set:
        """Tokens que encerram a geração. `tokenizer.ggml.eos_token_id` real
        do GGUF já é <|eot_id|> (fim de turno), mas <|end_of_text|> e
        <|eom_id|> (fim de mensagem em modo ferramenta/ipython) também
        encerram a geração na prática -- mesmo padrão defensivo usado em
        QwenTokenizer/Qwen3_5Tokenizer."""
        ids = {self.eos_token_id}
        for name in ("<|end_of_text|>", "<|eom_id|>"):
            tid = self.special_tokens.get(name)
            if tid is not None:
                ids.add(tid)
        return {i for i in ids if i is not None}
