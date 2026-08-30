import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class ApplyReattributionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        tools = self.root / "tools"
        tools.mkdir()
        shutil.copy2(HERE / "apply_reattributions.py", tools)
        shutil.copy2(HERE / "line_moves.py", tools)
        (self.root / "app/data/hk").mkdir(parents=True)
        (self.root / "app/audio/hk").mkdir(parents=True)
        self.write("tools/renames.json", {"hk": []})

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, value):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def read(self, rel):
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def run_tool(self):
        return subprocess.run(
            ["python3", str(self.root / "tools/apply_reattributions.py"), "hk"],
            cwd=self.root, text=True, capture_output=True, check=True)

    @staticmethod
    def line(node=1):
        return {"c": "convo", "n": node, "cn": "test", "t": "Hello."}

    def fixture(self, rule, *, source="wrong", target="live", selected=True):
        self.write("tools/reattributions.json", {"hk": [rule]})
        self.write("app/data/hk/characters.json", {
            "characters": [
                {"id": source, "name": "Wrong", "lines": [self.line()]},
                {"id": target, "name": "Live", "lines": []},
            ],
            "narrator": {"lines": []}, "unattributed": {"lines": []},
        })
        rel = f"{source}/takes/convo_1__voice__1.mp3"
        self.write("app/data/hk/takes.json", {source: {"convo_1": {
            "selected": rel if selected else None,
            "takes": [{"file": rel, "voiceId": "voice"}],
        }}})
        audio = self.root / "app/audio/hk" / rel
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"audio")

    def test_resolves_merged_target_before_creation_and_is_idempotent(self):
        rule = {"convo": "convo", "nodes": [1], "from": "wrong", "to": "old_alias",
                "to_name": "Old Alias"}
        self.fixture(rule)
        self.write("app/data/hk/merges.json", {"old_alias": "live"})

        self.run_tool()
        first_chars = self.read("app/data/hk/characters.json")
        self.assertNotIn("old_alias", {c["id"] for c in first_chars["characters"]})
        live = next(c for c in first_chars["characters"] if c["id"] == "live")
        self.assertEqual([1], [line["n"] for line in live["lines"]])

        first_takes = self.read("app/data/hk/takes.json")
        self.run_tool()
        self.assertEqual(first_chars, self.read("app/data/hk/characters.json"))
        self.assertEqual(first_takes, self.read("app/data/hk/takes.json"))

    def test_same_character_after_merge_resolution_is_a_noop(self):
        rule = {"convo": "convo", "nodes": [1], "from": "live", "to": "old_alias",
                "to_name": "Old Alias"}
        self.fixture(rule, source="live", target="other")
        self.write("app/data/hk/merges.json", {"old_alias": "live"})

        before = self.read("app/data/hk/characters.json")
        self.run_tool()
        self.assertEqual(before, self.read("app/data/hk/characters.json"))

    def test_cross_character_move_clears_keeper_by_default(self):
        rule = {"convo": "convo", "nodes": [1], "from": "wrong", "to": "live"}
        self.fixture(rule)
        self.write("app/data/hk/merges.json", {})

        self.run_tool()
        entry = self.read("app/data/hk/takes.json")["live"]["convo_1"]
        self.assertIsNone(entry["selected"])
        self.assertTrue(entry["takes"][0]["file"].startswith("live/"))

    def test_preserve_selected_requires_explicit_opt_in(self):
        rule = {"convo": "convo", "nodes": [1], "from": "wrong", "to": "live",
                "preserve_selected": True}
        self.fixture(rule)
        self.write("app/data/hk/merges.json", {})

        self.run_tool()
        entry = self.read("app/data/hk/takes.json")["live"]["convo_1"]
        self.assertEqual(entry["takes"][0]["file"], entry["selected"])

    def test_nonvoiceable_policy_survives_move_and_idempotent_rerun(self):
        rule = {"convo": "convo", "nodes": [1], "from": "wrong", "to": "live",
                "nonvoiceable": True, "reason": "Screen text, not speech."}
        self.fixture(rule)
        self.write("app/data/hk/merges.json", {})

        self.run_tool()
        self.run_tool()
        live = next(c for c in self.read("app/data/hk/characters.json")["characters"]
                    if c["id"] == "live")
        self.assertTrue(live["lines"][0]["nonvoiceable"])
        self.assertEqual("Screen text, not speech.", live["lines"][0]["attributionReason"])


if __name__ == "__main__":
    unittest.main()
