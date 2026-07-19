"""
Descoberta automática da biblioteca do HIP runtime: amdhip64.dll no
Windows, libamdhip64.so no Linux. Escaneia caminhos padrão sem exigir
configuração manual.

O nome do arquivo (dll_discovery.py) é herança do suporte original,
Windows-only, deste projeto; mantido como está para não mexer em todo
import existente. A busca Linux abaixo é um acréscimo pontual (ver
docs/LIMITATIONS.md), não verificado ainda contra hardware real (nenhuma
droplet/VM Linux+ROCm disponível no momento em que isto foi escrito).
"""

import glob
import os
import sys
from pathlib import Path
from typing import Optional


def _find_amdhip64_in(directory: Path) -> Optional[Path]:
    """Acha a DLL do HIP runtime num diretório, sem assumir um sufixo de
    versão fixo: o instalador nomeia o arquivo `amdhip64_<major>.dll` (ex.
    `amdhip64_6.dll` no ROCm 6.x, `amdhip64_7.dll` no 7.x, confirmado real
    ao instalar o ROCm 7.1: só existe `amdhip64_7.dll`, sem alias sem
    versão), já que travar numa lista fixa de nomes quebra a cada bump de major
    version. Prefere `amdhip64.dll` (alias sem versão, quando existe) e
    cai para o primeiro `amdhip64_*.dll` encontrado, ordenado do mais novo
    pro mais antigo (maior número de versão primeiro).
    """
    if not directory.is_dir():
        return None
    unversioned = directory / "amdhip64.dll"
    if unversioned.exists():
        return unversioned
    candidates = sorted(directory.glob("amdhip64_*.dll"), reverse=True)
    return candidates[0] if candidates else None


def find_hip_dll() -> Optional[str]:
    """
    Busca amdhip64.dll (ou amdhip64_<versao>.dll) em caminhos padrão do Windows.

    Ordem de busca:
    1. Variável de ambiente HIP_PATH
    2. C:\\Program Files\\AMD\\HIP\\bin\\
    3. C:\\Program Files (x86)\\AMD\\HIP\\bin\\
    4. C:\\Program Files\\AMD\\ROCm\\<versao>\\bin\\ (versão mais nova primeiro)
    5. PATH do sistema

    Returns:
        Path completo para a DLL do HIP runtime ou None se não encontrado
    """
    if sys.platform != "win32":
        return None

    hip_path = os.environ.get("HIP_PATH")
    if hip_path:
        found = _find_amdhip64_in(Path(hip_path) / "bin")
        if found:
            return str(found)

    standard_paths = [
        r"C:\Program Files\AMD\HIP\bin",
        r"C:\Program Files (x86)\AMD\HIP\bin",
    ]

    for path in standard_paths:
        found = _find_amdhip64_in(Path(path))
        if found:
            return str(found)

    rocm_base = Path(r"C:\Program Files\AMD\ROCm")
    if rocm_base.exists():
        # Versões mais novas primeiro (ex. 7.1 antes de 6.4), caso mais de
        # uma esteja instalada lado a lado.
        version_dirs = sorted(
            (d for d in rocm_base.iterdir() if d.is_dir()),
            key=lambda d: d.name,
            reverse=True,
        )
        for version_dir in version_dirs:
            found = _find_amdhip64_in(version_dir / "bin")
            if found:
                return str(found)

    path_dirs = os.environ.get("PATH", "").split(";")
    for dir_path in path_dirs:
        found = _find_amdhip64_in(Path(dir_path))
        if found:
            return str(found)

    return None


def _find_libamdhip64_in(directory: Path) -> Optional[Path]:
    """Equivalente Linux de `_find_amdhip64_in`: bibliotecas compartilhadas
    versionadas no Linux seguem `libamdhip64.so.<major>.<minor>.<patch>`
    com um symlink `libamdhip64.so` apontando pra versão corrente. Esse
    symlink normalmente existe (é o padrão dos pacotes `.deb` oficiais da
    AMD), mas o fallback pro glob versionado cobre o caso de faltar, mesma
    postura defensiva do lado Windows acima."""
    if not directory.is_dir():
        return None
    unversioned = directory / "libamdhip64.so"
    if unversioned.exists():
        return unversioned
    candidates = sorted(directory.glob("libamdhip64.so.*"), reverse=True)
    return candidates[0] if candidates else None


