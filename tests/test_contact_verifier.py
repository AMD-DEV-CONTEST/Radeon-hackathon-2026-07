from controller.contact_verifier import ContactAwareGraspVerifier, ContactVerifierConfig


def test_contact_verifier_requires_dual_finger_evidence():
    verifier = ContactAwareGraspVerifier(ContactVerifierConfig(
        min_consecutive_dual_finger_steps=3, unverified_lift_grace_steps=2,
    ))
    verifier.update({"is_grasped": True, "consecutive_dual_finger_contact_steps": 2})
    assert not verifier.grasp_verified
    assert not verifier.requires_recovery_before_transport()
    assert verifier.requires_recovery_before_transport()
    verifier.update({"is_grasped": True, "consecutive_dual_finger_contact_steps": 3})
    assert verifier.grasp_verified
    assert not verifier.requires_recovery_before_transport()
