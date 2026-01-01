#!/usr/bin/env python3
"""
main.py
Entry point for Drone_control_v1.3, a Python-based GUI application for drone control via SSH.
"""

import sys, os, logging, paramiko, re, time, keyring
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QTextEdit, QMessageBox, QLineEdit,
    QSizePolicy, QCheckBox, QTabWidget, QToolButton, QStyle, QDialog,
    QDialogButtonBox, QPlainTextEdit, QFormLayout
)
from PyQt5.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QPalette, QColor
from ssh_executor import SSHExecutor
from gui_components import SavedCommandsPage, AppLogPage, LogSignalHandler
from datetime import datetime

SCALE = 0.7

###############################################################################
# Logging Setup
###############################################################################
logger = logging.getLogger("DroneControl")

class WifiTempWorker(QThread):
    """Runs Wi-Fi temperature read over SSH off the UI thread."""
    temp_ready = pyqtSignal(object)   # float or None
    temp_error = pyqtSignal(str)

    def __init__(self, ssh_executor):
        super().__init__()
        self._ssh_executor = ssh_executor

    def run(self):
        try:
            t = self._ssh_executor.get_wifi_module_temperature()
            self.temp_ready.emit(t)
        except Exception as e:
            self.temp_error.emit(str(e))

logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
gui_log_handler = LogSignalHandler()
gui_log_handler.setFormatter(formatter)
logger.addHandler(gui_log_handler)

###############################################################################
# Dark GNOME-like Styling
###############################################################################
def apply_dark_gnome_style(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.Base, QColor(45, 45, 45))
    palette.setColor(QPalette.AlternateBase, QColor(60, 60, 60))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 225))
    palette.setColor(QPalette.ToolTipText, Qt.black)
    palette.setColor(QPalette.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.Button, QColor(60, 60, 60))
    palette.setColor(QPalette.ButtonText, QColor(230, 230, 230))
    palette.setColor(QPalette.Highlight, QColor(100, 180, 255))
    palette.setColor(QPalette.HighlightedText, Qt.white)
    app.setPalette(palette)

def apply_global_stylesheet(app):
    app.setStyleSheet(f"""
    QMainWindow {{
        background-color: #1E1E1E;
    }}
    QDockWidget#LeftMenuDock {{
        background-color: #2E2E2E;
    }}
    QPushButton {{
        background-color: #3A3A3A;
        color: #FFFFFF;
        border: 1px solid #555555;
        border-radius: 4px;
        font-size: {int(14 * SCALE)}pt;
        padding: {int(10 * SCALE)}px {int(16 * SCALE)}px;
        margin: {int(6 * SCALE)}px;
        min-width: {int(120 * SCALE)}px;
        min-height: {int(60 * SCALE)}px;
    }}
    QPushButton:hover {{
        background-color: #505050;
        border: 1px solid #888888;
    }}
    QPushButton:pressed {{
        background-color: #606060;
        border: 1px dashed #AAAAAA;
    }}
    QLabel {{
        color: #EEEEEE;
        font-size: {int(13 * SCALE)}pt;
    }}
    QLineEdit, QTextEdit {{
        background-color: #3A3A3A;
        color: white;
        border: 1px solid #555555;
        border-radius: 4px;
    }}
    QCheckBox {{
        color: white;
        font-size: {int(12 * SCALE)}pt;
    }}
    QTabWidget::pane {{
        border: 1px solid #555555;
        background: #2E2E2E;
    }}
    QTabBar::tab {{
        background: #3A3A3A;
        color: white;
        border: 1px solid #555555;
        border-radius: 4px;
        padding: 8px;
        margin: 2px;
    }}
    QTabBar::tab:hover {{
        background: #505050;
    }}
    QTabBar::tab:selected {{
        background: #606060;
    }}
    """)

