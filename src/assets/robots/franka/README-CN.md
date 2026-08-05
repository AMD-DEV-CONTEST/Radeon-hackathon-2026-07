# Franka Emika Panda 描述文件（MJCF）

需要 MuJoCo 2.3.3 或更高版本。

## 概述

本包包含 [Franka Emika Panda](https://www.franka.de/) 的简化机器人
描述文件（MJCF），该机器人由 [Franka Emika](https://www.franka.de/company)
开发。它源自[公开可用的 URDF 描述文件](https://github.com/frankaemika/franka_ros/tree/develop/franka_description)。

<p float="left">
  <img src="panda.png" width="400">
</p>

## URDF → MJCF 转换步骤

1. 使用 [Blender](https://www.blender.org/) 将 DAE [网格文件](https://github.com/frankaemika/franka_ros/tree/develop/franka_description/meshes/visual)转换为 OBJ 格式。
2. 用 [`obj2mjcf`](https://github.com/kevinzakka/obj2mjcf) 处理 `.obj` 文件。
3. 从为 `link0` 创建的结果子网格中删除了完全平坦的 `link0_6`。
4. 使用 [V-HACD](https://github.com/kmammou/v-hacd) 为 `link5` 的 STL 碰撞[网格文件](https://github.com/frankaemika/franka_ros/tree/develop/franka_description/meshes/collision)创建了凸分解。
5. 在 [URDF](https://github.com/frankaemika/franka_ros/tree/develop/franka_description/robots) 的 `<robot>` 子句中添加了 `<mujoco> <compiler discardvisual="false"/> </mujoco>`，以保留视觉几何体。
6. 将 URDF 加载到 MuJoCo 中并保存为对应的 MJCF 文件。
7. 与 [inertial.yaml](https://github.com/frankaemika/franka_ros/blob/develop/franka_description/robots/common/inertial.yaml) 中的惯性参数进行了匹配。
8. 在基座添加了一个追踪光源。
9. 手动编辑 MJCF，将公共属性提取到 `<default>` 部分。
10. 添加了 `<exclude>` 子句以防止 `link7` 和 `link8` 之间的碰撞。
11. 为指尖手动设计了碰撞几何体。
12. 为机械臂添加了位置控制执行器。
13. 添加了等式约束，使左手指模仿右手指的位置。
14. 添加了腱绳以将力平均分配给两个手指，以及一个作用于此腱绳的位置执行器。
15. 添加了 `scene.xml`，包含机器人、带纹理的地面平面、天空盒和雾效。

## 许可证

本模型基于 [Apache-2.0 许可证](LICENSE) 发布。
