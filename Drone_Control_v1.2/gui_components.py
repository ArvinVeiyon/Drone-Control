#!/usr/bin/env python3
"""
gui_components.py
Contains GUI components for Drone_control_v1.0, including SavedCommandsPage, AppLogPage, and LogSignalHandler.
"""

import os, json, logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QSizePolicy, QListWidget, QTextEdit
from PyQt5.QtCore import Qt, QObject, pyqtSignal

logger = logging.getLogger("DroneControl")

SCALE = 0.7

###############################################################################
# LogSignalHandler
###############################################################################
class LogSignalHandler(QObject, logging.Handler):
    log_signal = pyqtSignal(str)
    def __init__(self):
        super().__init__()
        logging.Handler.__init__(self)
        self.setLevel(logging.DEBUG)
    def emit(self, record):
        msg = self.format(record)
        self.log_signal.emit(msg)

###############################################################################
# SavedCommandsPage
###############################################################################
class SavedCommandsPage(QWidget):
    SAVED_COMMANDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "saved_commands.json")
    def __init__(self):
        super().__init__()
        self.commands = []
        self.load_saved_commands()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(20 * SCALE), int(20 * SCALE), int(20 * SCALE), int(20 * SCALE))
        layout.setSpacing(int(10 * SCALE))
        lblTitle = QLabel("Saved Commands")
        lblTitle.setStyleSheet(f"font-size: {int(16 * SCALE)}pt; font-weight: bold; margin-bottom: {int(10 * SCALE)}px;")
        layout.addWidget(lblTitle)
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(300)
        self.list_widget.itemDoubleClicked.connect(self.copy_command_silently)
        layout.addWidget(self.list_widget)
        input_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Enter command to save")
        self.cmd_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        input_layout.addWidget(self.cmd_input)
        btnAdd = QPushButton("Add")
        btnAdd.setStyleSheet("font-size: 8pt; min-width: 30px; min-height: 15px; background-color: #005BA1; color: white;")
        btnAdd.clicked.connect(self.add_command)
        input_layout.addWidget(btnAdd)
        btnRemove = QPushButton("Remove")
        btnRemove.setStyleSheet("font-size: 8pt; min-width: 30px; min-height: 15px; background-color: #AA0000; color: white;")
        btnRemove.clicked.connect(self.remove_command)
        input_layout.addWidget(btnRemove)
        layout.addLayout(input_layout)
        for cmd in self.commands:
            self.list_widget.addItem(cmd)

    def load_saved_commands(self):
        if os.path.exists(self.SAVED_COMMANDS_FILE):
            try:
                with open(self.SAVED_COMMANDS_FILE, "r") as f:
                    data = json.load(f)
                self.commands = data.get("commands", [])
            except Exception as e:
                logger.error(f"Failed to load saved commands: {e}")
                self.commands = []
        else:
            self.commands = []

    def save_saved_commands(self):
        os.makedirs(os.path.dirname(self.SAVED_COMMANDS_FILE), exist_ok=True)
        data = {"commands": self.commands}
        try:
            with open(self.SAVED_COMMANDS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save commands: {e}")

    def add_command(self):
        cmd = self.cmd_input.text().strip()
        if cmd:
            self.commands.append(cmd)
            self.list_widget.addItem(cmd)
            self.cmd_input.clear()
            self.save_saved_commands()

    def remove_command(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            if item.text() in self.commands:
                self.commands.remove(item.text())
            self.list_widget.takeItem(self.list_widget.row(item))
        self.save_saved_commands()

    def copy_command_silently(self, item):
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(item.text())
        logger.info(f"Copied command to clipboard: {item.text()}")

###############################################################################
# AppLogPage
###############################################################################
class AppLogPage(QWidget):
    def __init__(self, log_handler):
        super().__init__()
        self.log_handler = log_handler
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(20 * SCALE), int(20 * SCALE), int(20 * SCALE), int(20 * SCALE))
        layout.setSpacing(int(10 * SCALE))
        lblTitle = QLabel("App Log")
        lblTitle.setStyleSheet(f"font-size: {int(16 * SCALE)}pt; font-weight: bold; margin-bottom: {int(10 * SCALE)}px;")
        layout.addWidget(lblTitle)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        self.log_handler.log_signal.connect(self.append_log)

    def append_log(self, message):
        self.log_text.append(message)