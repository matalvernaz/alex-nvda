"""Provide an accessible Alex download and setup page in NVDA Settings and the Tools menu."""
# SPDX-License-Identifier: GPL-2.0-or-later

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
		information = _("Choose the speech engine to download or use. Apple components are downloaded directly from Apple. You can keep both engines and remove either one later. Your existing installation is kept until the new engine passes its speech test. You can close Settings while setup continues.")
		instructions = wx.StaticText(self, label=information)
		instructions.Wrap(600)
		settingsSizer.Add(instructions, flag=wx.EXPAND | wx.BOTTOM, border=10)
		engine_label = wx.StaticText(self, label=_("Speech &engine:"))
		settingsSizer.Add(engine_label)
		self.engine_keys = ["modern", "legacy"]
		self.engine = wx.Choice(self, choices=[_("Modern"), _("Legacy (Lion)")])
		self.engine.SetName(_("Speech engine"))
		selected = paths.selected_engine()
		self.engine.SetSelection(self.engine_keys.index(selected) if selected in self.engine_keys else 0)
		self.engine.Bind(wx.EVT_CHOICE, self._engine_changed)
		settingsSizer.Add(self.engine, flag=wx.EXPAND | wx.BOTTOM, border=8)
		self.keep_downloads = wx.CheckBox(self, label=_("&Keep downloads after successful setup"))
		settingsSizer.Add(self.keep_downloads, flag=wx.BOTTOM, border=8)
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
		data_buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.remove_data = wx.Button(self, label=_("&Remove selected engine's data..."))
		self.clear_downloads = wx.Button(self, label=_("&Delete saved downloads..."))
		for button in (self.remove_data, self.clear_downloads):
			data_buttons.Add(button, flag=wx.RIGHT | wx.TOP, border=8)
		settingsSizer.Add(data_buttons)
		self.download.Bind(wx.EVT_BUTTON, self._download)
		self.cancel_download.Bind(wx.EVT_BUTTON, self._cancel)
		self.use_alex.Bind(wx.EVT_BUTTON, self._use_alex)
		self.remove_data.Bind(wx.EVT_BUTTON, self._remove_data)
		self.clear_downloads.Bind(wx.EVT_BUTTON, self._clear_downloads)
		self.Bind(wx.EVT_WINDOW_DESTROY, self._destroyed)
		setup.controller.subscribe(self._updated)

	def _updated(self, state):
		wx.CallAfter(self._show_state, state)

	def _show_state(self, state):
		if not self._alive:
			return
		installed = paths.installed_engines()
		selected = self._selected_engine()
		stage = state.stage
		detail = state.detail
		if stage == "Not started" and selected in installed:
			stage = _("Ready")
			detail = _("Alex is already installed. You can use Alex or download again to repair the installation.")
		elif stage in ("Not started", "Ready") and selected not in installed:
			stage = _("Not installed")
			detail = _("Press Download and set up Alex to install this engine.")
		engines = []
		for key in self.engine_keys:
			name = paths.ENGINE_NAMES[key]
			availability = _("installed") if key in installed else _("not installed")
			if paths.selected_engine() == key and key in installed:
				availability = _("installed, selected for Alex")
			engines.append(f"{name}: {availability}")
		requirements = _("Modern setup: about 14.5 GB to download and 22 GB of temporary free space.") if selected == "modern" else _("Legacy setup: about 5.6 GB to download and 8 GB of temporary free space.")
		self.status.ChangeValue(f"{stage}\n{detail}\n" + "\n".join(engines) + "\n" + requirements)
		self.progress.SetValue(state.percent)
		self.progress.SetName(f"{stage}: {state.percent}%")
		self.download.Enable(not state.running)
		self.engine.Enable(not state.running)
		self.keep_downloads.Enable(not state.running)
		self.remove_data.Enable(selected in installed and not state.running)
		self.clear_downloads.Enable(not state.running)
		self.cancel_download.Enable(state.running and stage not in ("Cancelling", "Removing data"))
		self.use_alex.Enable(selected in installed and not state.running)
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
		setup.controller.start(paths.data_root(), self._selected_engine(), self.keep_downloads.GetValue())

	def _selected_engine(self):
		return self.engine_keys[self.engine.GetSelection()]

	def _engine_changed(self, event):
		self._show_state(setup.controller.state)

	def _cancel(self, event):
		setup.controller.cancel()

	def _use_alex(self, event):
		previous = paths.selected_engine()
		paths.select_engine(paths.data_root(), self._selected_engine())
		if synthDriverHandler.setSynth("alex"):
			ui.message(_("Alex is ready."))
		else:
			if previous in paths.installed_engines():
				paths.select_engine(paths.data_root(), previous)
			gui.messageBox(_("NVDA could not start Alex. Run setup again, then check the NVDA log if it still fails."), _("Alex"), wx.OK | wx.ICON_ERROR)

	def _remove_data(self, event):
		current = synthDriverHandler.getSynth()
		if current is not None and current.name == "alex":
			gui.messageBox(_("Switch to another synthesizer before removing Alex data."), _("Alex data"), wx.OK | wx.ICON_INFORMATION)
			return
		name = paths.ENGINE_NAMES[self._selected_engine()]
		message = _("Remove the downloaded data for {engine}? Your other installed engine will be kept. You can download this engine again later.").format(engine=name)
		if gui.messageBox(message, _("Remove Alex engine"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION) == wx.YES:
			setup.controller.remove(paths.data_root(), self._selected_engine())

	def _clear_downloads(self, event):
		message = _("Delete saved setup downloads, including unfinished downloads? Installed engines and their voice data will be kept.")
		if gui.messageBox(message, _("Delete Alex downloads"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION) == wx.YES:
			setup.controller.remove(paths.data_root())

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
