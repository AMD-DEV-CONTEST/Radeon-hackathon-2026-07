import re
import os
import hashlib
import subprocess
import shutil
from pathlib import Path
from vte.bridge.errors import HIPSafetyError
from vte.bridge.logger import get_logger

logger = get_logger(__name__)

def _sanitize_var(value: any) -> str:
    """Garante que apenas números e strings alfanuméricas entrem no template C++"""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):

        safe_str = re.sub(r'[^a-zA-Z0-9_]', '', value)
        if safe_str != value:
            raise HIPSafetyError(f"Variável de template insegura bloqueada: {value}")
        return safe_str
    raise HIPSafetyError(f"Tipo de variável não suportado no Codegen: {type(value)}")

def _sanitize_mega_kernel_params(params: dict) -> dict:
    """Sanitização relaxada para mega-kernels (controlada)"""
    ALLOWED_TYPES = (int, float, str, list, tuple, dict)
    ALLOWED_LIST_TYPES = (int, float)
    sanitized = {}
    
    for key, value in params.items():
        if isinstance(value, ALLOWED_TYPES):
            if isinstance(value, (list, tuple)):
                if not all(isinstance(x, ALLOWED_LIST_TYPES) for x in value):
                    raise HIPSafetyError(f"Lista inválida em mega-kernel param {key}: {value}")
                sanitized[key] = value
            elif isinstance(value, str):
                safe_str = re.sub(r'[^a-zA-Z0-9_]', '', value)
                if safe_str != value:
                    raise HIPSafetyError(f"String insegura em mega-kernel param {key}: {value}")
                sanitized[key] = safe_str
            else:
                sanitized[key] = value
        else:
            raise HIPSafetyError(f"Tipo não permitido em mega-kernel: {type(value)}")
    return sanitized

def get_kernel_cache_path(cpp_code: str, arch: str) -> str:
    """Retorna o caminho do cache (.hsaco) baseado no hash do código renderizado"""
    code_hash = hashlib.sha256(cpp_code.encode('utf-8')).hexdigest()[:16]
    return f"cache/kernels/{arch}/kernel_{code_hash}.hsaco"

