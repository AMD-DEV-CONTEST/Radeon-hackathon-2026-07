"""
DUNE (Deep Unfolded Neural Encoder) is the core class of the PAN class. It maps the point flow to the latent distance space: mu and lambda. 

Developed by Ruihua Han
Copyright (c) 2025 Ruihua Han <hanrh@connect.hku.hk>

NeuPAN planner is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

NeuPAN planner is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with NeuPAN planner. If not, see <https://www.gnu.org/licenses/>.
"""


import torch
from math import inf
from neupan.blocks import ObsPointNet, DUNETrain
from neupan.configuration import np_to_tensor
from neupan.util import time_it, file_check, repeat_mk_dirs
from typing import Optional
import sys


_DTYPE_ALIASES = {
    "float16": torch.float16,
    "fp16": torch.float16,
    "half": torch.float16,
    "float32": torch.float32,
    "fp32": torch.float32,
    "float": torch.float32,
    "bfloat16": torch.bfloat16,
    "bf16": torch.bfloat16,
}


class DUNE(torch.nn.Module):

    def __init__(
        self,
        receding: int = 10,
        checkpoint=None,
        robot=None,
        dune_max_num: int = 100,
        train_kwargs: Optional[dict] = None,
        inference_device: Optional[str | torch.device] = None,
        inference_dtype: Optional[str | torch.dtype] = None,
    ) -> None:
        super(DUNE, self).__init__()

        if train_kwargs is None:
            train_kwargs = dict()

        if robot is None:
            raise ValueError("robot parameter is required and cannot be None")

        self.T = receding
        self.max_num = dune_max_num

        self.robot = robot

        self.G = np_to_tensor(robot.G)
        self.h = np_to_tensor(robot.h)
        self.edge_dim = self.G.shape[0]
        self.state_dim = self.G.shape[1]

        # NeuPAN's optimization tensors stay on the planner device (normally CPU),
        # while the small learned DUNE model may run on a separate accelerator.
        # Keeping this boundary inside DUNE prevents cvxpylayers from receiving a
        # CUDA/ROCm tensor and trying to convert it directly to NumPy.
        self.planner_device = self.G.device
        self.planner_dtype = self.G.dtype
        self.inference_device = self._resolve_inference_device(inference_device)
        self.inference_dtype = self._resolve_inference_dtype(inference_dtype)

        self.model = ObsPointNet(2, self.edge_dim).to(
            device=self.planner_device, dtype=self.planner_dtype
        )
        self.load_model(checkpoint, train_kwargs)

        self.obstacle_points = None
        self.min_distance = inf

    def _resolve_inference_device(
        self, requested: Optional[str | torch.device]
    ) -> torch.device:
        if requested is None:
            return self.planner_device
        if isinstance(requested, str) and requested.lower() == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")

        device = torch.device(requested)
        if device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(
                "DUNE inference requested device='cuda', but PyTorch cannot access "
                "a CUDA/ROCm device. Use inference_device='cpu' or install a "
                "compatible CUDA/ROCm PyTorch build."
            )
        return device

    def _resolve_inference_dtype(
        self, requested: Optional[str | torch.dtype]
    ) -> torch.dtype:
        if requested is None:
            return self.planner_dtype
        if isinstance(requested, torch.dtype):
            dtype = requested
        else:
            try:
                dtype = _DTYPE_ALIASES[requested.lower()]
            except (AttributeError, KeyError) as exc:
                choices = ", ".join(sorted(_DTYPE_ALIASES))
                raise ValueError(
                    f"Unsupported DUNE inference dtype {requested!r}; choose one of: "
                    f"{choices}"
                ) from exc

        if dtype not in (torch.float16, torch.float32, torch.bfloat16):
            raise ValueError(
                "DUNE inference dtype must be float16, float32, or bfloat16, "
                f"got {dtype}"
            )
        return dtype

    def _prepare_inference_model(self) -> None:
        self.model.to(device=self.inference_device, dtype=self.inference_dtype)
        self.model.eval()


        
    @time_it('- dune forward')
    def forward(self, point_flow: list[torch.Tensor], R_list: list[torch.Tensor], obs_points_list: list[torch.Tensor]=[]) -> tuple[list[torch.Tensor], list[torch.Tensor], list[torch.Tensor]]:

        '''
        map point flow to the latent distance features: lam, mu

        Args:
            point_flow: point flow under the robot coordinate, list of (state_dim, num_points); list length: T+1
            R_list: list of Rotation matrix, list of (2, 2), used to generate the lam from mu; list length: T
            obstacle_points: tensor of shape (2, num_points), global coordinate; 

        Returns: 
            lam_list: list of lam tensor, each element is a tensor of shape (state_dim, num_points); list length: T+1
            mu_list: list of mu tensor, each element is a tensor of shape (edge_number, num_points); list length: T+1
            sort_point_list: list of point tensor, each element is a tensor of shape (state_dim, num_points); list length: T+1; 
        '''

        mu_list, lam_list, sort_point_list = [], [], []
        self.obstacle_points = obs_points_list[0] # current obstacle points considered in the dune at time 0

        total_points = torch.hstack(point_flow)
        
        # map the point flow to the latent distance features mu
        with torch.no_grad():
            model_input = total_points.T.to(
                device=self.inference_device, dtype=self.inference_dtype
            )
            total_mu = self.model(model_input).T.to(
                device=total_points.device, dtype=total_points.dtype
            )
        
        for index in range(self.T+1):
            num_points = point_flow[index].shape[1]
            mu = total_mu[:, index*num_points : (index+1)*num_points]
            R = R_list[index]
            p0 = point_flow[index]
            lam = (- R @ self.G.T @ mu)

            if mu.ndim == 1:
                mu = mu.unsqueeze(1)
                lam = lam.unsqueeze(1)

            distance = self.cal_objective_distance(mu, p0)

            if index == 0: 
                self.min_distance = torch.min(distance) 
            
            sort_indices = torch.argsort(distance)

            mu_list.append(mu[:, sort_indices])
            lam_list.append(lam[:, sort_indices])
            sort_point_list.append(obs_points_list[index][:, sort_indices])

        return mu_list, lam_list, sort_point_list


    def cal_objective_distance(self, mu: torch.Tensor, p0: torch.Tensor) -> torch.Tensor:

        '''
        input: 
            mu: (edge_dim, num_points)
            p0: (state_dim, num_points)   
        output:
            distance:  mu.T (G @ p0 - h),  (num_points,)
        ''' 

        temp = (self.G @ p0 - self.h).T.unsqueeze(2)
        muT = mu.T.unsqueeze(1)

        distance = torch.squeeze(torch.bmm(muT, temp)) 

        if distance.ndim == 0:
            distance = distance.unsqueeze(0)

        return distance
    


    def load_model(self, checkpoint: Optional[str]=None, train_kwargs: Optional[dict]=None):

        '''
        checkpoint: pth file path of the model
        '''

        try:
            if checkpoint is None:
                raise FileNotFoundError

            self.abs_checkpoint_path = file_check(checkpoint)
            self.model.load_state_dict(
                torch.load(
                    self.abs_checkpoint_path, map_location=torch.device("cpu")
                )
            )
            self._prepare_inference_model()

        except FileNotFoundError:

            if train_kwargs is None or len(train_kwargs) == 0:
                print('No train kwargs provided. Default value will be used.')
                train_kwargs = dict()
            
            direct_train = train_kwargs.get('direct_train', False)

            if direct_train:
                print('train or test the model directly.')
                return 

            if self.ask_to_train():
                self.train_dune(train_kwargs)

                if self.ask_to_continue():
                    self.model.load_state_dict(
                        torch.load(
                            self.full_model_name, map_location=torch.device("cpu")
                        )
                    )
                    self._prepare_inference_model()
                else:
                    print('You can set the new model path to the DUNE class to use the trained model.') 

            else:
                print('Can not find checkpoint. Please check the path or train first.')
                raise FileNotFoundError


    def train_dune(self, train_kwargs):

        model_name = train_kwargs.get("model_name", self.robot.name)

        checkpoint_path = sys.path[0] + '/model' + '/' + model_name
        checkpoint_path = repeat_mk_dirs(checkpoint_path)
        
        # DUNE training continues to follow the top-level NeuPAN planner device.
        # Restore the independently placed inference model after training.
        self.model.to(device=self.planner_device, dtype=self.planner_dtype)
        self.train_model = DUNETrain(self.model, self.G, self.h, checkpoint_path)
        try:
            self.full_model_name = self.train_model.start(**train_kwargs)
        finally:
            self._prepare_inference_model()
        print('Complete Training. The model is saved in ' + self.full_model_name)

    def ask_to_train(self):

        while True:
            choice = input("Do not find the DUNE model; Do you want to train the model now, input Y or N:").upper()
            if choice == 'Y':
                return True
            elif choice == 'N':
                print('Please set the your model path for the DUNE layer.')
                raise FileNotFoundError("DUNE model checkpoint not found and training was declined by user.")
            else:
                print("Wrong input, Please input Y or N.")


    def ask_to_continue(self):

        while True:
            choice = input("Do you want to continue the case running, input Y or N:").upper()
            if choice == 'Y':
                return True
            elif choice == 'N':
                print('exit the case running.')
                raise RuntimeError("User declined to continue after training DUNE model.")
            else:
                print("Wrong input, Please input Y or N.")


    @property
    def points(self):
        '''
        point considered in the dune layer
        '''

        return self.obstacle_points

    @property
    def model_device(self) -> torch.device:
        """Device used only by the learned DUNE point encoder."""

        return next(self.model.parameters()).device
