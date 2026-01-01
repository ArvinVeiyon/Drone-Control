#!/usr/bin/env python3
"""
ssh_executor.py
Handles SSH connections and commands for the Drone_control_v1.1 application using paramiko.
"""

import os
import json
import socket
import time
import keyring
import logging
import sys
from datetime import datetime

import paramiko

logger = logging.getLogger("DroneControl")


class SSHExecutor:
    CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "ssh_config.json")
    timeout = 5         # Default timeout in seconds
    max_attempts = 3    # Default max attempts for connection checks

    def __init__(self):
        self.ssh_config = self.load_config()

        self.username = self.ssh_config.get("username", "roz")
        self.password = keyring.get_password("Drone-Control", self.username) or "default_password"

        self.relay_username = self.ssh_config.get("relay_username", "vind-admin")
        self.relay_password = keyring.get_password("Drone-Control", self.relay_username) or "default_password"

        self.current_ip = self.ssh_config.get("primary_ip", "10.5.6.100")
        self.current_port = self.ssh_config.get("primary_port", "2222")

        self.secondary_ip = self.ssh_config.get("secondary_ip", None)
        self.secondary_port = self.ssh_config.get("secondary_port", "22")

        self.relay_ip = self.ssh_config.get("relay_ip", "10.5.6.100")
        self.relay_ssh_port = self.ssh_config.get("relay_ssh_port", "22")

        logger.debug(
            "SSHExecutor init with primary IP: %s:%s, secondary IP: %s:%s, relay IP: %s:%s",
            self.current_ip, self.current_port, self.secondary_ip, self.secondary_port,
            self.relay_ip, self.relay_ssh_port
        )

    # -------------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------------
    def _default_config(self):
        return {
            "primary_ip": "10.5.6.100",
            "primary_port": "2222",
            "secondary_ip": None,
            "secondary_port": "22",
            "username": "roz",
            "relay_ip": "10.5.6.100",
            "relay_ssh_port": "22",
            "relay_username": "vind-admin",
            # Wi-Fi temperature settings (kept for backward compatibility)
            "wifi_iface": "wlx782288d993c0",
            "wifi_temp": {"offset": 32, "scale": 2.5},
            # Optional UI features
            "connection_check_enabled": True,
            "connection_check_interval": 30000
        }

    def load_config(self):
        cfg_default = self._default_config()
        config_dir = os.path.dirname(self.CONFIG_FILE)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)

        if not os.path.exists(self.CONFIG_FILE):
            return cfg_default

        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as file:
                config = json.load(file)
            # Ensure all defaults exist
            for k, v in cfg_default.items():
                if k not in config:
                    config[k] = v
            return config
        except json.JSONDecodeError as e:
            logger.error("Error decoding config JSON: %s", e)
            return cfg_default
        except Exception as e:
            logger.error("Error reading config: %s", e)
            return cfg_default

    def save_config(self):
        config_dir = os.path.dirname(self.CONFIG_FILE)
        os.makedirs(config_dir, exist_ok=True)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as file:
            json.dump(self.ssh_config, file, indent=4)

    # -------------------------------------------------------------------------
    # Reachability & connection test
    # -------------------------------------------------------------------------
    def is_reachable(self, ip, port="22", timeout=None, max_attempts=None):
        if timeout is None:
            timeout = self.timeout
        if max_attempts is None:
            max_attempts = self.max_attempts

        logger.debug("Checking reachability for IP: %s:%s", ip, port)
        for attempt in range(max_attempts):
            try:
                socket.create_connection((ip, int(port)), timeout=timeout)
                logger.debug("IP %s:%s is reachable after attempt %d.", ip, port, attempt + 1)
                return True
            except Exception as e:
                logger.error("Attempt %d: Error reaching IP %s:%s: %s", attempt + 1, ip, port, e)
                if attempt < max_attempts - 1:
                    time.sleep(5)

        logger.error("Failed to reach IP %s:%s after %d attempts.", ip, port, max_attempts)
        return False

    def test_connection(self):
        logger.debug("Testing primary IP: %s:%s", self.current_ip, self.current_port)
        if self.current_ip and self.is_reachable(self.current_ip, self.current_port):
            logger.info("Primary IP is reachable: %s:%s", self.current_ip, self.current_port)
            return self.current_ip

        logger.warning("Primary IP %s:%s not reachable. Trying secondary.", self.current_ip, self.current_port)
        if self.secondary_ip and self.is_reachable(self.secondary_ip, self.secondary_port):
            logger.info("Secondary IP is reachable: %s:%s", self.secondary_ip, self.secondary_port)
            self.current_ip = self.secondary_ip
            self.current_port = self.secondary_port
            return self.secondary_ip

        logger.error(
            "Both primary (%s:%s) and secondary (%s:%s) IPs are not reachable.",
            self.current_ip, self.current_port, self.secondary_ip, self.secondary_port
        )
        return None

    # -------------------------------------------------------------------------
    # Command execution
    # -------------------------------------------------------------------------
    def _connect(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(self.current_ip, int(self.current_port), self.username, self.password, timeout=self.timeout)
        return ssh

    def execute_command(self, command, success_msg="Command executed successfully.",
                        error_msg="Failed to execute command.", max_attempts=None):
        """
        Execute a remote command and return True/False only (legacy behavior used by UI buttons).
        """
        if not self.current_ip or not self.password:
            logger.error("No IP or password configured for companion.")
            return False
        if max_attempts is None:
            max_attempts = self.max_attempts

        for attempt in range(max_attempts):
            ssh = None
            try:
                ssh = self._connect()
                if command.startswith("sudo "):
                    cmd = f"echo {self.password} | sudo -S {command[5:]}"
                else:
                    cmd = command

                stdin, stdout, stderr = ssh.exec_command(cmd)
                exit_status = stdout.channel.recv_exit_status()
                if exit_status == 0:
                    logger.info("%s", success_msg)
                    return True

                error = stderr.read().decode(errors="ignore")
                logger.error("%s\nError: %s", error_msg, error)
                return False

            except paramiko.AuthenticationException as e:
                logger.error("SSH Authentication failed for command %s (attempt %d): %s", command, attempt + 1, e)
            except Exception as e:
                logger.error("Error executing command %s (attempt %d): %s", command, attempt + 1, e)
            finally:
                try:
                    if ssh:
                        ssh.close()
                except Exception:
                    pass

            if attempt < max_attempts - 1:
                time.sleep(5)

        return False

    def execute_command_capture(self, command, max_attempts=None):
        """
        Run a command over SSH and return (ok: bool, stdout: str, stderr: str, exit_status: int).
        Use this when you need to parse the command output.
        """
        if not self.current_ip or not self.password:
            logger.error("No IP or password configured for companion.")
            return False, "", "no ip/password", -1
        if max_attempts is None:
            max_attempts = self.max_attempts

        for attempt in range(max_attempts):
            ssh = None
            try:
                ssh = self._connect()
                stdin, stdout, stderr = ssh.exec_command(command)
                exit_status = stdout.channel.recv_exit_status()
                out = stdout.read().decode(errors="ignore")
                err = stderr.read().decode(errors="ignore")
                return exit_status == 0, out, err, exit_status
            except paramiko.AuthenticationException as e:
                logger.error("SSH auth failed for '%s' (attempt %d): %s", command, attempt + 1, e)
            except Exception as e:
                logger.error("Error executing '%s' (attempt %d): %s", command, attempt + 1, e)
            finally:
                try:
                    if ssh:
                        ssh.close()
                except Exception:
                    pass

            if attempt < max_attempts - 1:
                time.sleep(5)

        return False, "", "max attempts exceeded", -1

    def execute_command_all(self, command, success_msg="Command executed successfully on all systems.",
                            error_msg="Failed to execute command on all systems."):
        logger.debug("Executing command on all systems: %s", command)
        primary = self.execute_command(command, success_msg, error_msg)
        secondary = True
        if self.secondary_ip:
            orig_ip = self.current_ip
            orig_port = self.current_port
            self.current_ip = self.secondary_ip
            self.current_port = self.secondary_port
            secondary = self.execute_command(command, success_msg, error_msg)
            self.current_ip = orig_ip
            self.current_port = orig_port
        return primary and secondary

    # -------------------------------------------------------------------------
    # Relay commands
    # -------------------------------------------------------------------------
    def execute_relay_command(self, command, success_msg="Relay command executed successfully.",
                             error_msg="Failed to execute relay command.", max_attempts=None):
        if not self.relay_ip or not self.relay_password:
            logger.error("No relay IP or password configured.")
            return False
        if max_attempts is None:
            max_attempts = self.max_attempts

        for attempt in range(max_attempts):
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                ssh.connect(self.relay_ip, int(self.relay_ssh_port),
                            self.relay_username, self.relay_password, timeout=self.timeout)
                if command.startswith("sudo "):
                    stdin, stdout, stderr = ssh.exec_command(f"echo {self.relay_password} | sudo -S {command[5:]}")
                else:
                    stdin, stdout, stderr = ssh.exec_command(command)

                exit_status = stdout.channel.recv_exit_status()
                if exit_status == 0:
                    logger.info("%s", success_msg)
                    return True

                error = stderr.read().decode(errors="ignore")
                logger.error("%s\nError: %s", error_msg, error)
                return False

            except paramiko.AuthenticationException as e:
                logger.error("SSH Authentication failed for relay command %s (attempt %d): %s", command, attempt + 1, e)
            except Exception as e:
                logger.error("Error executing relay command %s (attempt %d): %s", command, attempt + 1, e)
            finally:
                try:
                    ssh.close()
                except Exception:
                    pass

            if attempt < max_attempts - 1:
                time.sleep(5)

        return False

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------
    def sync_date_time(self):
        now = datetime.now()
        date_time_string = now.strftime("%Y-%m-%d %H:%M:%S")
        if sys.platform.startswith("win"):
            logger.warning("Time synchronization not supported on Windows.")
            return False
        sync_command = f"sudo date -s \"{date_time_string}\""
        return self.execute_command(sync_command, "Date and time synchronized with drone.",
                                    "Failed to synchronize date and time.")

    def transfer_file(self, remote_path, local_path):
        if not self.current_ip or not self.password:
            logger.error("No IP or password configured for file transfer.")
            return False, None

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(self.current_ip, int(self.current_port), self.username, self.password, timeout=self.timeout)
            sftp = ssh.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            logger.info("File transferred successfully from %s to %s", remote_path, local_path)
            return True, local_path
        except Exception as e:
            logger.error("Error transferring file: %s", e)
            return False, None
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    def restart_relay_ssh_tunnel(self):
        logger.info("Attempting to restart relay SSH tunnel service.")
        tunnel_restart_command = "sudo systemctl restart ssh-tunnel-to-companion.service"
        return self.execute_relay_command(
            tunnel_restart_command,
            "Relay SSH tunnel service restarted successfully.",
            "Failed to restart relay SSH tunnel service."
        )

    # -------------------------------------------------------------------------
    # Wi-Fi temperature (RTL88x2EU procfs authoritative)
    # -------------------------------------------------------------------------
    def get_wifi_module_temperature(self):
        """
        Robust Wi-Fi module temperature:
        - Detect iface from WFB config (WFB_NICS) first
        - Then detect rtl88x2eu iface from /proc/net/rtl88x2eu/
        - Prefer rtl88x2eu procfs thermal_state (authoritative)
        - Fall back to wfb-cli (if it prints temperature)
        - Last fallback: sysfs hwmon temp1_input

        Returns float °C or None.
        """
        import re

        clamp_min, clamp_max = -40.0, 130.0

        ssh = None
        try:
            ssh = self._connect()

            def _safe_read(cmd: str) -> str:
                stdin, stdout, stderr = ssh.exec_command(cmd)
                # avoid hang
                stdout.channel.settimeout(self.timeout)
                return stdout.read().decode(errors="ignore").strip()

            def _pick_iface() -> str:
                # 1) What WFB is configured to use (first token of WFB_NICS)
                cmd = r"""sh -lc '
if [ -r /etc/default/wifibroadcast ]; then
  v=$(grep -E "^[[:space:]]*WFB_NICS=" /etc/default/wifibroadcast | tail -n1 | cut -d= -f2-)
  v=${v#\"}; v=${v%\"}; v=${v#\'}; v=${v%\'}
  set -- $v
  echo "${1:-}"
fi
'"""
                iface = _safe_read(cmd)
                if iface:
                    return iface

                # 2) Auto-detect rtl88x2eu iface from procfs folder listing
                cmd = r"""sh -lc 'ls -1 /proc/net/rtl88x2eu 2>/dev/null | grep -E "^wl" | head -n1 || true'"""
                iface = _safe_read(cmd)
                if iface:
                    return iface

                # 3) Fall back to configured iface
                return (self.ssh_config.get("wifi_iface") or "").strip()

            iface = _pick_iface()

            # A) Best: RTL88x2EU procfs thermal_state
            if iface:
                proc_path = f"/proc/net/rtl88x2eu/{iface}/thermal_state"
                proc_cmd = f"sh -lc 'timeout 2s cat {proc_path} 2>/dev/null || true'"
                proc_out = _safe_read(proc_cmd)

                temps = []
                for mm in re.finditer(r"temperature:\s*(-?\d+(?:\.\d+)?)", proc_out):
                    try:
                        t = float(mm.group(1))
                        if clamp_min <= t <= clamp_max:
                            temps.append(t)
                    except Exception:
                        pass

                if temps:
                    # conservative: hottest RF path
                    return float(f"{max(temps):.1f}")

            # B) Next: wfb-cli (only if it prints temp)
            wfb_cmd = r"""sh -lc '
TO=2
(out=$((timeout ${TO}s /usr/local/sbin/wfb-cli drone || timeout ${TO}s /usr/local/bin/wfb-cli drone || timeout ${TO}s wfb-cli drone) 2>/dev/null); \
echo "$out" | grep -iE "temp|temperature" | head -n 20) || true
'"""
            out = _safe_read(wfb_cmd)
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*°?\s*[Cc]\b", out)
            if m:
                val = float(m.group(1))
                if clamp_min <= val <= clamp_max:
                    return float(f"{val:.1f}")

            # C) Last fallback: sysfs hwmon
            sysfs_cmd = r"""sh -lc '
TO=2
for p in /sys/class/ieee80211/*/device/hwmon/*/temp1_input /sys/class/hwmon/hwmon*/temp1_input; do
  [ -r "$p" ] || continue
  v=$(timeout ${TO}s cat "$p" 2>/dev/null) || continue
  echo "$v"
  break
done
'"""
            val_s = _safe_read(sysfs_cmd)
            if val_s:
                try:
                    v = float(val_s)
                    if v > 200:  # millidegC -> degC
                        v /= 1000.0
                    if clamp_min <= v <= clamp_max:
                        return float(f"{v:.1f}")
                except Exception:
                    pass

            return None

        except Exception as e:
            logger.error("get_wifi_module_temperature failed: %s", e)
            return None
        finally:
            try:
                if ssh:
                    ssh.close()
            except Exception:
                pass
