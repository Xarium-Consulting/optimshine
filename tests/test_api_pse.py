#!/usr/bin/env python
#
# Copyright 2025 Norbert Kamiński <norbert.kaminski@xarium.world>
#
# SPDX-License-Identifier: LGPL-3.0-or-later
#

import io
import logging
import unittest

import optimshine.api_pse as api

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
import optimshine.optim_config as config

WARSAW = ZoneInfo("Europe/Warsaw")


class TestPseApi(unittest.TestCase):
    def setUp(self):
        cls_optim_config = config.OptimConfig()
        cls_optim_config.logger_setup()
        self.log = cls_optim_config.log
        cls_optim_config.envs_setup("tests/.testenv")

    def tearDown(self):
        self.log.handlers.clear()

    @patch("optimshine.api_common.ApiCommon.api_get_request")
    def test_get_pse_data_none_response(self, mock_api_get_request):
        stdio = io.StringIO()
        mock_api_get_request.return_value = None

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_pse = api.ApiPse(self.log)
        status = cls_api_pse.get_pse_data("2025-04-14")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Getting PSE data failed!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_get_request")
    def test_get_pse_data_wrong_response(self, mock_api_get_request):
        stdio = io.StringIO()
        mock_api_get_request.return_value = {"data": "Test issue"}

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_pse = api.ApiPse(self.log)
        status = cls_api_pse.get_pse_data("2025-04-14")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Getting RCE values failed! {'data': 'Test issue'}",
                      stdout)

    @patch("optimshine.api_common.ApiCommon.api_get_request")
    def test_get_pse_data_empty_data(self, mock_api_get_request):
        stdio = io.StringIO()
        mock_api_get_request.return_value = {"value": []}

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_pse = api.ApiPse(self.log)
        status = cls_api_pse.get_pse_data("2025-04-14")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("No RCE values available!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_get_request")
    def test_get_pse_data_pass(self, mock_api_get_request):
        mock_api_get_request.return_value = {
            "value": [
                {
                    "dtime": "2025-06-16 00:15:00",
                    "period": "00:00 - 00:15",
                    "rce_pln": 439.58000,
                    "dtime_utc": "2025-06-15 22:15:00",
                    "period_utc": "22:00 - 22:15",
                    "business_date": "2025-06-16",
                    "publication_ts": "2025-06-15 13:44:11.203",
                    "publication_ts_utc": "2025-06-15 11:44:11.203"
                },
                {
                    "dtime": "2025-06-16 00:30:00",
                    "period": "00:15 - 00:30",
                    "rce_pln": 449.58000,
                    "dtime_utc": "2025-06-15 22:30:00",
                    "period_utc": "22:15 - 22:30",
                    "business_date": "2025-06-16",
                    "publication_ts": "2025-06-15 13:44:11.203",
                    "publication_ts_utc": "2025-06-15 11:44:11.203"
                },
                {
                    "dtime": "2025-06-16 00:45:00",
                    "period": "00:30 - 00:45",
                    "rce_pln": 459.58000,
                    "dtime_utc": "2025-06-15 22:45:00",
                    "period_utc": "22:30 - 22:45",
                    "business_date": "2025-06-16",
                    "publication_ts": "2025-06-15 13:44:11.203",
                    "publication_ts_utc": "2025-06-15 11:44:11.203"
                },
            ]
        }
        expected_date = "2025-05-14"
        # "dtime" is the END of each period, so the quarter labelled
        # "00:00 - 00:15" carries dtime 00:15. Prices are keyed by the period
        # START, resolved in the market timezone rather than the host's, so
        # this expectation holds on any machine.
        expected_prices = {
            datetime(2025, 6, 16, 0, 0, tzinfo=WARSAW).timestamp(): 439.58,
            datetime(2025, 6, 16, 0, 15, tzinfo=WARSAW).timestamp(): 449.58,
            datetime(2025, 6, 16, 0, 30, tzinfo=WARSAW).timestamp(): 459.58,
        }

        cls_api_pse = api.ApiPse(self.log)
        status = cls_api_pse.get_pse_data("2025-05-14")

        self.assertTrue(status)
        self.assertTrue(hasattr(cls_api_pse, "rce_date"))
        self.assertEqual(expected_date, cls_api_pse.rce_date)
        self.assertTrue(hasattr(cls_api_pse, "rce_prices"))
        self.assertEqual(expected_prices, cls_api_pse.rce_prices)


if __name__ == "__main__":
    unittest.main()
