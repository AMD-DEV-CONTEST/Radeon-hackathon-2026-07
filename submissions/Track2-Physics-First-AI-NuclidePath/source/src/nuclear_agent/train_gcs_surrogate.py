"""Reproducible, independently validated GCS surrogate trainer."""
import argparse, json, random
from pathlib import Path
from nuclear_agent.gcs_surrogate import *

def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('--samples',type=int,default=256); p.add_argument('--epochs',type=int,default=50); p.add_argument('--seed',type=int,default=0); p.add_argument('--validation-seed',type=int,default=1); p.add_argument('--device',choices=['cpu','cuda'],default='cpu'); p.add_argument('--dtype',choices=['float32','float64'],default='float32'); p.add_argument('--output',required=True); a=p.parse_args(argv)
 if a.samples<2 or a.epochs<1: p.error('--samples must be >=2 and --epochs positive')
 if a.seed == a.validation_seed: p.error('--seed and --validation-seed must differ')
 if torch is None: p.error('PyTorch is required for training')
 if a.device == 'cuda' and not torch.cuda.is_available(): p.error('--device cuda requested but CUDA/ROCm is unavailable')
 random.seed(a.seed); torch.manual_seed(a.seed); torch.use_deterministic_algorithms(True)
 path=Path(__file__).parent/'data/parameters/illite_du_puy_cs_k_v1.json'; ntrain=a.samples//2; train=generate_dataset(ntrain,a.seed,parameter_path=path); val=generate_dataset(a.samples-ntrain,a.validation_seed,parameter_path=path)
 dtype=getattr(torch,a.dtype); x=torch.tensor(train.features,device=a.device,dtype=dtype); y=torch.tensor(train.labels,device=a.device,dtype=dtype).reshape(-1,1); model=GCSMLP().to(device=a.device,dtype=dtype); opt=torch.optim.Adam(model.parameters(),lr=.01)
 mean=x.mean(0); scale=x.std(0).clamp_min(torch.finfo(dtype).eps); model.train()
 for _ in range(a.epochs): opt.zero_grad(); loss=((model((x-mean)/scale)-y)**2).mean(); loss.backward(); opt.step()
 model.eval(); vx=torch.tensor(val.features,device=a.device,dtype=dtype); vm=validation_metrics(model((vx-mean)/scale).reshape(-1).detach().cpu().tolist(),val.labels)
 meta=metadata_for(path,a.seed,train_size=len(train.features),validation_size=len(val.features),validation_seed=a.validation_seed,scaler={'mean':mean.cpu().tolist(),'scale':scale.cpu().tolist()},dtype=a.dtype,metrics=vm)
 save_surrogate(a.output,model,meta); print(json.dumps(vm,sort_keys=True)); return 0
if __name__=='__main__': main()
