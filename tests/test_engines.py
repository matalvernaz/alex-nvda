"""Keep engine selection and removal safe when upgrading an existing Alex installation."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alex_native import paths


class EngineManagementTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.root = Path(self.temporary.name)
		self.addCleanup(self.temporary.cleanup)

	def installation(self, engine):
		tree = self.root / ("install-" + engine)
		for relative in paths.required_files(engine):
			file = tree / relative
			file.parent.mkdir(parents=True, exist_ok=True)
			file.write_bytes(b"synthetic fixture")
		return {"format": 1, "directory": tree.name, "engine_key": engine}

	def test_upgrade_preserves_old_installation_and_can_switch_back(self):
		legacy = self.installation("legacy")
		legacy.pop("engine_key")
		(self.root / "current.json").write_text(json.dumps(legacy))
		modern = self.installation("modern")
		paths.publish_installation(self.root, "modern", modern)
		self.assertEqual(paths.selected_engine(self.root), "modern")
		self.assertEqual(set(paths.installed_engines(self.root)), {"legacy", "modern"})
		paths.select_engine(self.root, "legacy")
		self.assertEqual(paths.active_installation(self.root), self.root / legacy["directory"])

	def test_removing_old_engine_preserves_active_modern_voice(self):
		paths.publish_installation(self.root, "legacy", self.installation("legacy"))
		modern = self.installation("modern")
		paths.publish_installation(self.root, "modern", modern)
		paths.remove_engine(self.root, "legacy")
		self.assertFalse((self.root / "install-legacy").exists())
		self.assertEqual(paths.active_installation(self.root), self.root / modern["directory"])

	def test_active_engine_removal_selects_remaining_installation(self):
		paths.publish_installation(self.root, "legacy", self.installation("legacy"))
		paths.publish_installation(self.root, "modern", self.installation("modern"))
		paths.remove_engine(self.root, "modern")
		self.assertEqual(paths.selected_engine(self.root), "legacy")
		self.assertEqual(paths.active_installation(self.root), self.root / "install-legacy")

	def test_missing_modern_component_is_not_selectable(self):
		state = self.installation("modern")
		(self.root / state["directory"] / paths.required_files("modern")[0]).unlink()
		with self.assertRaises(ValueError):
			paths.publish_installation(self.root, "modern", state)
		self.assertIsNone(paths.active_installation(self.root))

	def test_manifest_cannot_delete_a_directory_outside_managed_storage(self):
		outside = self.root / "unrelated"
		outside.mkdir()
		marker = outside / "keep.txt"
		marker.write_text("keep")
		(self.root / "legacy.json").write_text(json.dumps({"format": 1, "directory": "unrelated"}))
		with self.assertRaises(ValueError):
			paths.remove_engine(self.root, "legacy")
		self.assertEqual(marker.read_text(), "keep")

	def test_repair_reclaims_superseded_data_after_new_installation_is_selected(self):
		old = self.installation("legacy")
		paths.publish_installation(self.root, "legacy", old)
		new = dict(self.installation("legacy"), directory="install-repaired")
		(self.root / old["directory"]).rename(self.root / new["directory"])
		self.installation("legacy")
		paths.publish_installation(self.root, "legacy", new)
		self.assertEqual(paths.active_installation(self.root), self.root / new["directory"])
		self.assertFalse((self.root / old["directory"]).exists())

	def test_failed_selection_write_preserves_previous_installation_record(self):
		legacy = self.installation("legacy")
		paths.publish_installation(self.root, "legacy", legacy)
		write = paths._write_state
		def fail_current(file, state):
			if file.name == "current.json":
				raise OSError("synthetic disk failure")
			write(file, state)
		with patch.object(paths, "_write_state", side_effect=fail_current):
			with self.assertRaises(OSError):
				paths.publish_installation(self.root, "modern", self.installation("modern"))
		self.assertEqual(paths.active_installation(self.root), self.root / legacy["directory"])
		self.assertEqual(set(paths.installed_engines(self.root)), {"legacy"})


if __name__ == "__main__":
	unittest.main()
