"""
Downloader de modelos GGUF do Hugging Face Hub para a pasta Model/ do VTE --
o equivalente ao "ollama pull", mas restrito às arquiteturas que o VTE
realmente sabe rodar (ver vte/compiler/sanitizer.py::SUPPORTED_ARCHITECTURES).

Não existia nenhum download automático em lugar nenhum do projeto antes
deste módulo (confirmado por busca exaustiva por huggingface_hub/download):
até aqui, obter o .gguf e colocá-lo em Model/ era inteiramente manual (ver
docs/USAGE.md, "Where models go").
"""
from pathlib import Path
from typing import Optional

from ..bridge.logger import get_logger

logger = get_logger("VTE.Downloader")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Mapeia os mesmos nomes curados de VTEModel.MODEL_REGISTRY para
# "repo_id:filename" no Hugging Face Hub. Cada entrada foi CONFERIDA como
# existente de verdade (repo real, arquivo real, conteúdo real) antes de
# entrar aqui -- não é um palpite de convenção de nomes. O destino local usa
# o MESMO nome de arquivo (e subpasta, no caso do draft model) que
# VTEModel.MODEL_REGISTRY já espera, então `vte pull <nome>` seguido de
# `VTEModel.from_pretrained(<nome>)` funciona sem nenhum passo manual extra.
CURATED_CHECKPOINTS: dict[str, str] = {
    "qwen2.5:1.5b-q4_k_m": "Qwen/Qwen2.5-1.5B-Instruct-GGUF:qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "qwen2.5:7b-q4_k_m": "bartowski/Qwen2.5-7B-Instruct-GGUF:Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    "qwen2.5:0.5b-q4_k_m-draft": "Qwen/Qwen2.5-0.5B-Instruct-GGUF:qwen2.5-0.5b-instruct-q4_k_m.gguf",
    "granite-4.1:3b-q8_0": "unsloth/granite-4.1-3b-GGUF:granite-4.1-3b-Q8_0.gguf",
    "granite-4.1:30b-q8_0": "ibm-granite/granite-4.1-30b-GGUF:granite-4.1-30b-Q8_0.gguf",
    "qwen3.5:2b-q6_k": "unsloth/Qwen3.5-2B-GGUF:Qwen3.5-2B-Q6_K.gguf",
    "llama3.1:8b-instruct-q4_k_m": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF:Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
    "qwen2.5:32b-q4_k_m": "bartowski/Qwen2.5-32B-Instruct-GGUF:Qwen2.5-32B-Instruct-Q4_K_M.gguf",
}

# Nome de arquivo local (relativo a Model/) para cada nome curado -- réplica
# deliberada de VTEModel.MODEL_REGISTRY (não importado daqui: vte.core.model
# importa bastante coisa pesada de compiler/core só para definir a classe, e
# este módulo não precisa de nada disso só para resolver um nome de arquivo).
_CURATED_LOCAL_NAMES: dict[str, str] = {
    "qwen2.5:1.5b-q4_k_m": "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
    "qwen2.5:7b-q4_k_m": "Qwen2.5-7B-Instruct.Q4_K_M.gguf",
    "qwen2.5:0.5b-q4_k_m-draft": "Classifier/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
    "granite-4.1:3b-q8_0": "granite-4.1-3b-Q8_0.gguf",
    "granite-4.1:30b-q8_0": "granite-4.1-30b-Q8_0.gguf",
    "qwen3.5:2b-q6_k": "Qwen3.5-2B-Q6_K.gguf",
    "llama3.1:8b-instruct-q4_k_m": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
    "qwen2.5:32b-q4_k_m": "Qwen2.5-32B-Instruct-Q4_K_M.gguf",
}


def _parse_checkpoint(checkpoint: str) -> tuple[str, str]:
    if ":" not in checkpoint:
        raise ValueError(
            f"Checkpoint '{checkpoint}' inválido -- formato esperado é "
            f"'<repo_id>:<arquivo.gguf>' (mesma convenção do campo 'checkpoint' "
            f"em server_models.json do Lemonade)."
        )
    repo_id, filename = checkpoint.rsplit(":", 1)
    if not filename.endswith(".gguf"):
        raise ValueError(f"Checkpoint '{checkpoint}' não aponta para um arquivo .gguf.")
    return repo_id, filename


def pull_model(name_or_checkpoint: str, dest_dir: Optional[Path] = None, force: bool = False) -> Path:
    """
    Baixa um GGUF do Hugging Face Hub para Model/ (ou `dest_dir`).

    `name_or_checkpoint` aceita:
    - um nome curado (ex.: "qwen2.5:1.5b-q4_k_m", ver CURATED_CHECKPOINTS) --
      resolve para um repo/arquivo conhecido e salva com o mesmo nome que
      VTEModel.MODEL_REGISTRY já espera, pronto para `from_pretrained()`.
    - um checkpoint cru "repo_id:arquivo.gguf" -- qualquer repositório GGUF
      público no Hub, salvo com o nome do próprio arquivo.

    Idempotente por padrão: se o destino já existir, não baixa de novo
    (`force=True` para sobrescrever).
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        raise ImportError(
            "Baixar modelos requer 'huggingface_hub' (já é dependência declarada "
            "em pyproject.toml -- reinstale o VTE, ou rode 'pip install huggingface_hub')."
        ) from e

    dest_dir = Path(dest_dir) if dest_dir is not None else (_REPO_ROOT / "Model")
    dest_dir.mkdir(parents=True, exist_ok=True)

    if name_or_checkpoint in CURATED_CHECKPOINTS:
        checkpoint = CURATED_CHECKPOINTS[name_or_checkpoint]
        local_name = _CURATED_LOCAL_NAMES[name_or_checkpoint]
    else:
        checkpoint = name_or_checkpoint
        local_name = None

    repo_id, filename = _parse_checkpoint(checkpoint)
    if local_name is None:
        local_name = Path(filename).name  # ignora subpasta do repo remoto -- destino local é sempre plano

    local_path = dest_dir / local_name
    local_path.parent.mkdir(parents=True, exist_ok=True)

    if local_path.exists() and not force:
        logger.info(f"'{local_path}' já existe -- pulando download (force=True para sobrescrever).")
        return local_path

    logger.info(f"Baixando {repo_id}:{filename} -> {local_path}")
    downloaded = hf_hub_download(repo_id=repo_id, filename=filename, local_dir=str(dest_dir))
    downloaded_path = Path(downloaded)

    if downloaded_path != local_path:
        downloaded_path.replace(local_path)

    logger.info(f"Download concluído: {local_path}")
    return local_path
