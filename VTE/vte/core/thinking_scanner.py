"""
thinking_scanner.py — separa texto decodificado em seções "thinking"
(dentro de <think>...</think>) e "answer" (resto), sobre o STREAM de texto
já decodificado, não sobre IDs de token especiais.

Por que sobre texto, não sobre token ID: nem Qwen2.5 nem Granite têm
<think>/</think> como token especial no vocabulário deles -- só o Qwen3.5
tem (`Qwen3_5Tokenizer.decode()` reemite essas duas tags como texto
literal especificamente para isso, ver `_LITERAL_SPECIAL_TOKENS` em
tokenizer.py). Escanear a string em vez do ID também permite testar o
mecanismo com qualquer modelo já funcional, simplesmente instruindo-o via
prompt a escrever essas tags como texto comum -- o scanner não sabe nem
precisa saber a diferença.

As tags em si nunca aparecem na saída (são o marcador de transição, não
conteúdo) -- só o texto de dentro/fora de <think> é devolvido.
"""
from dataclasses import dataclass

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"
# Maior prefixo possível de qualquer uma das duas tags, usado pra decidir
# quanto texto "segurar" no fim de um chunk (pode ser o começo de uma tag
# que só termina no próximo chunk).
_MAX_TAG_LEN = max(len(THINK_OPEN), len(THINK_CLOSE))


@dataclass
class ScannedChunk:
    section: str  # "thinking" | "answer"
    text: str


class ThinkingSectionScanner:
    """Uma instância por geração (estado não é compartilhável entre turnos).

    feed(chunk) -> list[ScannedChunk] com o texto pronto pra emitir agora
    (pode estar vazia se o chunk inteiro ficou retido esperando uma tag
    completar). flush() força a saída de qualquer texto retido -- chamar
    no fim da geração para não perder o resto do buffer."""

    def __init__(self, start_in_thinking: bool = False):
        self._in_thinking = start_in_thinking
        self._pending = ""

    def feed(self, chunk: str) -> list:
        text = self._pending + chunk
        self._pending = ""
        out = []

        while text:
            open_idx = text.find(THINK_OPEN)
            close_idx = text.find(THINK_CLOSE)

            if not self._in_thinking and open_idx != -1:
                if open_idx > 0:
                    out.append(ScannedChunk("answer", text[:open_idx]))
                text = text[open_idx + len(THINK_OPEN):]
                self._in_thinking = True
                continue

            if self._in_thinking and close_idx != -1:
                if close_idx > 0:
                    out.append(ScannedChunk("thinking", text[:close_idx]))
                text = text[close_idx + len(THINK_CLOSE):]
                self._in_thinking = False
                continue

            # Nenhuma tag completa encontrada neste texto -- pode haver uma
            # tag começando bem no fim (cortada pelo limite do chunk).
            # Segura os últimos _MAX_TAG_LEN-1 caracteres como possível
            # início de tag e emite o resto com segurança.
            hold = min(len(text), _MAX_TAG_LEN - 1)
            safe_len = len(text) - hold
            if safe_len > 0:
                section = "thinking" if self._in_thinking else "answer"
                out.append(ScannedChunk(section, text[:safe_len]))
            self._pending = text[safe_len:]
            text = ""

        return out

    def flush(self) -> list:
        """Libera qualquer texto retido (chamar ao final da geração)."""
        if not self._pending:
            return []
        section = "thinking" if self._in_thinking else "answer"
        out = [ScannedChunk(section, self._pending)]
        self._pending = ""
        return out
