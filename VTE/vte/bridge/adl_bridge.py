"""
adl_bridge.py — binding ctypes mínimo para a AMD Display Library (ADL),
usado só para ler a temperatura real da GPU no Windows.

Todas as constantes, structs e assinaturas de função abaixo vêm verbatim
do SDK oficial da AMD (GPUOpen-LibrariesAndSDKs/display-library, arquivos
adl_sdk.h/adl_structures.h/adl_defines.h) e de uma implementação de
referência real e funcional (Youda008/HwMonitoringSnippets/ADLMonitoring.cpp)
-- nenhum valor aqui foi adivinhado. Isso importa porque um enum/offset
errado num binding ctypes não crasha (não há checagem de tipo em runtime)
-- ele silenciosamente lê outro campo (ex.: um clock em vez de uma
temperatura) e produz um número que PARECE real sem ser, exatamente a
categoria de bug que o projeto já documentou como a pior (ver "Bugs found
during development" no README).

`atiadlxx.dll` já vem com qualquer instalação de driver AMD no Windows
(`C:\\Windows\\System32\\atiadlxx.dll`) -- não precisa baixar SDK nenhum.

Duas APIs de temperatura, tentadas em ordem:
1. PMLog / Overdrive N (`ADL2_New_QueryPMLogData_Get`) -- o caminho real
   para RDNA/RDNA2/RDNA3. Confirmado funcionando nesta RX 7600 (retorna a
   temperatura "edge", a mesma que ferramentas como HWiNFO/GPU-Z chamam de
   "GPU Temperature").
2. Overdrive5 (`ADL_Overdrive5_Temperature_Get`) -- API legada (era GCN),
   mantida como fallback para placas mais antigas onde a PMLog pode não
   existir. Nesta RX 7600 retorna erro explícito (ADL_ERR=-1), tratado
   como "indisponível", nunca como sucesso silencioso.
"""
import ctypes
from typing import Optional

ADL_MAX_PATH = 256
ADL_OK = 0
ADL_PMLOG_MAX_SENSORS = 256
ADL_PMLOG_TEMPERATURE_EDGE = 8  # adl_defines.h -- índice direto em ADLPMLogDataOutput.sensors[]

ADL_MAIN_MALLOC_CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int)
ADL_CONTEXT_HANDLE = ctypes.c_void_p


class AdapterInfo(ctypes.Structure):
    """Layout exato de `AdapterInfo` em adl_structures.h (variante Windows,
    dentro do `#if defined(_WIN32) || defined(_WIN64)`)."""
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iAdapterIndex", ctypes.c_int),
        ("strUDID", ctypes.c_char * ADL_MAX_PATH),
        ("iBusNumber", ctypes.c_int),
        ("iDeviceNumber", ctypes.c_int),
        ("iFunctionNumber", ctypes.c_int),
        ("iVendorID", ctypes.c_int),
        ("strAdapterName", ctypes.c_char * ADL_MAX_PATH),
        ("strDisplayName", ctypes.c_char * ADL_MAX_PATH),
        ("iPresent", ctypes.c_int),
        ("iExist", ctypes.c_int),
        ("strDriverPath", ctypes.c_char * ADL_MAX_PATH),
        ("strDriverPathExt", ctypes.c_char * ADL_MAX_PATH),
        ("strPNPString", ctypes.c_char * ADL_MAX_PATH),
        ("iOSDisplayIndex", ctypes.c_int),
    ]


class ADLTemperature(ctypes.Structure):
    """`ADLTemperature` em adl_structures.h -- iTemperature em milésimos de
    grau Celsius. Usada só pela API legada Overdrive5."""
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iTemperature", ctypes.c_int),
    ]


class ADLSingleSensorData(ctypes.Structure):
    """`ADLSingleSensorData` em adl_structures.h -- `value` já em graus
    Celsius inteiros para sensores de temperatura (sem escala, confirmado
    na implementação de referência: `temperature = float(value) * 1.0f`)."""
    _fields_ = [
        ("supported", ctypes.c_int),
        ("value", ctypes.c_int),
    ]


