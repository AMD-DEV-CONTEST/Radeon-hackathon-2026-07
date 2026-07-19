"""incremental_decoder.py — decodifica bytes UTF-8 recebidos aos poucos (um
token BPE de cada vez) sem cortar caracteres multi-byte no meio.

Por que isto existe: os tokenizers BPE byte-level do projeto (Qwen2.5,
Granite, Qwen3.5) mapeiam cada token pra uma sequência de BYTES, não de
caracteres -- um emoji ou acento (2-4 bytes UTF-8) pode ter seus bytes
divididos entre 2+ tokens adjacentes. O loop de geração (`VTEModel.generate`)
decodifica UM token de cada vez pra fazer streaming da resposta; decodificar
esse único token isoladamente, quando ele contém só a METADE de um caractere
multi-byte, produz um byte solto que não forma UTF-8 válido -- `errors=
"replace"` então emite `�` (U+FFFD) no lugar, mesmo que o próximo token vá
completar a sequência corretamente. Esta classe segura (buffer) qualquer
sequência de bytes incompleta no fim de um `feed()` até que o próximo feed
a complete, em vez de decodificar cada pedaço isoladamente.
"""


def _utf8_seq_len(lead_byte: int) -> int:
    """Quantos bytes uma sequência UTF-8 iniciada por `lead_byte` deveria ter.
    Retorna 1 para ASCII e para lead bytes inválidos (trata como se fosse um
    byte solto -- evita segurar buffer indefinidamente por dado corrompido)."""
    if lead_byte < 0x80:
        return 1
    if lead_byte >> 5 == 0b110:
        return 2
    if lead_byte >> 4 == 0b1110:
        return 3
    if lead_byte >> 3 == 0b11110:
        return 4
    return 1


class IncrementalUTF8Decoder:
    """Uma instância por geração/sequência (estado não é compartilhável entre
    turnos nem entre sequências de um batch)."""

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, new_bytes: bytes) -> str:
        self._buffer.extend(new_bytes)
        buf = self._buffer
        n = len(buf)

        # Acha o último "lead byte" (não-continuation, 0x80-0xBF) dentro dos
        # últimos 4 bytes -- início da sequência multi-byte final, se houver.
        lead_pos = None
        for i in range(1, min(4, n) + 1):
            b = buf[n - i]
            if (b & 0xC0) != 0x80:
                lead_pos = n - i
                break

        if lead_pos is None:
            # 4+ bytes de continuation em sequência -- UTF-8 inválido; não há
            # como isso ser um caractere legítimo ainda incompleto. Não
            # segura buffer por dado corrompido: decodifica tudo com replace.
            out = bytes(buf).decode("utf-8", errors="replace")
            self._buffer = bytearray()
            return out

        expected_len = _utf8_seq_len(buf[lead_pos])
        have_len = n - lead_pos

        if have_len >= expected_len:
            # Sequência final completa (ou lead byte inválido, tratado como
            # 1 byte) -- pode decodificar o buffer inteiro.
            out = bytes(buf).decode("utf-8", errors="replace")
            self._buffer = bytearray()
            return out

        # Incompleta: decodifica só a parte antes do lead byte pendente
        # (sempre alinhada em fronteira de caractere, zero erros esperados)
        # e segura o resto pro próximo feed().
        complete_part = bytes(buf[:lead_pos])
        self._buffer = buf[lead_pos:]
        return complete_part.decode("utf-8", errors="replace")

    def flush(self) -> str:
        """Libera qualquer byte retido (chamar ao final da geração -- uma
        sequência genuinamente truncada pelo fim da geração vira `�`, não
        texto perdido silenciosamente)."""
        if not self._buffer:
            return ""
        out = bytes(self._buffer).decode("utf-8", errors="replace")
        self._buffer = bytearray()
        return out