class CodegenEngine:
    def __init__(self):
        # templates/ é separado por família de arquitetura (rdna/, cdna/):
        # todo template hoje é RDNA2/RDNA3 (wave32), então isto resolve pra
        # rdna/ diretamente. cdna/ existe como destino pros kernels wave64
        # de uma futura investigação em CDNA (MI300X e afins), ainda sem
        # nenhum template lá.
        self.templates_dir = Path(__file__).parent / "templates" / "rdna"
        self.logs_dir = Path("logs/Codegen")
        self.cache_dir = Path("cache/kernels")
        # Binários AOT congelados com o projeto (Fase 2, ver
        # scripts/build_kernel_cache.py) -- semeia o cache local a partir
        # daqui antes de precisar do hipcc, ver `compile_kernel()`.
        self.assets_dir = Path(__file__).parent.parent / "core" / "assets" / "kernels"

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def render_template(self, template_name: str, **kwargs) -> str:
        """Lê um template e substitui as variáveis seguras."""
        template_path = self.templates_dir / f"{template_name}.hip.template"
        
        if not template_path.exists():

            logger.warning(f"Template não encontrado no disco: {template_path}")
            return ""
            
        with open(template_path, "r", encoding="utf-8") as f:
            template_code = f.read()
            
        is_mega_kernel = kwargs.pop("is_mega_kernel", False)
        
        rendered_code = template_code
        if is_mega_kernel:
            safe_kwargs = _sanitize_mega_kernel_params(kwargs)
            for k, v in safe_kwargs.items():

                if isinstance(v, (list, tuple)):
                    v = "{" + ", ".join(map(str, v)) + "}"
                rendered_code = rendered_code.replace(f"{{{{ {k} }}}}", str(v))
        else:
            for k, v in kwargs.items():
                safe_val = _sanitize_var(v)
                rendered_code = rendered_code.replace(f"{{{{ {k} }}}}", safe_val)
                
        return rendered_code
        
    def _parse_vgpr_usage(self, compiler_output: str) -> int:
        """Extrai VGPR usage do output do hipcc para detectar Register Spilling"""

        match = re.search(r'vgpr_count:\s*(\d+)', compiler_output, re.IGNORECASE)
        if not match:
            match = re.search(r'VGPRs:\s*(\d+)', compiler_output, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return -1
        
    def _setup_hip_env(self) -> dict:
        """Prepara variáveis de ambiente para o hipcc funcionar no Windows com MSVC."""
        import glob
        env = os.environ.copy()

        rocm_bin = None
        hip_root = env.get("HIP_PATH") or env.get("ROCM_PATH")
        if hip_root and (Path(hip_root) / "bin" / "hipcc.exe").exists():
            rocm_bin = str(Path(hip_root) / "bin")
        else:
            default_roots = sorted(glob.glob(r"C:\Program Files\AMD\ROCm\*\bin"), reverse=True)
            if default_roots:
                rocm_bin = default_roots[0]

        if rocm_bin and rocm_bin not in env.get("PATH", ""):
            env["PATH"] = rocm_bin + os.pathsep + env.get("PATH", "")
        
        vs_roots = glob.glob(r"C:\Program Files (x86)\Microsoft Visual Studio\*\BuildTools\VC\Tools\MSVC\*\include")
        ucrt_roots = glob.glob(r"C:\Program Files (x86)\Windows Kits\10\Include\*\ucrt")
        um_roots   = glob.glob(r"C:\Program Files (x86)\Windows Kits\10\Include\*\um")
        shared_roots = glob.glob(r"C:\Program Files (x86)\Windows Kits\10\Include\*\shared")
        
        extra_includes = []
        if vs_roots:     extra_includes.append(sorted(vs_roots)[-1])
        if ucrt_roots:   extra_includes.append(sorted(ucrt_roots)[-1])
        if um_roots:     extra_includes.append(sorted(um_roots)[-1])
        if shared_roots: extra_includes.append(sorted(shared_roots)[-1])
        
        if extra_includes:
            env["INCLUDE"] = os.pathsep.join(extra_includes) + os.pathsep + env.get("INCLUDE", "")
            logger.debug(f"MSVC/SDK includes injetados: {extra_includes}")
        else:
            logger.warning("Headers MSVC/SDK não encontrados. hipcc pode falhar com 'cmath not found'.")
        
        return env

    def compile_kernel(self, template_name: str, arch: str, force_recompile: bool = False, **kwargs) -> str:
        """Renderiza e compila o kernel via hipcc.

        `force_recompile=True` ignora um `.hsaco` já existente no cache e
        força uma recompilação de verdade -- usado por `load_kernel_safe()`
        quando um binário PRÉ-COMPILADO distribuído com o projeto (AOT, ver
        docs/BUGS.md) falha ao carregar por incompatibilidade de driver/ABI
        do ROCm local: sem isto, recompilar encontraria o MESMO arquivo
        corrompido/incompatível no cache e devolveria o mesmo caminho
        quebrado de novo."""
        cpp_code = self.render_template(template_name, **kwargs)
        if not cpp_code:
            cpp_code = kwargs.get("mock_code", "")
            if not cpp_code:
                 cpp_code = str(kwargs)

        cache_path = get_kernel_cache_path(cpp_code, arch)

        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)

        code_hash = hashlib.sha256(cpp_code.encode('utf-8')).hexdigest()[:16]
        log_file = self.logs_dir / f"{template_name}_{code_hash}.hip"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(cpp_code)

        if not force_recompile and Path(cache_path).exists():
            logger.debug(f"Cache hit: {cache_path}")
            return cache_path

        # Semeadura AOT (Fase 2): antes de chamar hipcc, checa se já existe
        # um binário PRÉ-COMPILADO congelado com o projeto (mesmo hash de
        # código renderizado -- ou seja, exatamente este template com estes
        # kwargs, pra esta arch). Se existir, copia pro cache local e usa
        # direto -- hipcc/MSVC Build Tools nunca são chamados pro caso comum
        # (arquitetura já coberta pelo build_kernel_cache.py). Pulado
        # quando `force_recompile=True`: nesse caso o binário do cache (que
        # pode ser exatamente essa mesma semente) já falhou ao carregar, ver
        # `load_kernel_safe()` -- copiar de novo devolveria o mesmo binário
        # incompatível.
        if not force_recompile:
            asset_path = self.assets_dir / arch / Path(cache_path).name
            if asset_path.exists():
                shutil.copy2(asset_path, cache_path)
                logger.debug(f"Semeado do AOT empacotado: {asset_path} -> {cache_path}")
                return cache_path

        env = self._setup_hip_env()

        if not shutil.which("hipcc", path=env.get("PATH")):
            if force_recompile:
                # Binário AOT pré-compilado falhou ao carregar (driver/ABI do
                # ROCm local incompatível) E não há hipcc disponível pra
                # recompilar sob medida -- NUNCA sobrescreve com um mock aqui
                # (faria o kernel "funcionar" silenciosamente com um .hsaco
                # inútil, escondendo o problema real até o próximo load
                # falhar de um jeito mais confuso). Falha alto e claro.
                raise HIPSafetyError(
                    f"O kernel pré-compilado para '{template_name}' ({arch}) não carregou "
                    f"(driver/ROCm local incompatível com o binário distribuído) e não há "
                    f"hipcc no PATH pra recompilar. Instale o HIP SDK + MSVC Build Tools "
                    f"para compilar este kernel localmente."
                )
            logger.warning(f"hipcc não encontrado no PATH. Simulando compilaão de {cache_path}")
            with open(cache_path, "wb") as f:
                f.write(b"MOCK_HSACO")
            return cache_path

        if force_recompile and Path(cache_path).exists():
            try:
                Path(cache_path).unlink()
            except OSError:
                pass

        cmd = [
            "hipcc",
            "--genco",
            f"--offload-arch={arch}",
            "-O3",
            str(log_file),
            "-o",
            cache_path
        ]
        
        logger.info(f"Compilando kernel {template_name} para {arch}...")
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
            logger.info(f"Kernel compilado: {cache_path}")
            
            vgpr_usage = self._parse_vgpr_usage(result.stderr + result.stdout)
            if vgpr_usage > 128:
                logger.error(f"Kernel {template_name} usa {vgpr_usage} VGPRs (limite: 128). Register spilling detectado.")
                raise HIPSafetyError(f"VGPR usage excedeu o limite seguro (128): {vgpr_usage}")
                
        except subprocess.CalledProcessError as e:
            raise HIPSafetyError(f"Falha na compilação do kernel {template_name}:\n{e.stderr}")

        return cache_path

    def compile_source_for_arch(self, cpp_code: str, arch: str, label: str = "unknown") -> str:
        """
        Compila um código-fonte JÁ RENDERIZADO pra uma arquitetura, sem
        passar por `render_template()` de novo -- usado por
        `scripts/cross_compile_kernel_cache.py` pra gerar binários AOT de
        arquiteturas RDNA3 irmãs (gfx1100/gfx1101) a partir dos `.hip` já
        renderizados durante o warm-up real em gfx1102 (ver
        `scripts/build_kernel_cache.py`), sem precisar re-executar nenhum
        modelo. Mesmo hash de cache que `compile_kernel()` usaria pro MESMO
        código-fonte (`get_kernel_cache_path` não depende de template_name,
        só do conteúdo) -- então o resultado cai no mesmo lugar que
        `compile_kernel()` encontraria via `Path(cache_path).exists()`.

        IMPORTANTE: isto compila OFFLINE pra uma arquitetura que não é a
        deste processo -- hipcc aceita (`--offload-arch` é um alvo, não
        depende da GPU local), mas o binário resultante nunca é
        carregado/executado aqui (não tem como: esta máquina não tem essa
        GPU). "Compilou sem erro" não é o mesmo que "está correto" -- ver
        docs/LIMITATIONS.md."""
        cache_path = get_kernel_cache_path(cpp_code, arch)
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        if Path(cache_path).exists():
            return cache_path

        env = self._setup_hip_env()
        if not shutil.which("hipcc", path=env.get("PATH")):
            raise HIPSafetyError("hipcc não encontrado no PATH -- necessário para cross-compilação AOT.")

        code_hash = hashlib.sha256(cpp_code.encode('utf-8')).hexdigest()[:16]
        log_file = self.logs_dir / f"{label}_{code_hash}.hip"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(cpp_code)

        cmd = ["hipcc", "--genco", f"--offload-arch={arch}", "-O3", str(log_file), "-o", cache_path]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        except subprocess.CalledProcessError as e:
            raise HIPSafetyError(f"Falha na cross-compilação de '{label}' para {arch}:\n{e.stderr}")
        return cache_path

    def load_kernel_safe(self, hip, template_name: str, arch: str, kernel_name: str, **kwargs):
        """
        `compile_kernel()` + `hip.load_kernel()` num só passo, com fallback
        automático se o `.hsaco` resolvido (seja do cache local, seja um
        binário AOT pré-compilado distribuído com o projeto -- ver
        docs/BUGS.md) falhar ao carregar no driver local.

        `hipModuleLoad` pode falhar por incompatibilidade de ABI do Code
        Object do ROCm (driver atualizado, versão de ROCm diferente da que
        gerou o binário) -- um `.hsaco` pré-compilado é só um arquivo de
        bytes até ser testado no driver de verdade, não tem como saber de
        antemão se vai carregar. Em vez de tentar adivinhar códigos de erro
        específicos (frágil -- a ABI de erro do HIP muda entre versões do
        SDK), a política aqui é: qualquer falha em `hip.load_kernel()`
        aciona UMA tentativa de recompilação forçada (`force_recompile=True`,
        descarta o binário ruim) via `hipcc` local, e tenta carregar de novo.
        Se a segunda tentativa também falhar, o erro é real (não é
        incompatibilidade de binário) e sobe normalmente.
        """
        hsaco_path = self.compile_kernel(template_name=template_name, arch=arch, **kwargs)
        try:
            return hip.load_kernel(hsaco_path, kernel_name)
        except Exception as e:
            logger.warning(
                f"Falha ao carregar '{hsaco_path}' ({e}) -- possível binário pré-compilado "
                f"incompatível com o driver/ROCm local. Descartando e recompilando com hipcc..."
            )
            hsaco_path = self.compile_kernel(template_name=template_name, arch=arch, force_recompile=True, **kwargs)
            return hip.load_kernel(hsaco_path, kernel_name)