class ADLPMLogDataOutput(ctypes.Structure):
    """`ADLPMLogDataOutput` em adl_structures.h -- `sensors` é indexado
    DIRETAMENTE pelo valor do enum de sensor (ex.: `sensors[8]` é a
    temperatura "edge"), não uma lista a ser escaneada por um campo de ID."""
    _fields_ = [
        ("size", ctypes.c_int),
        ("sensors", ADLSingleSensorData * ADL_PMLOG_MAX_SENSORS),
    ]


# O PCI Vendor ID da AMD é 0x1002 (4098 decimal) -- mas `AdapterInfo.iVendorID`
# na prática retorna o valor "1002" como INTEIRO DECIMAL (0x3ea), não o hex
# 0x1002. Confirmado empiricamente nesta RX 7600 antes de codificar (via
# script de debug que imprimiu iVendorID cru) -- documentação nenhuma
# menciona essa peculiaridade, então checar os dois formatos é mais seguro
# que confiar só na leitura oficial do PCI-SIG.
AMD_PCI_VENDOR_ID_HEX = 0x1002
AMD_PCI_VENDOR_ID_DECIMAL_AS_INT = 1002


class ADLBridge:
    """Inicializa a ADL uma vez (lazy) e expõe só o que este projeto precisa:
    a temperatura da GPU AMD detectada. Falha graciosamente (retorna None)
    em qualquer etapa -- nunca levanta para o chamador."""

    def __init__(self):
        self._dll = None
        self._adl2_context = None
        self._adapter_index: Optional[int] = None
        self._init_attempted = False
        self._alloc_bufs = []  # mantém os buffers do callback de malloc vivos
        self._malloc_callback = None

    def _malloc(self, size: int) -> int:
        buf = (ctypes.c_char * size)()
        self._alloc_bufs.append(buf)
        return ctypes.cast(buf, ctypes.c_void_p).value or 0

    def _initialize(self) -> bool:
        try:
            dll = ctypes.WinDLL("atiadlxx.dll")
        except OSError:
            return False  # sem driver AMD instalado, ou não-Windows

        dll.ADL_Main_Control_Create.argtypes = [ADL_MAIN_MALLOC_CALLBACK, ctypes.c_int]
        dll.ADL_Main_Control_Create.restype = ctypes.c_int
        dll.ADL_Adapter_NumberOfAdapters_Get.argtypes = [ctypes.POINTER(ctypes.c_int)]
        dll.ADL_Adapter_NumberOfAdapters_Get.restype = ctypes.c_int
        dll.ADL_Adapter_AdapterInfo_Get.argtypes = [ctypes.POINTER(AdapterInfo), ctypes.c_int]
        dll.ADL_Adapter_AdapterInfo_Get.restype = ctypes.c_int
        dll.ADL_Overdrive5_Temperature_Get.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.POINTER(ADLTemperature)
        ]
        dll.ADL_Overdrive5_Temperature_Get.restype = ctypes.c_int

        # ADL2_*: variante com contexto explícito (necessária pra
        # ADL2_New_QueryPMLogData_Get); coexiste com as chamadas ADL_Main_*
        # sem contexto acima, ambas operando sobre o mesmo driver.
        if hasattr(dll, "ADL2_Main_Control_Create"):
            dll.ADL2_Main_Control_Create.argtypes = [
                ADL_MAIN_MALLOC_CALLBACK, ctypes.c_int, ctypes.POINTER(ADL_CONTEXT_HANDLE)
            ]
            dll.ADL2_Main_Control_Create.restype = ctypes.c_int
        if hasattr(dll, "ADL2_New_QueryPMLogData_Get"):
            dll.ADL2_New_QueryPMLogData_Get.argtypes = [
                ADL_CONTEXT_HANDLE, ctypes.c_int, ctypes.POINTER(ADLPMLogDataOutput)
            ]
            dll.ADL2_New_QueryPMLogData_Get.restype = ctypes.c_int

        self._malloc_callback = ADL_MAIN_MALLOC_CALLBACK(self._malloc)
        if dll.ADL_Main_Control_Create(self._malloc_callback, 1) != ADL_OK:
            return False

        num_adapters = ctypes.c_int(0)
        rc = dll.ADL_Adapter_NumberOfAdapters_Get(ctypes.byref(num_adapters))
        if rc != ADL_OK or num_adapters.value <= 0:
            return False

        infos = (AdapterInfo * num_adapters.value)()
        for info in infos:
            info.iSize = ctypes.sizeof(AdapterInfo)
        if dll.ADL_Adapter_AdapterInfo_Get(infos, ctypes.sizeof(infos)) != ADL_OK:
            return False

        for info in infos:
            is_amd = info.iVendorID in (AMD_PCI_VENDOR_ID_HEX, AMD_PCI_VENDOR_ID_DECIMAL_AS_INT)
            if is_amd and info.iPresent != 0:
                self._adapter_index = info.iAdapterIndex
                break

        if self._adapter_index is None:
            return False

        if hasattr(dll, "ADL2_Main_Control_Create"):
            context = ADL_CONTEXT_HANDLE()
            if dll.ADL2_Main_Control_Create(self._malloc_callback, 1, ctypes.byref(context)) == ADL_OK:
                self._adl2_context = context

        self._dll = dll
        return True

    def _read_pmlog_edge_temperature(self) -> Optional[float]:
        """Caminho real para RDNA/RDNA2/RDNA3 (confirmado funcionando nesta
        RX 7600). `sensors[ADL_PMLOG_TEMPERATURE_EDGE]` é indexação direta
        pelo enum, não uma busca -- ver docstring de ADLPMLogDataOutput."""
        if self._adl2_context is None or not hasattr(self._dll, "ADL2_New_QueryPMLogData_Get"):
            return None
        data = ADLPMLogDataOutput()
        rc = self._dll.ADL2_New_QueryPMLogData_Get(
            self._adl2_context, self._adapter_index, ctypes.byref(data)
        )
        if rc != ADL_OK:
            return None
        sensor = data.sensors[ADL_PMLOG_TEMPERATURE_EDGE]
        if not sensor.supported:
            return None
        return float(sensor.value)

    def _read_overdrive5_temperature(self) -> Optional[float]:
        """Fallback para placas mais antigas (era GCN) onde a PMLog pode
        não existir. iTemperature vem em milésimos de grau."""
        temp = ADLTemperature()
        temp.iSize = ctypes.sizeof(ADLTemperature)
        rc = self._dll.ADL_Overdrive5_Temperature_Get(
            self._adapter_index, 0, ctypes.byref(temp)
        )
        if rc != ADL_OK:
            return None
        return temp.iTemperature / 1000.0

    def get_temperature_celsius(self) -> Optional[float]:
        """Retorna a temperatura real em °C, ou None se a ADL não estiver
        disponível ou nenhuma das duas APIs funcionar nesta placa. Sanidade:
        qualquer valor fora de -10..130°C é tratado como leitura inválida
        (a única forma de chegar num número fisicamente implausível aqui
        seria um offset de struct errado), não uma temperatura real."""
        if not self._init_attempted:
            self._init_attempted = True
            try:
                self._initialize()
            except Exception:
                self._dll = None

        if self._dll is None or self._adapter_index is None:
            return None

        try:
            celsius = self._read_pmlog_edge_temperature()
            if celsius is None:
                celsius = self._read_overdrive5_temperature()
            if celsius is None:
                return None
            if not (-10.0 <= celsius <= 130.0):
                return None
            return celsius
        except Exception:
            return None
