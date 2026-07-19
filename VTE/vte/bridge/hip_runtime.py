import ctypes
import os
import ctypes.util
import subprocess
import sys
import time
import collections
from pathlib import Path
from typing import Optional, Any, Union

from .errors import HIPSafetyError, HIPRuntimeError

class MemoryGuardianOOMError(HIPSafetyError):
    """Exceção específica interceptada pelo Slab Allocator para fallback de RAM."""
    pass

from .logger import get_logger

logger = get_logger(__name__)

from vte.config import VRAM_USAGE_LIMIT
from vte.config import DEFAULT_GPU_ARCH, GPU_ARCH_MAP, CACHE_DIR, MAX_GRID_DIMENSIONS

from enum import IntEnum
from dataclasses import dataclass

class HIPError(IntEnum):
    success = 0
    invalidValue = 1
    outOfMemory = 2
    notInitialized = 3
    invalidDevice = 100
    noDevice = 101
    fileNotFound = 301
    unknown = 999

class HIPMemcpyKind(IntEnum):
    HostToHost = 0
    HostToDevice = 1
    DeviceToHost = 2
    DeviceToDevice = 3

@dataclass
class HIPDeviceProperties:
    name: str
    total_global_mem: int
    shared_mem_per_block: int
    max_threads_per_block: int
    warp_size: int
    multi_processor_count: int
    compute_capability: str
    gcn_arch_name: str = "gfx1100"
    
    def validate_for_vte(self) -> tuple[bool, str]:
        from vte.config import MIN_VRAM_REQUIRED
        if self.total_global_mem < MIN_VRAM_REQUIRED:
            return False, f"VRAM insuficiente: {self.total_global_mem} < {MIN_VRAM_REQUIRED}"
        if self.warp_size not in (32, 64):
            return False, f"Warp size não suportado: {self.warp_size}"
        return True, "GPU validada"

class hipUUID(ctypes.Structure):
    """16-byte device UUID (`hipUUID_t` em hip_runtime_api.h)."""
    _fields_ = [("bytes", ctypes.c_char * 16)]


class hipDeviceArch_t(ctypes.Structure):
    """Bitfield de 18 flags de 1 bit (`hasGlobalInt32Atomics`, `hasDoubles`,
    etc., ver hip_runtime_api.h), empacotado num único uint32 pelo ABI padrão
    x86_64. VTE não lê nenhuma dessas flags individualmente -- representado
    como um bloco opaco só para reservar o tamanho certo no fim da struct."""
    _fields_ = [("_bits", ctypes.c_uint32)]


class hipDeviceProp_t(ctypes.Structure):
    """
    Definição completa de hipDeviceProp_t, campo a campo, extraída direto de
    /opt/rocm/include/hip/hip_runtime_api.h (ROCm 7.2.1, validada ao vivo
    contra hardware real -- W7900/gfx1100 na nuvem e RX 7600/gfx1102 local,
    ver docs/BUGS.md).

    ATENÇÃO -- ROCm exporta 3 símbolos versionados diferentes pra essa
    função (`nm -D libamdhip64.so`): hipGetDeviceProperties@@hip_4.2 (ABI
    ANTIGA, pré uuid/luid/gcnArchName), hipGetDevicePropertiesR0000@@hip_4.2
    (idêntico) e hipGetDevicePropertiesR0600@@hip_6.0 (ABI ATUAL, é esta
    struct). ctypes resolve `lib.hipGetDeviceProperties` pelo nome NU, que
    bate no símbolo ANTIGO -- por isso o código deve sempre chamar
    `hipGetDevicePropertiesR0600` explicitamente (ver _map_hip_functions),
    nunca o nome sem sufixo. Chamar a versão antiga com ESTA struct (ou
    vice-versa) desalinha todo campo depois de `name` -- foi exatamente
    esse mismatch que fazia `multiProcessorCount` retornar lixo (38911 numa
    GPU com 32 CUs reais) antes desta correção; `total_global_mem`/
    `warp_size` pareciam corretos por coincidência de offset, não porque a
    struct antiga estivesse certa.
    """
    _fields_ = [
        ("name",                                     ctypes.c_char * 256),
        ("uuid",                                      hipUUID),
        ("luid",                                      ctypes.c_char * 8),
        ("luidDeviceNodeMask",                        ctypes.c_uint),
        ("totalGlobalMem",                             ctypes.c_size_t),
        ("sharedMemPerBlock",                          ctypes.c_size_t),
        ("regsPerBlock",                               ctypes.c_int),
        ("warpSize",                                   ctypes.c_int),
        ("memPitch",                                   ctypes.c_size_t),
        ("maxThreadsPerBlock",                         ctypes.c_int),
        ("maxThreadsDim",                              ctypes.c_int * 3),
        ("maxGridSize",                                ctypes.c_int * 3),
        ("clockRate",                                  ctypes.c_int),
        ("totalConstMem",                              ctypes.c_size_t),
        ("major",                                      ctypes.c_int),
        ("minor",                                      ctypes.c_int),
        ("textureAlignment",                           ctypes.c_size_t),
        ("texturePitchAlignment",                      ctypes.c_size_t),
        ("deviceOverlap",                              ctypes.c_int),
        ("multiProcessorCount",                        ctypes.c_int),
        ("kernelExecTimeoutEnabled",                   ctypes.c_int),
        ("integrated",                                 ctypes.c_int),
        ("canMapHostMemory",                           ctypes.c_int),
        ("computeMode",                                ctypes.c_int),
        ("maxTexture1D",                               ctypes.c_int),
        ("maxTexture1DMipmap",                         ctypes.c_int),
        ("maxTexture1DLinear",                         ctypes.c_int),
        ("maxTexture2D",                               ctypes.c_int * 2),
        ("maxTexture2DMipmap",                         ctypes.c_int * 2),
        ("maxTexture2DLinear",                         ctypes.c_int * 3),
        ("maxTexture2DGather",                         ctypes.c_int * 2),
        ("maxTexture3D",                               ctypes.c_int * 3),
        ("maxTexture3DAlt",                            ctypes.c_int * 3),
        ("maxTextureCubemap",                          ctypes.c_int),
        ("maxTexture1DLayered",                        ctypes.c_int * 2),
        ("maxTexture2DLayered",                        ctypes.c_int * 3),
        ("maxTextureCubemapLayered",                   ctypes.c_int * 2),
        ("maxSurface1D",                               ctypes.c_int),
        ("maxSurface2D",                               ctypes.c_int * 2),
        ("maxSurface3D",                               ctypes.c_int * 3),
        ("maxSurface1DLayered",                        ctypes.c_int * 2),
        ("maxSurface2DLayered",                        ctypes.c_int * 3),
        ("maxSurfaceCubemap",                          ctypes.c_int),
        ("maxSurfaceCubemapLayered",                   ctypes.c_int * 2),
        ("surfaceAlignment",                           ctypes.c_size_t),
        ("concurrentKernels",                          ctypes.c_int),
        ("ECCEnabled",                                 ctypes.c_int),
        ("pciBusID",                                   ctypes.c_int),
        ("pciDeviceID",                                ctypes.c_int),
        ("pciDomainID",                                ctypes.c_int),
        ("tccDriver",                                  ctypes.c_int),
        ("asyncEngineCount",                           ctypes.c_int),
        ("unifiedAddressing",                          ctypes.c_int),
        ("memoryClockRate",                            ctypes.c_int),
        ("memoryBusWidth",                             ctypes.c_int),
        ("l2CacheSize",                                ctypes.c_int),
        ("persistingL2CacheMaxSize",                   ctypes.c_int),
        ("maxThreadsPerMultiProcessor",                ctypes.c_int),
        ("streamPrioritiesSupported",                  ctypes.c_int),
        ("globalL1CacheSupported",                     ctypes.c_int),
        ("localL1CacheSupported",                      ctypes.c_int),
        ("sharedMemPerMultiprocessor",                 ctypes.c_size_t),
        ("regsPerMultiprocessor",                      ctypes.c_int),
        ("managedMemory",                              ctypes.c_int),
        ("isMultiGpuBoard",                            ctypes.c_int),
        ("multiGpuBoardGroupID",                       ctypes.c_int),
        ("hostNativeAtomicSupported",                  ctypes.c_int),
        ("singleToDoublePrecisionPerfRatio",           ctypes.c_int),
        ("pageableMemoryAccess",                       ctypes.c_int),
        ("concurrentManagedAccess",                    ctypes.c_int),
        ("computePreemptionSupported",                 ctypes.c_int),
        ("canUseHostPointerForRegisteredMem",          ctypes.c_int),
        ("cooperativeLaunch",                          ctypes.c_int),
        ("cooperativeMultiDeviceLaunch",               ctypes.c_int),
        ("sharedMemPerBlockOptin",                     ctypes.c_size_t),
        ("pageableMemoryAccessUsesHostPageTables",     ctypes.c_int),
        ("directManagedMemAccessFromHost",             ctypes.c_int),
        ("maxBlocksPerMultiProcessor",                 ctypes.c_int),
        ("accessPolicyMaxWindowSize",                  ctypes.c_int),
        ("reservedSharedMemPerBlock",                  ctypes.c_size_t),
        ("hostRegisterSupported",                      ctypes.c_int),
        ("sparseHipArraySupported",                    ctypes.c_int),
        ("hostRegisterReadOnlySupported",              ctypes.c_int),
        ("timelineSemaphoreInteropSupported",          ctypes.c_int),
        ("memoryPoolsSupported",                       ctypes.c_int),
        ("gpuDirectRDMASupported",                     ctypes.c_int),
        ("gpuDirectRDMAFlushWritesOptions",            ctypes.c_uint),
        ("gpuDirectRDMAWritesOrdering",                ctypes.c_int),
        ("memoryPoolSupportedHandleTypes",             ctypes.c_uint),
        ("deferredMappingHipArraySupported",           ctypes.c_int),
        ("ipcEventSupported",                          ctypes.c_int),
        ("clusterLaunch",                              ctypes.c_int),
        ("unifiedFunctionPointers",                    ctypes.c_int),
        ("reserved",                                   ctypes.c_int * 63),
        ("hipReserved",                                ctypes.c_int * 32),
        # -- campos exclusivos do HIP (não existem no CUDA), a partir daqui --
        ("gcnArchName",                                ctypes.c_char * 256),
        ("maxSharedMemoryPerMultiProcessor",           ctypes.c_size_t),
        ("clockInstructionRate",                       ctypes.c_int),
        ("arch",                                        hipDeviceArch_t),
        ("hdpMemFlushCntl",                            ctypes.c_void_p),
        ("hdpRegFlushCntl",                            ctypes.c_void_p),
        ("cooperativeMultiDeviceUnmatchedFunc",        ctypes.c_int),
        ("cooperativeMultiDeviceUnmatchedGridDim",     ctypes.c_int),
        ("cooperativeMultiDeviceUnmatchedBlockDim",    ctypes.c_int),
        ("cooperativeMultiDeviceUnmatchedSharedMem",   ctypes.c_int),
        ("isLargeBar",                                 ctypes.c_int),
        ("asicRevision",                               ctypes.c_int),
    ]

