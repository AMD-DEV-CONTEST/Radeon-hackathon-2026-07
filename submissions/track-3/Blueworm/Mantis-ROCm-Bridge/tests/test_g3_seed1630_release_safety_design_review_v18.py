"""Static, standard-library-only design-review tests for WP-G3-CORR-016.

These tests validate the WP-G3-CORR-016 read-only design review deterministically.
They do NOT run or import Genesis or any simulator; they parse frozen local
source text, the frozen WP-015 boundary trace, and the v18 contract. The two
collision classifiers are modeled as faithful single-pair predicates (see each
helper's docstring for its exact scope vs. the source); the multi-pair ``all(...)``
form of the scripted rule is asserted directly against source text. All numerics
are reproducible from the frozen inputs.
"""

import hashlib
import json
import math
import os
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _abspath(rel: str) -> str:
    return os.path.join(REPO_ROOT, rel)


def _sha256(rel: str) -> str:
    with open(_abspath(rel), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _read_text(rel: str) -> str:
    with open(_abspath(rel), "r", encoding="utf-8") as handle:
        return handle.read()


def _load_json(rel: str) -> dict:
    with open(_abspath(rel), "r", encoding="utf-8") as handle:
        return json.load(handle)


CONTRACT = _load_json(
    "configs/g3-seed1630-release-safety-design-review-v18.json"
)
TRACE = _load_json(
    "receipts/g3-seed1630-release-retreat-boundary-terminal-20260729-v16/"
    "run/release_retreat_boundary_trace.json"
)
OVERLAY = _load_json("configs/mantis-rim-support-overlay-v4.json")
SCENE = _load_json("configs/stack-bowls-genesis-v1.json")
TASK = _load_json("configs/task-pack-v1.json")


# --- quaternion helpers (standard library only) -----------------------------


def _quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return [
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ]


def _quat_conj(q):
    w, x, y, z = q
    return [w, -x, -y, -z]


def _quat_rotate(q, v):
    r = _quat_mul(_quat_mul(q, [0.0, v[0], v[1], v[2]]), _quat_conj(q))
    return [r[1], r[2], r[3]]


def _quat_inv_rotate(q, v):
    return _quat_rotate(_quat_conj(q), v)


def _rpy_to_quat(roll, pitch, yaw):
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    return [
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ]


# --- classifier predicates (single-pair models; see each docstring) ---------


def act_g3_allows(pair: str) -> bool:
    """Faithful single-pair re-implementation of _is_clamp_robot_bowl_pair.

    Allowed iff every robot geometry in the pair is a left/right clamp link.
    Stage- and side-independent; no active-bowl skip. This is a single-pair
    evaluation; the source applies this predicate to every robot-bowl contact.
    """

    labels = pair.split(" <> ")

    def is_robot(label):
        return label.startswith("mantis:")

    def is_table(label):
        return label.startswith("table:")

    def is_clamp(label):
        return any(
            label.startswith("mantis:%s_clamp" % side)
            for side in ("left", "right")
        )

    robot_labels = [label for label in labels if is_robot(label)]
    other_labels = [
        label
        for label in labels
        if not is_robot(label) and not is_table(label)
    ]
    if not robot_labels or not other_labels:
        return False
    return all(is_clamp(label) for label in robot_labels)


def scripted_allows(pair: str, stage: str, active_side, is_selected: bool) -> bool:
    """Representative single-pair projection of sample_safety's allow rule.

    This is NOT a line-for-line copy of sample_safety: the source iterates every
    nonselected bowl and applies ``all(f"mantis:{active_side_name}_clamp" in pair
    for pair in pairs)`` across the full pair list for that bowl, whereas this
    helper evaluates the allow predicate on one representative pair. It captures
    the stage/side gating used for the parity matrix (selected bowl skipped;
    nonselected allowed only during place/release on the active side). The
    multi-pair ``all(...)`` form is asserted directly against the source text in
    TestScriptedClassifierSource; it is not reproduced here.
    """

    if is_selected:
        return True
    suffix = stage.split(":")[-1]
    expected = (
        active_side is not None
        and suffix in {"place", "release"}
        and ("mantis:%s_clamp" % active_side) in pair
    )
    return bool(expected)


# --- tests ------------------------------------------------------------------


class TestInputIdentity(unittest.TestCase):
    def test_authoritative_input_sha256_pins(self):
        for entry in CONTRACT["authoritative_inputs"]:
            self.assertEqual(
                _sha256(entry["path"]),
                entry["sha256"],
                "hash drift for %s" % entry["path"],
            )

    def test_boundary_trace_sha256_pin(self):
        ev = CONTRACT["entry_evidence"]
        rel = ev["boundary_trace"]
        self.assertEqual(_sha256(rel), ev["boundary_trace_sha256"])

    def test_predecessor_receipt_manifest_and_terminal_pins(self):
        ev = CONTRACT["entry_evidence"]
        root = ev["predecessor_receipt"]  # trailing slash
        manifest_rel = root + "RECEIPT.SHA256SUMS"
        terminal_rel = root + "terminal.json"
        self.assertEqual(
            _sha256(manifest_rel),
            ev["predecessor_receipt_manifest_sha256"],
        )
        self.assertEqual(
            _sha256(terminal_rel),
            ev["predecessor_terminal_json_sha256"],
        )

    def test_trace_predecessor_binding(self):
        self.assertEqual(TRACE["work_package_id"], "WP-G3-CORR-015")
        self.assertEqual(TRACE["seed"], CONTRACT["entry_evidence"].get("seed", 1630)
                         if "seed" in CONTRACT.get("entry_evidence", {})
                         else 1630)
        # The contract references seed 1630 implicitly via the phase name; pin it.
        self.assertEqual(TRACE["seed"], 1630)


class TestChronology(unittest.TestCase):
    def setUp(self):
        self.by_label = {snap["label"]: snap for snap in TRACE["snapshots"]}

    def test_exact_five_labels_in_order(self):
        expected = [
            "final_pre_release",
            "immediate_post_release",
            "pre_retreat",
            "retreat_step_1",
            "retreat_step_2",
        ]
        self.assertEqual([s["label"] for s in TRACE["snapshots"]], expected)

    def test_final_pre_release_has_robot_bowl2_contact_target_absent(self):
        snap = self.by_label["final_pre_release"]
        self.assertEqual(snap["robot_bowl2_contact_pair_count"], 2)
        for pair in snap["robot_bowl2_contact_pairs"]:
            self.assertIn("source_mesh_collision", pair)
        self.assertFalse(snap["target_pair_present"])
        # No rim-support primitive present pre-release.
        for pair in snap["robot_bowl2_contact_pairs"]:
            self.assertNotIn("competition_rim_support_collision", pair)

    def test_target_sequence(self):
        seq = [s["target_pair_present"] for s in TRACE["snapshots"]]
        self.assertEqual(seq, [False, True, True, True, True])

    def test_post_pre_retreat_cache_identical_excluding_label(self):
        post = dict(self.by_label["immediate_post_release"])
        pre = dict(self.by_label["pre_retreat"])
        post.pop("label")
        pre.pop("label")
        self.assertEqual(post, pre)
        # And specifically the same physics/observation clock.
        self.assertEqual(
            self.by_label["immediate_post_release"]["contact_cache_source_physics_step"],
            self.by_label["pre_retreat"]["contact_cache_source_physics_step"],
        )

    def test_endpoint_collider_identity_transition(self):
        # Endpoint observations only: proves the collider identity at the two
        # snapshotted endpoints (source_mesh at 11768, rim-support primitive at
        # 12023). It does NOT verify a continuous handoff and does NOT rule out
        # a 2 -> 0 -> 1 path in the unobserved intervening steps.
        pre_pairs = self.by_label["final_pre_release"]["robot_bowl2_contact_pairs"]
        post_pairs = self.by_label["immediate_post_release"]["robot_bowl2_contact_pairs"]
        # Pre endpoint: source mesh only.
        self.assertTrue(all("source_mesh_collision" in p for p in pre_pairs))
        # Post endpoint: the competition rim-support primitive (target pair).
        self.assertEqual(len(post_pairs), 1)
        self.assertIn("competition_rim_support_collision", post_pairs[0])
        self.assertEqual(post_pairs[0], TRACE["target_pair"])

    def test_no_exact_onset_claim_in_analysis(self):
        analysis = _read_text(
            ".ops/wip/g3-seed1630-release-safety-design-review-20260729/ANALYSIS.md"
        )
        # The analysis must explicitly decline to assert an exact onset.
        self.assertIn("do not claim an exact", analysis.lower().replace("**", ""))


class TestGeometry(unittest.TestCase):
    def setUp(self):
        self.by_label = {snap["label"]: snap for snap in TRACE["snapshots"]}
        geo = OVERLAY["geometry"]
        self.half = [s / 2.0 for s in geo["size_xyz_m"]]
        self.origin = geo["origin_xyz_m"]
        self.rpy = geo["per_link_origin_rpy_rad"]["left_clamp_left_link"]
        self.q_box = _rpy_to_quat(*self.rpy)

    def _contact_in_box(self, snap):
        link = snap["left_clamp_poses"]["left_clamp_left_link"]
        t_link = link["position_xyz_m"]
        q_link = link["quaternion_wxyz"]
        contact_world = snap["robot_bowl2_contact_diagnostics"]["position"]["values"]
        delta = [contact_world[i] - t_link[i] for i in range(3)]
        contact_link = _quat_inv_rotate(q_link, delta)
        rel = [contact_link[i] - self.origin[i] for i in range(3)]
        return _quat_inv_rotate(self.q_box, rel)

    def _inside(self, box_local, tol=0.0):
        return all(abs(box_local[i]) <= self.half[i] + tol for i in range(3))

    def test_post_and_pre_retreat_target_within_v4_box(self):
        for label in ("immediate_post_release", "pre_retreat"):
            box_local = self._contact_in_box(self.by_label[label])
            self.assertTrue(self._inside(box_local), (label, box_local, self.half))

    def test_retreat_step1_within_v4_box(self):
        box_local = self._contact_in_box(self.by_label["retreat_step_1"])
        self.assertTrue(self._inside(box_local), box_local)

    def test_retreat_step2_strictly_inside_using_own_link_pose(self):
        # Using retreat_step_2's OWN link pose (required: the overlay is rigidly
        # attached to the link), the contact is strictly inside the v4 OBB. An
        # earlier -18 um "residual" was an artifact of transforming this contact
        # with the post-release link pose; this test pins the correct same-step
        # transform and asserts strict containment (not a boundary residual).
        box_local = self._contact_in_box(self.by_label["retreat_step_2"])
        self.assertTrue(self._inside(box_local), box_local)

    def test_retreat_step2_wrong_link_pose_reproduces_artifact(self):
        # Documents the artifact: transforming the retreat_step_2 contact with
        # the post-release link pose yields the bogus ~-18 um y residual. This
        # confirms the earlier number was a link-pose mismatch, not real geometry.
        post_link = self.by_label["immediate_post_release"]["left_clamp_poses"][
            "left_clamp_left_link"]
        snap = self.by_label["retreat_step_2"]
        cw = snap["robot_bowl2_contact_diagnostics"]["position"]["values"]
        delta = [cw[i] - post_link["position_xyz_m"][i] for i in range(3)]
        contact_link = _quat_inv_rotate(post_link["quaternion_wxyz"], delta)
        rel = [contact_link[i] - self.origin[i] for i in range(3)]
        bogus = _quat_inv_rotate(self.q_box, rel)
        # The bogus y value exceeds the y half-extent (the artifact).
        self.assertGreater(abs(bogus[1]), self.half[1])

    def test_pre_release_source_mesh_contacts_outside_v4_box(self):
        snap = self.by_label["final_pre_release"]
        positions = snap["robot_bowl2_contact_diagnostics"]["position"]["values"]
        # reshape to (2,3)
        pts = [positions[i * 3:(i + 1) * 3] for i in range(2)]
        link = snap["left_clamp_poses"]["left_clamp_left_link"]
        t_link = link["position_xyz_m"]
        q_link = link["quaternion_wxyz"]
        for pt in pts:
            delta = [pt[i] - t_link[i] for i in range(3)]
            contact_link = _quat_inv_rotate(q_link, delta)
            rel = [contact_link[i] - self.origin[i] for i in range(3)]
            box_local = _quat_inv_rotate(self.q_box, rel)
            self.assertFalse(self._inside(box_local), box_local)


class TestReleaseVsRetreatMotion(unittest.TestCase):
    def setUp(self):
        self.by_label = {snap["label"]: snap for snap in TRACE["snapshots"]}

    @staticmethod
    def _dist(a, b):
        return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))

    def test_release_interval_motion_dominates_retreat(self):
        b2_pre = self.by_label["final_pre_release"]["bowl2_pose"]["position_xyz_m"]
        b2_post = self.by_label["immediate_post_release"]["bowl2_pose"]["position_xyz_m"]
        b2_ret2 = self.by_label["retreat_step_2"]["bowl2_pose"]["position_xyz_m"]
        release_motion = self._dist(b2_pre, b2_post)
        retreat_motion = self._dist(b2_post, b2_ret2)
        self.assertGreater(release_motion, retreat_motion * 100.0)
        self.assertGreater(release_motion, 0.01)        # > 10 mm during release
        self.assertLess(retreat_motion, 0.001)          # < 1 mm across full retreat
        self.assertAlmostEqual(release_motion / retreat_motion, 700.3856506110528)

    def test_clamp_link_release_motion_dominates_retreat(self):
        ll_pre = self.by_label["final_pre_release"]["left_clamp_poses"][
            "left_clamp_left_link"]["position_xyz_m"]
        ll_post = self.by_label["immediate_post_release"]["left_clamp_poses"][
            "left_clamp_left_link"]["position_xyz_m"]
        ll_ret2 = self.by_label["retreat_step_2"]["left_clamp_poses"][
            "left_clamp_left_link"]["position_xyz_m"]
        release_motion = self._dist(ll_pre, ll_post)
        retreat_motion = self._dist(ll_post, ll_ret2)
        self.assertGreater(release_motion, retreat_motion * 100.0)
        self.assertAlmostEqual(release_motion / retreat_motion, 179.6125529896171)

    def test_relative_separation_change_is_small(self):
        # Reproducible relative metric: world-frame distance between
        # left_clamp_left_link and bowl2. This scalar changes little, but the
        # next test proves that it masks a material directional change. It
        # therefore cannot establish co-motion.
        def rel(label):
            ll = self.by_label[label]["left_clamp_poses"][
                "left_clamp_left_link"]["position_xyz_m"]
            b2 = self.by_label[label]["bowl2_pose"]["position_xyz_m"]
            return self._dist(ll, b2)

        release_change = abs(rel("immediate_post_release") - rel("final_pre_release"))
        retreat_change = abs(rel("retreat_step_2") - rel("immediate_post_release"))
        self.assertGreater(release_change, retreat_change)
        # Both relative changes are small in absolute terms (< 5 mm / < 1 mm).
        self.assertLess(release_change, 0.005)
        self.assertLess(retreat_change, 0.001)

    def test_release_relative_displacement_vector_change_is_nontrivial(self):
        pre = self.by_label["final_pre_release"]
        post = self.by_label["immediate_post_release"]
        b2_pre = pre["bowl2_pose"]["position_xyz_m"]
        b2_post = post["bowl2_pose"]["position_xyz_m"]
        ll_pre = pre["left_clamp_poses"]["left_clamp_left_link"][
            "position_xyz_m"
        ]
        ll_post = post["left_clamp_poses"]["left_clamp_left_link"][
            "position_xyz_m"
        ]
        bowl_delta = [b2_post[i] - b2_pre[i] for i in range(3)]
        link_delta = [ll_post[i] - ll_pre[i] for i in range(3)]
        relative_delta = [
            bowl_delta[i] - link_delta[i] for i in range(3)
        ]
        relative_delta_norm = math.sqrt(
            sum(component * component for component in relative_delta)
        )
        self.assertAlmostEqual(relative_delta_norm, 0.012116743141782845)

    def test_analysis_does_not_promote_scalar_separation_to_comotion(self):
        analysis = _read_text(
            ".ops/wip/g3-seed1630-release-safety-design-review-20260729/"
            "ANALYSIS.md"
        )
        normalized = " ".join(
            analysis.lower().replace("**", "").split()
        )
        self.assertNotIn(
            "most of the release-interval motion is co-motion",
            normalized,
        )
        self.assertIn(
            "neither “co-motion” nor a specific relative-motion mechanism "
            "is established",
            normalized,
        )


