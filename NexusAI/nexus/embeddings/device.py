from dataclasses import dataclass
@dataclass
class DeviceInfo:
    torch_available:bool;accelerator_available:bool;backend:str;device_name:str;torch_version:str|None;hip_version:str|None
def detect_device():
    try: import torch
    except ImportError:return DeviceInfo(False,False,"cpu","CPU",None,None)
    available=torch.cuda.is_available();hip=getattr(torch.version,"hip",None)
    if available:return DeviceInfo(True,True,"rocm" if hip else "cuda",torch.cuda.get_device_name(0),torch.__version__,hip)
    return DeviceInfo(True,False,"cpu","CPU",torch.__version__,hip)
