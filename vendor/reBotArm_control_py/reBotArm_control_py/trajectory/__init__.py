"""reBot-DevArm 轨迹规划包。

提供 SE(3) 测地线轨迹采样与 CLIK 关节空间跟踪。
"""

from .sampler import (
    TrajProfile,
    TrajPlanParams,
    CartesianPoint,
    CartesianTrajectory,
    CartesianTrajectoryResult,
    plan_cartesian_geodesic_trajectory,
)
from .clik_tracker import (
    IKParams,
    JointTrajectoryPoint,
    track_trajectory,
)
from .trajectory_planner import (
    TrajStats,
    plan_joint_space_trajectory,
    compute_traj_stats,
)

__all__ = [
    # 采样器
    "TrajProfile",
    "TrajPlanParams",
    "CartesianPoint",
    "CartesianTrajectory",
    "CartesianTrajectoryResult",
    "plan_cartesian_geodesic_trajectory",
    # CLIK 跟踪器
    "CLIKParams",
    "IKParams",     # 向后兼容别名
    "JointTrajectoryPoint",
    "track_trajectory",
    # 规划器
    "TrajStats",
    "plan_joint_space_trajectory",
    "compute_traj_stats",
]