class TestSamplingCadence(unittest.TestCase):
    def setUp(self):
        self.by_label = {snap["label"]: snap for snap in TRACE["snapshots"]}

    def test_cadence_fields(self):
        self.assertEqual(SCENE["control"]["physics_dt_s"], 0.004)
        self.assertEqual(
            SCENE["bimanual_rim_hook_probe"]["contact_sample_interval_steps"], 5
        )

    def test_first_scheduled_sample_after_12023_is_12025(self):
        interval = 5
        post = self.by_label["immediate_post_release"]["physics_step"]
        ret1 = self.by_label["retreat_step_1"]["physics_step"]
        ret2 = self.by_label["retreat_step_2"]["physics_step"]
        self.assertEqual(post, 12023)
        self.assertEqual(ret1, 12024)
        self.assertEqual(ret2, 12025)
        # No sample fires at 12023 or 12024; first grid point > 12023 is 12025.
        self.assertNotEqual(post % interval, 0)
        self.assertNotEqual(ret1 % interval, 0)
        self.assertEqual(ret2 % interval, 0)

    def test_failure_marker_is_not_onset(self):
        # The target pair is present at physics_step 12023 (post/pre-retreat),
        # which is earlier than the 12025 retreat_step_2 emission step.
        present_at_post = self.by_label["immediate_post_release"]["target_pair_present"]
        present_at_pre = self.by_label["pre_retreat"]["target_pair_present"]
        self.assertTrue(present_at_post)
        self.assertTrue(present_at_pre)
        self.assertLess(
            self.by_label["immediate_post_release"]["physics_step"],
            self.by_label["retreat_step_2"]["physics_step"],
        )

    def test_no_exact_onset_step_claimed(self):
        # The trace only brackets 11768 -> 12023; onset is only bounded above.
        pre = self.by_label["final_pre_release"]["physics_step"]
        post = self.by_label["immediate_post_release"]["physics_step"]
        self.assertEqual(pre, 11768)
        self.assertEqual(post, 12023)
        self.assertFalse(self.by_label["final_pre_release"]["target_pair_present"])


