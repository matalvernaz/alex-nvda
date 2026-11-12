"""Provide an accessible Alex download and setup page in NVDA Settings and the Tools menu."""

import addonHandler
import globalPluginHandler
import globalVars
import gui
from gettext import gettext as _
from gui.settingsDialogs import NVDASettingsDialog, SettingsPanel
import synthDriverHandler
import ui
import wx

from synthDrivers._alex_native import paths, setup

addonHandler.initTranslation()


class AlexSettingsPanel(SettingsPanel):
	title = _("Alex")

	def makeSettings(self, settingsSizer):
		self._alive = True
		self._announced_stage = None
		self._announced_percent = -1
		information = _("Download Alex and the required speech components directly from Apple. Setup downloads about 5.6 GB and needs about 8 GB of free space while it works. Downloads are removed after a successful setup. You can close Settings while setup continues.")
		instructions = wx.StaticText(self, label=information)
		instructions.Wrap(600)
		settingsSizer.Add(instructions, flag=wx.EXPAND | wx.BOTTOM, border=10)
		label = wx.StaticText(self, label=_("Setup status:"))
		settingsSizer.Add(label)
		self.status = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100))
		self.status.SetName(_("Alex setup status"))
		settingsSizer.Add(self.status, flag=wx.EXPAND | wx.BOTTOM, border=8)
		self.progress = wx.Gauge(self, range=100)
		self.progress.SetName(_("Alex setup progress"))
		settingsSizer.Add(self.progress, flag=wx.EXPAND | wx.BOTTOM, border=8)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.download = wx.Button(self, label=_("&Download and set up Alex"))
		self.cancel_download = wx.Button(self, label=_("&Cancel download"))
		self.use_alex = wx.Button(self, label=_("&Use Alex"))
		for button in (self.download, self.cancel_download, self.use_alex):
			buttons.Add(button, flag=wx.RIGHT, border=8)
		settingsSizer.Add(buttons)
		self.download.Bind(wx.EVT_BUTTON, self._download)
		self.cancel_download.Bind(wx.EVT_BUTTON, self._cancel)
		self.use_alex.Bind(wx.EVT_BUTTON, self._use_alex)
		self.Bind(wx.EVT_WINDOW_DESTROY, self._destroyed)
		setup.controller.subscribe(self._updated)

	def _updated(self, state):
		wx.CallAfter(self._show_state, state)

	def _show_state(self, state):
		if not self._alive:
			return
		installed = paths.active_installation() is not None
		stage = state.stage
		detail = state.detail
		if stage == "Not started" and installed:
			stage = _("Ready")
			detail = _("Alex is already installed. You can use Alex or download again to repair the installation.")
		self.status.ChangeValue(f"{stage}\n{detail}")
		self.progress.SetValue(state.percent)
		self.progress.SetName(f"{stage}: {state.percent}%")
		self.download.Enable(not state.running)
		self.cancel_download.Enable(state.running and stage != "Cancelling")
		self.use_alex.Enable(installed and not state.running)
		# Speak phase changes and ten-percent download milestones without flooding the speech queue.
		milestone = state.percent // 10
		stage_changed = stage != self._announced_stage
		if state.running or state.error or self._announced_stage is not None:
			if stage_changed or (stage.startswith("Downloading") and milestone != self._announced_percent):
				message = f"{stage}: {state.percent}%" if stage.startswith("Downloading") else f"{stage}. {detail}"
				ui.message(message)
		self._announced_stage = stage
		self._announced_percent = milestone

	def _download(self, event):
		current = synthDriverHandler.getSynth()
		if current is not None and current.name == "alex":
			gui.messageBox(_("Switch to another synthesizer before repairing Alex. Your existing Alex installation will be kept until setup finishes."), _("Alex setup"), wx.OK | wx.ICON_INFORMATION)
			return
		setup.controller.start(paths.data_root())

	def _cancel(self, event):
		setup.controller.cancel()

	def _use_alex(self, event):
		if synthDriverHandler.setSynth("alex"):
			ui.message(_("Alex is ready."))
		else:
			gui.messageBox(_("NVDA could not start Alex. Run setup again, then check the NVDA log if it still fails."), _("Alex"), wx.OK | wx.ICON_ERROR)

	def _destroyed(self, event):
		if event.GetEventObject() is self:
			self._alive = False
			setup.controller.unsubscribe(self._updated)
		event.Skip()

	def onSave(self):
		pass


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		self._item = None
		if globalVars.appArgs.secure:
			return
		NVDASettingsDialog.categoryClasses.append(AlexSettingsPanel)
		self._menu = gui.mainFrame.sysTrayIcon.toolsMenu
		self._item = self._menu.Append(wx.ID_ANY, _("Alex setup..."))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self._open, self._item)

	def _open(self, event):
		gui.mainFrame.popupSettingsDialog(NVDASettingsDialog, AlexSettingsPanel)

	def terminate(self):
		setup.controller.cancel()
		if AlexSettingsPanel in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.remove(AlexSettingsPanel)
		if self._item is not None:
			gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, handler=self._open, source=self._item)
			self._menu.Remove(self._item)
		super().terminate()
