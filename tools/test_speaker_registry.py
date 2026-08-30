import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from speaker_registry import resolve_node_actor, resolve_registry_actor


def normalize(text):
    return "".join(c.lower() for c in (text or "") if c.isalnum())


class SpeakerRegistryTests(unittest.TestCase):
    def setUp(self):
        self.actors = {
            "gobbet-actor": {"name": "Gobbet", "portrait": "npc_orkFemale_Gobbet"},
            "is0bel-actor": {"name": "Is0bel", "portrait": "npc_dwarfFemale_Is0bel"},
            "explicit-actor": {"name": "Explicit", "portrait": None},
        }
        self.registry = {
            "young-ork": {"name": "Young Ork", "portrait": "npc_orkFemale_Gobbet"},
            "is0bel": {"name": "Is0bel", "portrait": "npc_dwarfFemale_Is0bel"},
            "terminal": {"name": "Terminal", "portrait": None},
        }

    def test_portrait_resolves_alias_to_existing_actor(self):
        self.assertEqual(
            "gobbet-actor",
            resolve_registry_actor("young-ork", self.registry, self.actors, normalize),
        )

    def test_explicit_reference_wins_over_field_15(self):
        actor, provenance = resolve_node_actor(
            "explicit-actor", None, True, "is0bel", self.actors, lambda tag: None,
            self.registry, normalize)
        self.assertEqual(("explicit-actor", "source-ref"), (actor, provenance))

    def test_explicit_tag_wins_over_field_15(self):
        actor, provenance = resolve_node_actor(
            None, "crew", True, "is0bel", self.actors, lambda tag: "gobbet-actor",
            self.registry, normalize)
        self.assertEqual(("gobbet-actor", "source-tag"), (actor, provenance))

    def test_actorless_node_uses_field_15(self):
        actor, provenance = resolve_node_actor(
            None, None, True, "is0bel", self.actors, lambda tag: None,
            self.registry, normalize)
        self.assertEqual(("is0bel-actor", "active-speaker-override"), (actor, provenance))

    def test_stale_field_15_without_override_flag_falls_through(self):
        self.assertEqual(
            (None, None),
            resolve_node_actor(None, None, False, "is0bel", self.actors, lambda tag: None,
                               self.registry, normalize),
        )

    def test_unmatched_device_record_falls_through(self):
        self.assertEqual(
            (None, None),
            resolve_node_actor(None, None, True, "terminal", self.actors, lambda tag: None,
                               self.registry, normalize),
        )

    def test_duplicate_instances_of_one_identity_are_allowed(self):
        actors = dict(self.actors)
        actors["gobbet-second-instance"] = {
            "name": "Gobbet", "portrait": "npc_orkFemale_Gobbet"
        }
        self.assertIn(
            resolve_registry_actor("young-ork", self.registry, actors, normalize),
            {"gobbet-actor", "gobbet-second-instance"},
        )

    def test_ambiguous_portrait_between_distinct_identities_is_rejected(self):
        actors = dict(self.actors)
        actors["gobbet-double"] = {"name": "Gobbet Double", "portrait": "npc_orkFemale_Gobbet"}
        self.assertIsNone(resolve_registry_actor("young-ork", self.registry, actors, normalize))


if __name__ == "__main__":
    unittest.main()