class TestScriptedClassifierSource(unittest.TestCase):
    def setUp(self):
        text = _read_text("tools/run_genesis_stack_bowls_scripted_g1.py")
        start = text.index("def sample_safety(stage: str)")
        # bounded slice covering the bowl loop
        self.sample_safety = text[start:start + 4000]

    def test_selected_bowl_is_skipped(self):
        self.assertIn("if bowl_name == active_bowl_name:", self.sample_safety)
        # followed immediately by continue within the loop body
        idx = self.sample_safety.index("if bowl_name == active_bowl_name:")
        tail = self.sample_safety[idx:idx + 200]
        self.assertIn("continue", tail)

    def test_allow_set_is_place_release_only(self):
        self.assertIn('stage.split(":")[-1] in {"place", "release"}',
                      self.sample_safety)
        # Retreat is not in the allow set.
        self.assertNotIn('{"place", "release", "retreat"}', self.sample_safety)

    def test_active_side_clamp_substring_required(self):
        self.assertIn('f"mantis:{active_side_name}_clamp" in pair', self.sample_safety)

    def test_allow_rule_uses_all_pairs_form(self):
        # The exact source applies the clamp substring across the WHOLE pair
        # list for a bowl: all(f"mantis:{active_side_name}_clamp" in pair for
        # pair in pairs). scripted_allows() is only a single-pair projection of
        # this; assert the real all(...) form exists in source. The literal
        # spans several indented lines, so compare on whitespace-normalized text.
        normalized = " ".join(self.sample_safety.split())
        self.assertIn(
            "all( f\"mantis:{active_side_name}_clamp\" in pair for pair in pairs )",
            normalized,
        )

    def test_target_pair_rejected_in_retreat_via_replica(self):
        target = TRACE["target_pair"]
        self.assertFalse(scripted_allows(target, "bowl3:retreat", "left", False))
        # ...and accepted in release/place on the active side.
        self.assertTrue(scripted_allows(target, "bowl3:release", "left", False))
        self.assertTrue(scripted_allows(target, "bowl3:place", "left", False))


