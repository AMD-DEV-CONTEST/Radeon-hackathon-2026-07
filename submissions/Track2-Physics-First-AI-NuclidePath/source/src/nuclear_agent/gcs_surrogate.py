"""Safe, research-only guarded surrogate contract for the Cs/K oracle."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import median
from types import MappingProxyType
from typing import Any
import hashlib, json, math, random, os, tempfile, copy
from .gcs import CsKState, calculate_kd, load_illite_parameters

@dataclass(frozen=True)
class Domain:
    k_log10_min: float=-6.; k_log10_max: float=-1.; cs_log10_min: float=-12.; cs_log10_max: float=-3.; illite_min: float=.01; illite_max: float=1.
    def __post_init__(self):
        vals=asdict(self)
        if not all(math.isfinite(float(v)) for v in vals.values()) or not (self.k_log10_min < self.k_log10_max and self.cs_log10_min < self.cs_log10_max and 0 < self.illite_min < self.illite_max <= 1): raise ValueError('invalid demonstration domain')
    def contains(self,x):
        try:
            if len(x)!=3 or not all(math.isfinite(float(v)) for v in x): return False
            a,b,c=map(float,x); return self.k_log10_min<=a<=self.k_log10_max and self.cs_log10_min<=b<=self.cs_log10_max and self.illite_min<=c<=self.illite_max
        except (TypeError,ValueError,IndexError): return False
@dataclass(frozen=True)
class Dataset: features: tuple; labels: tuple
class SurrogateArtifactError(ValueError): pass

def oracle_parameter_hash(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _oracle(x,path): return math.log10(calculate_kd(load_illite_parameters(path), CsKState(10**x[0],10**x[1],x[2])).bulk_kd_l_kg)
def generate_dataset(samples,seed=0,domain=Domain(),parameter_path=None):
    if samples<1: raise ValueError('samples must be positive')
    path=parameter_path or Path(__file__).parent/'data/parameters/illite_du_puy_cs_k_v1.json'; r=random.Random(seed)
    f=tuple((r.uniform(domain.k_log10_min,domain.k_log10_max),r.uniform(domain.cs_log10_min,domain.cs_log10_max),r.uniform(domain.illite_min,domain.illite_max)) for _ in range(samples))
    return Dataset(f,tuple(_oracle(x,path) for x in f))
def _freeze(x):
    if isinstance(x,dict): return MappingProxyType({k:_freeze(v) for k,v in x.items()})
    if isinstance(x,list): return tuple(_freeze(v) for v in x)
    return x
def _thaw(x):
    if isinstance(x,MappingProxyType): return {k:_thaw(v) for k,v in x.items()}
    if isinstance(x,tuple): return [_thaw(v) for v in x]
    return x
@dataclass(frozen=True)
class SurrogateMetadata:
    model_version:str; oracle_parameter_hash:str; domain:Any; scaler:Any; architecture:Any; train_seed:int; dtype:str; validation_metrics:Any
    schema:str='gcs-surrogate'; schema_version:int=1; validation_seed:int=1; train_size:int=1; validation_size:int=1; metric_definition:str='relative linear Kd error after exp10(log10 Kd)'; acceptance_threshold:float=0.15; research_only:bool=True
    def __post_init__(self):
        for n in ('domain','scaler','architecture','validation_metrics'): object.__setattr__(self,n,_freeze(dict(getattr(self,n))))
    def to_dict(self): return copy.deepcopy({k:_thaw(getattr(self,k)) for k in self.__dataclass_fields__})
    @classmethod
    def from_dict(cls,d):
        required=set(cls.__dataclass_fields__)
        if not isinstance(d,dict) or set(d)!=required: raise ValueError('metadata schema mismatch')
        return cls(**d)
def metadata_for(path,train_seed=0,domain=Domain(),validation_seed=1,train_size=1,validation_size=1,scaler=None,dtype='float32',metrics=None):
    return SurrogateMetadata('gcs-surrogate-v1',oracle_parameter_hash(path),asdict(domain),scaler or {'mean':[0.,0.,0.],'scale':[1.,1.,1.]},{'input_dim':3,'hidden_dims':[64,64],'output_dim':1},train_seed,dtype,metrics or {'max_relative_kd_error':0.,'median_relative_kd_error':0.},validation_seed=validation_seed,train_size=train_size,validation_size=validation_size)
def validate_metadata(m,path):
    try:
        d=m.to_dict(); dom=Domain(**d['domain']); s=d['scaler']; a=d['architecture']; metrics=d['validation_metrics']
        vals=list(s['mean'])+list(s['scale']); ints=('train_seed','validation_seed','train_size','validation_size')
        return d['schema']=='gcs-surrogate' and d['schema_version']==1 and d['model_version']=='gcs-surrogate-v1' and d['metric_definition']=='relative linear Kd error after exp10(log10 Kd)' and m.oracle_parameter_hash==oracle_parameter_hash(path) and set(s)=={'mean','scale'} and len(vals)==6 and all(math.isfinite(float(v)) for v in vals) and all(float(v)>0 for v in s['scale']) and a=={'input_dim':3,'hidden_dims':[64,64],'output_dim':1} and d['dtype'] in ('float32','float64') and all(type(d[k]) is int and d[k]>0 for k in ('train_size','validation_size')) and all(type(d[k]) is int for k in ('train_seed','validation_seed')) and d['train_seed']!=d['validation_seed'] and set(metrics)=={'max_relative_kd_error','median_relative_kd_error'} and all(math.isfinite(float(v)) and float(v)>=0 for v in metrics.values()) and math.isfinite(d['acceptance_threshold']) and d['acceptance_threshold']>=0 and d['research_only'] is True
    except (AttributeError,TypeError,ValueError,KeyError,OverflowError): return False
def validation_metrics(predicted,actual):
    if not predicted or len(predicted)!=len(actual): raise ValueError('empty or mismatched validation set')
    errs=[abs(10**float(p)/10**float(a)-1) for p,a in zip(predicted,actual)]
    return {'max_relative_kd_error':max(errs),'median_relative_kd_error':median(errs)}
try:
 import torch; import torch.nn as nn
except ImportError: torch=None; nn=None
if nn:
 class GCSMLP(nn.Module):
  def __init__(self,hidden_dims=(64,64)):
   super().__init__(); h1,h2=hidden_dims; self.net=nn.Sequential(nn.Linear(3,h1),nn.Tanh(),nn.Linear(h1,h2),nn.Tanh(),nn.Linear(h2,1))
  def forward(self,x): return self.net(x)
else: GCSMLP=None
def _surrogate_predict(model,x,metadata=None):
    p=next(model.parameters()); dtype=p.dtype; mean=metadata.scaler['mean'] if metadata else [0,0,0]; scale=metadata.scaler['scale'] if metadata else [1,1,1]
    if metadata is not None and dtype != getattr(torch, metadata.dtype):
        raise ValueError('model dtype does not match metadata')
    with torch.no_grad():
        y=model((torch.tensor([x],device=p.device,dtype=dtype)-torch.tensor([mean],device=p.device,dtype=dtype))/torch.tensor([scale],device=p.device,dtype=dtype))
        if y.numel()!=1: raise ValueError('wrong output shape')
        v=float(y.reshape(-1)[0]);
        if not math.isfinite(v): raise ValueError('nonfinite output')
        return v
@dataclass(frozen=True)
class Prediction:
    value: Any; accepted: bool; reason: str; used_oracle: bool; log10_kd_l_kg: Any=None
    def __post_init__(self):
        if self.log10_kd_l_kg is None and self.value is not None: object.__setattr__(self,'log10_kd_l_kg',self.value)
def _fallback(x,path,reason):
    try: return Prediction(_oracle(x,path),False,reason,True)
    except Exception: return Prediction(None,False,'oracle_fallback_failed',False)
def predict_guarded(x,model,metadata=None,parameter_path=None,domain=Domain(),max_relative_error=None):
    path=parameter_path or Path(__file__).parent/'data/parameters/illite_du_puy_cs_k_v1.json'
    try: valid=len(x)==3 and all(math.isfinite(float(v)) for v in x); xx=tuple(map(float,x))
    except (TypeError,ValueError,OverflowError): valid=False; xx=()
    if not valid: return Prediction(None,False,'rejected_invalid_input',False)
    if any(abs(v)>300 for v in xx[:2]): return Prediction(None,False,'rejected_extreme_input',False)
    if metadata is not None and validate_metadata(metadata,path): domain=Domain(**metadata.to_dict()['domain'])
    if not domain.contains(xx): return _fallback(xx,path,'outside_domain')
    if model is None or torch is None: return _fallback(xx,path,'model_unavailable')
    if metadata is None or not validate_metadata(metadata,path): return _fallback(xx,path,'metadata_invalid')
    if max_relative_error is not None:
        if (isinstance(max_relative_error,bool) or not isinstance(max_relative_error,(int,float))
                or not math.isfinite(max_relative_error) or max_relative_error < 0
                or max_relative_error > metadata.acceptance_threshold):
            return _fallback(xx,path,'invalid_or_weaker_threshold_override')
    threshold=metadata.acceptance_threshold if max_relative_error is None else float(max_relative_error)
    if metadata.validation_metrics['max_relative_kd_error']>threshold: return _fallback(xx,path,'validation_error_threshold')
    try: return Prediction(_surrogate_predict(model,xx,metadata),True,'accepted',False)
    except Exception: return _fallback(xx,path,'inference_failed_oracle_fallback')
def save_surrogate(path,model,metadata):
    if torch is None: raise RuntimeError('PyTorch is not installed')
    path=Path(path)
    if path.suffix.lower()!='.json' or not validate_metadata(metadata,Path(__file__).parent/'data/parameters/illite_du_puy_cs_k_v1.json'): raise ValueError('invalid metadata or output path')
    state=path.with_suffix('.pt'); marker=path.with_suffix('.integrity.json'); path.parent.mkdir(parents=True,exist_ok=True)
    marker.unlink(missing_ok=True)
    try:
        # State first, metadata second, integrity marker last.  The marker is the
        # commit record: loaders reject every absent, partial, or mismatched pair.
        for target,writer in ((state,lambda t:torch.save({k:v.detach().cpu() for k,v in model.state_dict().items()},t)), (path,lambda t:t.write_text(json.dumps(metadata.to_dict(),sort_keys=True),encoding='utf-8'))):
            fd,tmp=tempfile.mkstemp(dir=path.parent); os.close(fd)
            try: writer(Path(tmp)); os.replace(tmp,target)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
        integrity={'metadata_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'state_sha256':hashlib.sha256(state.read_bytes()).hexdigest()}
        fd,tmp=tempfile.mkstemp(dir=path.parent); os.close(fd)
        try:
            Path(tmp).write_text(json.dumps(integrity,sort_keys=True),encoding='utf-8')
            os.replace(tmp,marker)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    except Exception:
        marker.unlink(missing_ok=True); path.unlink(missing_ok=True); state.unlink(missing_ok=True)
        raise
    try:
        load_surrogate(path,Path(__file__).parent/'data/parameters/illite_du_puy_cs_k_v1.json')
    except Exception as exc:
        path.unlink(missing_ok=True)
        state.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        raise SurrogateArtifactError('post-save integrity verification failed') from exc
def load_surrogate(path,parameter_path=None):
    if torch is None: raise SurrogateArtifactError('PyTorch is not installed')
    try:
        path=Path(path); state_path=path.with_suffix('.pt'); marker_path=path.with_suffix('.integrity.json')
        integrity=json.loads(marker_path.read_text(encoding='utf-8'))
        if (not isinstance(integrity,dict) or set(integrity)!={'metadata_sha256','state_sha256'}
                or integrity['metadata_sha256']!=hashlib.sha256(path.read_bytes()).hexdigest()
                or integrity['state_sha256']!=hashlib.sha256(state_path.read_bytes()).hexdigest()):
            raise ValueError('artifact pair integrity mismatch')
        m=SurrogateMetadata.from_dict(json.loads(path.read_text(encoding='utf-8')))
        if parameter_path and not validate_metadata(m,parameter_path): raise ValueError('metadata mismatch')
        hidden=tuple(m.architecture['hidden_dims']); model=GCSMLP(hidden).to(dtype=getattr(torch,m.dtype)); payload=torch.load(state_path,map_location='cpu',weights_only=True)
        expected={'net.0.weight':(hidden[0],3),'net.0.bias':(hidden[0],),'net.2.weight':(hidden[1],hidden[0]),'net.2.bias':(hidden[1],),'net.4.weight':(1,hidden[1]),'net.4.bias':(1,)}
        if set(payload)!=set(expected): raise ValueError('invalid tensor state schema')
        for k,shape in expected.items():
            if tuple(payload[k].shape)!=shape or str(payload[k].dtype)!=str(getattr(torch,m.dtype)): raise ValueError('invalid tensor shape or dtype')
        model.load_state_dict(payload); model.eval(); return model,m
    except SurrogateArtifactError: raise
    except Exception as e: raise SurrogateArtifactError(f'invalid surrogate artifact: {e}') from e