###############################################################################
# DroneControlApp
###############################################################################
class DroneControlApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Drone_control_v1.3")
        self.resize(int(1200 * SCALE), int(700 * SCALE))

        self.ssh_executor = SSHExecutor()
        # Wi-Fi temp polling state (avoid UI freezes)
        self._wifi_temp_busy = False
        self._wifi_temp_worker = None
        self.time_synced = False
        self.connection_check_enabled = bool(self.ssh_executor.ssh_config.get("connection_check_enabled", True))
        self.connection_check_interval = int(self.ssh_executor.ssh_config.get("connection_check_interval", 30000))  # ms
        self.camera_swapped = False
        self.is_rebooting_or_shutting_down = False

        # Labels shown in UI
        self.companion_version_label = QLabel("Companion Version: N/A")
        self.companion_version_label.setStyleSheet("font-size: 12pt; color: #FFFFFF;")
        self.wifi_temp_label = QLabel("Wi-Fi Temp: -- °C")
        self.wifi_temp_label.setStyleSheet("font-size: 12pt; color: #FFFFFF;")

        # Central container
        central_container = QWidget()
        central_layout = QVBoxLayout(central_container)
        central_layout.setContentsMargins(int(20 * SCALE), int(20 * SCALE), int(20 * SCALE), int(20 * SCALE))
        central_layout.setSpacing(int(10 * SCALE))
        self.setCentralWidget(central_container)

        # Top dock (status + temp + refresh)
        self.top_dock = QDockWidget("", self)
        self.top_dock.setObjectName("TopStatusDock")
        self.top_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.top_dock.setTitleBarWidget(QWidget())
        self.top_dock.setAllowedAreas(Qt.TopDockWidgetArea)
        self.addDockWidget(Qt.TopDockWidgetArea, self.top_dock)

        top_dock_widget = QWidget()
        top_dock_layout = QHBoxLayout(top_dock_widget)
        top_dock_layout.setContentsMargins(0, 0, 0, 0)
        top_dock_layout.setSpacing(8)

        self.top_status_label = QLabel("Connected and Ready | Drone IP: Checking...")
        self.top_status_label.setAlignment(Qt.AlignCenter)
        self.top_status_label.setMinimumHeight(int(40 * SCALE))
        self.top_status_label.setStyleSheet("""
            font-size: 16pt;
            font-weight: bold;
            color: black;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #006400, stop:1 #90EE90);
        """)

        top_dock_layout.addWidget(self.top_status_label)
        top_dock_layout.addWidget(self.wifi_temp_label, 0, Qt.AlignRight)

        self.refresh_btn = QToolButton()
        self.refresh_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.refresh_btn.setIconSize(QSize(int(16 * SCALE), int(16 * SCALE)))
        self.refresh_btn.setToolTip("Refresh Connection")
        self.refresh_btn.setStyleSheet("""
            QToolButton { background-color: transparent; border: none; margin-right: 10px; }
            QToolButton:hover { background-color: #505050; }
        """)
        self.refresh_btn.clicked.connect(self.refresh_connection_status)
        top_dock_layout.addWidget(self.refresh_btn, 0, Qt.AlignRight)

        self.top_dock.setWidget(top_dock_widget)

        # Main stack pages
        self.stack = QStackedWidget()
        central_layout.addWidget(self.stack)
        self.page_home = self.create_home_page()
        self.page_conn = self.create_conn_page()
        self.stack.addWidget(self.page_home)
        self.stack.addWidget(self.page_conn)
        self.stack.setCurrentWidget(self.page_home)

        # Side docks
        self.create_left_dock()
        self.create_right_dock()

        # Footer
        self.version_label = QLabel("App Version: v1.1")
        self.version_label.setStyleSheet("font-style: italic; color: #AAAAAA;")
        self.statusBar().addPermanentWidget(self.version_label)

        # Timers
        self.temp_timer = QTimer(self)
        self.temp_timer.timeout.connect(self.update_wifi_temp)
        # Wifi Module Temperature Check Delay
        self.temp_timer.start(1000)  

        # Initial connection check
        self.refresh_connection_status()

    # -------------------- Home Page --------------------
    def create_home_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(int(20 * SCALE), int(20 * SCALE), int(20 * SCALE), int(20 * SCALE))
        layout.setSpacing(int(15 * SCALE))

        # Header row
        header_layout = QHBoxLayout()
        lblTitle = QLabel("Camera Control")
        lblTitle.setStyleSheet(f"font-size: {int(20 * SCALE)}pt; font-weight: bold; color: #FFFFFF;")
        header_layout.addWidget(lblTitle)
        header_layout.addStretch()
        header_layout.addWidget(self.companion_version_label)
        layout.addLayout(header_layout)

        # Switch row
        rowSwitch = QHBoxLayout()
        rowSwitch.setSpacing(int(15 * SCALE))
        btnFrontSW = self.create_tile_button("F-SW", "#008B8B",
                                             "Front camera switched.",
                                             self.front_switch,
                                             "Failed to switch front camera. Check SSH credentials or remote command.")
        btnBottomSW = self.create_tile_button("B-SW", "#008B8B",
                                              "Bottom camera switched.",
                                              self.bottom_switch,
                                              "Failed to switch bottom camera. Check SSH credentials or remote command.")
        btnSplitFBSW = self.create_tile_button("F/B-SW", "#008B8B",
                                               "Split (Front/Bottom) switched.",
                                               self.split_front_bottom,
                                               "Failed to switch split (front/bottom). Check SSH credentials or remote command.")
        btnSplitBFSW = self.create_tile_button("B/F-SW", "#008B8B",
                                               "Split (Bottom/Front) switched.",
                                               self.split_bottom_front,
                                               "Failed to switch split (bottom/front). Check SSH credentials or remote command.")
        rowSwitch.addWidget(btnFrontSW)
        rowSwitch.addWidget(btnBottomSW)
        rowSwitch.addWidget(btnSplitFBSW)
        rowSwitch.addWidget(btnSplitBFSW)
        layout.addLayout(rowSwitch)

        # Capture row
        rowCapture = QHBoxLayout()
        rowCapture.setSpacing(int(15 * SCALE))
        btnCaptureFront = self.create_tile_button("Capture - Front", "#FFB900",
                                                  "Captured image from Front camera.",
                                                  self.capture_front,
                                                  "Failed to capture front image. Check SSH credentials or remote command.")
        btnCaptureBottom = self.create_tile_button("Capture - Bottom", "#FFB900",
                                                   "Captured image from Bottom camera.",
                                                   self.capture_bottom,
                                                   "Failed to capture bottom image. Check SSH credentials or remote command.")
        rowCapture.addWidget(btnCaptureFront)
        rowCapture.addWidget(btnCaptureBottom)
        layout.addLayout(rowCapture)

        # Record row
        rowRecord = QHBoxLayout()
        rowRecord.setSpacing(int(15 * SCALE))
        btnRecordFront = QPushButton("Record - Front")
        btnRecordFront.setStyleSheet(self._record_btn_css())
        btnRecordFront.clicked.connect(self.record_front)
        btnRecordBottom = QPushButton("Record - Bottom")
        btnRecordBottom.setStyleSheet(self._record_btn_css())
        btnRecordBottom.clicked.connect(self.record_bottom)
        rowRecord.addWidget(btnRecordFront)
        rowRecord.addWidget(btnRecordBottom)
        layout.addLayout(rowRecord)

        # Duration row
        dur_layout = QHBoxLayout()
        lblDur = QLabel("Record Duration (sec):")
        lblDur.setStyleSheet(f"font-size: {int(14 * SCALE)}pt; color: #FFFFFF;")
        self.record_duration_entry = QLineEdit()
        self.record_duration_entry.setFixedWidth(int(100 * SCALE))
        self.record_duration_entry.setPlaceholderText("Seconds")
        dur_layout.addWidget(lblDur)
        dur_layout.addWidget(self.record_duration_entry)
        layout.addLayout(dur_layout)

        # Placeholder
        placeholder = QLabel("[Camera feed preview or additional info here...]")
        placeholder.setStyleSheet(f"background-color: #3A3A3A; border: 1px solid #555555; font-size: {int(12 * SCALE)}pt; color: #FFFFFF;")
        placeholder.setAlignment(Qt.AlignCenter)
        layout.addWidget(placeholder)

        return page

    def _record_btn_css(self):
        return f"""
            QPushButton {{
                background-color: #10893E;
                color: white;
                border: 1px solid #555555;
                font-size: {int(14 * SCALE)}pt;
                padding: {int(8 * SCALE)}px;
                margin: {int(6 * SCALE)}px;
                min-width: {int(130 * SCALE)}px;
                min-height: {int(60 * SCALE)}px;
            }}
            QPushButton:hover {{ background-color: #666666; }}
            QPushButton:pressed {{ background-color: #777777; }}
        """

    # -------------------- Left Dock --------------------
    def create_left_dock(self):
        dock = QDockWidget("", self)
        dock.setObjectName("LeftMenuDock")
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock.setTitleBarWidget(QWidget())
        dock.setMinimumWidth(int(180 * SCALE))
        dock.setStyleSheet("background-color: #2E2E2E;")

        menuWidget = QWidget()
        menuLayout = QVBoxLayout(menuWidget)
        menuLayout.setContentsMargins(int(10 * SCALE), int(10 * SCALE), int(10 * SCALE), int(10 * SCALE))
        menuLayout.setSpacing(int(10 * SCALE))

        def style_menu_button(btn):
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #444444;
                    color: white;
                    border: 1px solid #555555;
                    font-size: 14pt;
                    padding: 10px;
                    margin: 4px;
                    min-width: 100px;
                }
                QPushButton:hover { background-color: #555555; }
                QPushButton:pressed { background-color: #666666; }
            """)

        btnHome = QPushButton("Home");            style_menu_button(btnHome)
        btnSettings = QPushButton("Settings");    style_menu_button(btnSettings)
        btnCompanionSSH = QPushButton("Companion SSH"); style_menu_button(btnCompanionSSH)
        btnRelaySSH = QPushButton("Relay SSH");   style_menu_button(btnRelaySSH)
        btnQGC = QPushButton("Launch QGC App");   style_menu_button(btnQGC)
        btnExit = QPushButton("Exit");            style_menu_button(btnExit)

        btnHome.clicked.connect(lambda: self.stack.setCurrentWidget(self.page_home))
        btnSettings.clicked.connect(lambda: self.stack.setCurrentWidget(self.page_conn))
        btnCompanionSSH.clicked.connect(self.open_companion_ssh_terminal)
        btnRelaySSH.clicked.connect(self.open_relay_ssh_terminal)
        btnQGC.clicked.connect(self.launch_qgc_app)
        btnExit.clicked.connect(self.close)

        for btn in [btnHome, btnSettings, btnCompanionSSH, btnRelaySSH, btnQGC, btnExit]:
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            menuLayout.addWidget(btn)

        # Danger zone actions
        companionRebootBtn = QPushButton("Companion Reboot")
        companionRebootBtn.setStyleSheet("background-color: #D2691E; color: white; font-weight: bold;")
        companionRebootBtn.clicked.connect(lambda: self.confirm_action(
            "Reboot ALL companion computers?",
            lambda: self.reboot_companion_and_restart_tunnel()))
        companionShutdownBtn = QPushButton("Companion Shutdown")
        companionShutdownBtn.setStyleSheet("background-color: #AA0000; color: white; font-weight: bold;")
        companionShutdownBtn.clicked.connect(lambda: self.confirm_action(
            "Shutdown ALL companion computers?",
            lambda: self.shutdown_companion_and_restart_tunnel()))
        relayRebootBtn = QPushButton("Reboot Relay")
        relayRebootBtn.setStyleSheet("background-color: #D2691E; color: white; font-weight: bold;")
        relayRebootBtn.clicked.connect(lambda: self.confirm_action(
            "Reboot the relay station?",
            lambda: self.reboot_relay()))
        relayShutdownBtn = QPushButton("Shutdown Relay")
        relayShutdownBtn.setStyleSheet("background-color: #AA0000; color: white; font-weight: bold;")
        relayShutdownBtn.clicked.connect(lambda: self.confirm_action(
            "Shutdown the relay station?",
            lambda: self.shutdown_relay()))

        menuLayout.addWidget(companionRebootBtn)
        menuLayout.addWidget(companionShutdownBtn)
        menuLayout.addWidget(relayRebootBtn)
        menuLayout.addWidget(relayShutdownBtn)
        menuLayout.addStretch()

        dock.setWidget(menuWidget)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    # -------------------- Right Dock --------------------
    def create_right_dock(self):
        dock = QDockWidget("", self)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock.setTitleBarWidget(QWidget())
        dock.setMinimumWidth(int(360 * SCALE))
        dock.setStyleSheet("background-color: #2E2E2E;")

        tabs = QTabWidget()
        self.app_log_page = AppLogPage(gui_log_handler)
        tabs.addTab(self.app_log_page, "App Log")
        self.saved_cmd_page = SavedCommandsPage()
        tabs.addTab(self.saved_cmd_page, "Saved Commands")

        dock.setWidget(tabs)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    # -------------------- Settings / Connection Page --------------------
    def create_conn_page(self):
        page = QWidget()
        main_layout = QVBoxLayout(page)
        main_layout.setContentsMargins(int(20 * SCALE), int(20 * SCALE), int(20 * SCALE), int(20 * SCALE))
        main_layout.setSpacing(int(20 * SCALE))

        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)

        # Connection Settings tab
        connection_tab = QWidget()
        conn_layout = QHBoxLayout(connection_tab)
        conn_layout.setContentsMargins(int(20 * SCALE), int(20 * SCALE), int(20 * SCALE), int(20 * SCALE))
        conn_layout.setSpacing(int(20 * SCALE))
        conn_layout.setAlignment(Qt.AlignTop)

        # Column 1 - Companion
        col1 = QWidget(); col1_layout = QVBoxLayout(col1); col1_layout.setSpacing(int(5 * SCALE))
        lblSSH = QLabel("Companion SSH Configuration")
        lblSSH.setStyleSheet(f"font-size: {int(14 * SCALE)}pt; font-weight: bold; color: #FFFFFF;")
        col1_layout.addWidget(lblSSH)
        col1_layout.addWidget(QLabel("Primary IP (Relay Tunnel):"))
        self.primary_ip_entry = QLineEdit(self.ssh_executor.ssh_config.get("primary_ip", "10.5.6.100"))
        col1_layout.addWidget(self.primary_ip_entry)
        col1_layout.addWidget(QLabel("Primary Port (Relay Tunnel):"))
        self.primary_port_entry = QLineEdit(self.ssh_executor.ssh_config.get("primary_port", "2222"))
        col1_layout.addWidget(self.primary_port_entry)
        col1_layout.addWidget(QLabel("Secondary IP (Optional):"))
        self.secondary_ip_entry = QLineEdit(str(self.ssh_executor.ssh_config.get("secondary_ip", "")))
        col1_layout.addWidget(self.secondary_ip_entry)
        col1_layout.addWidget(QLabel("Secondary Port:"))
        self.secondary_port_entry = QLineEdit(str(self.ssh_executor.ssh_config.get("secondary_port", "22")))
        col1_layout.addWidget(self.secondary_port_entry)
        col1_layout.addWidget(QLabel("Username (Companion):"))
        self.username_entry = QLineEdit(self.ssh_executor.username)
        col1_layout.addWidget(self.username_entry)
        col1_layout.addWidget(QLabel("Password:"))
        self.password_entry = QLineEdit(); self.password_entry.setEchoMode(QLineEdit.Password)
        col1_layout.addWidget(self.password_entry)
        btnApplySSH = QPushButton("Apply")
        btnApplySSH.setStyleSheet("background-color: #10893E; color: white; font-weight: bold;")
        btnApplySSH.clicked.connect(self.apply_ssh_config)
        col1_layout.addWidget(btnApplySSH)
        conn_layout.addWidget(col1)

        # Column 2 - Relay
        col2 = QWidget(); col2_layout = QVBoxLayout(col2); col2_layout.setSpacing(int(5 * SCALE))
        lblRelaySSH = QLabel("Relay SSH Configuration")
        lblRelaySSH.setStyleSheet(f"font-size: {int(14 * SCALE)}pt; font-weight: bold; color: #FFFFFF;")
        col2_layout.addWidget(lblRelaySSH)
        col2_layout.addWidget(QLabel("Relay IP:"))
        self.relay_ip_entry = QLineEdit(self.ssh_executor.ssh_config.get("relay_ip", "10.5.6.100"))
        col2_layout.addWidget(self.relay_ip_entry)
        col2_layout.addWidget(QLabel("Relay SSH Port:"))
        self.relay_ssh_port_entry = QLineEdit(self.ssh_executor.ssh_config.get("relay_ssh_port", "22"))
        col2_layout.addWidget(self.relay_ssh_port_entry)
        col2_layout.addWidget(QLabel("Username (Relay):"))
        self.relay_username_entry = QLineEdit(self.ssh_executor.relay_username)
        col2_layout.addWidget(self.relay_username_entry)
        col2_layout.addWidget(QLabel("Password:"))
        self.relay_password_entry = QLineEdit(); self.relay_password_entry.setEchoMode(QLineEdit.Password)
        col2_layout.addWidget(self.relay_password_entry)
        btnApplyRelaySSH = QPushButton("Apply")
        btnApplyRelaySSH.setStyleSheet("background-color: #10893E; color: white; font-weight: bold;")
        btnApplyRelaySSH.clicked.connect(self.apply_relay_ssh_config)
        col2_layout.addWidget(btnApplyRelaySSH)
        conn_layout.addWidget(col2)

        # Column 3 - Periodic Check
        col3 = QWidget(); col3_layout = QVBoxLayout(col3); col3_layout.setSpacing(int(5 * SCALE))
        lblCheck = QLabel("Periodic Connection Check")
        lblCheck.setStyleSheet(f"font-size: {int(14 * SCALE)}pt; font-weight: bold; color: #FFFFFF;")
        col3_layout.addWidget(lblCheck)
        self.conn_check_enabled_box = QCheckBox("Enable Periodic Connection Check")
        self.conn_check_enabled_box.setChecked(self.connection_check_enabled)
        col3_layout.addWidget(self.conn_check_enabled_box)
        col3_layout.addWidget(QLabel("Check Interval (seconds):"))
        self.interval_entry = QLineEdit(str(self.connection_check_interval // 1000))  # seconds
        col3_layout.addWidget(self.interval_entry)
        self.timeout_entry = QLineEdit(str(self.ssh_executor.timeout))
        col3_layout.addWidget(QLabel("Timeout (seconds):"))
        col3_layout.addWidget(self.timeout_entry)
        self.max_attempts_entry = QLineEdit(str(self.ssh_executor.max_attempts))
        col3_layout.addWidget(QLabel("Max Attempts:"))
        col3_layout.addWidget(self.max_attempts_entry)
        btnApplyCheck = QPushButton("Apply")
        btnApplyCheck.setStyleSheet("background-color: #10893E; color: white; font-weight: bold;")
        btnApplyCheck.clicked.connect(self.apply_connection_settings)
        col3_layout.addWidget(btnApplyCheck)
        conn_layout.addWidget(col3)

        tab_widget.addTab(connection_tab, "Connection Settings")

        # Camera Settings tab
        camera_tab = QWidget()
        main_cam_layout = QVBoxLayout(camera_tab)
        main_cam_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        main_cam_layout.setContentsMargins(int(20 * SCALE), int(20 * SCALE), int(20 * SCALE), int(20 * SCALE))
        main_cam_layout.setSpacing(int(20 * SCALE))

        lblCamTitle = QLabel("Camera Settings")
        lblCamTitle.setStyleSheet(f"font-size: {int(16 * SCALE)}pt; font-weight: bold; color: #FFFFFF;")
        main_cam_layout.addWidget(lblCamTitle)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignLeft)
        form_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form_layout.setSpacing(int(10 * SCALE))
        self.camera_device_entry = QLineEdit("/dev/video0")
        self.camera_res_entry = QLineEdit("1920x1080")
        self.camera_fps_entry = QLineEdit("60")
        self.camera_format_entry = QLineEdit("MJPG")
        form_layout.addRow("Camera Device:", self.camera_device_entry)
        form_layout.addRow("Resolution (WxH):", self.camera_res_entry)
        form_layout.addRow("FPS:", self.camera_fps_entry)
        form_layout.addRow("Format:", self.camera_format_entry)
        main_cam_layout.addLayout(form_layout)

        swap_checkbox = QCheckBox("Swap Cameras")
        swap_checkbox.setToolTip("When enabled, front becomes /dev/video2 and bottom becomes /dev/video0.")
        swap_checkbox.toggled.connect(self.toggle_camera_swap)
        main_cam_layout.addWidget(swap_checkbox, alignment=Qt.AlignLeft)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(int(10 * SCALE))
        btnApplyCam = QPushButton("Apply")
        btnApplyCam.setFixedSize(100, 30)
        btnApplyCam.setStyleSheet("background-color: #10893E; color: white; font-weight: bold;")
        btnApplyCam.clicked.connect(self.apply_camera_settings)
        btnQueryCam = QPushButton("Query")
        btnQueryCam.setFixedSize(100, 30)
        btnQueryCam.setStyleSheet("background-color: #007ACC; color: white; font-weight: bold;")
        btnQueryCam.clicked.connect(self.query_camera_details)
        btn_layout.addWidget(btnApplyCam, alignment=Qt.AlignLeft)
        btn_layout.addWidget(btnQueryCam, alignment=Qt.AlignLeft)
        main_cam_layout.addLayout(btn_layout)

        tab_widget.addTab(camera_tab, "Camera Settings")

        # About tab
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setContentsMargins(int(20 * SCALE), int(20 * SCALE), int(20 * SCALE), int(20 * SCALE))
        about_layout.setSpacing(int(10 * SCALE))
        lblAboutTitle = QLabel("About Drone_control_v1.3")
        lblAboutTitle.setStyleSheet(f"font-size: {int(16 * SCALE)}pt; font-weight: bold; color: #FFFFFF;")
        about_layout.addWidget(lblAboutTitle)
        about_text = QTextEdit()
        about_text.setReadOnly(True)
        about_text.setStyleSheet("background-color: #3A3A3A; color: #FFFFFF; border: 1px solid #555555;")
        about_text.setText("""
<b>Drone_control_v1.3</b><br>
A Python-based GUI application built with PyQt5 for controlling a drone's companion computer via SSH.<br><br>

<b>Description:</b><br>
This application provides a user-friendly interface to manage drone camera controls, and SSH connections. It connects to a companion computer through a relay station at 10.5.6.100:2222 (username: roz) and supports secondary IP failover. Features include camera switching, image/video capture, and system management (reboot/shutdown). Windows version uses paramiko for SSH.<br><br>

<b>Changelog:</b><br>
- Added Wi-Fi module temperature in the top status bar (updates every 5s).<br>
- Updated all "Apply ..." buttons to simply read "Apply."<br>
- Removed the large home-screen toggle for camera swap (use the checkbox in Camera Settings instead).<br>
- Companion computer version is displayed as "N/A" (not retrieved due to configuration).<br>
- Restored the three-column Connection Settings tab with improved alignment.<br>
- Added explicit port fields and relay SSH settings in Connection Settings tab.<br>
- Updated capture and video to match Rozcam script and transfer files via tunnel with delay.<br>
- Added Relay SSH and Shutdown Relay buttons to left menu, renamed Open SSH Terminal to Companion SSH.<br>
- Enhanced SSH command execution with retry logic (max_attempts=3, 5-second delay).<br>
- Added sudo password handling for SSH commands.<br>
- Added restart_relay_ssh_tunnel method to handle SSH tunnel restarts after reboots/shutdowns.<br>
- Renamed Reboot and Shutdown buttons to Companion Reboot and Companion Shutdown for clarity.<br>
- Removed ROS2 Topics tab and related functionality.<br>
- Improved reboot/shutdown handling and connection checks.<br><br>
""")
        about_layout.addWidget(about_text)
        tab_widget.addTab(about_tab, "About")

        return page

    # -------------------- Camera control helpers --------------------
    def toggle_camera_swap(self, new_state):
        self.camera_swapped = new_state
        state_str = "Swapped" if self.camera_swapped else "Default"
        logger.info("Camera swap toggled. Now using '%s' mapping.", state_str)
        self.show_success_message(f"Camera mapping is now: {state_str}")

    def front_switch(self):
        device = "/dev/video2" if self.camera_swapped else "/dev/video0"
        command = f"sudo vision_config_manager {device}"
        if self.ssh_executor.execute_command(command, "Front camera switched.", "Failed to switch front camera. Check SSH credentials or remote command."):
            self.show_success_message("Front camera switched.")
        else:
            self.show_error_message("Failed to switch front camera. Check SSH credentials or remote command.")

    def bottom_switch(self):
        device = "/dev/video0" if self.camera_swapped else "/dev/video2"
        command = f"sudo vision_config_manager {device}"
        if self.ssh_executor.execute_command(command, "Bottom camera switched.", "Failed to switch bottom camera. Check SSH credentials or remote command."):
            self.show_success_message("Bottom camera switched.")
        else:
            self.show_error_message("Failed to switch bottom camera. Check SSH credentials or remote command.")

    def split_front_bottom(self):
        command = "sudo vision_config_manager /dev/video2 /dev/video0" if self.camera_swapped else "sudo vision_config_manager /dev/video0 /dev/video2"
        if self.ssh_executor.execute_command(command, "Split (Front/Bottom) switched.", "Failed to switch split (front/bottom). Check SSH credentials or remote command."):
            self.show_success_message("Split (Front/Bottom) switched.")
        else:
            self.show_error_message("Failed to switch split (front/bottom). Check SSH credentials or remote command.")

    def split_bottom_front(self):
        command = "sudo vision_config_manager /dev/video0 /dev/video2" if self.camera_swapped else "sudo vision_config_manager /dev/video2 /dev/video0"
        if self.ssh_executor.execute_command(command, "Split (Bottom/Front) switched.", "Failed to switch split (bottom/front). Check SSH credentials or remote command."):
            self.show_success_message("Split (Bottom/Front) switched.")
        else:
            self.show_error_message("Failed to switch split (bottom/front). Check SSH credentials or remote command.")

    def capture_front(self):
        device = "/dev/video2" if self.camera_swapped else "/dev/video0"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_path = f"/home/roz/Model_image/Rozcam_{timestamp}.jpg"
        local_path = os.path.join(os.path.expanduser("~"), "Pictures", f"Rozcam_{timestamp}.jpg")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        command = f"Rozcam -i {device}"
        if self.ssh_executor.execute_command(command, f"Captured image from Front ({device}).", "Failed to capture front image. Check SSH credentials or remote command."):
            time.sleep(2)
            success, transferred_path = self.ssh_executor.transfer_file(remote_path, local_path)
            if success:
                self.show_success_message(f"Front image captured and saved to {transferred_path}")
            else:
                self.show_error_message(f"Failed to transfer front image from {remote_path}. Check path or permissions.")
        else:
            self.show_error_message("Failed to capture front image. Check SSH credentials or remote command.")

    def capture_bottom(self):
        device = "/dev/video0" if self.camera_swapped else "/dev/video2"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_path = f"/home/roz/Model_image/Rozcam_{timestamp}.jpg"
        local_path = os.path.join(os.path.expanduser("~"), "Pictures", f"Rozcam_{timestamp}.jpg")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        command = f"Rozcam -i {device}"
        if self.ssh_executor.execute_command(command, f"Captured image from Bottom ({device}).", "Failed to capture bottom image. Check SSH credentials or remote command."):
            time.sleep(2)
            success, transferred_path = self.ssh_executor.transfer_file(remote_path, local_path)
            if success:
                self.show_success_message(f"Bottom image captured and saved to {transferred_path}")
            else:
                self.show_error_message(f"Failed to transfer bottom image from {remote_path}. Check path or permissions.")
        else:
            self.show_error_message("Failed to capture bottom image. Check SSH credentials or remote command.")

    def record_front(self):
        device = "/dev/video2" if self.camera_swapped else "/dev/video0"
        dur = self.record_duration_entry.text().strip()
        if not dur.isdigit():
            self.show_error_message("Please enter a valid duration in seconds.")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_path = f"/home/roz/Model_video/Rozcam_{timestamp}.mp4"
        local_path = os.path.join(os.path.expanduser("~"), "Videos", f"Rozcam_{timestamp}.mp4")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        command = f"Rozcam -v {device} {dur}"
        if self.ssh_executor.execute_command(command, f"Recording Front camera ({device}) for {dur} seconds.", "Failed to record front camera. Check SSH credentials or remote command."):
            time.sleep(int(dur) + 2)
            success, transferred_path = self.ssh_executor.transfer_file(remote_path, local_path)
            if success:
                self.show_success_message(f"Front video recorded and saved to {transferred_path}")
            else:
                self.show_error_message(f"Failed to transfer front video from {remote_path}. Check path or duration.")
        else:
            self.show_error_message("Failed to record front camera. Check SSH credentials or remote command.")

    def record_bottom(self):
        device = "/dev/video0" if self.camera_swapped else "/dev/video2"
        dur = self.record_duration_entry.text().strip()
        if not dur.isdigit():
            self.show_error_message("Please enter a valid duration in seconds.")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_path = f"/home/roz/Model_video/Rozcam_{timestamp}.mp4"
        local_path = os.path.join(os.path.expanduser("~"), "Videos", f"Rozcam_{timestamp}.mp4")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        command = f"Rozcam -v {device} {dur}"
        if self.ssh_executor.execute_command(command, f"Recording Bottom camera ({device}) for {dur} seconds.", "Failed to record bottom camera. Check SSH credentials or remote command."):
            time.sleep(int(dur) + 2)
            success, transferred_path = self.ssh_executor.transfer_file(remote_path, local_path)
            if success:
                self.show_success_message(f"Bottom video recorded and saved to {transferred_path}")
            else:
                self.show_error_message(f"Failed to transfer bottom video from {remote_path}. Check path or duration.")
        else:
            self.show_error_message("Failed to record bottom camera. Check SSH credentials or remote command.")

    # -------------------- Connection / status --------------------
    def refresh_connection_status(self):
        if self.is_rebooting_or_shutting_down:
            self.update_connection_status("System Rebooting/Shutting Down", "gray", "Drone IP: Temporarily Unavailable", "gray")
            return

        original_timeout = self.ssh_executor.timeout
        original_max_attempts = self.ssh_executor.max_attempts
        try:
            self.ssh_executor.timeout = int(self.ssh_executor.timeout)
            self.ssh_executor.max_attempts = int(self.ssh_executor.max_attempts)
        except (ValueError, AttributeError):
            logger.warning("Invalid timeout or max attempts in settings, using defaults.")
            self.ssh_executor.timeout = 5
            self.ssh_executor.max_attempts = 3

        reachable_ip = self.ssh_executor.test_connection()
        if reachable_ip:
            self.update_connection_status("Connected and Ready", "green", f"Drone IP: {reachable_ip}:{self.ssh_executor.current_port}", "green")
            self.update_companion_version()
            self.update_wifi_temp()  # refresh immediately on connect
        else:
            self.update_connection_status("Not Ready", "red", "Drone IP: Not Connected", "red")
            self.ssh_executor.restart_relay_ssh_tunnel()

        self.ssh_executor.timeout = original_timeout
        self.ssh_executor.max_attempts = original_max_attempts

    def periodic_connection_check(self):
        if not self.connection_check_enabled or self.is_rebooting_or_shutting_down:
            self.update_connection_status("Connection Check Disabled", "gray", "Drone IP: N/A", "gray")
            return

        original_timeout = self.ssh_executor.timeout
        original_max_attempts = self.ssh_executor.max_attempts
        try:
            self.ssh_executor.timeout = int(self.ssh_executor.timeout)
            self.ssh_executor.max_attempts = int(self.ssh_executor.max_attempts)
        except (ValueError, AttributeError):
            logger.warning("Invalid timeout or max attempts in settings, using defaults.")
            self.ssh_executor.timeout = 5
            self.ssh_executor.max_attempts = 3

        reachable_ip = self.ssh_executor.test_connection()
        if reachable_ip:
            self.update_connection_status("Connected and Ready", "green", f"Drone IP: {reachable_ip}:{self.ssh_executor.current_port}", "green")
            if not self.time_synced:
                self.sync_time_with_popup(reachable_ip)
                self.time_synced = True
            self.update_companion_version()
            self.update_wifi_temp()
        else:
            self.update_connection_status("Not Ready", "red", "Drone IP: Not Connected", "red")
            self.ssh_executor.restart_relay_ssh_tunnel()

        self.ssh_executor.timeout = original_timeout
        self.ssh_executor.max_attempts = original_max_attempts
        QTimer.singleShot(self.connection_check_interval, self.periodic_connection_check)

    def update_connection_status(self, status_text, status_color, ip_text, ip_color):
        if status_color.lower() == "green":
            combined_text = f"Connected and Ready | {ip_text}"
            self.top_status_label.setText(combined_text)
            self.top_status_label.setStyleSheet("""
                font-size: 16pt;
                font-weight: bold;
                color: black;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #006400, stop:1 #90EE90);
            """)
        elif status_color.lower() == "red":
            combined_text = f"Not Ready | {ip_text}"
            self.top_status_label.setText(combined_text)
            self.top_status_label.setStyleSheet("""
                font-size: 16pt;
                font-weight: bold;
                color: white;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8B0000, stop:1 #FF6347);
            """)
        else:
            combined_text = f"{status_text} | {ip_text}"
            self.top_status_label.setText(combined_text)
            self.top_status_label.setStyleSheet("""
                font-size: 16pt;
                font-weight: bold;
                color: #FFFFFF;
                background-color: #2E2E2E;
            """)

    def sync_time_with_popup(self, reachable_ip):
        logger.info("Synchronizing time with drone at IP: %s:%s", reachable_ip, self.ssh_executor.current_port)
        success = self.ssh_executor.sync_date_time()
        if success:
            self.show_success_message("Time synchronized with the drone.")
        else:
            self.show_error_message("Failed to synchronize time with the drone.")

    def update_companion_version(self):
        command = "cat /etc/sid.conf"  # Assumes remote is Linux
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(self.ssh_executor.current_ip, int(self.ssh_executor.current_port), self.ssh_executor.username, self.ssh_executor.password, timeout=self.ssh_executor.timeout)
            stdin, stdout, stderr = ssh.exec_command(command)
            content = stdout.read().decode().strip()
            version = "N/A"
            if content:
                match = re.search(r"[\s:](\d+\.\d+)", content)
                version = match.group(1) if match else "N/A"
            self.companion_version_label.setText(f"Companion Version: {version}")
        except paramiko.AuthenticationException as e:
            logger.error("SSH Authentication failed for version retrieval: %s", e)
            self.companion_version_label.setText("Companion Version: N/A")
        except Exception as e:
            logger.error("Error retrieving companion version: %s", e)
            self.companion_version_label.setText("Companion Version: N/A")
        finally:
            ssh.close()

    # -------------------- Generic helpers --------------------
    def create_tile_button(self, text, bg_color, success_msg, command, error_msg):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: white;
                border: 1px solid #555555;
                font-size: {int(14 * SCALE)}pt;
                padding: {int(8 * SCALE)}px;
                margin: {int(6 * SCALE)}px;
                min-width: {int(130 * SCALE)}px;
                min-height: {int(60 * SCALE)}px;
            }}
            QPushButton:hover {{ background-color: #666666; }}
            QPushButton:pressed {{ background-color: #777777; }}
        """)
        if callable(command):
            btn.clicked.connect(command)
        else:
            btn.clicked.connect(lambda: self.execute_ssh_command(command, success_msg, error_msg))
        return btn

    def execute_ssh_command(self, command, success_msg, error_msg):
        if self.ssh_executor.execute_command(command, success_msg, error_msg):
            self.show_success_message(success_msg)
        else:
            self.show_error_message(error_msg)

    # -------------------- Settings actions --------------------
    def apply_ssh_config(self):
        self.ssh_executor.ssh_config["primary_ip"] = self.primary_ip_entry.text().strip()
        self.ssh_executor.ssh_config["primary_port"] = self.primary_port_entry.text().strip()
        self.ssh_executor.ssh_config["secondary_ip"] = self.secondary_ip_entry.text().strip()
        self.ssh_executor.ssh_config["secondary_port"] = self.secondary_port_entry.text().strip()
        self.ssh_executor.username = self.username_entry.text().strip()
        password = self.password_entry.text().strip()
        if password:
            keyring.set_password("Drone-Control", self.ssh_executor.username, password)
            self.ssh_executor.password = password
        self.ssh_executor.save_config()
        self.ssh_executor.current_ip = self.ssh_executor.ssh_config["primary_ip"]
        self.ssh_executor.current_port = self.ssh_executor.ssh_config["primary_port"]
        logger.info("Companion SSH Configuration updated: primary IP = %s:%s, secondary IP = %s:%s",
                    self.ssh_executor.ssh_config["primary_ip"],
                    self.ssh_executor.ssh_config["primary_port"],
                    self.ssh_executor.ssh_config["secondary_ip"],
                    self.ssh_executor.ssh_config["secondary_port"])
        self.show_success_message("Companion SSH Configuration updated successfully!")
        self.refresh_connection_status()

    def apply_relay_ssh_config(self):
        self.ssh_executor.ssh_config["relay_ip"] = self.relay_ip_entry.text().strip()
        self.ssh_executor.ssh_config["relay_ssh_port"] = self.relay_ssh_port_entry.text().strip()
        self.ssh_executor.relay_username = self.relay_username_entry.text().strip()
        relay_password = self.relay_password_entry.text().strip()
        if relay_password:
            keyring.set_password("Drone-Control", self.ssh_executor.relay_username, relay_password)
            self.ssh_executor.relay_password = relay_password
        self.ssh_executor.save_config()
        self.ssh_executor.relay_ip = self.ssh_executor.ssh_config["relay_ip"]
        self.ssh_executor.relay_ssh_port = self.ssh_executor.ssh_config["relay_ssh_port"]
        logger.info("Relay SSH Configuration updated: IP = %s:%s, username = %s",
                    self.ssh_executor.ssh_config["relay_ip"],
                    self.ssh_executor.ssh_config["relay_ssh_port"],
                    self.ssh_executor.relay_username)
        self.show_success_message("Relay SSH Configuration updated successfully!")
        self.refresh_connection_status()

    def apply_connection_settings(self):
        self.connection_check_enabled = self.conn_check_enabled_box.isChecked()
        self.ssh_executor.ssh_config["connection_check_enabled"] = self.connection_check_enabled
        try:
            interval_sec = int(self.interval_entry.text())
            if interval_sec <= 0:
                self.show_error_message("Interval must be a positive integer.")
                return
            self.connection_check_interval = interval_sec * 1000
            self.ssh_executor.ssh_config["connection_check_interval"] = self.connection_check_interval

            timeout_sec = int(self.timeout_entry.text())
            if timeout_sec <= 0:
                self.show_error_message("Timeout must be a positive integer.")
                return
            self.ssh_executor.timeout = timeout_sec

            max_attempts = int(self.max_attempts_entry.text())
            if max_attempts <= 0:
                self.show_error_message("Max attempts must be a positive integer.")
                return
            self.ssh_executor.max_attempts = max_attempts
        except ValueError:
            self.show_error_message("Invalid interval, timeout, or max attempts value. Please enter valid integers.")
            return

        self.ssh_executor.save_config()
        logger.info("Connection settings updated: enabled=%s, interval=%d ms, timeout=%d s, max_attempts=%d",
                    self.connection_check_enabled, self.connection_check_interval, self.ssh_executor.timeout, self.ssh_executor.max_attempts)
        self.show_success_message("Connection settings updated successfully!")
        if self.connection_check_enabled:
            self.periodic_connection_check()
        else:
            self.update_connection_status("Connection Check Disabled", "gray", "Drone IP: N/A", "gray")

    # -------------------- Camera settings to remote --------------------
    def apply_camera_settings(self):
        device = self.camera_device_entry.text().strip()
        resolution = self.camera_res_entry.text().strip()
        fps = self.camera_fps_entry.text().strip()
        fmt = self.camera_format_entry.text().strip()
        command = f"sudo vision_config_manager set-cam-params {device} {resolution} {fps} --format {fmt}"
        if self.ssh_executor.execute_command(command, "Camera settings updated successfully.", "Failed to update camera settings. Check SSH credentials or remote command availability."):
            self.update_cam_params_config(device, resolution, fps, fmt)
            self.show_success_message("Camera settings updated successfully.")
        else:
            self.show_error_message("Failed to update camera settings. Check SSH credentials or remote command availability.")

    def update_cam_params_config(self, device, resolution, fps, cam_format):
        config_path = "/etc/vision_streaming.conf"
        if sys.platform.startswith('win'):
            logger.warning("Config file update not supported on Windows locally; assuming remote Linux target.")
        ssh = paramiko.SSHClient(); sftp = None
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(self.ssh_executor.current_ip, int(self.ssh_executor.current_port), self.ssh_executor.username, self.ssh_executor.password, timeout=self.ssh_executor.timeout)
            sftp = ssh.open_sftp()
            with sftp.file(config_path, 'r') as file:
                lines = file.readlines()
            in_target = False
            new_lines = []
            res_updated = fps_updated = format_updated = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('[') and stripped.endswith(']'):
                    if in_target:
                        if not res_updated:
                            new_lines.append(f"resolution = {resolution}\n")
                        if not fps_updated:
                            new_lines.append(f"fps = {fps}\n")
                        if not format_updated:
                            new_lines.append(f"format = {cam_format}\n")
                    in_target = False
                    new_lines.append(line)
                    continue
                if "camera_name" in line and device in line:
                    in_target = True
                    new_lines.append(line)
                    continue
                if in_target:
                    if stripped.lstrip('#').startswith("resolution"):
                        new_lines.append(f"resolution = {resolution}\n"); res_updated = True
                    elif stripped.lstrip('#').startswith("fps"):
                        new_lines.append(f"fps = {fps}\n"); fps_updated = True
                    elif stripped.lstrip('#').startswith("format"):
                        new_lines.append(f"format = {cam_format}\n"); format_updated = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            if in_target:
                if not res_updated:
                    new_lines.append(f"resolution = {resolution}\n")
                if not fps_updated:
                    new_lines.append(f"fps = {fps}\n")
                if not format_updated:
                    new_lines.append(f"format = {cam_format}\n")
            with sftp.file(config_path, 'w') as file:
                file.writelines(new_lines)
            logger.info("Configuration file updated successfully with new camera parameters.")
            self.control_service('restart')
            self.show_success_message("Configuration file updated and service restarted successfully.")
        except paramiko.AuthenticationException as e:
            logger.error("SSH Authentication failed for config update: %s", e)
            self.show_error_message("Failed to update config file. Check SSH credentials.")
        except Exception as e:
            logger.error("Error updating config file: %s", e)
            self.show_error_message(f"Error updating config file: {str(e)}")
        finally:
            try:
                if sftp: sftp.close()
            except Exception:
                pass
            ssh.close()

    def control_service(self, action):
        if sys.platform.startswith('win'):
            logger.warning("Service control not supported on Windows; assuming remote Linux target.")
        command = f"sudo systemctl {action} vision_streaming.service"
        if self.ssh_executor.execute_command(command, f"Service {action}ed.", f"Failed to {action} service."):
            self.show_success_message(f"Service {action}ed.")
        else:
            self.show_error_message(f"Failed to {action} service.")

    def query_camera_details(self):
        device = self.camera_device_entry.text().strip()
        command = f"sudo vision_config_manager list-details {device}"
        if self.ssh_executor.execute_command(command, "Camera details queried successfully.", "Failed to query camera details. Check SSH credentials or remote command availability."):
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                ssh.connect(self.ssh_executor.current_ip, int(self.ssh_executor.current_port), self.ssh_executor.username, self.ssh_executor.password, timeout=self.ssh_executor.timeout)
                stdin, stdout, stderr = ssh.exec_command(command)
                details = stdout.read().decode()
                dialog = QDialog(self)
                dialog.setWindowTitle("Camera Details")
                dialog.resize(800, 600)
                layout = QVBoxLayout(dialog)
                text_area = QPlainTextEdit()
                text_area.setReadOnly(True)
                text_area.setPlainText(details)
                layout.addWidget(text_area)
                button_box = QDialogButtonBox(QDialogButtonBox.Close)
                button_box.rejected.connect(dialog.reject)
                layout.addWidget(button_box)
                dialog.exec_()
                self.show_success_message("Camera details queried successfully.")
            except paramiko.AuthenticationException as e:
                logger.error("SSH Authentication failed for camera query: %s", e)
                self.show_error_message("Failed to query camera details. Check SSH credentials or remote command availability.")
            except Exception as e:
                logger.error("Error querying camera details: %s", e)
                self.show_error_message("Failed to query camera details.")
            finally:
                ssh.close()
        else:
            self.show_error_message("Failed to query camera details. Check SSH credentials or remote command availability.")

    # -------------------- External tools --------------------
    def open_companion_ssh_terminal(self):
        if not self.ssh_executor.current_ip or not self.ssh_executor.username:
            self.show_error_message("No valid SSH configuration found for companion.")
            return
        user = self.ssh_executor.username
        ip = self.ssh_executor.current_ip
        port = self.ssh_executor.current_port
        if sys.platform.startswith('win'):
            command = f'start cmd /k "ssh -p {port} {user}@{ip}"'
        else:
            command = f"gnome-terminal -- ssh -p {port} {user}@{ip}"
        logger.info("Opening external SSH terminal to companion: %s", command)
        QTimer.singleShot(0, lambda: os.system(command))

    def open_relay_ssh_terminal(self):
        if not self.ssh_executor.relay_ip or not self.ssh_executor.relay_username:
            self.show_error_message("No valid SSH configuration found for relay.")
            return
        user = self.ssh_executor.relay_username
        ip = self.ssh_executor.relay_ip
        port = self.ssh_executor.relay_ssh_port
        if sys.platform.startswith('win'):
            command = f'start cmd /k "ssh -p {port} {user}@{ip}"'
        else:
            command = f"gnome-terminal -- ssh -p {port} {user}@{ip}"
        logger.info("Opening external SSH terminal to relay: %s", command)
        QTimer.singleShot(0, lambda: os.system(command))

    def launch_qgc_app(self):
        qgc_path = r"C:\Program Files\QGroundControl\QGroundControl.exe" if sys.platform.startswith('win') else "/home/vind/Desktop/QGroundControl.AppImage"
        if os.path.exists(qgc_path):
            logger.info("Launching QGC App from %s", qgc_path)
            QTimer.singleShot(0, lambda: os.system(f'"{qgc_path}"'))
        else:
            self.show_error_message(f"QGC App not found at {qgc_path}")

    def confirm_action(self, message, action):
        reply = QMessageBox.question(self, "Confirmation", message, QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            action()

    # -------------------- Reboot/shutdown helpers --------------------
    def reboot_companion_and_restart_tunnel(self):
        self.is_rebooting_or_shutting_down = True
        self.update_connection_status("System Rebooting", "gray", "Drone IP: Temporarily Unavailable", "gray")
        original_max_attempts = self.ssh_executor.max_attempts
        original_timeout = self.ssh_executor.timeout
        try:
            self.ssh_executor.max_attempts = 1
            self.ssh_executor.timeout = int(self.ssh_executor.timeout)
        except (ValueError, AttributeError):
            logger.warning("Invalid timeout or max attempts in settings for reboot, using defaults.")
            self.ssh_executor.timeout = 300
            self.ssh_executor.max_attempts = 1

        if self.ssh_executor.execute_command_all("sudo reboot", "Companion computers are rebooting.", "Failed to initiate reboot of companion computers."):
            self.show_success_message("Companion computers are rebooting.")
            time.sleep(90)
            self.refresh_connection_status()
        else:
            self.show_error_message("Failed to initiate reboot of companion computers.")
            self.ssh_executor.restart_relay_ssh_tunnel()

        self.ssh_executor.max_attempts = original_max_attempts
        self.ssh_executor.timeout = original_timeout

    def shutdown_companion_and_restart_tunnel(self):
        self.is_rebooting_or_shutting_down = True
        self.update_connection_status("System Shutting Down", "gray", "Drone IP: Temporarily Unavailable", "gray")
        original_max_attempts = self.ssh_executor.max_attempts
        original_timeout = self.ssh_executor.timeout
        try:
            self.ssh_executor.max_attempts = 1
            self.ssh_executor.timeout = int(self.ssh_executor.timeout)
        except (ValueError, AttributeError):
            logger.warning("Invalid timeout or max attempts in settings for shutdown, using defaults.")
            self.ssh_executor.timeout = 300
            self.ssh_executor.max_attempts = 1

        if self.ssh_executor.execute_command_all("sudo shutdown now", "Companion computers are shutting down.", "Failed to shut down companion computers."):
            self.show_success_message("Companion computers are shutting down.")
            time.sleep(120)
            self.refresh_connection_status()
        else:
            self.show_error_message("Failed to shut down companion computers.")
            self.ssh_executor.restart_relay_ssh_tunnel()

        self.ssh_executor.max_attempts = original_max_attempts
        self.ssh_executor.timeout = original_timeout

    def reboot_relay(self):
        self.is_rebooting_or_shutting_down = True
        self.update_connection_status("System Rebooting", "gray", "Drone IP: Temporarily Unavailable", "gray")
        original_max_attempts = self.ssh_executor.max_attempts
        original_timeout = self.ssh_executor.timeout
        try:
            self.ssh_executor.max_attempts = 1
            self.ssh_executor.timeout = int(self.ssh_executor.timeout)
        except (ValueError, AttributeError):
            logger.warning("Invalid timeout or max attempts in settings for relay reboot, using defaults.")
            self.ssh_executor.timeout = 300
            self.ssh_executor.max_attempts = 1

        if self.ssh_executor.execute_relay_command("sudo reboot", "Relay station is rebooting.", "Failed to reboot relay station."):
            self.show_success_message("Relay station is rebooting.")
            time.sleep(90)
            self.refresh_connection_status()
        else:
            self.show_error_message("Failed to reboot relay station.")
            self.ssh_executor.restart_relay_ssh_tunnel()

        self.ssh_executor.max_attempts = original_max_attempts
        self.ssh_executor.timeout = original_timeout

    def shutdown_relay(self):
        self.is_rebooting_or_shutting_down = True
        self.update_connection_status("System Shutting Down", "gray", "Drone IP: Temporarily Unavailable", "gray")
        original_max_attempts = self.ssh_executor.max_attempts
        original_timeout = self.ssh_executor.timeout
        try:
            self.ssh_executor.max_attempts = 1
            self.ssh_executor.timeout = int(self.ssh_executor.timeout)
        except (ValueError, AttributeError):
            logger.warning("Invalid timeout or max attempts in settings for relay shutdown, using defaults.")
            self.ssh_executor.timeout = 300
            self.ssh_executor.max_attempts = 1

        if self.ssh_executor.execute_relay_command("sudo shutdown now", "Relay station is shutting down.", "Failed to shut down relay station."):
            self.show_success_message("Relay station is shutting down.")
            time.sleep(120)
            self.refresh_connection_status()
        else:
            self.show_error_message("Failed to shut down relay station.")
            self.ssh_executor.restart_relay_ssh_tunnel()

        self.ssh_executor.max_attempts = original_max_attempts
        self.ssh_executor.timeout = original_timeout
    # -------------------- Wi-Fi Temp polling --------------------
    def update_wifi_temp(self):
        """Non-blocking Wi-Fi temperature update.

        Keeps the original method name so existing call sites remain unchanged,
        but moves SSH work into a worker thread to avoid freezing the UI.
        """
        # Skip if a previous read is still running
        if self._wifi_temp_busy:
            return

        self._wifi_temp_busy = True
        self._wifi_temp_worker = WifiTempWorker(self.ssh_executor)
        self._wifi_temp_worker.temp_ready.connect(self._on_wifi_temp_ready)
        self._wifi_temp_worker.temp_error.connect(self._on_wifi_temp_error)
        self._wifi_temp_worker.finished.connect(self._on_wifi_temp_finished)
        self._wifi_temp_worker.start()

    def _on_wifi_temp_ready(self, t):
        try:
            self.wifi_temp_label.setText("Wi-Fi Temp: " + (f"{t:.1f} °C" if t is not None else "N/A"))
        except Exception:
            self.wifi_temp_label.setText("Wi-Fi Temp: N/A")

    def _on_wifi_temp_error(self, msg):
        logger.error("Temp update failed: %s", msg)
        self.wifi_temp_label.setText("Wi-Fi Temp: N/A")

    def _on_wifi_temp_finished(self):
        self._wifi_temp_busy = False
        self._wifi_temp_worker = None

    # -------------------- Utilities --------------------
    def show_success_message(self, message):
        QMessageBox.information(self, "Success", message)

    def show_error_message(self, message):
        QMessageBox.warning(self, "Error", message)

# -------------------- Entrypoint --------------------
def main():
    app = QApplication(sys.argv)
    apply_dark_gnome_style(app)
    apply_global_stylesheet(app)
    logger.debug("Starting Drone_control_v1.3...")
    window = DroneControlApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