class TestActG3ClassifierSource(unittest.TestCase):
    def setUp(self):
        text = _read_text("src/mantis_rocm_bridge/act_closedloop_g3.py")
        start = text.index("def _is_clamp_robot_bowl_pair(pair: str)")
        whole = text[start:start + 1200]
        # Strip the docstring so its prose words ("stage", "pose") do not count
        # as control-flow gating; only executable statements are checked.
        doc_start = whole.index('"""')
        doc_end = whole.index('"""', doc_start + 3) + 3
        self.func = whole[doc_end:]

    def test_stage_independence(self):
        # The executable body must not gate on stage/action/pose/active side.
        for forbidden in ("stage", "pose", "action", "active_side"):
            self.assertNotIn(forbidden, self.func)

    def test_clamp_label_delegate_present(self):
        # _is_clamp_robot_bowl_pair delegates clamp membership to _is_clamp_label;
        # the mantis:{side}_clamp literal lives in that helper, not here.
        self.assertIn(
            "return all(_is_clamp_label(label) for label in robot_labels)",
            self.func,
        )

    def test_stage_free_all_clamp_allowance(self):
        # ACT G3 allows a clamp robot-bowl pair regardless of stage / active side.
        target = TRACE["target_pair"]
        self.assertTrue(act_g3_allows(target))
        # Replica is stage- and side-independent by construction; assert it on a
        # representative stage-free call signature.
        self.assertTrue(act_g3_allows(target))


