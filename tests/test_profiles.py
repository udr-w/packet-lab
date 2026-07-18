"""Multi-learner isolation — the 15 required guarantees plus ID hardening.

Every test builds learner-scoped Governor / LearnerModel / Trace rooted at a
profile directory, exactly as the CLI does, and proves one learner's state
never bleeds into another's.
"""

import tempfile
import unittest
from pathlib import Path

from packetlab.lab import curriculum as curriculum_mod
from packetlab.lab import toolgen
from packetlab.lab.governor import Action, Governor
from packetlab.lab.learner import LearnerModel
from packetlab.lab.profiles import LearnerProfiles, validate_learner_id
from packetlab.lab.toolgen import ToolArtifacts
from packetlab.lab.trace import Trace, new_run_id, read_trace, verify_chain
from packetlab.lab.specs import ToolSpec


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name)
        self.profiles = LearnerProfiles(self.state)
        self.curric = curriculum_mod.load()

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, learner_id):
        self.profiles.create(learner_id)
        return self.profiles.learner_dir(learner_id)

    def learner_model(self, learner_id):
        return LearnerModel(self.profiles.learner_dir(learner_id) / "learner.json")

    def governor(self, learner_id, trace=None):
        d = self.profiles.learner_dir(learner_id)
        return Governor(self.curric, trace=trace, state_path=d / "lesson.json")


