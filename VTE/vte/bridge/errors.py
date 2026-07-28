class VTEError(Exception):
    """Exceção base do VTE"""
    pass

class HIPSafetyError(VTEError):
    """Exceção levantada quando barreira de segurança é violada"""
    pass

class HIPRuntimeError(VTEError):
    """Exceção para erros do runtime HIP"""
    pass
