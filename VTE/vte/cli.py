"""
CLI genérica do VTE (`vte <comando>`). Hoje só tem `pull` (baixar um GGUF do
Hugging Face Hub para Model/, equivalente ao `ollama pull` -- ver
vte/core/downloader.py para o porquê disso não existir antes) e `list`
(mostrar os nomes curados disponíveis para `pull`).
"""
import argparse
import sys

from .core.downloader import CURATED_CHECKPOINTS, pull_model


def _cmd_pull(args):
    try:
        path = pull_model(args.name, dest_dir=args.dest, force=args.force)
    except Exception as e:
        print(f"Erro ao baixar '{args.name}': {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Modelo disponível em: {path}")


def _cmd_list(args):
    print("Nomes curados (uso: vte pull <nome>):")
    for name, checkpoint in CURATED_CHECKPOINTS.items():
        print(f"  {name:<30} {checkpoint}")
    print("\nTambém aceita qualquer checkpoint cru: vte pull <repo_id>:<arquivo.gguf>")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="vte", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pull_parser = sub.add_parser("pull", help="Baixa um GGUF do Hugging Face Hub para Model/.")
    pull_parser.add_argument("name", help="Nome curado (ex.: qwen2.5:1.5b-q4_k_m) ou 'repo_id:arquivo.gguf'.")
    pull_parser.add_argument("--dest", type=str, default=None, help="Pasta de destino (default: Model/ na raiz do repo).")
    pull_parser.add_argument("--force", action="store_true", help="Sobrescreve se o arquivo já existir.")
    pull_parser.set_defaults(func=_cmd_pull)

    list_parser = sub.add_parser("list", help="Lista os nomes curados disponíveis para 'vte pull'.")
    list_parser.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
