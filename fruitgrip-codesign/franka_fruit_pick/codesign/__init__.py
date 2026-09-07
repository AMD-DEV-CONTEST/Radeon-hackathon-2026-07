"""Task-adaptive end-effector co-design on top of the Franka fruit-pick demo.

Everything in this package is additive: it does not modify `franka_fruit_pick`'s
M1-M5 pipeline, it composes with it. The Franka arm (7 DOF), its base, and the
palm/mount geometry are held fixed per the project's invariants -- the only free
variable is the finger geometry of the parallel/multi-jaw end-effector.

Modules
-------
gripper_gen       Parametric MJCF generator for the finger geometry (structurally
                   valid by construction: primitive capsule chains, no mesh/URDF
                   generation or convex decomposition needed).
sim_episode       Generalized (N-finger) scripted pick-and-place episode runner,
                   with contact-force based grasp-stability / peak-stress metrics.
controller_adapt  Per-design controller (GraspProfile) adaptation -- the reward
                   co-adapts with the body instead of holding a fixed policy over
                   changing geometry.
evaluate          Multi-trial candidate scoring under the existing Layer-B domain
                   randomization, with a fixed trial budget/instance set so every
                   candidate (and the baseline) is compared symmetrically.
surrogate         Optional cheap regressor to screen candidates before they are
                   confirmed in real simulation (screen only -- never reported).
search            CMA-ES driver (per finger-count branch) with a diversity/niching
                   bonus, over the evaluate() scoring function.
diagnostics       Behavioral-diversity ("A1") and trajectory-logging diagnostics.
"""
