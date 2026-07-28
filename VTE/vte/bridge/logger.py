import logging
import sys
from pathlib import Path


class SafeStreamHandler(logging.StreamHandler):
    """StreamHandler à prova de console legado (cp1252 no Windows).

    Motivo: quando uma mensagem tem um caractere que o codepage do console
    não representa, o `StreamHandler.emit` padrão falha no `stream.write` e
    chama `handleError`, que por sua vez imprime o stack trace -- e a
    linha-fonte do stack pode conter o MESMO caractere problemático, fazendo
    a escrita falhar de novo, agora SEM ninguém para capturar. Essa segunda
    exceção escapa e derruba o processo. Foi exatamente o que travava o boot
    do motor na UI Flet (subprocesso com stdout cp1252 estrito).

    Aqui, qualquer UnicodeEncodeError na escrita é reescrito com os
    caracteres não representáveis substituídos (errors='replace'), garantindo
    que uma linha de log nunca derrube quem está logando -- na pior hipótese
    um caractere raro vira '?'.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            stream = self.stream
            enc = getattr(stream, "encoding", None) or "utf-8"
            safe = msg.encode(enc, errors="replace").decode(enc, errors="replace")
            stream.write(safe + self.terminator)
            self.flush()
        except Exception:
            # Último recurso: nunca deixar o logging propagar exceção para o
            # chamador. Silenciar é preferível a derrubar a inferência.
            pass


def get_logger(name: str) -> logging.Logger:
    """
    Configura e retorna um logger seguro para o módulo VTE.

    Args:
        name: Nome do logger (geralmente __name__)

    Returns:
        Instância configurada do logger.
    """
    logger = logging.getLogger(name)

    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    console_handler = SafeStreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    try:

        from vte.config import LOG_DIR
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / "hip_runtime.log"

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:

        print(f"Aviso: Nao foi possivel configurar log para arquivo: {e}")

    return logger
