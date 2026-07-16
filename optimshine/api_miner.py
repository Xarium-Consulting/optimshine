#!/usr/bin/env python
#
# Copyright 2025 Norbert Kamiński <norbert.kaminski@xarium.world>
#
# SPDX-License-Identifier: LGPL-3.0-or-later
#

import os
import socket
import json

from logging import RootLogger
from optimshine.api_common import ApiCommon

DEFAULT_PORT = 4028
SOCKET_TIMEOUT = 5          # seconds, total connect + exchange budget
MAX_RESPONSE_BYTES = 65536  # response size cap
RECV_CHUNK = 4096           # per-recv read size

# Operating mode -> CGMiner workmode integer (three distinct values)
WORKMODE_MAP = {
    "Eco": 0,
    "Standard": 1,
    "Super": 2,
}

# ascset payloads for enabling / disabling hashing
ASCSET_ON = "0,softon,1"
ASCSET_OFF = "0,softoff,1"


class ApiMiner(ApiCommon):
    """
    ApiMiner controls a Canaan Avalon Q crypto miner through its
    CGMiner-compatible JSON API over a raw TCP socket.
    """
    def __init__(self, log: RootLogger, dry_run: bool = False):
        """
        Initialize the ApiMiner client.

        Args:
            log (RootLogger): The logger used for all logging.
            dry_run (bool, optional): When True, state-changing commands are
                                      logged instead of transmitted to the
                                      Avalon Q. Fixed for the lifetime of the
                                      instance. Defaults to False.
        """
        self.log = log
        self.dry_run = bool(dry_run)

    def _load_config(self):
        """
        Read the miner connection settings from the environment.

        Returns:
            tuple or None: An (ip, port) tuple when MINER_IP is configured,
                           otherwise None.
        """
        ip = os.environ.get("MINER_IP")
        if not ip or not ip.strip():
            self.log.error(
                "MINER_IP is not configured! Set MINER_IP in the environment."
            )
            return None
        ip = ip.strip()

        port_value = os.environ.get("MINER_PORT")
        if not port_value or not port_value.strip():
            return (ip, DEFAULT_PORT)

        port_value = port_value.strip()
        try:
            port = int(port_value)
        except ValueError:
            self.log.error(
                f"Invalid MINER_PORT '{port_value}'! Falling back to "
                f"{DEFAULT_PORT}."
            )
            return (ip, DEFAULT_PORT)

        if 1 <= port <= 65535:
            return (ip, port)

        self.log.error(
            f"Invalid MINER_PORT '{port_value}'! Falling back to "
            f"{DEFAULT_PORT}."
        )
        return (ip, DEFAULT_PORT)

    def _send_command(self, command):
        """
        Send a JSON command to the miner over a TCP socket and return the
        parsed response.

        Args:
            command (dict): The command dictionary to serialize and transmit.

        Returns:
            dict or None: The parsed JSON response on success, None on any
                          failure.
        """
        config = self._load_config()
        if config is None:
            return None
        ip, port = config

        payload = json.dumps(command) + "\n"

        sock = None
        raw = b""
        try:
            sock = socket.create_connection((ip, port), timeout=SOCKET_TIMEOUT)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.sendall(payload.encode("utf-8"))

            while True:
                chunk = sock.recv(RECV_CHUNK)
                if not chunk:
                    break
                raw += chunk
                if len(raw) >= MAX_RESPONSE_BYTES:
                    self.log.error(
                        "Avalon Q response exceeded "
                        f"{MAX_RESPONSE_BYTES} bytes! Aborting read."
                    )
                    return None
        except socket.timeout:
            self.log.error(
                f"Timed out communicating with Avalon Q at {ip}:{port} "
                f"after {SOCKET_TIMEOUT}s!"
            )
            return None
        except OSError as error:
            self.log.error(
                f"Failed to connect to Avalon Q at {ip}:{port}! {error}"
            )
            return None
        finally:
            if sock is not None:
                sock.close()

        if not raw:
            self.log.error("Received an empty response from the Avalon Q!")
            return None

        # cgminer's API terminates responses with a trailing NUL byte and may
        # append stray whitespace; strip both so json.loads does not choke on
        # the "Extra data" that follows the closing brace.
        response_text = raw.decode("utf-8", errors="replace")
        response_text = response_text.rstrip("\x00").strip()
        try:
            return json.loads(response_text)
        except (json.JSONDecodeError, ValueError):
            self.log.error(
                f"Failed to parse Avalon Q response as JSON! {response_text}"
            )
            return None

    def _status_ok(self, response):
        """
        Interpret a CGMiner response's status.

        Args:
            response (dict): The parsed CGMiner response envelope.

        Returns:
            bool: True when the response reports a success status, False
                  otherwise.
        """
        if not isinstance(response, dict):
            return False

        status = response.get("STATUS")

        # Preferred shape: STATUS is a non-empty list whose first element is a
        # dict carrying an inner "STATUS" code.
        code = None
        if isinstance(status, list):
            if not status:
                return False
            element = status[0]
            if not isinstance(element, dict):
                return False
            code = element.get("STATUS")
        elif isinstance(status, str):
            # Fallback shape: STATUS is a plain string code.
            code = status
        else:
            return False

        if code in ("S", "I"):
            return True
        if code in ("E", "W"):
            return False

        # Missing inner code or an unknown status value.
        return False

    def summary(self):
        """
        Retrieve the miner summary statistics and store them on the instance.

        Sends the CGMiner summary command through the transport helper and,
        on success, stores the summary payload on ``self.summary_data`` so it
        can be read afterwards without re-issuing the command.

        Returns:
            bool: True if the summary was retrieved and stored, False
                  otherwise.
        """
        response = self._send_command({"command": "summary"})
        if response is None:
            self.log.error(
                "Failed to retrieve the Avalon Q summary! No response was "
                "returned by the miner."
            )
            return False

        # The response must report a success status in the STATUS envelope
        # (cgminer reports command status there, not inside SUMMARY).
        if not self._status_ok(response):
            self.log.error(
                "Avalon Q summary response did not report a success "
                f"status! {response}"
            )
            return False

        # The statistics live in the SUMMARY section, whose first element
        # carries the hash rate. Temperature and status are best-effort: real
        # cgminer firmware (e.g. 4.11.1) reports the hash rate here but not a
        # Temperature field, so only the hash rate is required.
        summary = None
        if isinstance(response, dict):
            section = response.get("SUMMARY")
            if isinstance(section, list) and section:
                element = section[0]
                if isinstance(element, dict):
                    summary = element

        if summary is None or "MHS av" not in summary:
            self.log.error(
                "Avalon Q summary response is missing the hash rate "
                f"statistics! {response}"
            )
            return False

        self.summary_data = summary
        return True

    def on(self):
        """
        Enable hashing on the miner.

        Sends the CGMiner ascset command that enables hashing through the
        transport helper. When dry-run mode is enabled, the exact payload is
        logged at INFO level and no socket is opened.

        Returns:
            bool: True on success, False otherwise.
        """
        command = {"command": "ascset", "parameter": ASCSET_ON}

        if self.dry_run:
            self.log.info(
                f"[DRY RUN] Would send power-on command to Avalon Q: {command}"
            )
            return True

        response = self._send_command(command)
        if response is None or not self._status_ok(response):
            if response is None:
                self.log.error(
                    "Failed to power on the Avalon Q! No response was "
                    "returned by the miner."
                )
            else:
                self.log.error(
                    f"Failed to power on the Avalon Q! {response}"
                )
            return False

        return True

    def off(self):
        """
        Disable hashing on the miner.

        Sends the CGMiner ascset command that disables hashing through the
        transport helper. When dry-run mode is enabled, the exact payload is
        logged at INFO level and no socket is opened.

        Returns:
            bool: True on success, False otherwise.
        """
        command = {"command": "ascset", "parameter": ASCSET_OFF}

        if self.dry_run:
            self.log.info(
                f"[DRY RUN] Would send power-off command to Avalon Q: "
                f"{command}"
            )
            return True

        response = self._send_command(command)
        if response is None or not self._status_ok(response):
            if response is None:
                self.log.error(
                    "Failed to power off the Avalon Q! No response was "
                    "returned by the miner."
                )
            else:
                self.log.error(
                    f"Failed to power off the Avalon Q! {response}"
                )
            return False

        return True

    def set_mode(self, mode):
        """
        Set the miner operating mode to Eco, Standard, or Super.

        Sends the CGMiner ascset command carrying the workmode value mapped
        from the requested operating mode through the transport helper. When
        dry-run mode is enabled, the exact payload is logged at INFO level and
        no socket is opened.

        Args:
            mode (str): The requested operating mode.

        Returns:
            bool: True on success, False otherwise.
        """
        if not isinstance(mode, str) or mode not in WORKMODE_MAP:
            self.log.error(
                f"Invalid Avalon Q operating mode '{mode}'! Expected one of "
                f"{sorted(WORKMODE_MAP)}."
            )
            return False

        command = {
            "command": "ascset",
            "parameter": f"0,workmode,set,{WORKMODE_MAP[mode]}",
        }

        if self.dry_run:
            self.log.info(
                f"[DRY RUN] Would send set-mode command to Avalon Q: {command}"
            )
            return True

        response = self._send_command(command)
        if response is None or not self._status_ok(response):
            if response is None:
                self.log.error(
                    f"Failed to set the Avalon Q operating mode to '{mode}'! "
                    "No response was returned by the miner."
                )
            else:
                self.log.error(
                    f"Failed to set the Avalon Q operating mode to '{mode}'! "
                    f"{response}"
                )
            return False

        return True

    def check(self):
        """
        Perform a connectivity and health check against the miner.

        Sends the CGMiner summary command through the transport helper. This
        is a read command, so it transmits even when dry-run mode is enabled.
        A successful status response confirms the Avalon Q is reachable and
        healthy.

        Returns:
            bool: True if the miner is reachable and healthy, False otherwise.
        """
        response = self._send_command({"command": "summary"})
        if response is None:
            self.log.error(
                "Avalon Q unreachable! No response was returned by the miner."
            )
            return False

        if not self._status_ok(response):
            self.log.error(
                f"Avalon Q health check failed! {response}"
            )
            return False

        return True
