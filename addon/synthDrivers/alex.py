"""Make Apple's downloaded Alex voice available as a separate NVDA synthesizer."""

import addonHandler
from gettext import gettext as _

from ._alex_native import pantheradriver, tree

addonHandler.initTranslation()


class SynthDriver(pantheradriver.PantheraDriver):
	name = "alex"
	description = _("Alex (Apple download)")
	TREE = tree
	TITLE = "Alex"
	DISC = "Apple download"
	EXTRACTOR = "Alex setup"
	INPUT_MODES_WORK = True
	HANDOFF_GRACE = 0.06
	# Do not reuse Lion's recording-specific loudness boost for the downloaded bank.
	VOLUME_NORM = {"Alex": 1.0}

	@classmethod
	def check(cls):
		return tree.usable()

	def __init__(self):
		if not tree.usable():
			raise RuntimeError("Alex is not set up. Open NVDA Settings, Alex, and download the required files.")
		super().__init__()
