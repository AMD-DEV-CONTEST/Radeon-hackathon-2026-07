import struct
import hashlib
from pathlib import Path
from dataclasses import dataclass
from vte.bridge.errors import HIPSafetyError
from vte.bridge.logger import get_logger

logger = get_logger(__name__)

# Tabela de arquiteturas suportadas: cada entrada é o "perfil de validação"
# daquela arquitetura -- substitui os 3 gates que antes eram literais únicos
# hardcoded (architecture != "qwen2", block_count != 28, nome de arquivo
# exato). Arquitetura desconhecida continua sendo um gate DURO (rejeita),
# só que parametrizado por entrada da tabela em vez de comparação única.
# Números confirmados contra os GGUFs reais (gguf.GGUFReader), não
# documentação de terceiros -- ver plano em curious-roaming-quasar.md.
SUPPORTED_ARCHITECTURES = {
    "qwen2": {
        # block_count DIFERE por variante dentro da mesma arquitetura
        # "qwen2" -- descoberto ao adicionar o Qwen2.5 0.5B (draft model
        # pro speculative decoding): 24 camadas, contra 28 no 1.5B/7B (que
        # coincidem entre si, mas não generalizam pra toda a família). Por
        # isso block_count mora dentro de cada variante, não no nível da
        # arquitetura -- `_validate_metadata_consistency` resolve a variante
        # pelo nome do arquivo PRIMEIRO, só then valida o block_count contra
        # a variante certa.
        "max_context_length": 100_000,
        "variants": [
            {
                "expected_filename": "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
                "block_count": 28,
                "size_min_key": "ALLOWED_MODEL_SIZE_MIN",
                "size_max_key": "ALLOWED_MODEL_SIZE_MAX",
                "hash_config_key": "QWEN2_5_EXPECTED_HASH",
            },
            {
                "expected_filename": "Qwen2.5-7B-Instruct.Q4_K_M.gguf",
                "block_count": 28,
                "size_min_key": "QWEN2_5_7B_SIZE_MIN",
                "size_max_key": "QWEN2_5_7B_SIZE_MAX",
                "hash_config_key": "QWEN2_5_7B_EXPECTED_HASH",
            },
            {
                # Draft model do speculative decoding (Fase 5) -- fica em
                # Model/Classifier/ (subpasta dedicada, separa o "gerador
                # automático" do resto), mas o whitelist de nome de arquivo
                # aqui só olha o basename (`Path.name`), então funciona sem
                # nenhuma mudança na resolução de caminho.
                "expected_filename": "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
                "block_count": 24,
                "size_min_key": "QWEN2_5_0_5B_SIZE_MIN",
                "size_max_key": "QWEN2_5_0_5B_SIZE_MAX",
                "hash_config_key": "QWEN2_5_0_5B_EXPECTED_HASH",
            },
            {
                # Benchmark do hackathon AMD (W7900 na nuvem, 2026-07-19) --
                # block_count confirmado via read_gguf_metadata() contra o
                # header real do arquivo (bartowski/Qwen2.5-32B-Instruct-GGUF).
                "expected_filename": "Qwen2.5-32B-Instruct-Q4_K_M.gguf",
                "block_count": 64,
                "size_min_key": "QWEN2_5_32B_SIZE_MIN",
                "size_max_key": "QWEN2_5_32B_SIZE_MAX",
                "hash_config_key": "QWEN2_5_32B_EXPECTED_HASH",
            },
        ],
    },
    "granite": {
        # Contexto nativo do Granite 4.1 é 131072 (bem maior que os 32768 do
        # Qwen2.5) -- o teto de sanidade precisa acomodar isso sem virar um
        # cheque em branco.
        "max_context_length": 200_000,
        "variants": [
            {
                "expected_filename": "granite-4.1-3b-Q8_0.gguf",
                "block_count": 40,
                "size_min_key": "GRANITE_4_1_3B_SIZE_MIN",
                "size_max_key": "GRANITE_4_1_3B_SIZE_MAX",
                "hash_config_key": "GRANITE_4_1_3B_EXPECTED_HASH",
            },
            {
                # Benchmark do hackathon AMD (W7900 na nuvem, 2026-07-19) --
                # block_count/tamanho confirmados via read_gguf_metadata()
                # contra o arquivo real baixado do repo oficial ibm-granite.
                "expected_filename": "granite-4.1-30b-Q8_0.gguf",
                "block_count": 64,
                "size_min_key": "GRANITE_4_1_30B_SIZE_MIN",
                "size_max_key": "GRANITE_4_1_30B_SIZE_MAX",
                "hash_config_key": "GRANITE_4_1_30B_EXPECTED_HASH",
            },
        ],
    },
    "qwen35": {
        # Contexto nativo real é 262144 (config.json:
        # max_position_embeddings) -- maior que o do Granite, teto de
        # sanidade generoso o bastante sem virar cheque em branco.
        "max_context_length": 300_000,
        "variants": [
            {
                "expected_filename": "Qwen3.5-2B-Q6_K.gguf",
                # 24 camadas no total (6 full_attention + 18
                # linear_attention/Gated DeltaNet) -- block_count no GGUF
                # conta TODAS, não só as de atenção completa (confirmado
                # via gguf.GGUFReader real).
                "block_count": 24,
                "size_min_key": "QWEN35_2B_SIZE_MIN",
                "size_max_key": "QWEN35_2B_SIZE_MAX",
                "hash_config_key": "QWEN35_2B_EXPECTED_HASH",
            },
        ],
    },
    "llama": {
        # Contexto nativo do Llama 3.1 é 131072 (128K, GGUF llama.context_length
        # confirmado via gguf.GGUFReader real) -- teto de sanidade generoso o
        # bastante sem virar cheque em branco.
        "max_context_length": 150_000,
        "variants": [
            {
                "expected_filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
                "block_count": 32,
                "size_min_key": "LLAMA3_1_8B_SIZE_MIN",
                "size_max_key": "LLAMA3_1_8B_SIZE_MAX",
                "hash_config_key": "LLAMA3_1_8B_EXPECTED_HASH",
            },
        ],
    },
}