class Isolation(Base):
    def test_01_new_learner_no_inherited_mastery(self):
        self.make("alpha")
        self.assertEqual(self.learner_model("alpha").summary()["total_concepts"], 0)

    def test_02_two_learners_different_mastery_same_concept(self):
        self.make("alpha"); self.make("beta")
        self.learner_model("alpha").add_evidence("dns.udp-53", "observation",
                                                 "saw it", "v3.0", None)
        self.learner_model("alpha").add_evidence("dns.udp-53", "explanation",
                                                 "because", "v3.0", None)
        self.assertEqual(self.learner_model("alpha").concept("dns.udp-53").state,
                         "mastered")
        self.assertEqual(self.learner_model("beta").concept("dns.udp-53").state,
                         "unseen")

    def test_03_recording_for_a_does_not_touch_b(self):
        self.make("alpha"); self.make("beta")
        self.learner_model("alpha").add_evidence("dns.udp-53", "prediction",
                                                 "p", "v3.0", None)
        self.assertEqual(len(self.learner_model("beta").concept("dns.udp-53").evidence), 0)

    def test_04_governor_state_isolated(self):
        self.make("alpha"); self.make("beta")
        rid = new_run_id()
        self.governor("alpha").start_lesson("v3.0", rid)
        # beta has no lesson state at all
        beta_status = self.governor("beta").status()
        self.assertNotEqual(beta_status.get("lesson_id"), "v3.0")

    def test_05_current_lesson_isolated(self):
        self.make("alpha"); self.make("beta")
        self.governor("alpha").start_lesson("v3.0", new_run_id())
        self.governor("beta").start_lesson("v1.1", new_run_id())
        self.assertEqual(self.governor("alpha").status()["lesson_id"], "v3.0")
        self.assertEqual(self.governor("beta").status()["lesson_id"], "v1.1")

    def test_06_switching_active_changes_state_used(self):
        self.make("alpha"); self.make("beta")
        self.profiles.set_active("alpha")
        self.assertEqual(self.profiles.get_active(), "alpha")
        self.profiles.set_active("beta")
        self.assertEqual(self.profiles.get_active(), "beta")

    def test_07_unknown_learner_rejected(self):
        with self.assertRaises(ValueError):
            self.profiles.set_active("ghost")

    def test_08_unsafe_ids_rejected(self):
        for bad in ["../etc", "a/b", "a b", "..", ".", "shared", "learners",
                    "active-learner", "con", "", "x" * 70, "a\x00b"]:
            self.assertIsNone(validate_learner_id(bad)[0], bad)
        # and normalisation of a valid one
        self.assertEqual(validate_learner_id("Engineer-01")[0], "engineer-01")

    def test_09_reset_one_does_not_reset_another(self):
        self.make("alpha"); self.make("beta")
        for who in ("alpha", "beta"):
            self.learner_model(who).add_evidence("dns.udp-53", "observation",
                                                 "x", "v3.0", None)
        self.profiles.reset("alpha")
        self.assertEqual(self.learner_model("alpha").summary()["total_concepts"], 0)
        self.assertEqual(self.learner_model("beta").summary()["total_concepts"], 1)

    def test_10_shared_curriculum_available_to_all(self):
        self.make("alpha"); self.make("beta")
        # The curriculum graph is shared, not per-learner.
        self.assertIsNotNone(self.governor("alpha").curriculum.lesson("v3.0"))
        self.assertIsNotNone(self.governor("beta").curriculum.lesson("v3.0"))

    def test_11_historical_example_not_loaded_into_new_learner(self):
        self.make("fresh")
        # A brand-new learner's state must be empty regardless of committed
        # example evidence elsewhere in the repo.
        self.assertEqual(self.learner_model("fresh").summary()["total_concepts"], 0)
        self.assertFalse((self.profiles.learner_dir("fresh") / "learner.json").exists())

    def test_12_traces_identify_the_learner(self):
        d = self.make("alpha")
        rid = new_run_id()
        trace = Trace(rid, "v3.0", base_dir=d, learner_id="alpha")
        trace.emit("governor", "lesson_started", lesson_id="v3.0")
        events = read_trace(trace.path)
        self.assertTrue(all(e.get("learner_id") == "alpha" for e in events))
        ok, _ = verify_chain(trace.path)
        self.assertTrue(ok)

    def test_13_provenance_does_not_leak_learner_identity(self):
        d = self.make("alpha")
        spec, _ = ToolSpec.from_dict(_TOOL_SPEC)
        arts = ToolArtifacts("adder", d, spec, _TOOL_SRC, _TOOL_TEST)
        ws = d / "workspace"; ws.mkdir(parents=True)
        val = toolgen.validate(spec, _TOOL_SRC, _TOOL_TEST, ws, ["ping"])
        tests = toolgen.run_tests(arts, val["source_sha256"], val["test_sha256"], ws)
        prov = toolgen.register(arts, val, tests, generator="fixture", root=d)
        blob = str(prov).lower()
        self.assertNotIn("alpha", blob)  # no learner id anywhere in provenance
        self.assertNotIn("learner", prov)

    def test_14_rapid_interleaved_writes_stay_separate(self):
        self.make("alpha"); self.make("beta")
        for i in range(20):
            self.learner_model("alpha").add_evidence(
                "dns.udp-53", "prediction", f"a{i}", "v3.0", None)
            self.learner_model("beta").add_evidence(
                "dns.udp-53", "prediction", f"b{i}", "v3.0", None)
        a = self.learner_model("alpha").concept("dns.udp-53").evidence
        b = self.learner_model("beta").concept("dns.udp-53").evidence
        self.assertTrue(all(e["summary"].startswith("a") for e in a))
        self.assertTrue(all(e["summary"].startswith("b") for e in b))

    def test_15_legacy_single_user_state_migrated(self):
        # Simulate a pre-multi-learner install: global state files.
        from packetlab.lab.statefile import atomic_write_json
        atomic_write_json(self.state / "lesson.json", {"lesson_id": "v3.0",
                                                       "generation": 1})
        atomic_write_json(self.state / "learner.json",
                          {"version": 1, "generation": 1,
                           "concepts": {"dns.udp-53": {"state": "in_progress",
                                                       "evidence": [], "updated_at": ""}}})
        migrated = self.profiles.migrate_legacy_if_present()
        self.assertEqual(migrated, "default")
        self.assertEqual(self.profiles.get_active(), "default")
        self.assertEqual(self.learner_model("default").concept("dns.udp-53").state,
                         "in_progress")
        # The global files are gone (moved, not left to become an implicit global).
        self.assertFalse((self.state / "lesson.json").exists())


_TOOL_SPEC = {
    "id": "adder", "purpose": "add", "lesson_id": "v1.1",
    "inputs": {"a": {"type": "integer"}, "b": {"type": "integer"}},
    "outputs": {"sum": {"type": "integer"}},
    "capabilities": {"commands": [], "filesystem": {"read": [], "write": []},
                     "network": "none"},
    "limits": {"timeout_seconds": 5, "max_output_bytes": 10000},
    "dependencies": {"python": ["standard-library-only"]}, "retention": "lesson",
}
_TOOL_SRC = b"""import json
import sys


def add(a, b):
    return a + b


def main():
    d = json.load(sys.stdin)
    print(json.dumps({'sum': add(d['a'], d['b'])}))


if __name__ == '__main__':
    main()
"""
_TOOL_TEST = b"""import unittest
import tool
class T(unittest.TestCase):
    def test_add(self):
        self.assertEqual(tool.add(2, 3), 5)
if __name__ == '__main__':
    unittest.main()
"""


if __name__ == "__main__":
    unittest.main()