class TestClassifierParityMatrix(unittest.TestCase):
    """Representative matrix (ANALYSIS section 4.3)."""

    TARGET = TRACE["target_pair"]
    SRC_LEFT = (
        "bowl2:bowl_link <> mantis:left_clamp_left_link:source_mesh_collision"
    )
    RIM_RIGHT = (
        "bowl2:bowl_link <> mantis:right_clamp_left_link:"
        "competition_rim_support_collision"
    )
    WRIST = (
        "bowl2:bowl_link <> mantis:left_wrist_yaw_link:source_mesh_collision"
    )

    def test_matrix_exposes_divergence(self):
        rows = [
            # (pair, stage, active_side, is_selected)
            (self.TARGET, "bowl3:place", "left", False),
            (self.TARGET, "bowl3:release", "left", False),
            (self.TARGET, "bowl3:retreat", "left", False),
            (self.TARGET, "stage_free", None, False),
            (self.SRC_LEFT, "bowl3:retreat", "left", False),
            (self.RIM_RIGHT, "bowl3:place", "left", False),
            (self.WRIST, "bowl3:place", "left", False),
            (self.TARGET, "bowl3:place", "left", True),
        ]
        divergent = []
        for pair, stage, side, selected in rows:
            s = scripted_allows(pair, stage, side, selected)
            a = act_g3_allows(pair)
            if s != a:
                divergent.append((pair, stage, side, selected, s, a))
        # At least one divergence must exist (rows 3/4/5/6).
        self.assertTrue(divergent, "expected classifier divergence")
        # The exact target pair during retreat must diverge.
        target_retreat = [
            d for d in divergent if d[0] == self.TARGET and d[1] == "bowl3:retreat"
        ]
        self.assertTrue(target_retreat)
        tr = target_retreat[0]
        self.assertFalse(tr[4])   # scripted rejects
        self.assertTrue(tr[5])    # ACT G3 accepts

    def test_agreement_on_nonclamp_pair(self):
        # Both classifiers reject a non-clamp robot link touching a bowl.
        self.assertFalse(scripted_allows(self.WRIST, "bowl3:place", "left", False))
        self.assertFalse(act_g3_allows(self.WRIST))

    def test_inactive_side_rejected_by_scripted_allowed_by_act(self):
        self.assertFalse(
            scripted_allows(self.RIM_RIGHT, "bowl3:place", "left", False)
        )
        self.assertTrue(act_g3_allows(self.RIM_RIGHT))


