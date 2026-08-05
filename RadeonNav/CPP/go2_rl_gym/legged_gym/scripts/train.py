import os
import numpy as np
from datetime import datetime
import sys

import isaacgym
from legged_gym.envs import *
from legged_gym.utils import get_args, task_registry
import torch

def train(args):
    env, env_cfg = task_registry.make_env(name=args.task, args=args)
    runner, train_cfg = task_registry.make_alg_runner(env=env, name=args.task, args=args)
    env.common_step_counter = runner.current_learning_iteration * env.num_steps_per_env  # resume env step counter
    env.update_reward_curriculum(force_update=True)  # force update reward curriculum at start
    runner.learn(num_learning_iterations=train_cfg.runner.max_iterations, init_at_random_ep_len=True)

if __name__ == '__main__':
    args = get_args()
    train(args)
