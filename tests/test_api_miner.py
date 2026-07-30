#!/usr/bin/env python
#
# Copyright 2025 Norbert Kamiński <norbert.kaminski@xarium.world>
#
# SPDX-License-Identifier: LGPL-3.0-or-later
#

import datetime
import io
import json
import logging
import os
import re
import socket
import time
import unittest

import optimshine.api_miner as api
import optimshine.optim_config as config

from unittest.mock import patch  # noqa: F401  (used by later test tasks)

from hypothesis import given, settings, strategies as st  # noqa: F401


def _is_error_fallback_port(raw):
    """
    Return True only for MINER_PORT values that must trigger the invalid-port
    error fallback in ``_load_config``.

    Empty/whitespace-only values are excluded: they yield the default port
    without logging an error. Numeric strings that parse to an integer within
    the valid 1..65535 range are also excluded.
    """
    stripped = raw.strip()
    if not stripped:
        return False
    try:
        port = int(stripped)
    except ValueError:
        return True
    return not (1 <= port <= 65535)


class TestApiMiner(unittest.TestCase):
    def setUp(self):
        cls_optim_config = config.OptimConfig()
        cls_optim_config.logger_setup()
        self.log = cls_optim_config.log
        cls_optim_config.envs_setup("tests/.testenv")

    def tearDown(self):
        self.log.handlers.clear()

    def _capture_log(self):
        """
        Attach a StringIO-backed StreamHandler to the test logger for capturing
        log output within a test.

        Returns:
            io.StringIO: The stream whose ``getvalue()`` yields captured log
                         output.
        """
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        return stdio

    def test_api_miner_importable(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(cls_api_miner.dry_run)

    # Feature: api-miner, Property 1: Valid port passthrough
    # For any integer p in the inclusive range 1..65535, when MINER_PORT is
    # set to str(p), _load_config (with a valid MINER_IP) returns p as the
    # port.
    # Validates: Requirements 1.2
    @settings(max_examples=200)
    @given(port=st.integers(min_value=1, max_value=65535))
    def test_valid_port_passthrough(self, port):
        cls_api_miner = api.ApiMiner(self.log)
        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": str(port),
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            result = cls_api_miner._load_config()

        self.assertIsNotNone(result)
        self.assertEqual(result, ("192.168.1.10", port, "cg-secret-key"))

    # Feature: api-miner, Property 2: Invalid port falls back to default
    # For any non-numeric string, value <= 0, or value > 65535 supplied as
    # MINER_PORT (with a valid MINER_IP), _load_config returns 4028 and logs
    # an error identifying the invalid port.
    # Validates: Requirements 1.4
    @settings(max_examples=200)
    @given(
        raw_port=st.one_of(
            # Non-numeric strings. Exclude the NUL character because it cannot
            # be stored in os.environ on any platform.
            st.text(
                alphabet=st.characters(
                    blacklist_characters="\x00",
                    blacklist_categories=("Cs",),
                )
            ),
            st.integers(max_value=0).map(str),
            st.integers(min_value=65536).map(str),
        ).filter(_is_error_fallback_port)
    )
    def test_invalid_port_falls_back_to_default(self, raw_port):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": raw_port,
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            result = cls_api_miner._load_config()

        self.assertEqual(result, ("192.168.1.10", 4028, "cg-secret-key"))

        log_output = stdio.getvalue()
        self.assertIn(raw_port.strip(), log_output)
        self.assertIn("MINER_PORT", log_output)

    # MINER_IP present with MINER_PORT unset -> default port used.
    # Validates: Requirements 1.1, 1.3
    def test_miner_ip_set_port_unset_uses_default(self):
        cls_api_miner = api.ApiMiner(self.log)
        env = {
            "MINER_IP": "192.168.1.10",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            os.environ.pop("MINER_PORT", None)
            result = cls_api_miner._load_config()

        self.assertEqual(result, ("192.168.1.10", 4028, "cg-secret-key"))

    # MINER_IP unset/empty -> returns None and logs a missing-config error.
    # Validates: Requirements 1.5
    def test_miner_ip_missing_returns_none_and_logs(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        env = {"MINER_IP": "", "COINGECKO_API_KEY": "cg-secret-key"}
        with patch.dict("os.environ", env, clear=False):
            result = cls_api_miner._load_config()

        self.assertIsNone(result)

        log_output = stdio.getvalue()
        self.assertIn("MINER_IP", log_output)

    # COINGECKO_API_KEY present -> returned as the third tuple element.
    # Validates: Requirements 1.1
    def test_coingecko_api_key_present_returned_in_config(self):
        cls_api_miner = api.ApiMiner(self.log)
        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            result = cls_api_miner._load_config()

        self.assertEqual(
            result, ("192.168.1.10", 4028, "cg-secret-key")
        )

    # COINGECKO_API_KEY present with MINER_PORT unset -> default port used and
    # the key is still returned as the third tuple element.
    # Validates: Requirements 1.1, 1.3
    def test_coingecko_api_key_present_with_default_port(self):
        cls_api_miner = api.ApiMiner(self.log)
        env = {
            "MINER_IP": "192.168.1.10",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            os.environ.pop("MINER_PORT", None)
            result = cls_api_miner._load_config()

        self.assertEqual(
            result, ("192.168.1.10", 4028, "cg-secret-key")
        )

    # COINGECKO_API_KEY unset -> returns None and logs a missing-config error.
    # Validates: Requirements 1.5
    def test_coingecko_api_key_unset_returns_none_and_logs(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            os.environ.pop("COINGECKO_API_KEY", None)
            result = cls_api_miner._load_config()

        self.assertIsNone(result)
        self.assertIn("COINGECKO_API_KEY", stdio.getvalue())

    # COINGECKO_API_KEY empty -> returns None and logs a missing-config error.
    # Validates: Requirements 1.5
    def test_coingecko_api_key_empty_returns_none_and_logs(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=False):
            result = cls_api_miner._load_config()

        self.assertIsNone(result)
        self.assertIn("COINGECKO_API_KEY", stdio.getvalue())

    # COINGECKO_API_KEY whitespace-only -> treated as missing: returns None and
    # logs a missing-config error.
    # Validates: Requirements 1.5
    def test_coingecko_api_key_whitespace_returns_none_and_logs(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "   ",
        }
        with patch.dict("os.environ", env, clear=False):
            result = cls_api_miner._load_config()

        self.assertIsNone(result)
        self.assertIn("COINGECKO_API_KEY", stdio.getvalue())

    # COINGECKO_API_KEY is checked before MINER_IP: when the key is missing the
    # error identifies the key even if MINER_IP is also unset.
    # Validates: Requirements 1.5
    def test_coingecko_api_key_missing_takes_precedence_over_miner_ip(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        env = {"MINER_IP": "", "COINGECKO_API_KEY": ""}
        with patch.dict("os.environ", env, clear=False):
            result = cls_api_miner._load_config()

        self.assertIsNone(result)
        log_output = stdio.getvalue()
        self.assertIn("COINGECKO_API_KEY", log_output)
        self.assertNotIn("MINER_IP is not configured", log_output)

    # Feature: api-miner, Property 3: Commands serialize to a single line
    # For any JSON-serializable command dict, the serialized payload produced
    # by the transport (json.dumps(command) + "\n", sent via sock.sendall)
    # contains no embedded newline except an optional single trailing
    # newline terminator.
    # Validates: Requirements 2.1
    @settings(max_examples=100)
    @given(
        command=st.dictionaries(
            keys=st.text(
                st.characters(
                    blacklist_characters="\x00",
                    blacklist_categories=("Cs",),
                )
            ),
            values=st.recursive(
                st.one_of(
                    st.none(),
                    st.booleans(),
                    st.integers(),
                    st.floats(allow_nan=False, allow_infinity=False),
                    st.text(
                        st.characters(
                            blacklist_characters="\x00",
                            blacklist_categories=("Cs",),
                        )
                    ),
                ),
                lambda children: st.one_of(
                    st.lists(children),
                    st.dictionaries(
                        keys=st.text(
                            st.characters(
                                blacklist_characters="\x00",
                                blacklist_categories=("Cs",),
                            )
                        ),
                        values=children,
                    ),
                ),
                max_leaves=10,
            ),
        )
    )
    def test_command_serializes_to_single_line(self, command):
        cls_api_miner = api.ApiMiner(self.log)

        sent_payloads = []

        class _FakeSocket:
            def settimeout(self, _timeout):
                pass

            def sendall(self, data):
                sent_payloads.append(data)

            def recv(self, _size):
                return b""

            def close(self):
                pass

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                return_value=_FakeSocket(),
            ):
                cls_api_miner._send_command(command)

        # The transport must have transmitted exactly one payload.
        self.assertEqual(len(sent_payloads), 1)
        payload = sent_payloads[0].decode("utf-8")

        # Strip a single optional trailing newline terminator, then assert no
        # embedded newline remains in the serialized command.
        if payload.endswith("\n"):
            body = payload[:-1]
        else:
            body = payload
        self.assertNotIn("\n", body)

    # Feature: api-miner, Property 4: Transport response round-trip
    # For any JSON-serializable object, when a mocked socket returns that
    # object's json.dumps encoding then closes the connection (EOF),
    # _send_command returns an object equal to the original.
    # Validates: Requirements 2.2
    @settings(max_examples=100)
    @given(
        obj=st.recursive(
            st.one_of(
                st.none(),
                st.booleans(),
                st.integers(),
                st.floats(allow_nan=False, allow_infinity=False),
                st.text(
                    st.characters(
                        blacklist_characters="\x00",
                        blacklist_categories=("Cs",),
                    )
                ),
            ),
            lambda children: st.one_of(
                st.lists(children),
                st.dictionaries(
                    keys=st.text(
                        st.characters(
                            blacklist_characters="\x00",
                            blacklist_categories=("Cs",),
                        )
                    ),
                    values=children,
                ),
            ),
            max_leaves=10,
        )
    )
    def test_transport_response_round_trip(self, obj):
        cls_api_miner = api.ApiMiner(self.log)

        # Encode the generated object exactly as the miner would, then split
        # it into chunks so the accumulation loop in _send_command is
        # exercised across multiple recv() calls before EOF.
        encoded = json.dumps(obj).encode("utf-8")
        chunk_size = 3
        chunks = [
            encoded[i:i + chunk_size]
            for i in range(0, len(encoded), chunk_size)
        ]
        # Terminate with EOF (b"") to simulate the miner closing the socket.
        chunks.append(b"")

        class _FakeSocket:
            def __init__(self):
                self._chunks = list(chunks)

            def settimeout(self, _timeout):
                pass

            def sendall(self, _data):
                pass

            def recv(self, _size):
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

            def close(self):
                pass

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                return_value=_FakeSocket(),
            ):
                result = cls_api_miner._send_command({"command": "x"})

        self.assertEqual(result, obj)

    # Feature: api-miner, Property 5: Socket is always closed
    # For any transport outcome (success, empty response, parse failure, size
    # overflow, timeout, or OSError) where socket.create_connection returns a
    # socket object, _send_command calls sock.close() exactly once regardless
    # of how the exchange terminates.
    # Validates: Requirements 2.6
    @settings(max_examples=100)
    @given(
        outcome=st.sampled_from(
            [
                "success",
                "empty",
                "parse_failure",
                "size_overflow",
                "timeout_sendall",
                "timeout_recv",
                "oserror_sendall",
                "oserror_recv",
            ]
        )
    )
    def test_socket_always_closed(self, outcome):
        cls_api_miner = api.ApiMiner(self.log)

        class _FakeSocket:
            def __init__(self, outcome):
                self._outcome = outcome
                self.close_count = 0
                if outcome == "success":
                    self._chunks = [b'{"ok": 1}', b""]
                elif outcome == "empty":
                    self._chunks = [b""]
                elif outcome == "parse_failure":
                    self._chunks = [b"not json at all", b""]
                elif outcome == "size_overflow":
                    # A single chunk at/over the cap forces the size-limit
                    # branch on the first recv.
                    self._chunks = [b"x" * api.MAX_RESPONSE_BYTES]
                else:
                    self._chunks = [b""]

            def settimeout(self, _timeout):
                pass

            def sendall(self, _data):
                if self._outcome == "timeout_sendall":
                    raise socket.timeout("simulated send timeout")
                if self._outcome == "oserror_sendall":
                    raise OSError("simulated send error")

            def recv(self, _size):
                if self._outcome == "timeout_recv":
                    raise socket.timeout("simulated recv timeout")
                if self._outcome == "oserror_recv":
                    raise OSError("simulated recv error")
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

            def close(self):
                self.close_count += 1

        fake_sock = _FakeSocket(outcome)

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                return_value=fake_sock,
            ):
                cls_api_miner._send_command({"command": "summary"})

        # Regardless of the transport outcome, the opened socket must be
        # closed exactly once.
        self.assertEqual(fake_sock.close_count, 1)

    # ------------------------------------------------------------------ #
    # Task 3.5: unit tests for _send_command transport paths (mocked      #
    # socket). Example / edge-case coverage complementing the property    #
    # tests above.                                                        #
    # ------------------------------------------------------------------ #

    class _ScriptedSocket:
        """
        A minimal fake socket for driving _send_command through a scripted
        sequence of recv() chunks. Records every payload passed to sendall and
        the number of close() calls so tests can assert on transport behavior.
        """

        def __init__(self, recv_chunks):
            self._chunks = list(recv_chunks)
            self.sent_payloads = []
            self.settimeout_args = []
            self.close_count = 0

        def settimeout(self, timeout):
            self.settimeout_args.append(timeout)

        def sendall(self, data):
            self.sent_payloads.append(data)

        def recv(self, _size):
            if self._chunks:
                return self._chunks.pop(0)
            return b""

        def close(self):
            self.close_count += 1

    # Full send/recv/close sequence: valid JSON is returned as a parsed dict,
    # and no real socket is ever created (socket.create_connection is patched,
    # so the real socket.socket constructor is never invoked -> no network
    # I/O).
    # Validates: Requirements 2.1, 9.1
    def test_send_command_success_returns_parsed_dict_no_real_socket(self):
        cls_api_miner = api.ApiMiner(self.log)
        fake_sock = self._ScriptedSocket([b'{"result": "ok", "n": 42}', b""])

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                return_value=fake_sock,
            ) as mock_conn:
                # Guard against any real socket construction: if _send_command
                # bypassed create_connection and built a raw socket, this mock
                # would record the call and the assertion below would fail.
                with patch(
                    "optimshine.api_miner.socket.socket"
                ) as mock_raw_socket:
                    result = cls_api_miner._send_command(
                        {"command": "summary"}
                    )

        # The parsed JSON object is returned unchanged.
        self.assertEqual(result, {"result": "ok", "n": 42})

        # The connection was opened via create_connection exactly once, with
        # the configured host/port and timeout.
        mock_conn.assert_called_once_with(
            ("192.168.1.10", 4028), timeout=api.SOCKET_TIMEOUT
        )

        # No real socket object was ever constructed: all I/O went through the
        # patched fake, so no bytes touched a real network socket.
        mock_raw_socket.assert_not_called()

        # The command was transmitted exactly once and the socket was closed.
        self.assertEqual(len(fake_sock.sent_payloads), 1)
        self.assertEqual(fake_sock.close_count, 1)

    # Missing configuration: _load_config returns None, so _send_command bails
    # out before opening a socket.
    # Validates: Requirements 2.3
    def test_send_command_missing_config_returns_none_without_socket(self):
        cls_api_miner = api.ApiMiner(self.log)

        env = {"MINER_IP": "", "COINGECKO_API_KEY": ""}
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection"
            ) as mock_connect:
                result = cls_api_miner._send_command({"command": "summary"})

        self.assertIsNone(result)
        mock_connect.assert_not_called()

    # Connection failure: create_connection raises OSError -> None.
    # Validates: Requirements 2.3
    def test_send_command_connection_failure_returns_none(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                side_effect=OSError("connection refused"),
            ):
                result = cls_api_miner._send_command({"command": "summary"})

        self.assertIsNone(result)
        self.assertIn("192.168.1.10", stdio.getvalue())

    # Timeout on connect -> None; the 5-second timeout is configured on
    # create_connection.
    # Validates: Requirements 2.7
    def test_send_command_connect_timeout_returns_none(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        # The configured timeout budget must be 5 seconds.
        self.assertEqual(api.SOCKET_TIMEOUT, 5)

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                side_effect=socket.timeout("timed out"),
            ) as mock_conn:
                result = cls_api_miner._send_command({"command": "summary"})

        self.assertIsNone(result)
        # create_connection was invoked with timeout=SOCKET_TIMEOUT (== 5).
        mock_conn.assert_called_once_with(
            ("192.168.1.10", 4028), timeout=api.SOCKET_TIMEOUT
        )
        self.assertIn("Timed out", stdio.getvalue())

    # Timeout during recv -> None; settimeout(SOCKET_TIMEOUT) is invoked on the
    # socket so the exchange itself is bounded to 5 seconds.
    # Validates: Requirements 2.7
    def test_send_command_recv_timeout_returns_none_and_sets_timeout(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        class _TimeoutOnRecvSocket(self._ScriptedSocket):
            def recv(self, _size):
                raise socket.timeout("recv timed out")

        fake_sock = _TimeoutOnRecvSocket([])

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                return_value=fake_sock,
            ):
                result = cls_api_miner._send_command({"command": "summary"})

        self.assertIsNone(result)
        # settimeout was configured with the 5-second budget.
        self.assertIn(api.SOCKET_TIMEOUT, fake_sock.settimeout_args)
        # The socket is still closed on the timeout path.
        self.assertEqual(fake_sock.close_count, 1)
        self.assertIn("Timed out", stdio.getvalue())

    # Empty response: recv returns b"" immediately -> None.
    # Validates: Requirements 2.5
    def test_send_command_empty_response_returns_none(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        fake_sock = self._ScriptedSocket([b""])

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                return_value=fake_sock,
            ):
                result = cls_api_miner._send_command({"command": "summary"})

        self.assertIsNone(result)
        self.assertEqual(fake_sock.close_count, 1)
        self.assertIn("empty response", stdio.getvalue().lower())

    # Size overflow: recv returns >= MAX_RESPONSE_BYTES bytes -> None.
    # Validates: Requirements 2.8
    def test_send_command_size_overflow_returns_none(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        # A single chunk at the cap trips the size-limit branch on first recv.
        fake_sock = self._ScriptedSocket([b"x" * api.MAX_RESPONSE_BYTES])

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                return_value=fake_sock,
            ):
                result = cls_api_miner._send_command({"command": "summary"})

        self.assertIsNone(result)
        self.assertEqual(fake_sock.close_count, 1)
        self.assertIn(str(api.MAX_RESPONSE_BYTES), stdio.getvalue())

    # Non-JSON bytes then EOF -> None, and the raw text is logged.
    # Validates: Requirements 2.4
    def test_send_command_non_json_returns_none_and_logs_raw(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        raw_text = "this is not json <garbage>"
        fake_sock = self._ScriptedSocket([raw_text.encode("utf-8"), b""])

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch(
                "optimshine.api_miner.socket.create_connection",
                return_value=fake_sock,
            ):
                result = cls_api_miner._send_command({"command": "summary"})

        self.assertIsNone(result)
        self.assertEqual(fake_sock.close_count, 1)
        # The raw, unparseable response text is included in the error log.
        self.assertIn(raw_text, stdio.getvalue())

    # ------------------------------------------------------------------ #
    # Task 4.2: property test for _status_ok status interpretation.       #
    # ------------------------------------------------------------------ #

    # Feature: api-miner, Property 8: Status interpretation
    # For any CGMiner response envelope, _status_ok returns True on success
    # status ("S", "I") and False on error/warning status ("E", "W"),
    # regardless of the surrounding envelope fields or the response shape
    # (list-of-dict inner STATUS vs. top-level STATUS string fallback).
    # Validates: Requirements 4.3, 4.4, 5.3, 5.4, 6.5, 6.6, 7.2, 7.4
    @settings(max_examples=200)
    @given(
        code=st.sampled_from(["S", "I", "E", "W"]),
        shape=st.sampled_from(["list", "string"]),
        # Arbitrary surrounding envelope fields to strengthen the property:
        # extra top-level keys and extra keys inside the STATUS element.
        msg=st.text(
            st.characters(
                blacklist_characters="\x00",
                blacklist_categories=("Cs",),
            )
        ),
        description=st.text(
            st.characters(
                blacklist_characters="\x00",
                blacklist_categories=("Cs",),
            )
        ),
        extra_top=st.dictionaries(
            keys=st.text(
                st.characters(
                    blacklist_characters="\x00",
                    blacklist_categories=("Cs",),
                )
            ).filter(lambda k: k != "STATUS"),
            values=st.integers(),
            max_size=4,
        ),
    )
    def test_status_interpretation(
        self, code, shape, msg, description, extra_top
    ):
        cls_api_miner = api.ApiMiner(self.log)

        if shape == "list":
            element = {
                "STATUS": code,
                "Msg": msg,
                "Description": description,
            }
            response = {"STATUS": [element]}
        else:
            # Top-level string fallback shape.
            response = {"STATUS": code, "Msg": msg}

        # Vary the surrounding envelope with arbitrary extra top-level keys.
        response.update(extra_top)

        expected = code in ("S", "I")
        self.assertEqual(cls_api_miner._status_ok(response), expected)

    # ------------------------------------------------------------------ #
    # Task 4.3: unit tests for _status_ok edge cases. Example / edge-case #
    # coverage complementing the Property 8 test above.                   #
    # ------------------------------------------------------------------ #

    # Missing STATUS key entirely -> False.
    # Validates: Requirements 7.2, 7.4
    def test_status_ok_missing_status_key_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(cls_api_miner._status_ok({}))
        self.assertFalse(cls_api_miner._status_ok({"other": "value"}))

    # STATUS is an empty list -> False.
    # Validates: Requirements 7.2, 7.4
    def test_status_ok_empty_status_list_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(cls_api_miner._status_ok({"STATUS": []}))

    # STATUS list whose first element is not a dict -> False.
    # Validates: Requirements 7.2, 7.4
    def test_status_ok_non_dict_element_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(cls_api_miner._status_ok({"STATUS": ["not-a-dict"]}))
        self.assertFalse(cls_api_miner._status_ok({"STATUS": [123]}))
        self.assertFalse(cls_api_miner._status_ok({"STATUS": [None]}))

    # First element dict is missing the inner "STATUS" key -> False.
    # Validates: Requirements 7.2, 7.4
    def test_status_ok_missing_inner_status_key_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(
            cls_api_miner._status_ok({"STATUS": [{"Msg": "hello"}]})
        )

    # Unknown status code, both list and string-fallback shapes -> False.
    # Validates: Requirements 7.2, 7.4
    def test_status_ok_unknown_status_code_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(
            cls_api_miner._status_ok({"STATUS": [{"STATUS": "X"}]})
        )
        self.assertFalse(cls_api_miner._status_ok({"STATUS": "X"}))

    # STATUS is neither a list nor a string (e.g. an int or dict) -> False.
    # Validates: Requirements 7.2, 7.4
    def test_status_ok_non_list_non_string_status_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(cls_api_miner._status_ok({"STATUS": 123}))
        self.assertFalse(cls_api_miner._status_ok({"STATUS": {"STATUS": "S"}}))
        self.assertFalse(cls_api_miner._status_ok({"STATUS": None}))

    # Response is not a dict at all -> False.
    # Validates: Requirements 7.2, 7.4
    def test_status_ok_response_not_a_dict_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(cls_api_miner._status_ok(None))
        self.assertFalse(cls_api_miner._status_ok("not-a-dict"))
        self.assertFalse(cls_api_miner._status_ok([{"STATUS": "S"}]))
        self.assertFalse(cls_api_miner._status_ok(42))

    # ------------------------------------------------------------------ #
    # Task 6.2: unit tests for summary success and failure.               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _summary_response():
        """
        A well-formed CGMiner summary response containing the hash rate,
        temperature, and status statistics.
        """
        return {
            "STATUS": [{"STATUS": "S", "Msg": "Summary"}],
            "SUMMARY": [
                {"MHS av": 12345.6, "Temperature": 63.0, "Status": "hashing"}
            ],
            "id": 1,
        }

    # summary sends the summary command through the transport helper.
    # Validates: Requirements 3.1
    def test_summary_sends_summary_command(self):
        cls_api_miner = api.ApiMiner(self.log)

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._summary_response(),
        ) as mock_send:
            cls_api_miner.summary()

        mock_send.assert_called_once_with({"command": "summary"})

    # Success path: statistics present -> data stored and True returned.
    # Validates: Requirements 3.2
    def test_summary_success_stores_data_and_returns_true(self):
        cls_api_miner = api.ApiMiner(self.log)
        response = self._summary_response()

        with patch.object(
            cls_api_miner, "_send_command", return_value=response
        ):
            result = cls_api_miner.summary()

        self.assertTrue(result)
        self.assertEqual(
            cls_api_miner.summary_data,
            {"MHS av": 12345.6, "Temperature": 63.0, "Status": "hashing"},
        )

    # After a successful summary, the stored data is readable without
    # re-issuing the command (a second read does not call the transport).
    # Validates: Requirements 3.3
    def test_summary_stored_data_readable_without_reissue(self):
        cls_api_miner = api.ApiMiner(self.log)
        response = self._summary_response()

        with patch.object(
            cls_api_miner, "_send_command", return_value=response
        ) as mock_send:
            self.assertTrue(cls_api_miner.summary())

        # The command was issued exactly once.
        self.assertEqual(mock_send.call_count, 1)

        # The stored data remains readable afterward with no further transport
        # calls.
        stored = cls_api_miner.summary_data
        self.assertEqual(stored["MHS av"], 12345.6)
        self.assertEqual(stored["Temperature"], 63.0)
        self.assertEqual(stored["Status"], "hashing")
        self.assertEqual(mock_send.call_count, 1)

    # Transport returns None -> False, prior summary_data unchanged, error
    # logged.
    # Validates: Requirements 3.4
    def test_summary_none_returns_false_and_preserves_prior_data(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        # Seed prior successful summary data.
        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._summary_response(),
        ):
            self.assertTrue(cls_api_miner.summary())
        prior = cls_api_miner.summary_data

        with patch.object(
            cls_api_miner, "_send_command", return_value=None
        ):
            result = cls_api_miner.summary()

        self.assertFalse(result)
        # Prior data is left unchanged.
        self.assertEqual(cls_api_miner.summary_data, prior)
        self.assertIn("summary", stdio.getvalue().lower())

    # Response missing the required statistics -> False, prior data unchanged,
    # response included in the error log.
    # Validates: Requirements 3.5
    def test_summary_missing_stats_returns_false_and_preserves_prior(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        # Seed prior successful summary data.
        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._summary_response(),
        ):
            self.assertTrue(cls_api_miner.summary())
        prior = cls_api_miner.summary_data

        # A response whose SUMMARY element lacks the required fields.
        bad_response = {
            "STATUS": [{"STATUS": "S"}],
            "SUMMARY": [{"Elapsed": 100}],
            "id": 1,
        }
        with patch.object(
            cls_api_miner, "_send_command", return_value=bad_response
        ):
            result = cls_api_miner.summary()

        self.assertFalse(result)
        # Prior data is left unchanged.
        self.assertEqual(cls_api_miner.summary_data, prior)
        # The offending response is included in the error log.
        self.assertIn("SUMMARY", stdio.getvalue())

    # Malformed SUMMARY sections: the section is not a list, is an empty list,
    # or its first element is not a dict. Each is rejected rather than raising.
    # Validates: Requirements 3.2
    def test_summary_malformed_section_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)

        for section in ("not-a-list", [], [["not-a-dict"]], [None]):
            with self.subTest(section=section):
                response = {
                    "STATUS": [{"STATUS": "S"}],
                    "SUMMARY": section,
                    "id": 1,
                }
                with patch.object(
                    cls_api_miner, "_send_command", return_value=response
                ):
                    self.assertFalse(cls_api_miner.summary())

    # A response that is not a dict at all is rejected by summary.
    # Validates: Requirements 3.2
    def test_summary_non_dict_response_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)

        with patch.object(
            cls_api_miner, "_send_command", return_value=["not", "a", "dict"]
        ):
            self.assertFalse(cls_api_miner.summary())

    # Real cgminer firmware (e.g. 4.11.1) returns the hash rate in SUMMARY but
    # no Temperature/Status field, reporting command status in the STATUS
    # envelope instead. summary must accept this shape and store the data.
    # Validates: Requirements 3.2
    def test_summary_accepts_real_firmware_shape_without_temperature(self):
        cls_api_miner = api.ApiMiner(self.log)

        # A trimmed real cgminer 4.11.1 summary response: hash rate present,
        # no Temperature/Status keys, success reported in the STATUS envelope.
        response = {
            "STATUS": [
                {"STATUS": "S", "Code": 11, "Msg": "Summary",
                 "Description": "cgminer 4.11.1"}
            ],
            "SUMMARY": [{"Elapsed": 1563483, "MHS av": 55342101.68}],
            "id": 1,
        }
        with patch.object(
            cls_api_miner, "_send_command", return_value=response
        ):
            result = cls_api_miner.summary()

        self.assertTrue(result)
        self.assertEqual(cls_api_miner.summary_data["MHS av"], 55342101.68)

    # A success SUMMARY payload combined with an error STATUS envelope must
    # fail: cgminer reports command status in STATUS, not SUMMARY.
    # Validates: Requirements 3.5
    def test_summary_error_status_returns_false(self):
        cls_api_miner = api.ApiMiner(self.log)
        response = {
            "STATUS": [{"STATUS": "E", "Msg": "boom"}],
            "SUMMARY": [{"MHS av": 123.0}],
            "id": 1,
        }
        with patch.object(
            cls_api_miner, "_send_command", return_value=response
        ):
            result = cls_api_miner.summary()

        self.assertFalse(result)

    # ------------------------------------------------------------------ #
    # Task 7.2: unit tests for on/off success and failure. The transport #
    # helper (_send_command) is patched so no socket I/O occurs; the      #
    # default construction leaves dry_run disabled.                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _success_response():
        """A CGMiner response whose status indicates success."""
        return {"STATUS": [{"STATUS": "S", "Msg": "ok"}], "id": 1}

    @staticmethod
    def _failure_response():
        """A CGMiner response whose status indicates an error."""
        return {"STATUS": [{"STATUS": "E", "Msg": "denied"}], "id": 1}

    # on() sends the correct ascset power-on payload when not dry-run.
    # Validates: Requirements 4.1
    def test_on_sends_ascset_on_payload_when_not_dry_run(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(cls_api_miner.dry_run)

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._success_response(),
        ) as mock_send:
            cls_api_miner.on()

        command = mock_send.call_args.args[0]
        self.assertEqual(command["command"], "ascset")
        # Payload has the shape "0,softon,1: <future_unix_timestamp>".
        self.assertRegex(
            command["parameter"],
            rf"^0,{api.ASCSET_ON},1: \d+$",
        )

    # off() sends the correct ascset power-off payload when not dry-run.
    # Validates: Requirements 5.1
    def test_off_sends_ascset_off_payload_when_not_dry_run(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(cls_api_miner.dry_run)

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._success_response(),
        ) as mock_send:
            cls_api_miner.off()

        command = mock_send.call_args.args[0]
        self.assertEqual(command["command"], "ascset")
        # Payload has the shape "0,softoff,1: <future_unix_timestamp>".
        self.assertRegex(
            command["parameter"],
            rf"^0,{api.ASCSET_OFF},1: \d+$",
        )

    # on() returns True when the response status indicates success.
    # Validates: Requirements 4.3
    def test_on_success_status_returns_true(self):
        cls_api_miner = api.ApiMiner(self.log)

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._success_response(),
        ):
            result = cls_api_miner.on()

        self.assertTrue(result)

    # off() returns True when the response status indicates success.
    # Validates: Requirements 5.3
    def test_off_success_status_returns_true(self):
        cls_api_miner = api.ApiMiner(self.log)

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._success_response(),
        ):
            result = cls_api_miner.off()

        self.assertTrue(result)

    # on() returns False when the transport helper returns None, and logs an
    # error reporting the power-on failure.
    # Validates: Requirements 4.4
    def test_on_none_response_returns_false_and_logs(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        with patch.object(
            cls_api_miner, "_send_command", return_value=None
        ):
            result = cls_api_miner.on()

        self.assertFalse(result)
        self.assertIn("power on", stdio.getvalue().lower())

    # on() returns False when the response status indicates failure, and the
    # response is included in the error log.
    # Validates: Requirements 4.4
    def test_on_failure_status_returns_false_and_logs_response(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        response = self._failure_response()

        with patch.object(
            cls_api_miner, "_send_command", return_value=response
        ):
            result = cls_api_miner.on()

        self.assertFalse(result)
        log_output = stdio.getvalue()
        self.assertIn("power on", log_output.lower())
        self.assertIn("denied", log_output)

    # off() returns False when the transport helper returns None, and logs an
    # error reporting the power-off failure.
    # Validates: Requirements 5.4
    def test_off_none_response_returns_false_and_logs(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        with patch.object(
            cls_api_miner, "_send_command", return_value=None
        ):
            result = cls_api_miner.off()

        self.assertFalse(result)
        self.assertIn("power off", stdio.getvalue().lower())

    # off() returns False when the response status indicates failure, and the
    # response is included in the error log.
    # Validates: Requirements 5.4
    def test_off_failure_status_returns_false_and_logs_response(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        response = self._failure_response()

        with patch.object(
            cls_api_miner, "_send_command", return_value=response
        ):
            result = cls_api_miner.off()

        self.assertFalse(result)
        log_output = stdio.getvalue()
        self.assertIn("power off", log_output.lower())
        self.assertIn("denied", log_output)

    # ------------------------------------------------------------------ #
    # Task 8.2: property test for distinct, deterministic mode mapping.   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _workmode_int_from_payload(command):
        """
        Extract the workmode integer from an ascset set-mode command payload.

        The payload has the shape
        ``{"command": "ascset", "parameter": "0,workmode,set,<n>"}``; this
        returns ``<n>`` as an int.
        """
        parameter = command["parameter"]
        prefix, workmode, verb, value = parameter.split(",")
        assert prefix == "0"
        assert workmode == "workmode"
        assert verb == "set"
        return int(value)

    # Feature: api-miner, Property 6: Mode mapping is distinct and
    # deterministic
    # For the three operating modes ("Eco", "Standard", "Super"), the mapping
    # to a CGMiner workmode integer is deterministic across repeated set_mode
    # calls (the payload built for a given mode is identical every time) and
    # the three resulting integers are mutually distinct. set_mode is driven
    # with _send_command patched so no socket I/O occurs, and the exact
    # command payload handed to the transport is inspected.
    # Validates: Requirements 6.2
    @settings(max_examples=100)
    @given(
        # Vary the number of repeated calls per mode and the order in which
        # the modes are exercised so determinism is checked across many
        # interleavings.
        repeats=st.integers(min_value=2, max_value=8),
        order=st.permutations(["Eco", "Standard", "Super"]),
    )
    def test_mode_mapping_distinct_and_deterministic(self, repeats, order):
        cls_api_miner = api.ApiMiner(self.log)

        # Map each mode to the workmode integer(s) observed across repeated
        # set_mode calls. A well-behaved mapping yields exactly one integer
        # per mode no matter how many times it is called.
        observed = {mode: set() for mode in order}

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._success_response(),
        ) as mock_send:
            for mode in order:
                for _ in range(repeats):
                    self.assertTrue(cls_api_miner.set_mode(mode))
                    command = mock_send.call_args.args[0]
                    self.assertEqual(command["command"], "ascset")
                    observed[mode].add(
                        self._workmode_int_from_payload(command)
                    )

        # Determinism: every repeated call for a mode produced the same
        # workmode integer.
        for mode in order:
            self.assertEqual(
                len(observed[mode]),
                1,
                f"Mode '{mode}' mapped to more than one workmode integer: "
                f"{observed[mode]}",
            )

        # Distinctness: the three modes map to three mutually distinct
        # integers.
        workmode_ints = [next(iter(observed[mode])) for mode in order]
        self.assertEqual(len(set(workmode_ints)), 3)

    # ------------------------------------------------------------------ #
    # Task 8.3: property test for invalid mode rejection.                 #
    # ------------------------------------------------------------------ #

    # Feature: api-miner, Property 7: Invalid modes are rejected without
    # contacting the miner
    # For any value that is not exactly one of the strings "Eco", "Standard",
    # or "Super" (including None, empty string, non-string types such as ints,
    # floats, booleans, lists, and dicts, and arbitrary strings), set_mode
    # returns False, logs an error identifying the invalid mode, and never
    # invokes the transport helper (_send_command). set_mode is driven with
    # _send_command patched so the test can assert it is never called.
    # Validates: Requirements 6.3
    @settings(max_examples=200)
    @given(
        mode=st.one_of(
            st.none(),
            st.booleans(),
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.lists(st.integers(), max_size=3),
            st.dictionaries(
                keys=st.text(
                    st.characters(
                        blacklist_characters="\x00",
                        blacklist_categories=("Cs",),
                    )
                ),
                values=st.integers(),
                max_size=3,
            ),
            # Arbitrary strings, including the empty string. The three valid
            # mode strings are excluded so every generated value is invalid.
            st.text(
                st.characters(
                    blacklist_characters="\x00",
                    blacklist_categories=("Cs",),
                )
            ),
        ).filter(lambda m: m not in ("Eco", "Standard", "Super"))
    )
    def test_invalid_mode_rejected_without_contacting_miner(self, mode):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._success_response(),
        ) as mock_send:
            result = cls_api_miner.set_mode(mode)

        # The invalid mode is rejected.
        self.assertFalse(result)

        # The transport helper is never invoked: no bytes reach the miner.
        mock_send.assert_not_called()

        # An error identifying the invalid mode is logged.
        log_output = stdio.getvalue()
        self.assertIn("mode", log_output.lower())
        self.assertIn(str(mode), log_output)

    # ------------------------------------------------------------------ #
    # Task 8.4: unit tests for set_mode success and failure. The          #
    # transport helper (_send_command) is patched so no socket I/O        #
    # occurs; the default construction leaves dry_run disabled.           #
    # ------------------------------------------------------------------ #

    # set_mode sends the mapped ascset workmode payload when not dry-run,
    # for each valid operating mode.
    # Validates: Requirements 6.1
    def test_set_mode_sends_mapped_payload_when_not_dry_run(self):
        for mode in ("Eco", "Standard", "Super"):
            with self.subTest(mode=mode):
                cls_api_miner = api.ApiMiner(self.log)
                self.assertFalse(cls_api_miner.dry_run)

                with patch.object(
                    cls_api_miner,
                    "_send_command",
                    return_value=self._success_response(),
                ) as mock_send:
                    cls_api_miner.set_mode(mode)

                mock_send.assert_called_once_with(
                    {
                        "command": "ascset",
                        "parameter":
                            f"0,workmode,set,{api.WORKMODE_MAP[mode]}",
                    }
                )

    # set_mode returns True when the response status indicates success.
    # Validates: Requirements 6.5
    def test_set_mode_success_status_returns_true(self):
        cls_api_miner = api.ApiMiner(self.log)

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._success_response(),
        ):
            result = cls_api_miner.set_mode("Standard")

        self.assertTrue(result)

    # set_mode returns False when the transport helper returns None, and logs
    # an error reporting the mode-change failure.
    # Validates: Requirements 6.6
    def test_set_mode_none_response_returns_false_and_logs(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        with patch.object(
            cls_api_miner, "_send_command", return_value=None
        ):
            result = cls_api_miner.set_mode("Eco")

        self.assertFalse(result)
        log_output = stdio.getvalue().lower()
        self.assertIn("mode", log_output)
        self.assertIn("eco", log_output)

    # set_mode returns False when the response status indicates failure, and
    # the response is included in the error log.
    # Validates: Requirements 6.6
    def test_set_mode_failure_status_returns_false_and_logs_response(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        response = self._failure_response()

        with patch.object(
            cls_api_miner, "_send_command", return_value=response
        ):
            result = cls_api_miner.set_mode("Super")

        self.assertFalse(result)
        log_output = stdio.getvalue()
        self.assertIn("mode", log_output.lower())
        self.assertIn("Super", log_output)
        self.assertIn("denied", log_output)

    # ------------------------------------------------------------------ #
    # Task 9.2: unit tests for check success and failure. The transport  #
    # helper (_send_command) is patched so no socket I/O occurs; the      #
    # default construction leaves dry_run disabled.                       #
    # ------------------------------------------------------------------ #

    # check() sends the summary command through the transport helper.
    # Validates: Requirements 7.1
    def test_check_sends_summary_command(self):
        cls_api_miner = api.ApiMiner(self.log)

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._success_response(),
        ) as mock_send:
            cls_api_miner.check()

        mock_send.assert_called_once_with({"command": "summary"})

    # check() returns True when the response reports a success status.
    # Validates: Requirements 7.2
    def test_check_success_status_returns_true(self):
        cls_api_miner = api.ApiMiner(self.log)

        with patch.object(
            cls_api_miner,
            "_send_command",
            return_value=self._success_response(),
        ):
            result = cls_api_miner.check()

        self.assertTrue(result)

    # check() returns False when the transport helper returns None, and logs
    # an error reporting that the Avalon Q is unreachable.
    # Validates: Requirements 7.3
    def test_check_none_response_returns_false_and_logs_unreachable(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        with patch.object(
            cls_api_miner, "_send_command", return_value=None
        ):
            result = cls_api_miner.check()

        self.assertFalse(result)
        self.assertIn("unreachable", stdio.getvalue().lower())

    # check() returns False when the response reports an error/warning status,
    # and the response is included in the error log.
    # Validates: Requirements 7.4
    def test_check_failure_status_returns_false_and_logs_response(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        response = self._failure_response()

        with patch.object(
            cls_api_miner, "_send_command", return_value=response
        ):
            result = cls_api_miner.check()

        self.assertFalse(result)
        self.assertIn("denied", stdio.getvalue())

    # ------------------------------------------------------------------ #
    # Task 10.1: property test for dry-run suppressing state-changing     #
    # transmission.                                                       #
    # ------------------------------------------------------------------ #

    # Feature: api-miner, Property 9: Dry-run suppresses state-changing
    # transmission
    # For any state-changing operation (on, off, or set_mode with any valid
    # mode), when dry_run is enabled the operation returns True, logs the
    # exact payload at INFO level, and never invokes the transport helper
    # (_send_command) or opens a socket. Both _send_command and
    # socket.create_connection are patched so the test can assert neither is
    # ever invoked, and the INFO-level log output is captured to confirm the
    # exact command payload was logged.
    # Validates: Requirements 4.2, 5.2, 6.4, 8.3, 8.4, 8.5
    @settings(max_examples=150)
    @given(
        operation=st.sampled_from(
            [
                ("on", None),
                ("off", None),
                ("set_mode", "Eco"),
                ("set_mode", "Standard"),
                ("set_mode", "Super"),
            ]
        )
    )
    def test_dry_run_suppresses_state_changing_transmission(self, operation):
        op_name, mode = operation
        cls_api_miner = api.ApiMiner(self.log, dry_run=True)
        self.assertTrue(cls_api_miner.dry_run)

        # Capture log output at INFO level so the dry-run simulation record is
        # observed (the ApiMiner logs the simulation via self.log.info).
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        handler.setLevel(logging.INFO)
        self.log.addHandler(handler)
        self.log.setLevel(logging.INFO)

        # A fragment of the exact command payload the operation is expected to
        # log. on/off carry a dynamic timestamp, so only the stable prefix is
        # checked for those.
        if op_name == "on":
            expected_fragment = (
                f"'command': 'ascset', 'parameter': '0,{api.ASCSET_ON},1: "
            )
        elif op_name == "off":
            expected_fragment = (
                f"'command': 'ascset', 'parameter': '0,{api.ASCSET_OFF},1: "
            )
        else:
            expected_fragment = str({
                "command": "ascset",
                "parameter": f"0,workmode,set,{api.WORKMODE_MAP[mode]}",
            })

        # Patch both the transport helper and the raw socket factory so the
        # test can prove neither is invoked in dry-run mode.
        with patch.object(cls_api_miner, "_send_command") as mock_send:
            with patch(
                "optimshine.api_miner.socket.create_connection"
            ) as mock_conn:
                if op_name == "on":
                    result = cls_api_miner.on()
                elif op_name == "off":
                    result = cls_api_miner.off()
                else:
                    result = cls_api_miner.set_mode(mode)

        # The state-changing operation returns True in dry-run mode.
        self.assertTrue(result)

        # No transmission occurred: neither the transport helper nor a socket
        # was ever opened.
        mock_send.assert_not_called()
        mock_conn.assert_not_called()

        # The payload that would have been transmitted is present in the
        # captured INFO-level log output.
        self.assertIn(expected_fragment, stdio.getvalue())

    # ------------------------------------------------------------------ #
    # Task 10.2: property test for dry-run preserving read transmission.  #
    # ------------------------------------------------------------------ #

    # Feature: api-miner, Property 10: Dry-run preserves read transmission
    # For any read operation (summary, check), enabling dry_run does NOT
    # suppress transmission: the transport helper (_send_command) is still
    # invoked exactly as it would be when dry_run is disabled -- once, with
    # the {"command": "summary"} payload. _send_command is patched to return a
    # well-formed success/summary response so the read completes normally,
    # and the transport call count and argument are asserted to confirm reads
    # transmit even in dry-run mode.
    # Validates: Requirements 8.6
    @settings(max_examples=150)
    @given(read_op=st.sampled_from(["summary", "check"]))
    def test_dry_run_preserves_read_transmission(self, read_op):
        cls_api_miner = api.ApiMiner(self.log, dry_run=True)
        self.assertTrue(cls_api_miner.dry_run)

        # Return a response appropriate for the read under test: summary
        # inspects the SUMMARY section, while check only inspects STATUS.
        if read_op == "summary":
            response = self._summary_response()
        else:
            response = self._success_response()

        with patch.object(
            cls_api_miner, "_send_command", return_value=response
        ) as mock_send:
            if read_op == "summary":
                result = cls_api_miner.summary()
            else:
                result = cls_api_miner.check()

        # The read succeeds with the well-formed response.
        self.assertTrue(result)

        # The transport helper is invoked exactly once, transmitting the
        # summary command exactly as it would when dry_run is disabled.
        self.assertEqual(mock_send.call_count, 1)
        mock_send.assert_called_once_with({"command": "summary"})

    # ------------------------------------------------------------------ #
    # Task 10.3: unit tests for dry-run defaults and construction.        #
    # Example / edge-case coverage complementing the Property 9 / 10      #
    # tests above.                                                        #
    # ------------------------------------------------------------------ #

    # Default construction leaves dry-run disabled.
    # Validates: Requirements 8.2
    def test_default_construction_dry_run_disabled(self):
        cls_api_miner = api.ApiMiner(self.log)
        self.assertFalse(cls_api_miner.dry_run)

    # Passing dry_run=True at construction enables dry-run mode.
    # Validates: Requirements 8.1
    def test_construction_with_dry_run_true_enables_dry_run(self):
        cls_api_miner = api.ApiMiner(self.log, dry_run=True)
        self.assertTrue(cls_api_miner.dry_run)

    # With dry-run enabled, each state-changing method (on, off, set_mode)
    # returns True and no socket is opened: both the transport helper
    # (_send_command) and socket.create_connection are patched and asserted
    # never to be invoked.
    # Validates: Requirements 9.4
    def test_dry_run_state_changing_methods_return_true_no_socket(self):
        for op_name, mode in (
            ("on", None),
            ("off", None),
            ("set_mode", "Eco"),
        ):
            with self.subTest(operation=op_name, mode=mode):
                cls_api_miner = api.ApiMiner(self.log, dry_run=True)
                self.assertTrue(cls_api_miner.dry_run)

                with patch.object(
                    cls_api_miner, "_send_command"
                ) as mock_send:
                    with patch(
                        "optimshine.api_miner.socket.create_connection"
                    ) as mock_conn:
                        if op_name == "on":
                            result = cls_api_miner.on()
                        elif op_name == "off":
                            result = cls_api_miner.off()
                        else:
                            result = cls_api_miner.set_mode(mode)

                # The state-changing method returns True in dry-run mode.
                self.assertTrue(result)

                # No socket is opened: neither the transport helper nor the
                # socket factory is ever invoked.
                mock_send.assert_not_called()
                mock_conn.assert_not_called()

    # ------------------------------------------------------------------ #
    # Unit tests for _get_btc_price (CoinGecko simple/price, mocked HTTP). #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _btc_price_response(price=250000.0, last_updated_at=1752710400):
        """
        A well-formed CoinGecko simple/price response for bitcoin in PLN.
        """
        return {
            "bitcoin": {
                "pln": price,
                "last_updated_at": last_updated_at,
            }
        }

    # Success path: the BTC price and last-updated date are returned as a
    # dict.
    def test_fetch_btc_price_success_returns_price_and_date(self):
        cls_api_miner = api.ApiMiner(self.log)
        response = self._btc_price_response(
            price=250000.0, last_updated_at=1752710400
        )

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch.object(
                cls_api_miner, "api_get_request", return_value=response
            ) as mock_get:
                result = cls_api_miner._fetch_btc_price()

        # last_updated_at 1752710400 == 2025-07-17 00:00:00 UTC.
        self.assertEqual(result["price"], 250000.0)
        self.assertEqual(
            result["date"],
            datetime.datetime(
                2025, 7, 17, 0, 0, 0, tzinfo=datetime.timezone.utc
            ),
        )
        self.assertEqual(mock_get.call_count, 1)

    # The CoinGecko API key from the environment is forwarded as the
    # x-cg-demo-api-key header and the bitcoin/pln price endpoint is queried.
    def test_fetch_btc_price_sends_api_key_header_and_pln_query(self):
        cls_api_miner = api.ApiMiner(self.log)

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch.object(
                cls_api_miner,
                "api_get_request",
                return_value=self._btc_price_response(),
            ) as mock_get:
                cls_api_miner._fetch_btc_price()

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        url = args[0]
        self.assertIn("vs_currencies=pln", url)
        self.assertIn("ids=bitcoin", url)
        self.assertEqual(
            kwargs["extra_headers"], {"x-cg-demo-api-key": "cg-secret-key"}
        )

    # When last_updated_at is absent, the current UTC time is used as the date
    # while the price is still returned.
    def test_fetch_btc_price_missing_last_updated_uses_current_time(self):
        cls_api_miner = api.ApiMiner(self.log)
        response = {"bitcoin": {"pln": 123456.0}}

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch.object(
                cls_api_miner, "api_get_request", return_value=response
            ):
                result = cls_api_miner._fetch_btc_price()

        self.assertEqual(result["price"], 123456.0)
        # A tz-aware UTC datetime is returned even without last_updated_at.
        self.assertIsInstance(result["date"], datetime.datetime)
        self.assertEqual(result["date"].tzinfo, datetime.timezone.utc)

    # Missing config (e.g. COINGECKO_API_KEY unset) -> returns None without
    # querying CoinGecko.
    def test_fetch_btc_price_missing_config_returns_none(self):
        cls_api_miner = api.ApiMiner(self.log)

        env = {"MINER_IP": "192.168.1.10", "MINER_PORT": "4028"}
        with patch.dict("os.environ", env, clear=False):
            os.environ.pop("COINGECKO_API_KEY", None)
            with patch.object(
                cls_api_miner, "api_get_request"
            ) as mock_get:
                result = cls_api_miner._fetch_btc_price()

        self.assertIsNone(result)
        mock_get.assert_not_called()

    # No response from CoinGecko (None) -> None and a warning is logged.
    def test_fetch_btc_price_no_response_returns_none_and_warns(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch.object(
                cls_api_miner, "api_get_request", return_value=None
            ):
                result = cls_api_miner._fetch_btc_price()

        self.assertIsNone(result)
        self.assertIn("BTC price is not available!", stdio.getvalue())

    # Unexpected response shape (missing bitcoin/pln keys) -> None and a
    # warning is logged.
    def test_fetch_btc_price_unexpected_shape_returns_none_and_warns(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch.object(
                cls_api_miner,
                "api_get_request",
                return_value={"unexpected": "payload"},
            ):
                result = cls_api_miner._fetch_btc_price()

        self.assertIsNone(result)
        self.assertIn("BTC price is not available!", stdio.getvalue())

    # Null price value -> None and a warning is logged.
    def test_fetch_btc_price_null_price_returns_none_and_warns(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()
        response = {"bitcoin": {"pln": None, "last_updated_at": 1752710400}}

        env = {
            "MINER_IP": "192.168.1.10",
            "MINER_PORT": "4028",
            "COINGECKO_API_KEY": "cg-secret-key",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch.object(
                cls_api_miner, "api_get_request", return_value=response
            ):
                result = cls_api_miner._fetch_btc_price()

        self.assertIsNone(result)
        self.assertIn("BTC price is not available!", stdio.getvalue())

    # ------------------------------------------------------------------ #
    # Unit tests for the _get_btc_price cache.                           #
    # ------------------------------------------------------------------ #

    def _btc_price(self, price=250000.0):
        """
        Build a BTC price record of the shape _fetch_btc_price returns.

        Args:
            price (float, optional): The price in PLN. Defaults to 250000.0.

        Returns:
            dict: A record with a ``date`` and a ``price``.
        """
        return {
            "date": datetime.datetime(
                2025, 7, 17, tzinfo=datetime.timezone.utc
            ),
            "price": price,
        }

    # Repeated calls within the TTL reuse the cached value, so CoinGecko is
    # queried exactly once.
    def test_get_btc_price_caches_within_ttl(self):
        cls_api_miner = api.ApiMiner(self.log)
        expected = self._btc_price()

        with patch.object(
            cls_api_miner, "_fetch_btc_price", return_value=expected
        ) as mock_fetch:
            first = cls_api_miner._get_btc_price()
            second = cls_api_miner._get_btc_price()
            third = cls_api_miner._get_btc_price()

        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertEqual(third, expected)
        mock_fetch.assert_called_once()

    # Once the TTL has elapsed the price is fetched again.
    def test_get_btc_price_refetches_after_ttl(self):
        cls_api_miner = api.ApiMiner(self.log)
        fresh = self._btc_price(price=260000.0)

        with patch.object(
            cls_api_miner, "_fetch_btc_price", return_value=self._btc_price()
        ) as mock_fetch:
            cls_api_miner._get_btc_price()
            mock_fetch.assert_called_once()

        # Age the cache past the TTL.
        cls_api_miner._btc_price_cached_at -= (api.BTC_PRICE_CACHE_TTL + 1)

        with patch.object(
            cls_api_miner, "_fetch_btc_price", return_value=fresh
        ) as mock_fetch:
            result = cls_api_miner._get_btc_price()

        mock_fetch.assert_called_once()
        self.assertEqual(result, fresh)

    # A failed fetch is not cached, so the next call retries and can recover.
    def test_get_btc_price_does_not_cache_failure(self):
        cls_api_miner = api.ApiMiner(self.log)

        with patch.object(
            cls_api_miner, "_fetch_btc_price", return_value=None
        ) as mock_fetch:
            self.assertIsNone(cls_api_miner._get_btc_price())
            self.assertIsNone(cls_api_miner._get_btc_price())

        # Both calls attempted a real fetch; nothing was cached.
        self.assertEqual(mock_fetch.call_count, 2)
        self.assertFalse(hasattr(cls_api_miner, "_btc_price_cache"))

        # A later success is returned and cached as usual.
        expected = self._btc_price()
        with patch.object(
            cls_api_miner, "_fetch_btc_price", return_value=expected
        ) as mock_fetch:
            self.assertEqual(cls_api_miner._get_btc_price(), expected)
            self.assertEqual(cls_api_miner._get_btc_price(), expected)

        mock_fetch.assert_called_once()

    # A cache timestamp in the future (for example after a clock change) is
    # treated as stale rather than reused indefinitely.
    def test_get_btc_price_ignores_future_cache_timestamp(self):
        cls_api_miner = api.ApiMiner(self.log)
        stale = self._btc_price(price=1.0)
        fresh = self._btc_price(price=260000.0)

        cls_api_miner._btc_price_cache = stale
        cls_api_miner._btc_price_cached_at = (
            datetime.datetime.now().timestamp() + 3600
        )

        with patch.object(
            cls_api_miner, "_fetch_btc_price", return_value=fresh
        ) as mock_fetch:
            result = cls_api_miner._get_btc_price()

        mock_fetch.assert_called_once()
        self.assertEqual(result, fresh)

    # The cache works when ApiMiner is mixed into a class that never calls
    # ApiMiner.__init__, which is how OptimShine uses it.
    def test_get_btc_price_cache_without_init(self):
        class Mixed(api.ApiMiner):
            def __init__(self, log):
                # Deliberately does not call ApiMiner.__init__.
                self.log = log

        cls_mixed = Mixed(self.log)
        expected = self._btc_price()

        with patch.object(
            cls_mixed, "_fetch_btc_price", return_value=expected
        ) as mock_fetch:
            self.assertEqual(cls_mixed._get_btc_price(), expected)
            self.assertEqual(cls_mixed._get_btc_price(), expected)

        mock_fetch.assert_called_once()

    # ------------------------------------------------------------------ #
    # Unit tests for get_current_miner_profitability (mocked BTC price).  #
    # ------------------------------------------------------------------ #

    # Success path: returns True and stores profitability per kWh on
    # self.profitability as (daily_btc_profit * btc_price) /
    # daily_kwh_consumption for each valid mode.
    def test_get_current_miner_profitability_success(self):
        btc_price = {
            "date": datetime.datetime(
                2025, 7, 17, tzinfo=datetime.timezone.utc
            ),
            "price": 250000.0,
        }

        for mode in ("Eco", "Standard", "Super"):
            with self.subTest(mode=mode):
                cls_api_miner = api.ApiMiner(self.log)
                # The consumption constants are in watts, so they are
                # converted to kWh consumed per 24h.
                expected = (
                    api.WORKMODE_AVERAGE_PROFITABILITY[mode]
                    * btc_price["price"]
                    / (api.WORKMODE_POWER_CONSUMPTION[mode] * 24 / 1000)
                )
                with patch.object(
                    cls_api_miner, "_get_btc_price", return_value=btc_price
                ) as mock_price:
                    result = cls_api_miner.get_current_miner_profitability(
                        mode
                    )

                self.assertTrue(result)
                self.assertAlmostEqual(cls_api_miner.profitability, expected)
                mock_price.assert_called_once()

    # Invalid mode -> False, an error is logged, no profitability is stored,
    # and the BTC price is never fetched.
    def test_get_current_miner_profitability_invalid_mode(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        for mode in ("Turbo", "", None, 123):
            with self.subTest(mode=mode):
                with patch.object(
                    cls_api_miner, "_get_btc_price"
                ) as mock_price:
                    result = cls_api_miner.get_current_miner_profitability(
                        mode
                    )

                self.assertFalse(result)
                mock_price.assert_not_called()

        self.assertFalse(hasattr(cls_api_miner, "profitability"))
        self.assertIn("Unknown Avalon Q operating mode", stdio.getvalue())

    # BTC price unavailable -> False, an error is logged, and no profitability
    # is stored.
    def test_get_current_miner_profitability_no_btc_price(self):
        cls_api_miner = api.ApiMiner(self.log)
        stdio = self._capture_log()

        with patch.object(
            cls_api_miner, "_get_btc_price", return_value=None
        ):
            result = cls_api_miner.get_current_miner_profitability("Eco")

        self.assertFalse(result)
        self.assertFalse(hasattr(cls_api_miner, "profitability"))
        self.assertIn(
            "Cannot compute miner profitability!", stdio.getvalue()
        )

    # Higher BTC price yields proportionally higher profitability for the same
    # mode.
    def test_get_current_miner_profitability_scales_with_price(self):
        def _price(value):
            return {
                "date": datetime.datetime(
                    2025, 7, 17, tzinfo=datetime.timezone.utc
                ),
                "price": value,
            }

        cls_low = api.ApiMiner(self.log)
        with patch.object(
            cls_low, "_get_btc_price", return_value=_price(100000.0)
        ):
            self.assertTrue(
                cls_low.get_current_miner_profitability("Standard")
            )

        cls_high = api.ApiMiner(self.log)
        with patch.object(
            cls_high, "_get_btc_price", return_value=_price(200000.0)
        ):
            self.assertTrue(
                cls_high.get_current_miner_profitability("Standard")
            )

        self.assertAlmostEqual(
            cls_high.profitability, cls_low.profitability * 2
        )


# ---------------------------------------------------------------------- #
# Task 12.1: skip-guarded integration tests against real hardware.        #
#                                                                         #
# These tests exercise a real Avalon Q over the network. They do NOT mock #
# the socket. The suite is guarded on the MINER_IP environment variable:  #
# when it is unset or empty the whole TestCase is reported as skipped     #
# rather than executed or failed.                                         #
#                                                                         #
# Note: the skipUnless decorator is evaluated at class-definition (import)#
# time, so it reads MINER_IP directly from the process environment before #
# OptimConfig.envs_setup loads tests/.testenv. Because load_dotenv does   #
# not override an already-set variable, a real MINER_IP supplied in the   #
# environment is preserved, while an unset/empty MINER_IP causes the      #
# tests to skip. setUp performs a second, defensive skip in case the      #
# effective MINER_IP is empty after environment setup.                    #
# ---------------------------------------------------------------------- #

_MINER_IP_ENV = os.environ.get("MINER_IP")


@unittest.skipUnless(
    bool(_MINER_IP_ENV and _MINER_IP_ENV.strip()),
    "MINER_IP is not set; skipping real-hardware integration tests.",
)
class TestApiMinerIntegration(unittest.TestCase):
    """
    Integration tests that talk to a real Avalon Q miner. Skipped unless a
    non-empty MINER_IP is configured in the environment (Req 9.8).
    """

    def setUp(self):
        cls_optim_config = config.OptimConfig()
        cls_optim_config.logger_setup()
        self.log = cls_optim_config.log
        cls_optim_config.envs_setup("tests/.testenv")

        # load_dotenv does not override an already-set MINER_IP, so a real
        # hardware address from the process environment is preserved. If the
        # effective value is empty, skip defensively (Req 9.8).
        effective_ip = os.environ.get("MINER_IP")
        if not effective_ip or not effective_ip.strip():
            self.skipTest("MINER_IP is empty after environment setup.")

        self.cls_api_miner = api.ApiMiner(self.log)

        # Record the state to restore in tearDown: the active operating mode
        # and whether the miner was powered on before the test ran (Req 9.7).
        self._original_mode = self._current_mode()
        self._was_powered_on = self._soft_power_on()

    def tearDown(self):
        # Restore the state that was in effect before the test ran, undoing any
        # mode change or power change performed during the test (Req 9.7).
        original_mode = getattr(self, "_original_mode", None)
        if original_mode is not None:
            self.cls_api_miner.set_mode(original_mode)

        # Only power down when the miner was known to be off beforehand. An
        # indeterminate reading must not switch off a miner that was running.
        if getattr(self, "_was_powered_on", None) is False:
            self.cls_api_miner.off()
            time.sleep(api.ASCSET_DELAY + 2)
        self.log.handlers.clear()

    def _soft_power_on(self):
        """
        Report whether the miner is soft-powered on.

        This is the commanded power state, not a measure of work being done.
        The Avalon Q reports the two soft on/off commands it last accepted as
        ``SoftOnTime[<unix_ts>]`` and ``SoftOffTime[<unix_ts>]`` in its
        ``estats`` output, so whichever timestamp is later identifies the state
        currently in effect.

        Two fields are deliberately not used:

        - ``SoftOFF[<n>]`` is not a boolean. A live miner reports values such
          as 4, so comparing it against 0 reads as "off" even when the miner is
          running.
        - the hash rate, because a miner that has just been powered on reports
          no hash rate until it has reached a pool and taken work, so zero does
          not distinguish "off" from "on but not yet hashing".

        Returns:
            bool or None: True when the miner is powered on, False when it is
                          switched off, or None when the state cannot be
                          determined.
        """
        response = self.cls_api_miner._send_command({"command": "estats"})
        if not isinstance(response, dict):
            return None

        stats = response.get("STATS")
        if not isinstance(stats, list):
            return None

        blob = json.dumps(stats)
        on_match = re.search(r"SoftOnTime\[(\d+)\]", blob)
        off_match = re.search(r"SoftOffTime\[(\d+)\]", blob)
        if not on_match or not off_match:
            return None

        on_time = int(on_match.group(1))
        off_time = int(off_match.group(1))
        if on_time == off_time:
            # Cannot tell which command came last.
            return None

        return on_time > off_time

    def _current_mode(self):
        """
        Read the active operating mode name from the miner.

        cgminer reports the active work mode in the ``estats`` output as a
        ``WORKMODE[<n>]`` token embedded in the AVALON stats string (it is not
        present in the ``summary`` response). This sends ``estats`` directly,
        extracts that integer, and maps it back to a WORKMODE_MAP key.

        Returns:
            str or None: The active mode name (a WORKMODE_MAP key) when it can
                         be determined, otherwise None.
        """
        response = self.cls_api_miner._send_command({"command": "estats"})
        if not isinstance(response, dict):
            return None

        # Flatten the STATS section into a single searchable string; the
        # WORKMODE[n] token lives inside a nested "MM ID0:Summary" value.
        stats = response.get("STATS")
        if not isinstance(stats, list):
            return None
        blob = json.dumps(stats)

        match = re.search(r"WORKMODE\[(\d+)\]", blob)
        if not match:
            return None

        reverse = {value: key for key, value in api.WORKMODE_MAP.items()}
        return reverse.get(int(match.group(1)))

    # Against the real miner, summary, set_mode, and check each return True.
    # A mode change is only accepted while the miner is powered on, so the
    # miner is switched on first when it was off. tearDown restores both the
    # original mode and the original power state.
    # Validates: Requirements 9.6, 9.7
    def test_real_hardware_summary_set_mode_check(self):
        # summary succeeds against the real Avalon Q.
        self.assertTrue(self.cls_api_miner.summary())

        # A mode change is only accepted while the miner is powered on, so turn
        # it on first if it was off. The ascset action is scheduled
        # ASCSET_DELAY seconds in the future, so wait for it to take effect
        # before sending the mode change.
        if self._was_powered_on is False:
            self.log.info("Miner is off. Powering it on for the mode change.")
            self.assertTrue(self.cls_api_miner.on())
            time.sleep(api.ASCSET_DELAY + 40)
            # Confirm the commanded power state flipped. The hash rate is
            # deliberately not used: reaching a pool and taking work takes far
            # longer than the ascset delay, so the miner can be powered on and
            # legitimately not hashing yet.
            self.assertIsNot(
                self._soft_power_on(), False,
                "Miner still reports soft-off after on()."
            )
        elif self._was_powered_on is None:
            self.log.warning(
                "Could not determine the miner power state; assuming it is on."
            )

        # set_mode succeeds against the real Avalon Q. Prefer the mode that
        # was already in effect so the exercise is minimally disruptive; fall
        # back to a known-valid mode when it cannot be determined. tearDown
        # restores the original mode regardless.
        target_mode = self._original_mode or "Standard"
        self.assertTrue(self.cls_api_miner.set_mode(target_mode))

        # check confirms the miner is reachable and healthy.
        self.assertTrue(self.cls_api_miner.check())


if __name__ == "__main__":
    unittest.main()
