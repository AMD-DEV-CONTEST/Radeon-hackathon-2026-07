import unittest

from parcel_sorter.mobile_harness import MobileHarnessConfig
from parcel_sorter.mobile_vla_service import (
    SERVICE_PROTOCOL,
    dispatch_policy_service_request,
)


class _FakeController:
    def __init__(self) -> None:
        self.reset_count = 0
        self.config = None

    def reset_runtime_state(self) -> None:
        self.reset_count += 1

    def select(self, **kwargs):
        return (1.0, 2.0), {"stage": kwargs["stage"]}

    def set_harness_config(self, config) -> None:
        self.config = config

    def observe_contact_forces(self, left, right) -> None:
        self.forces = (left, right)

    def clear_action_chunk(self) -> None:
        self.cleared = True


def _request(command: str, **payload):
    return {"protocol": SERVICE_PROTOCOL, "command": command, **payload}


class MobileVLAServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = _FakeController()

    def dispatch(self, request, episode_index=-1):
        return dispatch_policy_service_request(
            self.controller,
            request,
            session_id="session-1",
            episode_index=episode_index,
            description={"policy_type": "pi05"},
        )

    def test_begin_episode_resets_state_and_increments_index(self) -> None:
        reply, close, index = self.dispatch(_request("begin_episode"))
        self.assertTrue(reply["ok"])
        self.assertFalse(close)
        self.assertEqual(index, 0)
        self.assertEqual(self.controller.reset_count, 1)

    def test_select_attaches_persistent_attribution(self) -> None:
        reply, _, index = self.dispatch(
            _request("select", kwargs={"stage": "transport"}), episode_index=4
        )
        telemetry = reply["result"]["telemetry"]
        self.assertEqual(index, 4)
        self.assertEqual(telemetry["policy_runtime_session_id"], "session-1")
        self.assertEqual(telemetry["policy_runtime_episode_index"], 4)
        self.assertTrue(telemetry["persistent_policy_service"])

    def test_harness_config_is_reconstructed_from_audited_fields(self) -> None:
        config = MobileHarnessConfig(min_progress_ratio=0.75)
        reply, _, _ = self.dispatch(
            _request("set_harness_config", config=config.__dict__)
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(self.controller.config, config)

    def test_protocol_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "protocol mismatch"):
            self.dispatch({"protocol": "wrong", "command": "describe"})


if __name__ == "__main__":
    unittest.main()