class TestAuthorityNotEstablished(unittest.TestCase):
    def test_task_pack_does_not_freeze_robot_bowl_allowlist(self):
        sp = TASK["success_predicate"]
        self.assertTrue(sp["no_safety_failure"])
        self.assertIn("collision_safety", TASK["evaluation"]["failure_taxonomy"])
        # No frozen allowlist field exists.
        self.assertNotIn("robot_bowl_contact_allowlist", TASK)
        self.assertNotIn("collision_allowlist", TASK)

    def test_analysis_states_authority_not_established(self):
        analysis = _read_text(
            ".ops/wip/g3-seed1630-release-safety-design-review-20260729/ANALYSIS.md"
        )
        self.assertIn("not established", analysis.lower())

    def test_analysis_recommends_no_runtime_implementation(self):
        analysis = _read_text(
            ".ops/wip/g3-seed1630-release-safety-design-review-20260729/ANALYSIS.md"
        )
        self.assertIn("No runtime implementation", analysis)


class TestClaimBoundary(unittest.TestCase):
    def test_claims_do_not_assert_exact_contact_onset(self):
        analysis = _read_text(
            ".ops/wip/g3-seed1630-release-safety-design-review-20260729/ANALYSIS.md"
        )
        # Strip markdown emphasis so bolded non-claims still match.
        low = analysis.lower().replace("**", "")
        # Positive: explicit non-claim language present.
        self.assertTrue(
            "do not claim the exact unobserved onset" in low
            or "do not claim an exact onset" in low
        )
        # Negative: no assertion of an exact onset step number inside the interval.
        self.assertNotIn("onset at physics_step", low)
        self.assertNotIn("exact onset step is", low)


if __name__ == "__main__":
    unittest.main()