def find_hip_so() -> Optional[str]:
    """
    Busca libamdhip64.so em caminhos padrão de uma instalação ROCm no Linux.

    NÃO verificado contra hardware real (nenhuma máquina Linux+ROCm
    disponível): os caminhos abaixo vêm da convenção documentada dos
    pacotes ROCm oficiais da AMD (`/opt/rocm-<versão>/`, symlink `/opt/rocm`
    pra versão corrente), não de teste direto. Ver docs/LIMITATIONS.md.

    Ordem de busca:
    1. Nome puro via `ctypes.CDLL("libamdhip64.so")` (deixa o linker do
       sistema resolver, funciona de graça se ROCM_PATH/LD_LIBRARY_PATH ou
       o cache do ldconfig já estiverem configurados, ex.: dentro da
       imagem Docker oficial da AMD).
    2. Variável de ambiente ROCM_PATH
    3. Variável de ambiente HIP_PATH
    4. /opt/rocm/lib e /opt/rocm/lib64 (symlink pra versão corrente)
    5. /opt/rocm-<versão>/lib(64) (versão mais nova primeiro, glob direto,
       caso o symlink acima não exista)
    6. LD_LIBRARY_PATH

    Returns:
        Caminho (ou nome puro, no caso 1) pronto para `ctypes.CDLL()`, ou
        None se não encontrado.
    """
    if sys.platform == "win32":
        return None

    bare_name = "libamdhip64.so"

    rocm_path = os.environ.get("ROCM_PATH")
    if rocm_path:
        for sub in ("lib", "lib64"):
            found = _find_libamdhip64_in(Path(rocm_path) / sub)
            if found:
                return str(found)

    hip_path = os.environ.get("HIP_PATH")
    if hip_path:
        for sub in ("lib", "lib64"):
            found = _find_libamdhip64_in(Path(hip_path) / sub)
            if found:
                return str(found)

    for sub in ("lib", "lib64"):
        found = _find_libamdhip64_in(Path("/opt/rocm") / sub)
        if found:
            return str(found)

    # Diretórios de versão mais nova primeiro (ex. /opt/rocm-7.14.0 antes de
    # /opt/rocm-6.4.0), caso mais de uma esteja instalada lado a lado ou o
    # symlink /opt/rocm não exista por algum motivo.
    version_dirs = sorted(glob.glob("/opt/rocm-*"), reverse=True)
    for version_dir in version_dirs:
        for sub in ("lib", "lib64"):
            found = _find_libamdhip64_in(Path(version_dir) / sub)
            if found:
                return str(found)

    for dir_path in os.environ.get("LD_LIBRARY_PATH", "").split(":"):
        if dir_path:
            found = _find_libamdhip64_in(Path(dir_path))
            if found:
                return str(found)

    # Último recurso: nome puro, deixa ctypes/o linker do sistema resolver.
    # Só chega aqui se nada acima bateu (os casos comuns já retornaram um
    # caminho explícito acima), mas ainda vale tentar antes de desistir.
    return bare_name


def find_hip_library() -> Optional[str]:
    """Dispatcher por plataforma: `find_hip_dll()` no Windows,
    `find_hip_so()` no Linux, `None` em qualquer outra. Ponto de entrada
    único que `hip_runtime.py` usa; ver docstring do módulo."""
    if sys.platform == "win32":
        return find_hip_dll()
    if sys.platform.startswith("linux"):
        return find_hip_so()
    return None


def validate_hip_installation() -> tuple[bool, str]:
    """
    Valida que o AMD HIP SDK está instalado corretamente.
    
    Returns:
        (success, message)
    """
    dll_path = find_hip_library()

    if dll_path is None:
        if sys.platform == "win32":
            return False, (
                "AMD HIP SDK não encontrado!\n\n"
                "Instale o HIP SDK:\n"
                "1. Baixe em: https://www.amd.com/en/developer/resources/rocm-hub/hip-sdk.html\n"
                "2. Instale e reinicie o terminal\n"
                "3. Verifique que a variável HIP_PATH está definida"
            )
        return False, (
            "libamdhip64.so não encontrada!\n\n"
            "Instale o ROCm:\n"
            "1. Siga https://rocm.docs.amd.com/en/latest/\n"
            "2. Verifique que ROCM_PATH aponta pro diretório de instalação"
        )

    import subprocess
    import shutil

    # hipcc.bat/hipcc.exe só existem no Windows; no Linux, `hipcc` já
    # resolve sozinho via PATH se a instalação ROCm estiver configurada.
    if sys.platform == "win32" and (not shutil.which("hipcc") or not shutil.which("hipcc.bat")):
        bin_dir = Path(dll_path).parent
        hipcc_bat = bin_dir / "hipcc.bat"
        hipcc_exe = bin_dir / "hipcc.exe"
        if hipcc_bat.exists() or hipcc_exe.exists():
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    try:
        result = subprocess.run(
            ["hipcc", "--version"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        if result.returncode != 0:
            return False, "hipcc encontrado, mas retornou erro ao checar versão."
    except FileNotFoundError:
        return False, f"hipcc não encontrado. A DLL está em {dll_path}, mas o compilador está ausente."
    
    return True, f"HIP SDK encontrado: {dll_path}"
