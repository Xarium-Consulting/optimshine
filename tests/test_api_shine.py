#!/usr/bin/env python
#
# Copyright 2025 Norbert Kamiński <norbert.kaminski@xarium.world>
#
# SPDX-License-Identifier: LGPL-3.0-or-later
#

import io
import os
import logging
import unittest

import optimshine.api_shine as api
import optimshine.optim_config as config
import tests.test_api_shine_data as api_data

from datetime import datetime, timedelta
from unittest.mock import patch


class TestApiShine(unittest.TestCase):
    def setUp(self):
        cls_optim_config = config.OptimConfig()
        cls_optim_config.logger_setup()
        self.log = cls_optim_config.log
        cls_optim_config.envs_setup("tests/.testenv")

    def tearDown(self):
        self.log.handlers.clear()

    def test_get_shine_api_url_wrong_endpoint(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_shine = api.ApiShine(self.log)

        result = cls_api_shine._get_shine_api_url("wrong_endpoint")

        stdout = stdio.getvalue()

        self.assertIsNone(result)
        self.assertIn("wrong_endpoint API endpoint not found!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_user_login(self, mock_api_post_request):
        mock_api_post_request.return_value = (
            {"data": {"token": api_data.test_token}}
        )

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.login_shine()
        self.assertTrue(hasattr(cls_api_shine, "token"))
        self.assertEqual(cls_api_shine.token, api_data.test_token)
        self.assertTrue(hasattr(cls_api_shine, "token_ttl"))
        self.assertEqual(cls_api_shine.token_ttl, 1748987050)
        self.assertTrue(result)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_user_login_wrong_password(self, mock_api_post_request):
        stdio = io.StringIO()
        mock_api_post_request.return_value = (
            {"data": "Wrong password"}
        )

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_shine = api.ApiShine(self.log)

        result = cls_api_shine.login_shine()
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Login attempt failed. {'data': 'Wrong password'}",
                      stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_user_login_empty_token(self, mock_api_post_request):
        mock_api_post_request.return_value = (
            {"data": {"token": None}}
        )
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.login_shine()
        stdout = stdio.getvalue()

        self.assertTrue(hasattr(cls_api_shine, "token"))
        self.assertIsNone(cls_api_shine.token)
        self.assertIn("Login token not acquired.", stdout)
        self.assertFalse(result)

    @patch("optimshine.api_shine.datetime")
    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_user_login_max_ttl(self, mock_api_post_request, mock_datatime):
        mock_api_post_request.return_value = (
            {"data": {"token": api_data.test_token}}
        )
        mock_now = datetime.fromtimestamp(1748987050) - timedelta(days=1,
                                                                  hours=1)
        mock_datatime.datetime.now.return_value = mock_now
        excepted_ttl_ts = (mock_now + timedelta(days=1)).timestamp()
        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.login_shine()
        self.assertTrue(hasattr(cls_api_shine, "token"))
        self.assertEqual(cls_api_shine.token, api_data.test_token)
        self.assertTrue(hasattr(cls_api_shine, "token_ttl"))
        self.assertEqual(cls_api_shine.token_ttl, excepted_ttl_ts)
        self.assertTrue(result)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_user_login_api_request_failed(self, mock_api_post_request):
        stdio = io.StringIO()
        mock_api_post_request.return_value = None

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.login_shine()
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Login attempt failed!", stdout)

    def test_user_login_user_name(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        os.environ["SHINE_USER"] = ""

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.login_shine()
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Shine API user or password not set!", stdout)
        os.environ["SHINE_USER"] = "test"

    @patch("optimshine.api_shine.ApiShine._get_shine_api_url")
    def test_user_login_wrong_endpoint(self, mock_get_url):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_get_url.return_value = None

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.login_shine()
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Parsing login API URL failed!", stdout)

    def test_get_plant_list_not_authorized(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.get_plant_list()
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Session is not authorized!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_plant_list_none_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = None

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine.get_plant_list()
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Getting plant list failed!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_plant_list_wrong_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = (
            {"data": "Test issue"}
        )

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine.get_plant_list()
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Getting plants list failed. {'data': 'Test issue'}",
                      stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_plant_list_empty_list(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = (
            {"data": {"dataList": []}}
        )

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine.get_plant_list()
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("No plants available!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_plant_list_pass(self, mock_api_post_request):
        mock_api_post_request.return_value = (
            {"data": {"dataList": [
                {
                    "plantName": "plant1",
                    "id": "111",
                    "longitude": "00.000000",
                    "latitude": "00.000000",
                    "timeZone": "UTC",
                },
                {
                    "plantName": "plant2",
                    "id": "222",
                    "longitude": "11.000000",
                    "latitude": "11.000000",
                    "timeZone": "Europe/Warsaw",
                },
            ]}}
        )

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine.get_plant_list()

        self.assertTrue(result)
        self.assertTrue(hasattr(cls_api_shine, "plants_id"))
        self.assertEqual(cls_api_shine.plants_id["plant1"]["id"], '111')
        self.assertEqual(cls_api_shine.plants_id["plant1"]["latitude"],
                         '00.000000')
        self.assertEqual(cls_api_shine.plants_id["plant2"]["longitude"],
                         '11.000000')
        self.assertEqual(cls_api_shine.plants_id["plant2"]["timezone"],
                         'Europe/Warsaw')

    def test_get_device_list_not_authorized(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.get_device_list("test", "test")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Session is not authorized!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_device_list_none_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = None

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine.get_device_list("test", "test")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Getting device list failed!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_device_list_wrong_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = (
            {"data": "Test issue"}
        )

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine.get_device_list("test", "test")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Getting device list failed. {'data': 'Test issue'}",
                      stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_device_list_empty_list(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = (
            {"data": {"dataList": []}}
        )

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine.get_device_list("test", "test")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("No devices available!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_device_list_pass(self, mock_api_post_request):
        mock_api_post_request.return_value = (
            {"data": {"dataList": [
                {
                    "deviceSn": "100201000624330078",
                },
                {
                    "deviceSn": "100201000624330079",
                },
            ]}}
        )

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine.get_device_list("test", "test")

        self.assertTrue(result)
        self.assertTrue(hasattr(cls_api_shine, "device_list"))
        self.assertEqual(cls_api_shine.device_list,
                         ["100201000624330078", "100201000624330079"])

    def test_get_pv_production_data_not_authorized(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine._get_pv_production_data("test", "test")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Session is not authorized!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_pv_production_data_none_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = None

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine._get_pv_production_data("test")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Getting PV data failed!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_pv_production_data_wrong_response(self,
                                                   mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {"data": "Wrong data"}

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine._get_pv_production_data("test", "test")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Getting PV data failed. {'data': 'Wrong data'}",
                      stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_pv_production_data_empty_data(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {
            "data": {
                "storageMateDTOS": [],
                "dataTime": [],
            }
        }

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine._get_pv_production_data("test", "test")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("No PV data acquired!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_pv_production_data_pass(self, mock_api_post_request):
        mock_api_post_request.return_value = {
            "data": {
                "storageMateDTOS": [
                    {
                        "field": "pvTotalPower",
                        "name": "Total PV Power",
                        "unit": "W",
                        "sort": 6,
                        "classify": 0,
                        "data": [
                            "1",
                            "2",
                            "3",
                            "4",
                        ]
                    }
                ],
                "dataTime": [
                    "00:00",
                    "00:05",
                    "00:10",
                    "00:15",
                ],
            }
        }
        excepted_result = {
            "inverter_sn": "test_sn",
            "data_date": "test_date",
            "data_time": [
                "00:00",
                "00:05",
                "00:10",
                "00:15",
            ],
            "data": {
                "pvTotalPower": {
                    "label": api.SHINE_PV_DATA_LABELS["pvTotalPower"],
                    "data": ["1", "2", "3", "4"],
                    "unit": "W",
                }
            }
        }

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = api_data.test_token
        result = cls_api_shine._get_pv_production_data("test_sn", "test_date")

        self.assertTrue(result)
        self.assertTrue(hasattr(cls_api_shine, "pv_data"))
        self.assertEqual(cls_api_shine.pv_data, excepted_result)

    def test_get_setting_value_not_authorized(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.get_setting_value("test", "")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Session is not authorized!", stdout)

    def test_get_setting_value_wrong_value_name(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.get_setting_value("test", "wrong_value")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("wrong_value is not supported!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_setting_value_response_none(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = None

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.get_setting_value("test",
                                                 "battery_charge_current")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Getting setting values failed!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_setting_value_wrong_data(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {"data": "Test issue"}

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.get_setting_value("test",
                                                 "battery_charge_current")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn(
            "Getting battery_charge_current value failed."
            " {'data': 'Test issue'}",
            stdout
        )

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_setting_value_pass(self, mock_api_post_request):
        mock_api_post_request.return_value = {
            "data": {
                "bmchc": 20,
            }
        }

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.get_setting_value("test",
                                                 "battery_charge_current")

        self.assertTrue(result)
        self.assertEqual(cls_api_shine.setting_value, 20)

    def test_setting_command_status_not_authorized(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine._setting_command_status("test", 10)
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Session is not authorized!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_setting_command_status_none_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = None

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine._setting_command_status("test", 10)
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Getting command stasus failed!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_setting_command_status_wrong_response(self,
                                                   mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {"data": "Test issue"}

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine._setting_command_status("test", 10)
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Checking command status failed. {'data': 'Test issue'}",
                      stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_setting_command_status_timeout(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {"data": {"result": 0}}

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine._setting_command_status("test", 2)
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Command timeout!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_setting_command_status_pass(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {"data": {"result": 1}}

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine._setting_command_status("test", 2)
        stdout = stdio.getvalue()

        self.assertTrue(result)
        self.assertIn("Setting command sent successfuly.", stdout)

    def test_set_charge_current_not_authorized(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.set_charge_current("test", 2)
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Session is not authorized!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_set_charge_current_none_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = None

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.set_charge_current("test", 2)
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Setting charge current failed!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_set_charge_current_wrong_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {"data": "Test issue"}

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.set_charge_current("test", 2)
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Sending setting command failed. {'data': 'Test issue'}",
                      stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    @patch("optimshine.api_shine.ApiShine._setting_command_status")
    def test_set_charge_current_failed_status(self,
                                              mock_setting_command_status,
                                              mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {"data": [{"id": "test"}]}
        mock_setting_command_status.return_value = False

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.set_charge_current("test", 2)
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Wrong command status. Setting charge current failed!",
                      stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    @patch("optimshine.api_shine.ApiShine._setting_command_status")
    def test_set_charge_current_pass(self, mock_setting_command_status,
                                     mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {"data": [{"id": "test"}]}
        mock_setting_command_status.return_value = True

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.set_charge_current("test", 2)
        stdout = stdio.getvalue()

        self.assertTrue(result)
        self.assertIn("Charge current successfuly set.", stdout)

    def test_get_device_value_not_authorized(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        result = cls_api_shine.get_device_value("test", "")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Session is not authorized!", stdout)

    def test_get_device_value_wrong_value_name(self):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.get_device_value("test", "wrong_value")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("wrong_value is not supported!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_device_value_none_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = None

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.get_device_value("test", "battery_soc")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn("Getting device values failed!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_device_value_wrong_response(self, mock_api_post_request):
        stdio = io.StringIO()
        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        mock_api_post_request.return_value = {"data": "Test issue"}

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.get_device_value("test", "battery_soc")
        stdout = stdio.getvalue()

        self.assertFalse(result)
        self.assertIn(
            "Getting battery_soc value failed. {'data': 'Test issue'}",
            stdout
        )

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_device_value_pass(self, mock_api_post_request):
        mock_api_post_request.return_value = {"data": {"emsSoc": 68}}

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.get_device_value("test", "battery_soc")

        self.assertTrue(result)
        self.assertEqual(hasattr(cls_api_shine, "device_value"), True)
        self.assertEqual(cls_api_shine.device_value, 68)

    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_device_value_pv_power_pass(self, mock_api_post_request):
        mock_api_post_request.return_value = {"data": {"pvTotalPower": 1543}}

        cls_api_shine = api.ApiShine(self.log)
        cls_api_shine.token = "test"
        result = cls_api_shine.get_device_value("test", "pv_power")

        self.assertTrue(result)
        self.assertEqual(hasattr(cls_api_shine, "device_value"), True)
        self.assertEqual(cls_api_shine.device_value, 1543)


if __name__ == "__main__":
    unittest.main()
