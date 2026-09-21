import numpy as np

from smolvla_qvgm_rlinf.processors import ActionTransform


def test_action_roundtrip_with_checkpoint_statistics():
    transform = ActionTransform(
        offset=np.array([0.1, -0.2, 0.3, 0, 0.2, -0.1, 0]),
        scale=np.array([0.5, 0.4, 0.3, 1, 0.8, 0.7, 1]),
        clip=False,
    )
    action = np.linspace(-0.8, 0.8, 21, dtype=np.float32).reshape(3, 7)
    recovered = transform.unnormalize(transform.normalize(action))
    np.testing.assert_allclose(recovered, action, atol=1e-6)


def test_identity_execution_clips_and_binarizes_gripper():
    transform = ActionTransform.identity()
    action = np.array([[1.2, -1.3, 0, 0, 0, 0, 0.01]], dtype=np.float32)
    executable = transform.unnormalize(transform.normalize(action))
    np.testing.assert_allclose(executable[0, :2], [1, -1])
    np.testing.assert_allclose(transform.binarize_gripper(executable)[0, -1], 1)