@dataclass
class GGUFHeader:
    magic: bytes
    version: int
    tensor_count: int
    kv_count: int
    architecture: str = ""
    context_length: int = 0
    embedding_length: int = 0
    block_count: int = 0

class GGUFSanitizer:
    def __init__(self, model_path: str | Path):
        self.path = Path(model_path)
        self.header: GGUFHeader | None = None
        self.is_uncataloged_variant: bool = False

    def _validate_or_generate_hash(self, profile: dict) -> bool:
        """
        Se o hash esperado (config.py, chave `profile['hash_config_key']`)
        estiver vazio/placeholder, calcula o hash e exibe para o usuário
        configurar -- mesmo mecanismo de antes, agora parametrizado pela
        arquitetura detectada em vez de uma única constante do Qwen.
        """
        import vte.config as config

        expected_hash = getattr(config, profile["hash_config_key"], None)
        calculated_hash = self._calculate_sha256()

        if not expected_hash or expected_hash == "sha256:PLACEHOLDER":
            logger.warning(
                f"PRIMEIRA EXECUÇÃO - Hash não configurado. Adicione no config.py: "
                f"{profile['hash_config_key']} = '{calculated_hash}'"
            )
            return True

        if calculated_hash != expected_hash:
            raise HIPSafetyError(
                f"Hash não corresponde!\n"
                f"Calculado: {calculated_hash}\n"
                f"Esperado:  {expected_hash}"
            )

        return True

    def _calculate_sha256(self) -> str:
        """Calcula o SHA-256 do arquivo em chunks de 8MB para não estourar a memória."""
        sha256_hash = hashlib.sha256()
        try:
            with open(self.path, "rb") as f:
                for byte_block in iter(lambda: f.read(8 * 1024 * 1024), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except IOError as e:
            raise HIPSafetyError(f"Falha ao ler arquivo para hash: {e}")

    def _read_string(self, f) -> str:
        length_bytes = f.read(8)
        if len(length_bytes) < 8:
            raise HIPSafetyError("EOF inesperado lendo string length")
        length = struct.unpack("<Q", length_bytes)[0]
        if length > 65536:
             raise HIPSafetyError(f"String excessivamente longa nos metadados: {length} bytes")
        str_bytes = f.read(length)
        if len(str_bytes) < length:
             raise HIPSafetyError("EOF inesperado lendo string data")
        return str_bytes.decode('utf-8', errors='replace')

    def _parse_kv_pairs(self, f, kv_count: int):
        for i in range(kv_count):
            key = self._read_string(f)

            vtype_bytes = f.read(4)
            if len(vtype_bytes) < 4:
                raise HIPSafetyError("EOF lendo value type")
            vtype = struct.unpack("<I", vtype_bytes)[0]

            # Chaves de hiperparâmetro são lidas pelo SUFIXO (".context_length",
            # ".embedding_length", ".block_count") em vez de um prefixo
            # "qwen2." fixo -- funciona para qualquer arquitetura (qwen2.*,
            # granite.*, etc.) sem precisar saber a arquitetura de antemão
            # (a ordem dos pares chave/valor no GGUF não é garantida, então
            # não dá pra depender de "general.architecture" já ter sido lido
            # antes destas chaves). Verificado contra os dois GGUFs reais do
            # projeto: nenhuma outra chave colide com esses sufixos.
            if key == "general.architecture":
                if vtype == 8:
                    self.header.architecture = self._read_string(f)
                else:
                    raise HIPSafetyError("general.architecture não é string")
            elif key.endswith(".context_length"):
                if vtype == 4:
                    self.header.context_length = struct.unpack("<I", f.read(4))[0]
                else:
                    self._skip_value(f, vtype)
            elif key.endswith(".embedding_length"):
                if vtype == 4:
                     self.header.embedding_length = struct.unpack("<I", f.read(4))[0]
                else:
                     self._skip_value(f, vtype)
            elif key.endswith(".block_count"):
                if vtype == 4:
                     self.header.block_count = struct.unpack("<I", f.read(4))[0]
                else:
                     self._skip_value(f, vtype)
            else:
                self._skip_value(f, vtype)

    def _skip_value(self, f, vtype: int):

        sizes = {0:1, 1:1, 2:2, 3:2, 4:4, 5:4, 6:4, 7:1, 10:8, 11:8, 12:8}
        if vtype in sizes:
            f.read(sizes[vtype])
        elif vtype == 8:
            self._read_string(f)
        elif vtype == 9:
             atype_bytes = f.read(4)
             alen_bytes = f.read(8)
             if len(atype_bytes) < 4 or len(alen_bytes) < 8:
                 raise HIPSafetyError("EOF lendo array metadata")
             atype = struct.unpack("<I", atype_bytes)[0]
             alen = struct.unpack("<Q", alen_bytes)[0]
             # 250_000 estourava de verdade no Llama 3.1 8B: seu
             # `tokenizer.ggml.merges` tem 280147 regras (vocabulário BPE de
             # 128k tokens, medido via gguf.GGUFReader real), bem acima do
             # teto anterior calibrado só contra Qwen2.5/Granite/Qwen3.5 (
             # vocabulários bem menores). Ainda um teto real, não um cheque
             # em branco -- só generoso o bastante pro maior array legítimo
             # já visto (merges), não pra qualquer array malformado.
             if alen > 500000:
                 raise HIPSafetyError(f"Array muito longo nos metadados: {alen} elementos")
             for _ in range(alen):
                 self._skip_value(f, atype)
        else:
             raise HIPSafetyError(f"Tipo de valor GGUF não suportado/conhecido: {vtype}")

    def _validate_metadata_consistency(self) -> dict:
        """Valida que os metadados são consistentes com o PERFIL da arquitetura
        detectada (`SUPPORTED_ARCHITECTURES`) e retorna a VARIANTE (tamanho de
        modelo) resolvida por `block_count` + faixa de tamanho de arquivo
        (não mais por nome de arquivo -- descoberta de modelos é dinâmica
        agora, ver `VTEModel.from_pretrained`: basta copiar um .gguf pra
        pasta Model/, sem editar código). A arquitetura em si (lida do
        próprio GGUF, `general.architecture`) continua sendo o gate DURO --
        arquitetura desconhecida é sempre rejeitada.

        `block_count` sozinho NÃO é suficiente pra desambiguar: o Qwen2.5
        1.5B e 7B têm o MESMO block_count (28) -- só o tamanho do arquivo
        distingue as duas variantes. Por isso checa as duas coisas juntas,
        na ordem das variantes cadastradas. Se nada bater (block_count
        novo, ou block_count conhecido mas tamanho fora de toda faixa
        catalogada), NÃO é rejeitado -- pode ser um tamanho novo, ainda não
        visto, da mesma arquitetura já suportada -- vira um aviso claro
        (log + status, ver `VTEModel.from_pretrained`) e usa limites de
        tamanho/hash genéricos em vez dos específicos de uma variante
        conhecida."""
        profile = SUPPORTED_ARCHITECTURES.get(self.header.architecture)
        if profile is None:
            supported = ", ".join(SUPPORTED_ARCHITECTURES.keys())
            raise HIPSafetyError(
                f"Arquitetura não suportada: '{self.header.architecture}'. "
                f"Suportadas: {supported}"
            )

        if self.header.context_length > profile["max_context_length"]:
            raise HIPSafetyError(f"context_length suspeito: {self.header.context_length}")

        import vte.config as config
        file_size = self.path.stat().st_size
        variant = None
        for v in profile["variants"]:
            if v["block_count"] != self.header.block_count:
                continue
            size_min = getattr(config, v["size_min_key"])
            size_max = getattr(config, v["size_max_key"])
            if size_min <= file_size <= size_max:
                variant = v
                break
        if variant is None:
            self.is_uncataloged_variant = True
            logger.warning(
                f"'{self.path.name}': arquitetura '{self.header.architecture}' suportada, mas "
                f"block_count={self.header.block_count} não corresponde a nenhuma variante "
                f"catalogada (tamanhos conhecidos: {[v['block_count'] for v in profile['variants']]}). "
                f"Carregando com validação de tamanho/hash genérica -- confirme que este é "
                f"realmente um GGUF válido dessa arquitetura antes de usar em produção."
            )
            return {
                "block_count": self.header.block_count,
                "size_min_key": None,
                "size_max_key": None,
                "hash_config_key": f"UNCATALOGED_{self.header.architecture.upper()}",
            }

        self.is_uncataloged_variant = False
        return variant

    def validate(self) -> bool:
        logger.info(f"Validando modelo: {self.path}")

        if not self.path.exists() or not self.path.is_file():
            raise HIPSafetyError("Modelo não encontrado")

        # Descoberta dinâmica (ver VTEModel.from_pretrained): sem whitelist
        # de nome de arquivo -- o gate de segurança real é a arquitetura
        # (`general.architecture`, lida do próprio GGUF em
        # `_validate_metadata_consistency`, sempre um HARD gate) mais os
        # limites estruturais já impostos abaixo (magic number, versão,
        # tensor_count/kv_count com teto) ANTES de qualquer valor do arquivo
        # ser usado pra dimensionar alocação.
        try:
            with open(self.path, "rb") as f:
                magic = f.read(4)
                if magic != b"GGUF":
                    raise HIPSafetyError("Magic number inválido (não é arquivo GGUF)")

                version = struct.unpack("<I", f.read(4))[0]
                if version != 3:
                    raise HIPSafetyError(f"Versão GGUF não suportada: {version}. Somente v3 permitida.")

                tensor_count = struct.unpack("<Q", f.read(8))[0]
                if tensor_count > 1000:
                    raise HIPSafetyError(f"Tensor count excessivo: {tensor_count}")

                kv_count = struct.unpack("<Q", f.read(8))[0]
                if kv_count > 100:
                     raise HIPSafetyError(f"KV count excessivo: {kv_count}")

                self.header = GGUFHeader(magic, version, tensor_count, kv_count)

                self._parse_kv_pairs(f, kv_count)
                variant = self._validate_metadata_consistency()

        except struct.error as e:
            raise HIPSafetyError(f"Erro de struct lendo GGUF: {e}")

        # Checagens que dependem de já saber a arquitetura/variante (tamanho,
        # hash) -- feitas DEPOIS do parse, usando a variante resolvida em
        # `_validate_metadata_consistency`. Variante não-catalogada (tamanho
        # novo dentro de uma arquitetura já suportada) usa limites de
        # tamanho genéricos (1MB-64GB, só descarta lixo/arquivo vazio) em
        # vez dos min/max específicos calibrados pra cada variante conhecida.
        import vte.config as config
        size = self.path.stat().st_size
        if variant["size_min_key"] is None:
            size_min, size_max = 1024 * 1024, 64 * 1024 * 1024 * 1024
        else:
            size_min = getattr(config, variant["size_min_key"])
            size_max = getattr(config, variant["size_max_key"])
        if size < size_min or size > size_max:
             raise HIPSafetyError(f"Tamanho fora do esperado: {size} bytes")

        self._validate_or_generate_hash(variant)

        logger.info("Validação do modelo concluída com sucesso.")
        return True