hipMemcpyHostToDevice = 1
hipMemcpyDeviceToHost = 2

HIP_STREAM_CAPTURE_MODE_GLOBAL = 0
HIP_STREAM_CAPTURE_MODE_THREAD_LOCAL = 1
HIP_STREAM_CAPTURE_MODE_RELAXED = 2

class HIPRuntime:
    """Wrapper nativo para a dll do HIP SDK com barreiras de segurança."""

    # Estado de PROCESSO (não por instância) -- ver `safe_malloc`/`cleanup`.
    # Bug real encontrado na Fase 5 (dois modelos/HIPRuntime coexistindo no
    # mesmo processo, draft + alvo): (1) o teto de 95% de VRAM
    # (`VRAM_USAGE_LIMIT`) somava só `self._active_allocations` -- cada
    # instância de HIPRuntime achava que tinha os 95% inteiros pra si,
    # ignorando o que a OUTRA instância já tinha alocado no mesmo contexto
    # HIP/GPU física; (2) `cleanup()` chama `hipDeviceReset()`
    # incondicionalmente, que reseta o contexto HIP INTEIRO -- ao descarregar
    # um modelo (ex.: o draft) com o alvo ainda carregado, o reset destruía
    # também as alocações do alvo, causando os `hipFree retornou código 1`
    # observados ao descarregar o segundo modelo em testes com dois modelos.
    # Corrigido com dois contadores de CLASSE (compartilhados por todas as
    # instâncias no processo): `_process_wide_allocated_bytes` (soma real de
    # bytes vivos, usada na checagem de 95%) e `_live_instance_count` (só
    # chama hipDeviceReset quando a ÚLTIMA instância do processo faz cleanup).
    _process_wide_allocated_bytes: int = 0
    _live_instance_count: int = 0

    def __init__(self, library_path: Optional[str] = None):
        """Inicializa o runtime localizando a amdhip64.dll e mapeando funções."""
        self._lib: Optional[ctypes.CDLL] = None
        self._initialized: bool = False
        self._active_allocations: dict[int, tuple[int, str]] = {}
        self._in_cleanup_mode: bool = False
        self._prevent_host_copies: bool = True
        self._vram_total: int = 0
        # 32 = fallback pré-detecção (mesmo valor da RX 7600, referência
        # histórica de calibração) -- initialize() sobrescreve com o valor
        # REAL da GPU antes de qualquer kernel ser dimensionado.
        self._num_cus: int = 32
        self._stream: ctypes.c_void_p = ctypes.c_void_p(0)
        # Índice do device HIP selecionado em initialize() (default 0 até lá).
        # Numa máquina com mais de uma GPU AMD visível (ex.: dGPU RDNA3 +
        # iGPU), NÃO é seguro assumir que o device 0 do driver é a discreta --
        # a ordem de enumeração do HIP não é garantida pelo runtime. Ver
        # _select_device_index().
        self._device_index: int = 0
        self.watchdog = None
        self.gpu_utilization_guard = None
        self._counted_as_live = False

        # Limitador de duty cycle: complementa o GPUUtilizationGuard (que só
        # DETECTA uso sustentado alto via contador do Windows, com atraso de
        # segundos por causa do overhead de subprocess). Este mecanismo age
        # de forma preventiva a cada synchronize(): mede a fração de tempo
        # recente em que a GPU esteve ocupada com nosso trabalho e insere uma
        # pequena pausa se ultrapassar o limite, achatando o pico antes dele
        # se formar — em vez de só reagir depois que já aconteceu.
        self._duty_cycle_window: "collections.deque[tuple[float, float]]" = collections.deque()
        self._duty_cycle_window_seconds = 2.0
        self._duty_cycle_limit = 0.95
        self._duty_cycle_max_sleep = 0.25
        
        if library_path is None:
            from .dll_discovery import find_hip_library
            library_path = find_hip_library()
            if library_path is None:
                if sys.platform == "win32":
                    raise HIPRuntimeError(
                        "amdhip64.dll não encontrada. Instale o AMD HIP SDK:\n"
                        "https://www.amd.com/en/developer/resources/rocm-hub/hip-sdk.html"
                    )
                raise HIPRuntimeError(
                    "libamdhip64.so não encontrada. Instale o ROCm e confirme "
                    "que ROCM_PATH aponta pro diretório de instalação:\n"
                    "https://rocm.docs.amd.com/en/latest/"
                )

        path_to_load = library_path
        try:
            self._lib = ctypes.CDLL(path_to_load)
            logger.info(f"Biblioteca do HIP runtime carregada de {path_to_load}")
            # A biblioteca pode estar fora do PATH/LD_LIBRARY_PATH global (ex.:
            # local customizado do HIP SDK/ROCm), então injeta a pasta aqui pra
            # que subprocessos deste processo (hipcc, via codegen.py) a
            # encontrem mesmo sem configuração manual de ambiente.
            # codegen.py::_setup_hip_env já faz sua própria busca (HIP_PATH/
            # ROCM_PATH), mas isso não ajuda chamadas fora daquele caminho
            # específico.
            bin_dir = str(Path(path_to_load).parent)
            if bin_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        except Exception as e:
            raise HIPRuntimeError(f"Falha ao carregar {path_to_load}: {e}")
            
        self._map_hip_functions()

    def _find_hip_dll(self) -> Optional[str]:
        from .dll_discovery import find_hip_dll
        return find_hip_dll()

    def _map_hip_functions(self):
        """Mapeia assinaturas das funções HIP C."""
        if not self._lib: return
        self._lib.hipInit.argtypes = [ctypes.c_uint]
        self._lib.hipInit.restype = ctypes.c_int
        self._lib.hipGetDeviceCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
        self._lib.hipGetDeviceCount.restype = ctypes.c_int
        self._lib.hipSetDevice.argtypes = [ctypes.c_int]
        self._lib.hipSetDevice.restype = ctypes.c_int
        # hipGetDevicePropertiesR0600 explícito, NÃO o nome nu -- ver o
        # docstring de hipDeviceProp_t acima pra por que (libamdhip64.so
        # exporta 3 símbolos versionados diferentes pra essa função; o nome
        # sem sufixo bate na ABI antiga, incompatível com esta struct).
        self._lib.hipGetDevicePropertiesR0600.argtypes = [ctypes.POINTER(hipDeviceProp_t), ctypes.c_int]
        self._lib.hipGetDevicePropertiesR0600.restype = ctypes.c_int
        self._lib.hipDeviceGetAttribute.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int]
        self._lib.hipDeviceGetAttribute.restype = ctypes.c_int
        self._lib.hipMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        self._lib.hipMalloc.restype = ctypes.c_int
        self._lib.hipFree.argtypes = [ctypes.c_void_p]
        self._lib.hipFree.restype = ctypes.c_int
        self._lib.hipMemcpy.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        self._lib.hipMemcpy.restype = ctypes.c_int
        self._lib.hipMemset.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
        self._lib.hipMemset.restype = ctypes.c_int
        self._lib.hipModuleLoad.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p]
        self._lib.hipModuleLoad.restype = ctypes.c_int
        self._lib.hipModuleGetFunction.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_char_p]
        self._lib.hipModuleGetFunction.restype = ctypes.c_int
        self._lib.hipModuleLaunchKernel.argtypes = [
            ctypes.c_void_p, 
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)
        ]
        self._lib.hipModuleLaunchKernel.restype = ctypes.c_int
        self._lib.hipDeviceSynchronize.argtypes = []
        self._lib.hipDeviceSynchronize.restype = ctypes.c_int
        self._lib.hipDeviceReset.argtypes = []
        self._lib.hipDeviceReset.restype = ctypes.c_int
        self._lib.hipMemGetInfo.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        self._lib.hipMemGetInfo.restype = ctypes.c_int
        self._lib.hipStreamCreate.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self._lib.hipStreamCreate.restype = ctypes.c_int

        self._lib.hipStreamBeginCapture.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._lib.hipStreamBeginCapture.restype = ctypes.c_int
        self._lib.hipStreamEndCapture.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self._lib.hipStreamEndCapture.restype = ctypes.c_int
        self._lib.hipGraphInstantiate.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        self._lib.hipGraphInstantiate.restype = ctypes.c_int
        self._lib.hipGraphLaunch.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._lib.hipGraphLaunch.restype = ctypes.c_int
        self._lib.hipGraphExecKernelNodeSetParams.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self._lib.hipGraphExecKernelNodeSetParams.restype = ctypes.c_int
        self._lib.hipGraphDestroy.argtypes = [ctypes.c_void_p]
        self._lib.hipGraphDestroy.restype = ctypes.c_int
        self._lib.hipGraphExecDestroy.argtypes = [ctypes.c_void_p]
        self._lib.hipGraphExecDestroy.restype = ctypes.c_int

        # Eventos HIP — usados para profiling on-device (Etapa A). Medem tempo
        # de GPU real entre dois pontos da stream, isolando o custo do kernel
        # do overhead de dispatch CPU->fila.
        self._lib.hipEventCreate.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self._lib.hipEventCreate.restype = ctypes.c_int
        self._lib.hipEventRecord.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._lib.hipEventRecord.restype = ctypes.c_int
        self._lib.hipEventSynchronize.argtypes = [ctypes.c_void_p]
        self._lib.hipEventSynchronize.restype = ctypes.c_int
        self._lib.hipEventElapsedTime.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_void_p, ctypes.c_void_p]
        self._lib.hipEventElapsedTime.restype = ctypes.c_int
        self._lib.hipEventDestroy.argtypes = [ctypes.c_void_p]
        self._lib.hipEventDestroy.restype = ctypes.c_int

    def event_create(self) -> ctypes.c_void_p:
        """Cria um evento HIP para timing. Retorna o handle."""
        ev = ctypes.c_void_p()
        self._check_error(self._lib.hipEventCreate(ctypes.byref(ev)), "hipEventCreate")
        return ev

    def event_record(self, event: ctypes.c_void_p):
        """Grava o evento na stream padrão do runtime."""
        self._check_error(self._lib.hipEventRecord(event, self._stream), "hipEventRecord")

    def event_elapsed_ms(self, start: ctypes.c_void_p, stop: ctypes.c_void_p) -> float:
        """Sincroniza no stop e retorna o tempo GPU decorrido entre start e stop (ms)."""
        self._check_error(self._lib.hipEventSynchronize(stop), "hipEventSynchronize")
        ms = ctypes.c_float(0.0)
        self._check_error(self._lib.hipEventElapsedTime(ctypes.byref(ms), start, stop), "hipEventElapsedTime")
        return ms.value

    def event_destroy(self, event: ctypes.c_void_p):
        try:
            self._lib.hipEventDestroy(event)
        except Exception:
            pass

    def _check_error(self, err: int, context: str):
        if err != 0:
            raise HIPRuntimeError(f"Erro HIP: {context} retornou código {err}")

    def _identify_device_arch(self, device_id: int) -> tuple[str, Optional[str]]:
        """(nome comercial, arquitetura VTE-suportada ou None) pro device
        `device_id`. Prioriza `gcnArchName` (ISA real reportada pelo driver,
        ver hipDeviceProp_t/get_gpu_architecture) validada contra o conjunto
        de arquiteturas que VTE conhece (GPU_ARCH_MAP.values()) -- necessário
        porque nem toda GPU com uma ISA real é uma discreta suportada (ex.
        iGPU de APU). Cai pro match por nome comercial só se gcnArchName vier
        vazio (ROCm antigo o bastante pra não popular o campo)."""
        props = self.get_device_properties(device_id)
        name = props["name"]
        gcn_arch_name = props.get("gcn_arch_name", "")
        if gcn_arch_name:
            arch = gcn_arch_name.split(":")[0]
            return name, (arch if arch in GPU_ARCH_MAP.values() else None)

        name_lower = name.lower()
        matched_arch = next((arch for pattern, arch in GPU_ARCH_MAP.items() if pattern in name_lower), None)
        return name, matched_arch

    def _select_device_index(self) -> int:
        """Escolhe QUAL device HIP usar quando o sistema tem mais de uma GPU
        AMD visível (ex.: dGPU RDNA3 + iGPU no mesmo chassi/notebook).

        hipSetDevice(0) fixo era inseguro nesse cenário: a ordem de
        enumeração do driver HIP não é garantida colocar a discreta no índice
        0, e VTE hoje só suporta arquiteturas discretas RDNA2/RDNA3 (ver
        GPU_ARCH_MAP em vte/config.py -- nenhuma entrada de iGPU existe lá).
        Reaproveita esse MESMO mapa (não gcnArchName, que a struct
        hipDeviceProp_t hand-mantida aqui nem expõe -- ver o comentário sobre
        multi_processor_count logo abaixo por que essa struct já mordeu a
        gente antes) para inspecionar cada device pelo nome comercial e
        escolher o primeiro que bate com uma arquitetura que VTE realmente
        sabe rodar. Isso automaticamente pula qualquer iGPU (nenhum nome de
        APU está em GPU_ARCH_MAP), sem precisar que o host (Lemonade) passe
        nenhum índice explícito.

        Só um device, ou nenhum bate no mapa: cai pro índice 0 (comportamento
        de antes, preservado -- é o caso comum de máquina com uma GPU só).
        VTE_DEVICE_INDEX força um índice específico, escape hatch pra quem
        sabe exatamente qual quer (ex.: dois discretos RDNA3 na mesma
        máquina, caso que a heurística de nome sozinha não desambigua).

        VTE_TARGET_ARCH_FAMILY (ex.: "gfx110X", o que o adapter VTE da
        Lemonade sempre define hoje) restringe a escolha a uma geração RDNA
        específica: sem isso, um sistema com uma RDNA2 E uma RDNA3 discretas
        podia escolher a RDNA2 silenciosamente (primeira na ordem de
        enumeração do HIP), mesmo numa integração que só valida gfx110X. Com
        a env var definida e nenhum device dessa família encontrado, falha
        alto e claro em vez de cair pra uma geração não validada."""
        override = os.environ.get('VTE_DEVICE_INDEX')
        if override is not None:
            logger.info(f"VTE_DEVICE_INDEX={override} (override manual, sem auto-detecção).")
            return int(override)

        target_family = os.environ.get('VTE_TARGET_ARCH_FAMILY')

        count = ctypes.c_int(0)
        err = self._lib.hipGetDeviceCount(ctypes.byref(count))
        if err != 0 or count.value <= 1:
            if count.value == 1 and target_family is not None:
                name, matched_arch = self._identify_device_arch(0)
                if matched_arch is None or not matched_arch.startswith(target_family[:-1]):
                    raise HIPRuntimeError(
                        f"VTE_TARGET_ARCH_FAMILY={target_family}, mas o único device HIP visível "
                        f"('{name}', arch {matched_arch or 'desconhecida'}) não pertence a essa família."
                    )
            return 0

        candidates = []
        for i in range(count.value):
            try:
                name, matched_arch = self._identify_device_arch(i)
            except Exception as e:
                logger.warning(f"Não foi possível ler propriedades do device {i}: {e}")
                continue
            candidates.append((i, name, matched_arch))

        supported = [(i, name, arch) for i, name, arch in candidates if arch is not None]
        if target_family is not None:
            family_prefix = target_family[:-1]  # "gfx110X" -> "gfx110"
            supported = [(i, name, arch) for i, name, arch in supported if arch.startswith(family_prefix)]
            if not supported:
                raise HIPRuntimeError(
                    f"VTE_TARGET_ARCH_FAMILY={target_family}, mas nenhum dos {count.value} devices "
                    f"HIP visíveis pertence a essa família "
                    f"({[(n, a) for _, n, a in candidates]}). Recusando escolher uma geração não validada."
                )

        if supported:
            chosen_index, chosen_name, _ = supported[0]
            if len(supported) > 1:
                logger.warning(
                    f"Múltiplas GPUs AMD suportadas detectadas ({[n for _, n, _ in supported]}); "
                    f"usando a primeira ({chosen_name}, device {chosen_index}). Defina "
                    f"VTE_DEVICE_INDEX para escolher outra explicitamente."
                )
            else:
                logger.info(f"GPU selecionada: {chosen_name} (device {chosen_index}) entre {count.value} devices HIP visíveis.")
            return chosen_index

        logger.warning(
            f"Nenhum dos {count.value} devices HIP visíveis bate com uma arquitetura "
            f"conhecida ({[n for _, n, _ in candidates]}); usando device 0 como fallback."
        )
        return 0

    def initialize(self) -> bool:
        """Inicializa runtime HIP e detecta GPU."""
        try:
            from vte.bridge.kernel_profiler import PROFILER as _PROFILER
            self._profiler = _PROFILER
        except Exception:
            self._profiler = None
        err = self._lib.hipInit(0)
        if err != 0:
            logger.error(f"hipInit falhou com código {err}")
            return False

        self._device_index = self._select_device_index()

        err = self._lib.hipSetDevice(self._device_index)
        if err != 0:
            logger.error(f"hipSetDevice({self._device_index}) falhou com código {err}")
            return False

        try:
            props = self.get_device_properties(self._device_index)
            self._vram_total = props["total_global_mem"]
            # Número real de Compute Units da GPU (lido uma vez aqui, não
            # re-consultado em hot path) -- usado para dimensionar grids
            # (Split-KV, QKV Two-Pass Split-K, causal_conv1d) de forma
            # proporcional a QUALQUER RDNA2/RDNA3, não só aos 32 CUs fixos
            # da RX 7600 em que os fatores originais foram calibrados. Ver
            # docs/PERFORMANCE.md para a fórmula de cada um.
            #
            # NÃO lido de props["multi_processor_count"] (hipDeviceProp_t):
            # investigação real (2026-07) achou esse campo retornando lixo
            # (38911 na RX 7600, que tem 32 CUs de verdade) -- a struct
            # hipDeviceProp_t inteira é grande, mantida à mão neste arquivo,
            # e nunca foi validada de fato contra o ABI real do
            # amdhip64_6.dll instalado (tools/validate_structs.py só roda a
            # checagem se `hip-python` estiver instalado, o que não está
            # neste ambiente -- a validação sempre foi um no-op silencioso).
            # Trocado por hipDeviceGetAttribute(hipDeviceAttributeMultiprocessorCount),
            # uma API estável de valor único, sem depender do layout da
            # struct gigante. Confirmado também um quirk real e documentado
            # do RDNA: essa API retorna a contagem de WGPs (Work Group
            # Processors), não de CUs -- RDNA agrupa 2 CUs por WGP. Medido
            # na RX 7600 (32 CUs reais, RDNA3/gfx1102): a API retornou 16,
            # exatamente a metade -- por isso o *2 abaixo.
            self._num_cus = self._get_multiprocessor_count_raw(self._device_index) * 2
            arch = self.get_gpu_architecture()

            err = self._lib.hipStreamCreate(ctypes.byref(self._stream))
            if err != 0:
                logger.warning(f"Falha ao criar stream assincrona ({err}). Usando default.")

            logger.info(f"HIP Inicializado. GPU: {props['name']} | Arch: {arch} | CUs: {self._num_cus} | VRAM: {self._vram_total / 1024**2:.1f} MB")
            self._initialized = True

            from .watchdog import KernelWatchdog
            self.watchdog = KernelWatchdog(self)
            self.watchdog.start()

            from .gpu_utilization_guard import GPUUtilizationGuard
            self.gpu_utilization_guard = GPUUtilizationGuard(self.watchdog, threshold_percent=95.0)
            self.gpu_utilization_guard.start()

            HIPRuntime._live_instance_count += 1
            self._counted_as_live = True

            return True
        except Exception as e:
            logger.error(f"Falha ao ler propriedades da GPU: {e}")
            return False

    def _get_multiprocessor_count_raw(self, device_id: int = 0) -> int:
        """hipDeviceGetAttribute(hipDeviceAttributeMultiprocessorCount) --
        63 é o índice real desse enum no header do ROCm 6.4 instalado
        (contado programaticamente a partir de hip_runtime_api.h; é um enum
        C de valores implícitos, não uma constante documentada em nenhum
        lugar estável o bastante para outra forma de obter esse número sem
        depender do header em si). Em RDNA isto retorna WGPs, não CUs --
        quem chama (initialize()) faz a correção *2."""
        value = ctypes.c_int(-1)
        HIP_ATTR_MULTIPROCESSOR_COUNT = 63
        err = self._lib.hipDeviceGetAttribute(ctypes.byref(value), HIP_ATTR_MULTIPROCESSOR_COUNT, device_id)
        if err != 0:
            raise HIPSafetyError(f"hipDeviceGetAttribute(multiprocessorCount) falhou: código {err}")
        return value.value

    def get_device_properties(self, device_id: int = 0) -> HIPDeviceProperties:
        """Lê propriedades da GPU usando struct validada."""
        props = hipDeviceProp_t()
        err = self._lib.hipGetDevicePropertiesR0600(ctypes.byref(props), device_id)
        if err != 0:
            raise HIPSafetyError(f"hipGetDevicePropertiesR0600 falhou: código {err}")

        return {
            "name": props.name.decode("utf-8").rstrip('\x00'),
            "total_global_mem": props.totalGlobalMem,
            "shared_mem_per_block": props.sharedMemPerBlock,
            "max_threads_per_block": props.maxThreadsPerBlock,
            "warp_size": props.warpSize,
            "multi_processor_count": props.multiProcessorCount,
            "compute_capability": f"{props.major}.{props.minor}",
            "gcn_arch_name": props.gcnArchName.decode("utf-8").rstrip('\x00'),
        }

    def get_num_cus(self) -> int:
        """Nº de Compute Units da GPU ativa, lido em initialize() (não
        re-consulta hipGetDeviceProperties aqui -- hot path). Override via
        VTE_NUM_CUS para testar o dimensionamento de grid com uma contagem
        diferente na mesma GPU física (ex.: simular uma RX 6800/7900 XTX na
        RX 7600), sem precisar do hardware real."""
        override = os.environ.get('VTE_NUM_CUS')
        if override:
            return int(override)
        return self._num_cus

    def get_gpu_architecture(self) -> str:
        """Detecta arquitetura da GPU ativa (self._device_index, selecionado
        em initialize() -- ver _select_device_index()) dinamicamente.

        Usa `gcnArchName` (lido direto do driver via hipDeviceProp_t, ver seu
        docstring) como fonte primária -- é a ISA real reportada pelo ROCm,
        não um palpite. O nome comercial (GPU_ARCH_MAP) continua como
        fallback só pra ROCm antigo o bastante pra não popular esse campo:
        placas workstation/server (W7900 incluída) reportam o nome genérico
        "AMD Radeon Graphics" via ROCm, então o match por nome comercial
        sozinho não as distingue -- foi assim que se confirmou ao vivo que
        gcnArchName é necessário, não só preferível (ver docs/BUGS.md)."""
        if not self._lib:
            raise HIPRuntimeError("HIPRuntime não inicializado (lib missing)")

        props = self.get_device_properties(self._device_index)

        gcn_arch_name = props.get("gcn_arch_name", "")
        if gcn_arch_name:
            # gcnArchName pode vir com sufixo de features (ex.
            # "gfx1100:sramecc+:xnack-") -- arch pura é a parte antes do ':'.
            return gcn_arch_name.split(":")[0]

        gpu_name = props["name"].lower()
        for pattern, arch in GPU_ARCH_MAP.items():
            if pattern in gpu_name:
                return arch

        logger.warning(f"Arquitetura para GPU '{gpu_name}' não mapeada. Usando fallback {DEFAULT_GPU_ARCH}.")
        return DEFAULT_GPU_ARCH

    def get_real_mem_info(self) -> tuple[int, int]:
        """
        `hipMemGetInfo()` -- (bytes livres, bytes totais) REAIS, medidos pelo
        driver na GPU física inteira, não uma estimativa a partir do que ESTE
        processo já alocou. Ao contrário de `_process_wide_allocated_bytes`
        (soma só do que o VTE mesmo pediu via hipMalloc, em qualquer
        instância deste processo), isto reflete TUDO que está usando VRAM
        naquele momento -- outro processo (jogo, navegador com aceleração de
        GPU, outro app de IA) reduz o "livre" reportado aqui exatamente como
        reduziria no Gerenciador de Tarefas, mesmo sem o VTE saber nada sobre
        esse outro processo. Fonte de verdade real para a checagem de 95% em
        `safe_malloc` e para o `VRAMPressureGuard` (vram_pressure_guard.py).
        """
        if not self._initialized:
            raise HIPSafetyError("Operação HIP requer inicialização (chame initialize()).")
        free_bytes = ctypes.c_size_t(0)
        total_bytes = ctypes.c_size_t(0)
        err = self._lib.hipMemGetInfo(ctypes.byref(free_bytes), ctypes.byref(total_bytes))
        self._check_error(err, "hipMemGetInfo")
        return free_bytes.value, total_bytes.value

    def safe_malloc(self, size_bytes: int, tag: str = "unnamed") -> ctypes.c_void_p:
        """Aloca VRAM com validações de segurança."""
        if not self._initialized:
            raise HIPSafetyError("Operação HIP requer inicialização (chame initialize()).")
        if size_bytes <= 0:
            raise HIPSafetyError(f"Tentativa de alocar tamanho inválido: {size_bytes} bytes.")
        # Teto de sanidade contra o VRAM FÍSICO REAL da GPU ativa (medido em
        # initialize(), não um valor fixo) -- nenhuma alocação única pode
        # logicamente exceder a VRAM total do device. Bug real encontrado no
        # benchmark do hackathon (2026-07): esse teto era uma CONSTANTE fixa
        # de 8GB (calibrada pra RX 7600, único hardware testado até então),
        # que rejeitava a alocação legítima de ~29.9GB do slab de pesos do
        # Granite 4.1 30B numa W7900 de 48GB -- a checagem de 95%
        # (VRAM_USAGE_LIMIT, logo abaixo) já é o guard real e correto contra
        # OOM; este teto aqui é só sanidade "não maior que o device inteiro".
        if size_bytes > self._vram_total:
            raise HIPSafetyError(
                f"Tentativa de alocar acima da VRAM total do device: {size_bytes} > {self._vram_total}."
            )
            
        # Checagem de PROCESSO (não só desta instância) -- ver comentário na
        # classe. Sem isto, um segundo modelo (ex.: draft da Fase 5) via os
        # 95% inteiros como livres, ignorando o que o primeiro já reservou no
        # mesmo contexto HIP físico.
        total_allocated = HIPRuntime._process_wide_allocated_bytes
        if (total_allocated + size_bytes) > (self._vram_total * VRAM_USAGE_LIMIT):
            raise MemoryGuardianOOMError(
                f"OOM Preventivo: alocar {size_bytes} bytes [{tag}] excederia 95% da VRAM "
                f"({self._vram_total} bytes totais). Já reservado no processo (todos os "
                f"modelos carregados): {total_allocated} bytes."
            )

        # Checagem REAL (não só o que o VTE mesmo alocou): `hipMemGetInfo`
        # reflete a GPU física inteira, incluindo VRAM usada por QUALQUER
        # outro processo (jogo, navegador com aceleração de GPU, outro app de
        # IA) -- a checagem acima só sabe sobre alocações do próprio VTE, e
        # ficaria cega pra esse caso (poderia aprovar uma alocação que passa
        # de 95% real só porque, do ponto de vista do VTE, "ainda cabia").
        # Falha best-effort: se `hipMemGetInfo` falhar por algum motivo, não
        # bloqueia a alocação por causa disso -- a checagem acima já cobre o
        # caso comum (só VTE usando a GPU).
        try:
            real_free, real_total = self.get_real_mem_info()
            if size_bytes > (real_free - int(real_total * (1.0 - VRAM_USAGE_LIMIT))):
                raise MemoryGuardianOOMError(
                    f"OOM Preventivo (VRAM real da GPU): alocar {size_bytes} bytes [{tag}] passaria de "
                    f"{VRAM_USAGE_LIMIT*100:.0f}% de uso real da GPU. Livre agora: {real_free} de "
                    f"{real_total} bytes -- outro programa (jogo, navegador, etc.) pode estar usando "
                    f"VRAM além do que o VTE alocou. Feche outros programas que usam a GPU ou reduza "
                    f"o context_length/modelo antes de carregar."
                )
        except MemoryGuardianOOMError:
            raise
        except Exception as e:
            logger.warning(f"Não foi possível consultar hipMemGetInfo para checagem real de VRAM: {e}")

        ptr = ctypes.c_void_p()
        err = self._lib.hipMalloc(ctypes.byref(ptr), size_bytes)
        if err == HIPError.outOfMemory:
            raise MemoryGuardianOOMError(f"hipMalloc falhou com OOM. Acionando Memory Guardian para fallback na RAM (Tamanho: {size_bytes}).")
        self._check_error(err, "hipMalloc")

        ptr_val = ptr.value
        if ptr_val is None:
            raise HIPSafetyError("hipMalloc retornou ponteiro nulo com status 0.")

        self._active_allocations[ptr_val] = (size_bytes, tag)
        HIPRuntime._process_wide_allocated_bytes += size_bytes
        logger.debug(f"Alocado {size_bytes} bytes na VRAM em 0x{ptr_val:016X} [{tag}]")
        return ptr

    def safe_free(self, ptr: ctypes.c_void_p, tag: str = "unnamed") -> bool:
        """Libera VRAM com comportamento dual baseado no cleanup mode."""
        ptr_val = ptr.value or 0
        if ptr_val not in self._active_allocations:
            if self._in_cleanup_mode:
                logger.warning(f"Tentativa de liberar ponteiro não rastreável durante cleanup: 0x{ptr_val:016X} [{tag}]")
                return False
            else:
                raise HIPSafetyError(f"Tentativa de liberar ponteiro não rastreado: 0x{ptr_val:016X} [{tag}]. Uso após free ou corrupção.")
                
        size_bytes, _ = self._active_allocations[ptr_val]
        err = self._lib.hipFree(ptr)
        self._check_error(err, "hipFree")
        del self._active_allocations[ptr_val]
        HIPRuntime._process_wide_allocated_bytes = max(0, HIPRuntime._process_wide_allocated_bytes - size_bytes)
        logger.debug(f"Liberada memória em 0x{ptr_val:016X} [{tag}]")
        return True

    def safe_memcpy_host_to_device(self, dst: ctypes.c_void_p, src: bytes, tag: str = "unnamed") -> bool:
        """Copia RAM para VRAM (Host -> Device) com validação."""
        if not self._initialized:
            raise HIPSafetyError("HIP não inicializado.")
        
        dst_val = dst.value or 0
        valid_ptr = False
        actual_alloc_base = 0
        actual_alloc_size = 0
        
        for alloc_base, (size, t) in self._active_allocations.items():
            if alloc_base <= dst_val < alloc_base + size:
                valid_ptr = True
                actual_alloc_base = alloc_base
                actual_alloc_size = size
                break
                
        if not valid_ptr:
            raise HIPSafetyError(f"memcpy_h2d: Ponteiro de destino não rastreado: 0x{dst_val:016X} [{tag}]")
            
        src_len = len(src)
        if dst_val + src_len > actual_alloc_base + actual_alloc_size:
             raise HIPSafetyError(f"memcpy_h2d Overflow: dst_len ({src_len}) cruza fronteira da alocação principal.")
            
        c_src = (ctypes.c_char * src_len).from_buffer_copy(src)
        err = self._lib.hipMemcpy(dst, ctypes.byref(c_src), src_len, hipMemcpyHostToDevice)
        self._check_error(err, "hipMemcpy (H2D)")
        return True

    def safe_memset(self, dst: ctypes.c_void_p, size_bytes: int, tag: str = "unnamed", value: int = 0) -> bool:
        """Zera (ou preenche com `value`) uma região de VRAM, com a mesma
        validação de fronteira do safe_memcpy_host_to_device -- usado pelos
        buffers de estado persistente (ex: Gated DeltaNet do Qwen3.5) que,
        ao contrário do KV cache (só lido depois de escrito por um token
        real), são LIDOS antes de qualquer escrita no primeiro passo de
        decode. hipMalloc não zera memória por conta própria -- sem isto, o
        estado inicial é lixo de VRAM residual, não os zeros que a
        implementação de referência assume (`torch.zeros(...)`)."""
        if not self._initialized:
            raise HIPSafetyError("HIP não inicializado.")

        dst_val = dst.value or 0
        valid_ptr = False
        actual_alloc_base = 0
        actual_alloc_size = 0

        for alloc_base, (size, t) in self._active_allocations.items():
            if alloc_base <= dst_val < alloc_base + size:
                valid_ptr = True
                actual_alloc_base = alloc_base
                actual_alloc_size = size
                break

        if not valid_ptr:
            raise HIPSafetyError(f"memset: Ponteiro de destino não rastreado: 0x{dst_val:016X} [{tag}]")

        if dst_val + size_bytes > actual_alloc_base + actual_alloc_size:
            raise HIPSafetyError(f"memset Overflow: size ({size_bytes}) cruza fronteira da alocação principal [{tag}].")

        err = self._lib.hipMemset(dst, ctypes.c_int(value), size_bytes)
        self._check_error(err, "hipMemset")
        return True

    def safe_memcpy_device_to_host(self, dst: bytearray, src: ctypes.c_void_p, tag: str = "unnamed") -> bool:
        """Copia VRAM para RAM (Device -> Host) com validação de segurança (Isolation)."""
        if not self._initialized:
            raise HIPSafetyError("HIP não inicializado.")
            
        if self._prevent_host_copies:
            allowed_tags = ["logits", "output", "sampler"]
            if not any(allowed in tag.lower() for allowed in allowed_tags):
                raise HIPSafetyError(f"Isolamento de Dados: Cópia VRAM -> RAM bloqueada para '{tag}'. "
                                     f"Tags permitidas: {allowed_tags}")
            
        src_val = src.value if hasattr(src, 'value') else src
        src_val = src_val or 0
        
        valid_ptr = False
        actual_alloc_base = 0
        actual_alloc_size = 0
        
        for alloc_base, (size, t) in self._active_allocations.items():
            if alloc_base <= src_val < alloc_base + size:
                valid_ptr = True
                actual_alloc_base = alloc_base
                actual_alloc_size = size
                break
                
        if not valid_ptr:
            raise HIPSafetyError(f"memcpy_d2h: Ponteiro fonte não rastreado: 0x{src_val:016X} [{tag}]")
            
        dst_len = len(dst)
        if src_val + dst_len > actual_alloc_base + actual_alloc_size:
             raise HIPSafetyError(f"memcpy_d2h Overflow: dst_len ({dst_len}) cruza fronteira da alocação principal.")
             
        c_dst = (ctypes.c_char * dst_len).from_buffer(dst)
        err = self._lib.hipMemcpy(c_dst, src, dst_len, hipMemcpyDeviceToHost)
        self._check_error(err, "hipMemcpy (D2H)")
        return True

    def compile_kernel(self, source_path: str, kernel_name: str) -> str:
        """Compila .hip em .hsaco determinando a arch."""
        arch = self.get_gpu_architecture()
        cache_dir = CACHE_DIR / "kernels" / arch
        cache_dir.mkdir(parents=True, exist_ok=True)
        hsaco_path = cache_dir / f"{kernel_name}.hsaco"
        
        if hsaco_path.exists():
            logger.info(f"Usando kernel cacheado: {hsaco_path}")
            return str(hsaco_path)
            
        logger.info(f"Compilando kernel {kernel_name} para {arch}...")
        
        cmd = [
            "hipcc", "--genco", f"--offload-arch={arch}", "-O3",
            "-o", str(hsaco_path), str(source_path)
        ]
        
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=creationflags)
            logger.debug(f"hipcc output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Falha ao compilar kernel. Saída: {e.stderr}")
            raise HIPRuntimeError(f"Compilação do kernel {kernel_name} falhou.")
            
        return str(hsaco_path)

    def load_kernel(self, hsaco_path: str, kernel_name: str) -> tuple[ctypes.c_void_p, ctypes.c_void_p]:
        """Carrega módulo e recupera função do kernel."""
        module = ctypes.c_void_p()
        err = self._lib.hipModuleLoad(ctypes.byref(module), hsaco_path.encode('utf-8'))
        self._check_error(err, "hipModuleLoad")
        
        function = ctypes.c_void_p()
        err = self._lib.hipModuleGetFunction(ctypes.byref(function), module, kernel_name.encode('utf-8'))
        self._check_error(err, "hipModuleGetFunction")
        
        return module, function

    def launch_kernel(self, function: ctypes.c_void_p, grid: tuple, block: tuple, args: list, shared_mem: int = 0, expected_args: int = None) -> bool:
        """Executa um kernel com as configurações providas e validação de ABI."""
        if getattr(self, 'watchdog', None) is not None and self.watchdog.is_panic_state():
            raise HIPSafetyError(
                "GPU em PANIC MODE (KernelWatchdog detectou timeout anterior). "
                "Novos lançamentos bloqueados até reinicialização do runtime."
            )
        self._throttle_before_dispatch()

        if expected_args is not None and len(args) != expected_args:
            raise HIPSafetyError(
                f"ABI Mismatch: kernel espera {expected_args} args, "
                f"recebeu {len(args)}"
            )
            
        for i, arg in enumerate(args):
            if isinstance(arg, ctypes.c_void_p) and (arg.value == 0 or arg.value is None):
                # Ponteiro nulo é legítimo para argumentos opcionais (ex.: bias
                # nullptr em matmuls sem bias). Nível debug para não poluir o log.
                logger.debug(f"Argumento {i} do kernel é ponteiro nulo/zero (esperado se for bias opcional).")
                
        if len(grid) != 3 or any(g <= 0 for g in grid):
            raise HIPSafetyError(f"Grid dims inválidas: {grid}")
        if len(block) != 3 or any(b <= 0 for b in block):
            raise HIPSafetyError(f"Block dims inválidas: {block}")
            
        total_grid = grid[0] * grid[1] * grid[2]
        if total_grid > MAX_GRID_DIMENSIONS:
            raise HIPSafetyError(f"Grid Bomb bloqueada! O total de blocos solicitados ({total_grid}) excede o limite arquitetural de {MAX_GRID_DIMENSIONS}.")
            
        props = self.get_device_properties(self._device_index)
        total_block = block[0] * block[1] * block[2]
        if total_block > props["max_threads_per_block"]:
            raise HIPSafetyError(f"Block size ({total_block}) excede o limite max_threads_per_block ({props['max_threads_per_block']}).")
            
        max_shared_mem = props["shared_mem_per_block"]
        if shared_mem > max_shared_mem:
             raise HIPSafetyError(f"LDS Overflow bloqueado! Shared memory ({shared_mem}) excede máximo da GPU ({max_shared_mem}).")
             
        c_args = (ctypes.c_void_p * len(args))()
        for i, arg in enumerate(args):
            c_args[i] = ctypes.cast(ctypes.byref(arg), ctypes.c_void_p)

        prof = getattr(self, '_profiler', None)
        prof_on = prof is not None and prof.enabled
        if prof_on:
            ev_start = self.event_create()
            ev_stop = self.event_create()
            self.event_record(ev_start)

        err = self._lib.hipModuleLaunchKernel(
            function,
            grid[0], grid[1], grid[2],
            block[0], block[1], block[2],
            shared_mem, self._stream, c_args, None
        )
        self._check_error(err, "hipModuleLaunchKernel")

        if prof_on:
            self.event_record(ev_stop)
            prof.record(self.event_elapsed_ms(ev_start, ev_stop))
            self.event_destroy(ev_start)
            self.event_destroy(ev_stop)
        return True
    def launch_kernel_recorded(self, function: ctypes.c_void_p, args: list, grid: tuple, block: tuple, shared_mem: int = 0) -> bool:
        """
        Lança um kernel no stream atual.
        
        Se o stream estiver em modo de captura (hipStreamBeginCapture),
        o driver HIP grava a chamada no Grafo em vez de executar na GPU.
        A semântica é idêntica ao launch_kernel normal — a magia está no driver.
        """
        if len(grid) != 3 or any(g <= 0 for g in grid):
            raise HIPSafetyError(f"Grid dims inválidas: {grid}")
        if len(block) != 3 or any(b <= 0 for b in block):
            raise HIPSafetyError(f"Block dims inválidas: {block}")
        
        total_grid = grid[0] * grid[1] * grid[2]
        if total_grid > MAX_GRID_DIMENSIONS:
            raise HIPSafetyError(f"Grid Bomb bloqueada! Total de blocos ({total_grid}) excede limite ({MAX_GRID_DIMENSIONS}).")
        
        num_args = len(args)
        c_args = (ctypes.c_void_p * num_args)()
        for i, arg in enumerate(args):
            if isinstance(arg, ctypes.c_void_p):
                c_args[i] = ctypes.cast(ctypes.byref(arg), ctypes.c_void_p)
            elif isinstance(arg, int):
                c_val = ctypes.c_uint64(arg)
                c_args[i] = ctypes.cast(ctypes.pointer(c_val), ctypes.c_void_p)
            else:
                c_args[i] = ctypes.cast(ctypes.byref(arg), ctypes.c_void_p)
        
        err = self._lib.hipModuleLaunchKernel(
            function,
            grid[0], grid[1], grid[2],
            block[0], block[1], block[2],
            shared_mem,
            self._stream,
            c_args,
            None
        )
        self._check_error(err, "hipModuleLaunchKernel (recorded)")
        return True

    def synchronize(self) -> bool:
        """Aguarda a execução, monitorado pelo KernelWatchdog (limite de tempo de GPU)."""
        if getattr(self, 'watchdog', None) is not None and self.watchdog.is_panic_state():
            raise HIPSafetyError(
                "GPU em PANIC MODE (KernelWatchdog detectou timeout anterior). "
                "Novos lançamentos bloqueados até reinicialização do runtime."
            )

        watchdog = getattr(self, 'watchdog', None)
        exec_id = watchdog.register_execution("hipDeviceSynchronize", estimated_ms=3000) if watchdog else None
        start = time.perf_counter()
        try:
            err = self._lib.hipDeviceSynchronize()
        finally:
            if exec_id and watchdog is not None:
                watchdog.complete_execution(exec_id)
        end = time.perf_counter()

        self._check_error(err, "hipDeviceSynchronize")
        self._throttle_duty_cycle(end, end - start)
        return True

    def _throttle_duty_cycle(self, now: float, busy_duration: float):
        """
        Registra uma medição REAL de tempo ocupado (chamado ao fim de
        synchronize(), depois que o trabalho já rodou) e aplica o teto de
        duty cycle. Complementa _throttle_before_dispatch, que age de forma
        preventiva ANTES do próximo lançamento.
        """
        self._duty_cycle_window.append((now, busy_duration))
        self._enforce_duty_cycle_limit(now)

    def _throttle_before_dispatch(self):
        """
        Checagem PREVENTIVA chamada no início de todo lançamento de kernel/grafo
        (launch_kernel, launch_kernel_recorded, graph_launch) — antes de
        despachar mais trabalho, verifica se o histórico recente já está no
        teto de 95% e pausa ali mesmo, em vez de deixar o novo lançamento
        somar-se ao que já está no limite. Isso converge mais rápido ao teto
        real (95%) do que só corrigir depois do synchronize().
        """
        self._enforce_duty_cycle_limit(time.perf_counter())

    def _enforce_duty_cycle_limit(self, now: float):
        """
        Mede a fração de tempo (janela deslizante de _duty_cycle_window_seconds)
        em que a GPU esteve ocupada executando nosso trabalho e insere uma
        pausa proporcional se ultrapassar _duty_cycle_limit (95%) — limita
        preventivamente o uso sustentado de "processador" da GPU, complementar
        ao VRAM_SAFETY_MARGIN (memória) e ao GPUUtilizationGuard (detecção
        reativa via contador do Windows).
        """
        window = getattr(self, '_duty_cycle_window', None)
        if window is None:
            return

        cutoff = now - self._duty_cycle_window_seconds
        while window and window[0][0] < cutoff:
            window.popleft()

        if not window:
            return

        window_span = now - window[0][0]
        if window_span <= 0:
            return

        total_busy = sum(d for _, d in window)
        duty_cycle = total_busy / window_span

        if duty_cycle > self._duty_cycle_limit:
            needed_idle = (total_busy / self._duty_cycle_limit) - window_span
            if needed_idle > 0:
                sleep_time = min(needed_idle, self._duty_cycle_max_sleep)
                logger.debug(
                    f"Duty cycle da GPU em {duty_cycle * 100:.1f}% "
                    f"(limite {self._duty_cycle_limit * 100:.0f}%). Pausando {sleep_time * 1000:.0f}ms."
                )
                time.sleep(sleep_time)
                # A própria pausa conta como tempo ocioso na janela seguinte;
                # não precisa registrar uma entrada extra no deque.

    def stream_begin_capture(self):
        """Inicia captura de stream"""
        err = self._lib.hipStreamBeginCapture(self._stream, HIP_STREAM_CAPTURE_MODE_GLOBAL)
        self._check_error(err, "hipStreamBeginCapture")

    def stream_end_capture(self) -> ctypes.c_void_p:
        """Finaliza captura e retorna hipGraph_t"""
        graph = ctypes.c_void_p()
        err = self._lib.hipStreamEndCapture(self._stream, ctypes.byref(graph))
        self._check_error(err, "hipStreamEndCapture")
        return graph

    def graph_instantiate(self, graph: ctypes.c_void_p) -> ctypes.c_void_p:
        """Instancia grafo executável"""
        graph_exec = ctypes.c_void_p()
        err = self._lib.hipGraphInstantiate(
            ctypes.byref(graph_exec),
            graph,
            None,
            None,
            0
        )
        self._check_error(err, "hipGraphInstantiate")
        return graph_exec

    def graph_launch(self, graph_exec: ctypes.c_void_p):
        """Lança grafo no stream"""
        if getattr(self, 'watchdog', None) is not None and self.watchdog.is_panic_state():
            raise HIPSafetyError(
                "GPU em PANIC MODE (KernelWatchdog detectou timeout anterior). "
                "Novos lançamentos bloqueados até reinicialização do runtime."
            )
        self._throttle_before_dispatch()
        err = self._lib.hipGraphLaunch(graph_exec, self._stream)
        self._check_error(err, "hipGraphLaunch")

    def graph_exec_kernel_node_set_params(self, graph_exec: ctypes.c_void_p, node: ctypes.c_void_p, params: ctypes.c_void_p):
        """Atualiza parâmetros de um kernel node"""
        err = self._lib.hipGraphExecKernelNodeSetParams(graph_exec, node, params)
        self._check_error(err, "hipGraphExecKernelNodeSetParams")

    def graph_destroy(self, graph: ctypes.c_void_p):
        err = self._lib.hipGraphDestroy(graph)
        self._check_error(err, "hipGraphDestroy")

    def graph_exec_destroy(self, graph_exec: ctypes.c_void_p):
        err = self._lib.hipGraphExecDestroy(graph_exec)
        self._check_error(err, "hipGraphExecDestroy")

    def cleanup(self):
        """Limpa as alocações da GPU com comportamento fail-safe."""
        self._in_cleanup_mode = True
        logger.info("Iniciando cleanup de alocações HIP...")

        if getattr(self, 'gpu_utilization_guard', None) is not None:
            self.gpu_utilization_guard.stop()
        self.gpu_utilization_guard = None

        if getattr(self, 'watchdog', None) is not None:
            self.watchdog.stop()
        self.watchdog = None

        allocs = list(self._active_allocations.items())
        for ptr_val, (size, tag) in allocs:
            try:
                self.safe_free(ctypes.c_void_p(ptr_val), f"{tag}_cleanup")
            except Exception as e:
                logger.error(f"Erro ao limpar alocação 0x{ptr_val:016X}: {e}")

        if self._counted_as_live:
            HIPRuntime._live_instance_count = max(0, HIPRuntime._live_instance_count - 1)
            self._counted_as_live = False

        # hipDeviceReset() reseta o CONTEXTO HIP INTEIRO -- não só as
        # alocações desta instância. Bug real encontrado na Fase 5: com dois
        # modelos carregados no mesmo processo (draft + alvo), descarregar
        # UM deles (ex.: o draft) chamava isto incondicionalmente e destruía
        # também as alocações do OUTRO modelo ainda em uso, causando
        # `hipFree retornou código 1` ao tentar descarregá-lo depois. Só
        # reseta o device quando esta é a ÚLTIMA instância viva do processo
        # (`_live_instance_count`, decrementado acima) -- com um único
        # modelo carregado (caso comum) o comportamento é idêntico a antes.
        if self._initialized and self._lib and hasattr(self._lib, 'hipDeviceReset') and HIPRuntime._live_instance_count == 0:
            try:
                self._lib.hipDeviceReset()
            except Exception as e:
                logger.error(f"Erro em hipDeviceReset: {e}")

        self._in_cleanup_mode = False
        self._initialized = False
        logger.info("Cleanup HIP concluído.")

    def __enter__(self):
        self.initialize()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False
