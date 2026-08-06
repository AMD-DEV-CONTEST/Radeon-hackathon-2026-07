import type { RobotManifest } from './robotApi'

/** Shown when /api/robots fails — users can still enter wizards. */
export const FALLBACK_ROBOT_MANIFESTS: RobotManifest[] = [
  {
    runtime_id: 'so101',
    robot_type: 'so101',
    display_name: 'SO-101 Follower Arm',
    joint_count: 6,
    urdf_url: '/api/urdf/so101.urdf',
    capabilities: { teleop: true, record: true, train: true, inference: true },
    ui: {
      route: '/robots/so101',
    },
  },
  {
    runtime_id: 'reachy_mini',
    robot_type: 'reachy_mini',
    display_name: 'Reachy Mini',
    joint_count: 7,
    urdf_url: '/api/urdf/reachy_mini/reachy_mini.urdf',
    capabilities: { teleop: true, virtual: true },
    ui: { route: '/robots/reachy_mini' },
  },
  {
    runtime_id: 'b601_rs',
    robot_type: 'b601_rs',
    display_name: 'reBot B601-RS',
    joint_count: 7,
    urdf_url: '/api/urdf/b601_rs/b601_rs.urdf',
    capabilities: { teleop: true, record: true, train: true, inference: true, motor_recovery: true },
    ui: {
      route: '/robots/b601_rs',
    },
  },
]
