#!/usr/bin/env python
#
# Copyright 2025 Norbert Kamiński <norbert.kaminski@xarium.world>
#
# SPDX-License-Identifier: LGPL-3.0-or-later
#

import io
import logging
import unittest

from datetime import datetime, timedelta, timezone
from unittest.mock import call, MagicMock, patch
from zoneinfo import ZoneInfo

from optimshine.api_common import MARKET_TIMEZONE

from optimshine.api_miner import WORKMODE_POWER_CONSUMPTION
from optimshine.optim_shine import OptimShine


class TestOptimShine(unittest.TestCase):
    @patch('optimshine.optim_shine.sdnotify')
    def setUp(self, mock_sdnotify):
        mock_sdnotify.SystemdNotifier.return_value = MagicMock()

        self.cl = OptimShine("tests/.testenv")
        self.stdio = io.StringIO()
        handler = logging.StreamHandler(stream=self.stdio)
        self.cl.log.addHandler(handler)

    def tearDown(self):
        if self.cl.scheduler.running:
            self.cl.scheduler.shutdown()
        self.cl.log.handlers.clear()

    def test_shine_setup_login_failed(self):
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = False

        with self.assertRaises(SystemExit) as test_exit:
            self.cl._shine_setup()

        stdout = self.stdio.getvalue()
        self.assertIn("Failed to login to Shine API", stdout)
        self.cl.login_shine.assert_called_once()
        self.assertEqual(test_exit.exception.code, 1)

    def test_shine_setup_get_plant_failed(self):
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = True
        self.cl.get_plant_list = MagicMock()
        self.cl.get_plant_list.return_value = False

        with self.assertRaises(SystemExit) as test_exit:
            self.cl._shine_setup()

        stdout = self.stdio.getvalue()
        self.assertIn("Getting plant list failed.", stdout)
        self.cl.login_shine.assert_called_once()
        self.cl.get_plant_list.assert_called_once()
        self.assertEqual(test_exit.exception.code, 1)

    def test_shine_setup_none_plant_list(self):
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = True
        self.cl.get_plant_list = MagicMock()
        self.cl.get_plant_list.return_value = True
        self.cl.plants_id = None

        with self.assertRaises(SystemExit) as test_exit:
            self.cl._shine_setup()

        stdout = self.stdio.getvalue()
        self.assertIn("Plants list is empty", stdout)
        self.cl.login_shine.assert_called_once()
        self.cl.get_plant_list.assert_called_once()
        self.assertEqual(test_exit.exception.code, 1)

    def test_shine_setup_wrong_plant(self):
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = True
        self.cl.get_plant_list = MagicMock()
        self.cl.get_plant_list.return_value = True
        self.cl.plants_id = "Wrong data"

        with self.assertRaises(SystemExit) as test_exit:
            self.cl._shine_setup()

        stdout = self.stdio.getvalue()
        self.assertIn("test_plant not found in the plant list", stdout)
        self.cl.login_shine.assert_called_once()
        self.cl.get_plant_list.assert_called_once()
        self.assertEqual(test_exit.exception.code, 1)

    @patch("optimshine.optim_shine.os")
    def test_shine_setup_no_env_plant_one_plant_pass(self, mock_os):
        mock_os.getenv.return_value = None
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = True
        self.cl.get_plant_list = MagicMock()
        self.cl.get_plant_list.return_value = True
        self.cl.plants_id = {"plant_name": {"id": "0000"}}
        self.cl.get_device_list = MagicMock()
        self.cl.get_device_list.return_value = True
        self.cl.device_list = ["1111"]

        self.cl._shine_setup()
        stdout = self.stdio.getvalue()

        self.assertIn("API Shine setup was successful", stdout)
        self.cl.login_shine.assert_called_once()
        self.cl.get_plant_list.assert_called_once()
        self.cl.get_device_list.assert_called_once_with("0000", "INV")
        self.assertEqual(self.cl.inverters, ["1111"])

    @patch("optimshine.optim_shine.os")
    def test_shine_setup_no_env_plant_many_plants(self, mock_os):
        mock_os.getenv.return_value = None
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = True
        self.cl.get_plant_list = MagicMock()
        self.cl.get_plant_list.return_value = True
        self.cl.plants_id = {"plant_name1": {"id": "0000"},
                             "plant_name2": {"id": "2222"}}

        with self.assertRaises(SystemExit) as test_exit:
            self.cl._shine_setup()

        stdout = self.stdio.getvalue()
        self.assertIn("You must set SHINE_PLANT", stdout)
        self.cl.login_shine.assert_called_once()
        self.cl.get_plant_list.assert_called_once()
        self.assertEqual(test_exit.exception.code, 1)

    def test_shine_setup_get_device_list_failure(self):
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = True
        self.cl.get_plant_list = MagicMock()
        self.cl.get_plant_list.return_value = True
        self.cl.plants_id = {"test_plant": {"id": "0000"},
                             "plant_name2": {"id": "2222"}}
        self.cl.get_device_list = MagicMock()
        self.cl.get_device_list.return_value = False

        with self.assertRaises(SystemExit) as test_exit:
            self.cl._shine_setup()

        stdout = self.stdio.getvalue()
        self.assertIn("Failed to get list of inverters", stdout)
        self.cl.login_shine.assert_called_once()
        self.cl.get_plant_list.assert_called_once()
        self.cl.get_device_list.assert_called_once_with("0000", "INV")
        self.assertEqual(test_exit.exception.code, 1)

    def test_shine_setup_empty_device_list(self):
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = True
        self.cl.get_plant_list = MagicMock()
        self.cl.get_plant_list.return_value = True
        self.cl.plants_id = {"test_plant": {"id": "0000"},
                             "plant_name2": {"id": "2222"}}
        self.cl.get_device_list = MagicMock()
        self.cl.get_device_list.return_value = True
        self.cl.device_list = None

        with self.assertRaises(SystemExit) as test_exit:
            self.cl._shine_setup()

        stdout = self.stdio.getvalue()
        self.assertIn("No inverters found", stdout)
        self.cl.login_shine.assert_called_once()
        self.cl.get_plant_list.assert_called_once()
        self.cl.get_device_list.assert_called_once_with("0000", "INV")
        self.assertEqual(test_exit.exception.code, 1)

    def test_shine_setup_pass(self):
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = True
        self.cl.get_plant_list = MagicMock()
        self.cl.get_plant_list.return_value = True
        self.cl.plants_id = {"test_plant": {"id": "0000"},
                             "plant_name2": {"id": "2222"}}
        self.cl.get_device_list = MagicMock()
        self.cl.get_device_list.return_value = True
        self.cl.device_list = ["1111"]

        self.cl._shine_setup()

        stdout = self.stdio.getvalue()
        self.assertIn("API Shine setup was successful", stdout)
        self.cl.login_shine.assert_called_once()
        self.cl.get_plant_list.assert_called_once()
        self.cl.get_device_list.assert_called_once_with("0000", "INV")
        self.assertEqual(self.cl.inverters, ["1111"])

    def test_check_weather_get_weather_data_fail(self):
        test_date = datetime(year=2025, month=6, day=4).strftime("%Y-%m-%d")
        self.cl.get_weather_data = MagicMock()
        self.cl.get_weather_data.return_value = False

        status = self.cl._check_weather("0.000", "0.000", test_date)

        stdout = self.stdio.getvalue()
        self.cl.get_weather_data.assert_called_once_with("0.000", "0.000",
                                                         test_date)
        self.assertIn("Weather forecast is not available", stdout)
        self.assertFalse(status)

    def test_check_weather_empty_weather_data(self):
        test_date = datetime(year=2025, month=6, day=4).strftime("%Y-%m-%d")
        self.cl.get_weather_data = MagicMock()
        self.cl.get_weather_data.return_value = True
        self.cl.weather_data = {"low_clouds_data": []}

        status = self.cl._check_weather("0.000", "0.000", test_date)

        self.cl.get_weather_data.assert_called_once_with("0.000", "0.000",
                                                         test_date)
        self.assertFalse(self.cl.not_cloudy)
        self.assertTrue(status)

    def test_check_weather_not_cloudy(self):
        test_date = datetime(year=2025, month=6, day=4).strftime("%Y-%m-%d")
        self.cl.get_weather_data = MagicMock()
        self.cl.get_weather_data.return_value = True
        self.cl.weather_data = {
            "low_clouds_data": [0.038, 0.172, 0.115, 0.9]
        }

        status = self.cl._check_weather("0.000", "0.000", test_date)

        self.cl.get_weather_data.assert_called_once_with("0.000", "0.000",
                                                         test_date)
        self.assertTrue(self.cl.not_cloudy)
        self.assertTrue(status)

    def test_check_weather_cloudy_50_50(self):
        test_date = datetime(year=2025, month=6, day=4).strftime("%Y-%m-%d")
        self.cl.get_weather_data = MagicMock()
        self.cl.get_weather_data.return_value = True
        self.cl.weather_data = {
            "low_clouds_data": [0.8, 0.8, 0.115, 0.164]
        }

        status = self.cl._check_weather("0.000", "0.000", test_date)

        self.cl.get_weather_data.assert_called_once_with("0.000", "0.000",
                                                         test_date)
        self.assertFalse(self.cl.not_cloudy)
        self.assertTrue(status)

    def test_check_weather_cloudy(self):
        test_date = datetime(year=2025, month=6, day=4).strftime("%Y-%m-%d")
        self.cl.get_weather_data = MagicMock()
        self.cl.get_weather_data.return_value = True
        self.cl.weather_data = {
            "low_clouds_data": [0.8, 0.8, 0.8, 0.115, 0.164]
        }

        status = self.cl._check_weather("0.000", "0.000", test_date)

        self.cl.get_weather_data.assert_called_once_with("0.000", "0.000",
                                                         test_date)
        self.assertFalse(self.cl.not_cloudy)
        self.assertTrue(status)

    def test_get_daily_judge_factors_no_plant(self):
        status = self.cl._get_daily_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("No plant info available", stdout)
        self.assertFalse(status)

    def test_get_daily_judge_factors_check_weather_fail(self):
        self.cl._check_weather = MagicMock()
        self.cl._check_weather.return_value = False
        self.cl.plant = {"latitude": "0.0000", "longitude": "10.0000"}
        # The source resolves the business date in the market timezone,
        # so the expectation must too.
        date = datetime.now(tz=timezone.utc).astimezone(
            MARKET_TIMEZONE
        ).strftime("%Y-%m-%d")

        status = self.cl._get_daily_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("Failed to check weather", stdout)
        self.cl._check_weather.assert_called_once_with("0.0000", "10.0000",
                                                       date)
        self.assertFalse(status)

    def test_get_daily_judge_factors_get_pse_data_fail(self):
        self.cl._check_weather = MagicMock()
        self.cl._check_weather.return_value = True
        self.cl.get_pse_data = MagicMock()
        self.cl.get_pse_data.return_value = False
        self.cl.plant = {"latitude": "0.0000", "longitude": "10.0000"}
        # The source resolves the business date in the market timezone,
        # so the expectation must too.
        date = datetime.now(tz=timezone.utc).astimezone(
            MARKET_TIMEZONE
        ).strftime("%Y-%m-%d")
        self.cl.not_cloudy = False

        status = self.cl._get_daily_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("Failed to get RCE prices", stdout)
        self.cl._check_weather.assert_called_once_with("0.0000", "10.0000",
                                                       date)
        self.cl.get_pse_data.assert_called_once_with(date)
        self.assertFalse(status)

    def test_get_daily_judge_factors_pass(self):
        self.cl._check_weather = MagicMock()
        self.cl._check_weather.return_value = True
        self.cl.get_pse_data = MagicMock()
        self.cl.get_pse_data.return_value = True
        self.cl.plant = {"latitude": "0.0000", "longitude": "10.0000"}
        # The source resolves the business date in the market timezone,
        # so the expectation must too.
        date = datetime.now(tz=timezone.utc).astimezone(
            MARKET_TIMEZONE
        ).strftime("%Y-%m-%d")
        self.cl.not_cloudy = False
        expected_timestamp = datetime(
            year=2025,
            month=5,
            day=14,
            hour=2,
            minute=45,
            second=0,
            microsecond=0,
            tzinfo=ZoneInfo("Europe/Warsaw")
        ).timestamp()
        self.cl.rce_prices = {
            expected_timestamp - 9000: 439.58,
            expected_timestamp - 4500: 449.58,
            expected_timestamp: 59.58,
        }

        status = self.cl._get_daily_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("Successfully obtained judge factors", stdout)
        self.cl._check_weather.assert_called_once_with("0.0000", "10.0000",
                                                       date)
        self.cl.get_pse_data.assert_called_once_with(date)
        self.assertTrue(status)
        self.assertEqual(self.cl.min_price, 59.58)
        self.assertEqual(self.cl.min_price_timestamp, expected_timestamp)

    def _setup_current_judge_factors(self):
        """
        Configure the common state and mocks used by the
        _get_current_judge_factors tests: a valid token, weather data, RCE
        prices, and stubbed helpers. Individual tests override pieces as
        needed.
        """
        self.cl.token_ttl = (
            datetime.now() + timedelta(minutes=30)
        ).timestamp()
        self.cl.weather_data = {
            "sunrise_time": (datetime.now() - timedelta(hours=3)).timestamp(),
            "sunset_time": (datetime.now() + timedelta(hours=3)).timestamp(),
            "first_sample_time": 0,
            "interval": 3600,
            "low_clouds_data": [0.1],
        }
        self.cl.weather_data["sunrise_tomorrow_time"] = (
            datetime.now() + timedelta(hours=18)
        )
        self.cl.rce_prices = {123456: 250.0}
        self.cl.get_timestamp_quarter = MagicMock(return_value=123456)
        self.cl._check_current_weather = MagicMock(return_value=True)
        self.cl.get_current_miner_profitability = MagicMock(return_value=True)
        self.cl.profitability = 1.5

    def test_get_current_judge_factors_no_weather_data(self):
        status = self.cl._get_current_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("No weather data available!", stdout)
        self.assertFalse(status)

    def test_get_current_judge_factors_no_rce_prices(self):
        self.cl.weather_data = {}

        status = self.cl._get_current_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("No RCE prices available!", stdout)
        self.assertFalse(status)

    def test_get_current_judge_factors_reauthorization_failed(self):
        self._setup_current_judge_factors()
        self.cl.token_ttl = (
            datetime.now() - timedelta(minutes=30)
        ).timestamp()
        self.cl.login_shine = MagicMock(return_value=False)

        status = self.cl._get_current_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("Authorization token has expired", stdout)
        self.cl.login_shine.assert_called_once()
        self.assertFalse(status)

    def test_get_current_judge_factors_check_weather_fail(self):
        self._setup_current_judge_factors()
        self.cl._check_current_weather = MagicMock(return_value=False)

        status = self.cl._get_current_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("Checking current weather failed!", stdout)
        self.assertFalse(status)

    def test_get_current_judge_factors_uses_market_quarter(self):
        self._setup_current_judge_factors()
        # A fixed absolute instant: 12:20 UTC == 14:20 in the market timezone,
        # so the quarter in effect starts at 14:15 market time.
        instant = datetime(2025, 6, 16, 12, 20, tzinfo=timezone.utc)
        quarter_ts = int(
            datetime(2025, 6, 16, 14, 15,
                     tzinfo=MARKET_TIMEZONE).timestamp()
        )
        self.cl.rce_prices = {quarter_ts: 400.0}
        self.cl.get_timestamp_quarter = self.cl.__class__.\
            get_timestamp_quarter.__get__(self.cl)
        # Anchor every clock-derived value to the test instant so the result
        # does not depend on the real date. Without this the token would look
        # expired and trigger a real login attempt.
        self.cl.token_ttl = (instant + timedelta(hours=1)).timestamp()
        self.cl.login_shine = MagicMock(return_value=True)
        self.cl.weather_data["sunrise_time"] = (
            instant - timedelta(hours=3)
        ).timestamp()
        self.cl.weather_data["sunset_time"] = (
            instant + timedelta(hours=3)
        ).timestamp()

        class FakeDatetime:
            @staticmethod
            def now(tz=None):
                if tz:
                    return instant.astimezone(tz)
                return instant.astimezone().replace(tzinfo=None)

        with patch("optimshine.optim_shine.datetime", FakeDatetime):
            status = self.cl._get_current_judge_factors()

        self.assertTrue(status)
        self.assertEqual(self.cl.current_rce_price, 0.4)

    def test_get_daily_judge_factors_uses_market_date(self):
        self.cl._check_weather = MagicMock(return_value=True)
        self.cl.get_pse_data = MagicMock(return_value=True)
        self.cl.plant = {"latitude": "0.0000", "longitude": "10.0000"}
        self.cl.not_cloudy = False
        # More than one price so the min_price scan sets min_price_timestamp.
        self.cl.rce_prices = {123456: 250.0, 124356: 100.0}
        # 22:30 UTC on 16 June is already 00:30 on 17 June in the market
        # timezone, so the business date must be the 17th even though a host
        # in UTC or further west still reads the 16th locally.
        instant = datetime(2025, 6, 16, 22, 30, tzinfo=timezone.utc)

        class FakeDatetime:
            @staticmethod
            def now(tz=None):
                if tz:
                    return instant.astimezone(tz)
                return instant.astimezone().replace(tzinfo=None)

        with patch("optimshine.optim_shine.datetime", FakeDatetime):
            status = self.cl._get_daily_judge_factors()

        self.assertTrue(status)
        self.cl.get_pse_data.assert_called_once_with("2025-06-17")

    def test_get_current_judge_factors_rce_quarter_missing(self):
        self._setup_current_judge_factors()
        self.cl.rce_prices = {999999: 250.0}

        status = self.cl._get_current_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("Current quarter not found in RCE prices", stdout)
        self.assertFalse(status)

    def test_get_current_judge_factors_profitability_fail(self):
        self._setup_current_judge_factors()
        self.cl.get_current_miner_profitability = MagicMock(return_value=False)

        status = self.cl._get_current_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("Getting miner profitability failed", stdout)
        self.assertFalse(status)

    def test_get_current_judge_factors_night_pass(self):
        self._setup_current_judge_factors()
        # Force the night branch: sunrise in the future.
        self.cl.weather_data["sunrise_time"] = (
            datetime.now() + timedelta(hours=1)
        ).timestamp()

        status = self.cl._get_current_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("Successfully obtained current judge factors", stdout)
        self.assertTrue(status)
        self.assertTrue(self.cl.if_night)
        self.cl._check_current_weather.assert_not_called()
        self.assertEqual(self.cl.current_rce_price, 0.25)
        self.assertEqual(
            self.cl.miner_profitability,
            {"Eco": 1.5, "Standard": 1.5, "Super": 1.5},
        )

    def test_get_current_judge_factors_day_pass(self):
        self._setup_current_judge_factors()

        status = self.cl._get_current_judge_factors()

        stdout = self.stdio.getvalue()
        self.assertIn("Successfully obtained current judge factors", stdout)
        self.assertTrue(status)
        self.assertFalse(self.cl.if_night)
        self.cl._check_current_weather.assert_called_once()
        self.assertEqual(self.cl.current_rce_price, 0.25)
        self.assertEqual(
            self.cl.get_current_miner_profitability.call_count, 3
        )

    def test_check_current_weather_no_weather_data(self):
        status = self.cl._check_current_weather("2025-06-04", "10:00:00 AM")

        stdout = self.stdio.getvalue()
        self.assertIn("No weather data available!", stdout)
        self.assertFalse(status)

    def test_check_current_weather_sample_out_of_range(self):
        self.cl.weather_data = {
            "first_sample_time": 0,
            "interval": 3600,
            "low_clouds_data": [0.1],
        }
        self.cl.get_timestamp_hour = MagicMock(return_value=7200)

        status = self.cl._check_current_weather("2025-06-04", "10:00:00 AM")

        stdout = self.stdio.getvalue()
        # The message reports the offending sample number.
        self.assertIn("Sample number 2 out of range", stdout)
        self.assertFalse(status)

    def test_check_current_weather_sample_before_range(self):
        # An hour before the forecast starts yields a negative sample number.
        # Indexing with it would read from the end of the list, so the last
        # sample is made cloudy to prove that value is not used.
        self.cl.weather_data = {
            "first_sample_time": 86400,
            "interval": 3600,
            "low_clouds_data": [0.1, 0.1, 0.95],
        }
        self.cl.get_timestamp_hour = MagicMock(return_value=86400 - 3600)

        status = self.cl._check_current_weather("2025-06-16", "12:00:00 PM")

        stdout = self.stdio.getvalue()
        self.assertIn("Sample number -1 out of range", stdout)
        self.assertFalse(status)
        self.assertFalse(self.cl.cloudy_now)

    def test_check_current_weather_sample_far_before_range(self):
        self.cl.weather_data = {
            "first_sample_time": 86400,
            "interval": 3600,
            "low_clouds_data": [0.95, 0.95, 0.95],
        }
        self.cl.get_timestamp_hour = MagicMock(return_value=0)

        status = self.cl._check_current_weather("2025-06-16", "12:00:00 PM")

        stdout = self.stdio.getvalue()
        self.assertIn("out of range", stdout)
        self.assertFalse(status)
        self.assertFalse(self.cl.cloudy_now)

    def test_check_current_weather_first_sample_in_range(self):
        # The lower bound itself is valid.
        self.cl.weather_data = {
            "first_sample_time": 86400,
            "interval": 3600,
            "low_clouds_data": [0.9, 0.1],
        }
        self.cl.get_timestamp_hour = MagicMock(return_value=86400)

        status = self.cl._check_current_weather("2025-06-16", "12:00:00 PM")

        self.assertTrue(status)
        self.assertTrue(self.cl.cloudy_now)

    def test_check_current_weather_cloudy(self):
        self.cl.weather_data = {
            "first_sample_time": 0,
            "interval": 3600,
            "low_clouds_data": [0.1, 0.9],
        }
        self.cl.get_timestamp_hour = MagicMock(return_value=3600)

        status = self.cl._check_current_weather("2025-06-04", "10:00:00 AM")

        self.assertTrue(status)
        self.assertTrue(self.cl.cloudy_now)

    def test_check_current_weather_not_cloudy(self):
        self.cl.weather_data = {
            "first_sample_time": 0,
            "interval": 3600,
            "low_clouds_data": [0.1, 0.9],
        }
        self.cl.get_timestamp_hour = MagicMock(return_value=0)

        status = self.cl._check_current_weather("2025-06-04", "10:00:00 AM")

        self.assertTrue(status)
        self.assertFalse(self.cl.cloudy_now)

    def test_get_inverter_judge_factors_get_soc_fail(self):
        self.cl.get_device_value = MagicMock(return_value=False)

        soc, pv = self.cl._get_inverter_judge_factors("INV")

        stdout = self.stdio.getvalue()
        self.assertIn("Getting battery state of charge failed", stdout)
        self.cl.get_device_value.assert_called_once_with("INV", "battery_soc")
        self.assertIsNone(soc)
        self.assertIsNone(pv)

    def test_get_inverter_judge_factors_get_pv_fail(self):
        self.cl.get_device_value = MagicMock(side_effect=[True, False])
        self.cl.device_value = 55

        soc, pv = self.cl._get_inverter_judge_factors("INV")

        stdout = self.stdio.getvalue()
        self.assertIn("Getting PV production failed", stdout)
        self.cl.get_device_value.assert_has_calls([
            call("INV", "battery_soc"),
            call("INV", "pv_power"),
        ])
        self.assertIsNone(soc)
        self.assertIsNone(pv)

    def test_get_inverter_judge_factors_night_pass(self):
        def _device_value(_inv, _name):
            self.cl.device_value = 41.0
            return True

        self.cl.get_device_value = MagicMock(side_effect=_device_value)

        soc, pv = self.cl._get_inverter_judge_factors("INV", night=True)

        stdout = self.stdio.getvalue()
        self.assertIn("It's night. Omitting PV production", stdout)
        self.cl.get_device_value.assert_called_once_with("INV", "battery_soc")
        self.assertEqual(soc, 41.0)
        self.assertIsNone(pv)

    def test_get_inverter_judge_factors_day_pass(self):
        soc_pv = iter([41.0, 1543.0])

        def _device_value(_inv, _name):
            self.cl.device_value = next(soc_pv)
            return True

        self.cl.get_device_value = MagicMock(side_effect=_device_value)

        soc, pv = self.cl._get_inverter_judge_factors("INV")

        self.cl.get_device_value.assert_has_calls([
            call("INV", "battery_soc"),
            call("INV", "pv_power"),
        ])
        self.assertEqual(soc, 41.0)
        self.assertEqual(pv, 1543.0)

    def test_compare_miner_to_pse_no_price(self):
        self.cl.current_rce_price = None

        mode = self.cl._compare_miner_to_pse()

        stdout = self.stdio.getvalue()
        self.assertIn("No current PSE price available!", stdout)
        self.assertIsNone(mode)

    def test_compare_miner_to_pse_missing_price_attribute(self):
        mode = self.cl._compare_miner_to_pse()

        stdout = self.stdio.getvalue()
        self.assertIn("No current PSE price available!", stdout)
        self.assertIsNone(mode)

    def test_compare_miner_to_pse_missing_profitability(self):
        self.cl.current_rce_price = 0.25

        mode = self.cl._compare_miner_to_pse()

        stdout = self.stdio.getvalue()
        self.assertIn("No miner profitability available!", stdout)
        self.assertIsNone(mode)

    def test_compare_miner_to_pse_empty_profitability(self):
        self.cl.current_rce_price = 0.25
        self.cl.miner_profitability = {}

        mode = self.cl._compare_miner_to_pse()

        stdout = self.stdio.getvalue()
        self.assertIn("No miner profitability available!", stdout)
        self.assertIsNone(mode)

    def test_compare_miner_to_pse_does_not_recompute(self):
        self.cl.current_rce_price = 0.3
        self.cl.miner_profitability = {"Eco": 0.2, "Standard": 0.5,
                                       "Super": 0.9}
        self.cl.get_current_miner_profitability = MagicMock(return_value=True)

        mode = self.cl._compare_miner_to_pse()

        # The figures gathered by _get_current_judge_factors are reused, so no
        # profitability is recomputed here.
        self.cl.get_current_miner_profitability.assert_not_called()
        self.assertEqual(mode, "Standard")

    def test_compare_miner_to_pse_price_wins(self):
        self.cl.current_rce_price = 1.0
        self.cl.miner_profitability = {"Eco": 0.2, "Standard": 0.5,
                                       "Super": 0.9}

        mode = self.cl._compare_miner_to_pse()

        stdout = self.stdio.getvalue()
        self.assertIn("PSE price is more profitable", stdout)
        self.assertEqual(mode, "pse")

    def test_compare_miner_to_pse_least_profitable_mode_wins(self):
        self.cl.current_rce_price = 0.3
        self.cl.miner_profitability = {"Eco": 0.2, "Standard": 0.5,
                                       "Super": 0.9}

        mode = self.cl._compare_miner_to_pse()

        stdout = self.stdio.getvalue()
        self.assertIn("Miner is more profitable in 'Standard' mode", stdout)
        self.assertEqual(mode, "Standard")

    def test_compare_miner_to_pse_all_modes_beat_price(self):
        self.cl.current_rce_price = 0.1
        self.cl.miner_profitability = {"Eco": 0.2, "Standard": 0.5,
                                       "Super": 0.9}

        mode = self.cl._compare_miner_to_pse()

        self.assertEqual(mode, "Eco")

    def test_compare_miner_to_pse_equal_price_sells(self):
        self.cl.current_rce_price = 0.9
        self.cl.miner_profitability = {"Eco": 0.2, "Standard": 0.5,
                                       "Super": 0.9}

        mode = self.cl._compare_miner_to_pse()

        self.assertEqual(mode, "pse")

    def test_judge_factors_feed_compare_miner_to_pse(self):
        # End to end over the two methods: _get_current_judge_factors gathers
        # the profitability figures and _compare_miner_to_pse consumes them,
        # without either being mocked out.
        self._setup_current_judge_factors()
        profits = {"Eco": 0.2, "Standard": 0.5, "Super": 0.9}

        def _profitability(mode):
            self.cl.profitability = profits[mode]
            return True

        self.cl.get_current_miner_profitability = MagicMock(
            side_effect=_profitability
        )

        self.assertTrue(self.cl._get_current_judge_factors())
        # rce_prices holds 250.0, which the source scales to 0.25 PLN/kWh.
        self.assertEqual(self.cl.current_rce_price, 0.25)
        self.assertEqual(self.cl.miner_profitability, profits)

        # Each mode is computed exactly once, by the judge factors.
        self.assertEqual(
            self.cl.get_current_miner_profitability.call_count, 3
        )

        mode = self.cl._compare_miner_to_pse()

        self.assertEqual(mode, "Standard")
        # Still three: the comparison reused the gathered figures.
        self.assertEqual(
            self.cl.get_current_miner_profitability.call_count, 3
        )

    def test_select_miner_mode_no_price(self):
        self.cl.miner_profitability = {"Eco": 0.5}

        mode = self.cl._select_miner_mode(5000)

        stdout = self.stdio.getvalue()
        self.assertIn("No current PSE price available!", stdout)
        self.assertIsNone(mode)

    def test_select_miner_mode_no_profitability(self):
        self.cl.current_rce_price = 0.25

        mode = self.cl._select_miner_mode(5000)

        stdout = self.stdio.getvalue()
        self.assertIn("No miner profitability available!", stdout)
        self.assertIsNone(mode)

    def test_select_miner_mode_price_beats_every_mode(self):
        self.cl.current_rce_price = 1.0
        self.cl.miner_profitability = {"Eco": 0.34, "Standard": 0.28,
                                       "Super": 0.27}

        mode = self.cl._select_miner_mode(5000)

        stdout = self.stdio.getvalue()
        self.assertIn("PSE price is more profitable", stdout)
        self.assertEqual(mode, "pse")

    def test_select_miner_mode_picks_least_profitable_feasible(self):
        # All three beat the price and PV covers all three. Profitability falls
        # as consumption rises, so the least profitable feasible mode is Super.
        self.cl.current_rce_price = 0.1
        self.cl.miner_profitability = {"Eco": 0.34, "Standard": 0.28,
                                       "Super": 0.27}

        mode = self.cl._select_miner_mode(
            WORKMODE_POWER_CONSUMPTION["Super"] + 500
        )

        self.assertEqual(mode, "Super")

    def test_select_miner_mode_rejects_unprofitable_covered_mode(self):
        # The regression this method exists for: PV covers Super, but only Eco
        # beats the grid price. Selecting on PV coverage alone would mine in
        # Super at a loss.
        self.cl.current_rce_price = 0.30
        self.cl.miner_profitability = {"Eco": 0.34, "Standard": 0.28,
                                       "Super": 0.27}

        mode = self.cl._select_miner_mode(
            WORKMODE_POWER_CONSUMPTION["Super"] + 500
        )

        self.assertEqual(mode, "Eco")

    def test_select_miner_mode_profitable_but_pv_too_low(self):
        # Eco is the only profitable mode and the PV production cannot even
        # cover it, so nothing should run.
        self.cl.current_rce_price = 0.30
        self.cl.miner_profitability = {"Eco": 0.34, "Standard": 0.28,
                                       "Super": 0.27}

        mode = self.cl._select_miner_mode(
            WORKMODE_POWER_CONSUMPTION["Eco"] - 1
        )

        stdout = self.stdio.getvalue()
        self.assertIn(
            "PV production is too low for any profitable miner mode", stdout
        )
        self.assertEqual(mode, "TOO_LOW")

    def test_select_miner_mode_prefers_larger_when_both_feasible(self):
        # Eco and Standard both beat the price and both fit; Standard is the
        # less profitable of the two, so it is chosen.
        self.cl.current_rce_price = 0.275
        self.cl.miner_profitability = {"Eco": 0.34, "Standard": 0.28,
                                       "Super": 0.27}

        mode = self.cl._select_miner_mode(
            WORKMODE_POWER_CONSUMPTION["Super"] + 500
        )

        self.assertEqual(mode, "Standard")

    def test_select_miner_mode_equal_price_is_not_profitable(self):
        # Strictly greater than the price is required.
        self.cl.current_rce_price = 0.34
        self.cl.miner_profitability = {"Eco": 0.34, "Standard": 0.28,
                                       "Super": 0.27}

        mode = self.cl._select_miner_mode(100000)

        self.assertEqual(mode, "pse")

    def test_compare_miner_to_pv_prod_too_low(self):
        mode = self.cl._compare_miner_to_pv_prod(0.5)

        stdout = self.stdio.getvalue()
        self.assertIn("PV production is too low for any miner mode", stdout)
        self.assertEqual(mode, "TOO_LOW")

    def test_compare_miner_to_pv_prod_eco(self):
        mode = self.cl._compare_miner_to_pv_prod(
            WORKMODE_POWER_CONSUMPTION["Eco"]
        )

        stdout = self.stdio.getvalue()
        self.assertIn("PV production covers 'Eco' mode", stdout)
        self.assertEqual(mode, "Eco")

    def test_compare_miner_to_pv_prod_standard(self):
        mode = self.cl._compare_miner_to_pv_prod(
            WORKMODE_POWER_CONSUMPTION["Super"] - 0.1
        )

        self.assertEqual(mode, "Standard")

    def test_compare_miner_to_pv_prod_super(self):
        mode = self.cl._compare_miner_to_pv_prod(
            WORKMODE_POWER_CONSUMPTION["Super"] + 100
        )

        self.assertEqual(mode, "Super")

    def test_optim_charge_battery_reauthorization_failed(self):
        token_ttl_date = datetime.now() - timedelta(minutes=30)
        self.cl.token_ttl = token_ttl_date.timestamp()
        self.cl.login_shine = MagicMock()
        self.cl.login_shine.return_value = False
        with self.assertRaises(RuntimeError):
            self.cl.optim_charge_battery("INV", "test_mode")

        stdout = self.stdio.getvalue()
        self.assertIn("Authorization token has expired. Failed to login",
                      stdout)
        self.cl.login_shine.assert_called_once()

    def test_optim_charge_battery_wrong_mode(self):
        token_ttl_date = datetime.now() + timedelta(minutes=30)
        self.cl.token_ttl = token_ttl_date.timestamp()

        with self.assertRaises(AttributeError):
            self.cl.optim_charge_battery("INV", "test_mode")

        stdout = self.stdio.getvalue()
        self.assertIn("test_mode charge mode unknown", stdout)

    def test_optim_charge_battery_get_setting_value_failed(self):
        token_ttl_date = datetime.now() + timedelta(minutes=30)
        self.cl.token_ttl = token_ttl_date.timestamp()
        self.cl.get_setting_value = MagicMock()
        self.cl.get_setting_value.return_value = False

        with self.assertRaises(RuntimeError):
            self.cl.optim_charge_battery("INV", "normal_charge")

        stdout = self.stdio.getvalue()
        self.assertIn("Getting battery charge current failed", stdout)
        self.cl.get_setting_value.assert_called_once_with(
            "INV",
            "battery_charge_current"
        )

    def test_optim_charge_battery_same_value_pass(self):
        token_ttl_date = datetime.now() + timedelta(minutes=30)
        self.cl.token_ttl = token_ttl_date.timestamp()
        self.cl.get_setting_value = MagicMock()
        self.cl.get_setting_value.return_value = True
        self.cl.setting_value = 600

        status = self.cl.optim_charge_battery("INV", "normal_charge")

        stdout = self.stdio.getvalue()
        self.assertIn("Correct charge current value is already set", stdout)
        self.cl.get_setting_value.assert_called_once_with(
            "INV",
            "battery_charge_current"
        )
        self.assertTrue(status)

    def test_optim_charge_battery_set_charge_current_failed(self):
        token_ttl_date = datetime.now() + timedelta(minutes=30)
        self.cl.token_ttl = token_ttl_date.timestamp()
        self.cl.get_setting_value = MagicMock()
        self.cl.get_setting_value.return_value = True
        self.cl.setting_value = 10
        self.cl.set_charge_current = MagicMock()
        self.cl.set_charge_current.return_value = False

        with self.assertRaises(RuntimeError):
            self.cl.optim_charge_battery("INV", "normal_charge")

        stdout = self.stdio.getvalue()
        self.assertIn("Failed to set battery charge current", stdout)
        self.cl.get_setting_value.assert_called_once_with(
            "INV",
            "battery_charge_current"
        )
        self.cl.set_charge_current.assert_called_once_with("INV", 60)

    def test_optim_charge_battery_get_setting_value_validation_failed(self):
        token_ttl_date = datetime.now() + timedelta(minutes=30)
        self.cl.token_ttl = token_ttl_date.timestamp()
        self.cl.get_setting_value = MagicMock()
        self.cl.get_setting_value.side_effect = [True, False]
        self.cl.setting_value = 10
        self.cl.set_charge_current = MagicMock()
        self.cl.set_charge_current.return_value = True

        with self.assertRaises(RuntimeError):
            self.cl.optim_charge_battery("INV", "normal_charge")

        stdout = self.stdio.getvalue()
        self.assertIn("failed (Validation)", stdout)
        self.cl.get_setting_value.assert_has_calls([
            call("INV", "battery_charge_current"),
            call("INV", "battery_charge_current"),
        ])
        self.cl.set_charge_current.assert_called_once_with("INV", 60)

    def side_effect_set_charge_current_10(self, _, __):
        self.cl.setting_value = 100
        return True

    def side_effect_set_charge_current_60(self, _, __):
        self.cl.setting_value = 600
        return True

    def test_optim_charge_battery_wrong_value_afeter_set(self):
        token_ttl_date = datetime.now() + timedelta(minutes=30)
        self.cl.token_ttl = token_ttl_date.timestamp()
        self.cl.get_setting_value = MagicMock()
        self.cl.get_setting_value.return_value = True
        self.cl.setting_value = 10
        self.cl.set_charge_current = MagicMock()
        self.cl.set_charge_current.side_effect = (
            self.side_effect_set_charge_current_10
        )

        with self.assertRaises(RuntimeError):
            self.cl.optim_charge_battery("INV", "normal_charge")

        stdout = self.stdio.getvalue()
        self.assertIn("Wrong current value", stdout)
        self.cl.get_setting_value.assert_has_calls([
            call("INV", "battery_charge_current"),
            call("INV", "battery_charge_current"),
        ])
        self.cl.set_charge_current.assert_called_once_with("INV", 60)

    def test_optim_charge_battery_pass(self):
        token_ttl_date = datetime.now() + timedelta(minutes=30)
        self.cl.token_ttl = token_ttl_date.timestamp()
        self.cl.get_setting_value = MagicMock()
        self.cl.get_setting_value.return_value = True
        self.cl.setting_value = 10
        self.cl.set_charge_current = MagicMock()
        self.cl.set_charge_current.side_effect = (
            self.side_effect_set_charge_current_60
        )

        status = self.cl.optim_charge_battery("INV", "normal_charge")

        stdout = self.stdio.getvalue()
        self.assertIn("Battery charging optimization was successful", stdout)
        self.cl.get_setting_value.assert_has_calls([
            call("INV", "battery_charge_current"),
            call("INV", "battery_charge_current"),
        ])
        self.cl.set_charge_current.assert_called_once_with("INV", 60)
        self.assertTrue(status)

    def _setup_strategy(self):
        """
        Configure the common state and mocks used by the optim_strategy_day and
        optim_strategy_night tests: an inverter list, weather data, stubbed
        judge factors and stubbed miner/battery actions. Individual tests
        override pieces as needed.
        """
        self.cl.inverters = ["INV"]
        self.cl.not_cloudy = True
        self.cl.weather_data = {
            "sunrise_time": (datetime.now() - timedelta(hours=3)).timestamp(),
            "sunset_time": (datetime.now() + timedelta(hours=6)).timestamp(),
            "sunrise_tomorrow_time": datetime.now() + timedelta(hours=18),
        }
        self.cl.cloudy_now = False
        self.cl.current_rce_price = 0.25
        self.cl._get_current_judge_factors = MagicMock(return_value=True)
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(50.0, 2000.0)
        )
        self.cl.optim_charge_battery = MagicMock(return_value=True)
        self.cl.on = MagicMock(return_value=True)
        self.cl.off = MagicMock(return_value=True)
        self.cl.set_mode = MagicMock(return_value=True)
        # Jobs added to a stopped scheduler have no next run time, which
        # scheduler_list_jobs reads.
        self.cl.scheduler.start()

    def test_optim_strategy_night_no_inverters(self):
        with self.assertRaises(RuntimeError):
            self.cl.optim_strategy_night()

        stdout = self.stdio.getvalue()
        self.assertIn("No inverter list found", stdout)

    def test_optim_strategy_night_no_weather_data(self):
        self.cl.inverters = ["INV"]

        with self.assertRaises(RuntimeError):
            self.cl.optim_strategy_night()

        stdout = self.stdio.getvalue()
        self.assertIn("No weather data available", stdout)

    def test_optim_strategy_night_switch_to_day(self):
        self._setup_strategy()

        status = self.cl.optim_strategy_night()

        stdout = self.stdio.getvalue()
        job = self.cl.scheduler.get_job("optim_strategy_day")
        self.assertIn("It's day. Run day optimization.", stdout)
        self.assertIsNotNone(job)
        self.assertTrue(status)

    def test_optim_strategy_night_inverter_values_fail(self):
        self._setup_strategy()
        self.cl.weather_data["sunset_time"] = (
            datetime.now() - timedelta(hours=1)
        ).timestamp()
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(None, None)
        )

        with self.assertRaises(RuntimeError):
            self.cl.optim_strategy_night()

        stdout = self.stdio.getvalue()
        job = self.cl.scheduler.get_job("optim_strategy_night")
        self.assertIn("Failed to get inverter values", stdout)
        self.assertIsNotNone(job)

    def test_optim_strategy_night_low_battery(self):
        self._setup_strategy()
        self.cl.weather_data["sunset_time"] = (
            datetime.now() - timedelta(hours=1)
        ).timestamp()
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(35.0, None)
        )

        self.cl.optim_strategy_night()

        stdout = self.stdio.getvalue()
        self.assertIn("Battery state low.", stdout)
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()
        self.cl.set_mode.assert_not_called()

    @patch("optimshine.optim_shine.time")
    def test_optim_strategy_night_mining_eco(self, mock_time):
        self._setup_strategy()
        self.cl.weather_data["sunset_time"] = (
            datetime.now() - timedelta(hours=1)
        ).timestamp()
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(60.0, None)
        )

        self.cl.optim_strategy_night()

        stdout = self.stdio.getvalue()
        job = self.cl.scheduler.get_job("optim_strategy_night")
        self.assertIn("Mining in eco mode.", stdout)
        self.cl.on.assert_called_once()
        self.cl.set_mode.assert_called_once_with("Eco")
        self.cl.off.assert_not_called()
        mock_time.sleep.assert_called_once_with(20)
        self.assertIsNotNone(job)

    def test_optim_strategy_day_no_inverters(self):
        with self.assertRaises(RuntimeError):
            self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("No inverter list found", stdout)

    def test_optim_strategy_day_no_weather_data(self):
        self.cl.inverters = ["INV"]

        with self.assertRaises(RuntimeError):
            self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("No weather data available", stdout)

    def test_optim_strategy_day_no_daily_weather_info(self):
        self.cl.inverters = ["INV"]
        self.cl.weather_data = {}

        with self.assertRaises(RuntimeError):
            self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("No daily weather info", stdout)

    def test_optim_strategy_day_switch_to_night(self):
        self._setup_strategy()
        self.cl.weather_data["sunset_time"] = (
            datetime.now() - timedelta(hours=1)
        ).timestamp()

        status = self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        job = self.cl.scheduler.get_job("optim_strategy_night")
        self.assertIn("It's night. Run night optimization.", stdout)
        self.assertIsNotNone(job)
        self.assertTrue(status)

    def test_optim_strategy_day_judge_factors_fail(self):
        self._setup_strategy()
        self.cl._get_current_judge_factors = MagicMock(return_value=False)

        with self.assertRaises(RuntimeError):
            self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        job = self.cl.scheduler.get_job("optim_strategy_day")
        self.assertIn("Failed to get current judge factors", stdout)
        self.assertIsNotNone(job)

    def test_optim_strategy_day_inverter_values_fail(self):
        self._setup_strategy()
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(None, None)
        )

        with self.assertRaises(RuntimeError):
            self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        job = self.cl.scheduler.get_job("optim_strategy_day")
        self.assertIn("Failed to get inverter values", stdout)
        self.assertIsNotNone(job)

    @patch("optimshine.optim_shine.time")
    def test_optim_strategy_day_negative_price(self, mock_time):
        self._setup_strategy()
        self.cl.current_rce_price = -0.1

        status = self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        job = self.cl.scheduler.get_job("optim_strategy_day")
        self.assertIn("Negative energy price.", stdout)
        self.cl.optim_charge_battery.assert_called_once_with(
            "INV", "fast_charge"
        )
        self.cl.on.assert_called_once()
        self.cl.set_mode.assert_called_once_with("Super")
        mock_time.sleep.assert_called_once_with(20)
        self.assertIsNotNone(job)
        self.assertTrue(status)

    @patch("optimshine.optim_shine.time")
    def test_optim_strategy_day_negative_price_all_inverters(self, mock_time):
        self._setup_strategy()
        self.cl.inverters = ["INV1", "INV2", "INV3"]
        self.cl.current_rce_price = -0.1

        status = self.cl.optim_strategy_day()

        # Every battery is charged, not just the first one.
        self.cl.optim_charge_battery.assert_has_calls([
            call("INV1", "fast_charge"),
            call("INV2", "fast_charge"),
            call("INV3", "fast_charge"),
        ])
        self.assertEqual(self.cl.optim_charge_battery.call_count, 3)
        # The miner is a single shared device, so it is commanded once.
        self.cl.on.assert_called_once()
        self.cl.set_mode.assert_called_once_with("Super")
        mock_time.sleep.assert_called_once_with(20)
        self.assertIsNotNone(self.cl.scheduler.get_job("optim_strategy_day"))
        self.assertTrue(status)

    def test_optim_strategy_day_negative_price_skips_inverter_reads(self):
        self._setup_strategy()
        self.cl.inverters = ["INV1", "INV2"]
        self.cl.current_rce_price = -0.1

        with patch("optimshine.optim_shine.time"):
            self.assertTrue(self.cl.optim_strategy_day())

        # The decision needs no per-inverter readings, so none are taken.
        self.cl._get_inverter_judge_factors.assert_not_called()

    @patch("optimshine.optim_shine.time")
    def test_optim_strategy_day_skips_unprofitable_covered_mode(self,
                                                                mock_time):
        # End to end regression: PV covers Super but only Eco beats the grid
        # price, so the miner must run in Eco rather than the biggest covered
        # mode. _select_miner_mode is deliberately not mocked here.
        self._setup_strategy()
        self.cl.current_rce_price = 0.30
        self.cl.miner_profitability = {"Eco": 0.34, "Standard": 0.28,
                                       "Super": 0.27}
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(50.0, WORKMODE_POWER_CONSUMPTION["Super"] + 500)
        )

        self.cl.optim_strategy_day()

        self.cl.on.assert_called_once()
        self.cl.set_mode.assert_called_once_with("Eco")
        self.cl.off.assert_not_called()

    @patch("optimshine.optim_shine.time")
    def test_optim_strategy_day_sells_when_no_mode_profitable(self,
                                                              mock_time):
        # PV covers every mode, but none beats the grid price, so the miner
        # stays off and the energy is sold.
        self._setup_strategy()
        self.cl.current_rce_price = 0.50
        self.cl.miner_profitability = {"Eco": 0.34, "Standard": 0.28,
                                       "Super": 0.27}
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(50.0, WORKMODE_POWER_CONSUMPTION["Super"] + 500)
        )

        self.cl.optim_strategy_day()

        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()
        self.cl.set_mode.assert_not_called()

    def test_optim_strategy_day_cloudy_low_battery(self):
        self._setup_strategy()
        self.cl.cloudy_now = True
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(79.0, 2000.0)
        )

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Cloudy weather, low battery", stdout)
        self.cl.optim_charge_battery.assert_called_once_with(
            "INV", "fast_charge"
        )
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()

    def test_optim_strategy_day_cloudy_full_battery_sell(self):
        self._setup_strategy()
        self.cl.cloudy_now = True
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(85.0, 2000.0)
        )
        self.cl._select_miner_mode = MagicMock(return_value="pse")

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Cloudy weather, full battery", stdout)
        self.assertIn("Charging battery and selling energy", stdout)
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()

    def test_optim_strategy_day_cloudy_full_battery_pv_too_low(self):
        self._setup_strategy()
        self.cl.cloudy_now = True
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(85.0, 0.1)
        )
        self.cl._select_miner_mode = MagicMock(return_value="TOO_LOW")

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Too low production to mine", stdout)
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()

    @patch("optimshine.optim_shine.time")
    def test_optim_strategy_day_cloudy_full_battery_mining(self, mock_time):
        self._setup_strategy()
        self.cl.cloudy_now = True
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(85.0, 2000.0)
        )
        self.cl._select_miner_mode = MagicMock(return_value="Standard")

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Mining in Standard mode.", stdout)
        self.cl.on.assert_called_once()
        self.cl.set_mode.assert_called_once_with("Standard")
        self.cl.off.assert_not_called()
        mock_time.sleep.assert_called_once_with(20)

    def test_optim_strategy_day_sunny_low_battery(self):
        self._setup_strategy()
        self.cl._get_inverter_judge_factors = MagicMock(
            return_value=(34.0, 2000.0)
        )

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Sunny weather. Low battery.", stdout)
        self.cl.optim_charge_battery.assert_called_once_with(
            "INV", "fast_charge"
        )
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()

    def test_optim_strategy_day_sunny_high_price(self):
        self._setup_strategy()
        self.cl.current_rce_price = 0.7

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        # The message reports the price that triggered the branch.
        self.assertIn("Sunny weather. High PSE price: 0.7", stdout)
        self.cl.optim_charge_battery.assert_called_once_with(
            "INV", "no_charge"
        )
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()

    def test_optim_strategy_day_sunny_sell(self):
        self._setup_strategy()
        self.cl._select_miner_mode = MagicMock(return_value="pse")

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Charging battery and selling energy", stdout)
        self.cl.optim_charge_battery.assert_called_once_with(
            "INV", "slow_charge"
        )
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()

    def test_optim_strategy_day_sunny_pv_too_low(self):
        self._setup_strategy()
        self.cl._select_miner_mode = MagicMock(return_value="TOO_LOW")

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Too low production to mine", stdout)
        self.cl.optim_charge_battery.assert_called_once_with(
            "INV", "slow_charge"
        )
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()

    @patch("optimshine.optim_shine.time")
    def test_optim_strategy_day_sunny_mining(self, mock_time):
        self._setup_strategy()
        self.cl._select_miner_mode = MagicMock(return_value="Super")

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        job = self.cl.scheduler.get_job("optim_strategy_day")
        self.assertIn("Mining in Super mode", stdout)
        self.cl.optim_charge_battery.assert_called_once_with(
            "INV", "slow_charge"
        )
        self.cl.on.assert_called_once()
        self.cl.set_mode.assert_called_once_with("Super")
        self.cl.off.assert_not_called()
        mock_time.sleep.assert_called_once_with(20)
        self.assertIsNotNone(job)

    @patch("optimshine.optim_shine.time")
    def test_optim_strategy_day_almost_dark_mining(self, mock_time):
        self._setup_strategy()
        self.cl.weather_data["sunset_time"] = (
            datetime.now() + timedelta(hours=1)
        ).timestamp()
        self.cl._select_miner_mode = MagicMock(return_value="Eco")

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Almost dark", stdout)
        self.assertIn("Mining in Eco mode", stdout)
        self.cl.optim_charge_battery.assert_called_once_with(
            "INV", "fast_charge"
        )
        self.cl.on.assert_called_once()
        self.cl.set_mode.assert_called_once_with("Eco")
        mock_time.sleep.assert_called_once_with(20)

    def test_optim_strategy_day_almost_dark_sell(self):
        self._setup_strategy()
        self.cl.weather_data["sunset_time"] = (
            datetime.now() + timedelta(hours=1)
        ).timestamp()
        self.cl._select_miner_mode = MagicMock(return_value="pse")

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Almost dark", stdout)
        self.assertIn("Charging battery and selling energy", stdout)
        self.cl.optim_charge_battery.assert_called_once_with(
            "INV", "fast_charge"
        )
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()

    def test_optim_strategy_day_almost_dark_pv_too_low(self):
        self._setup_strategy()
        self.cl.weather_data["sunset_time"] = (
            datetime.now() + timedelta(hours=1)
        ).timestamp()
        self.cl._select_miner_mode = MagicMock(return_value="TOO_LOW")

        self.cl.optim_strategy_day()

        stdout = self.stdio.getvalue()
        self.assertIn("Too low production to mine", stdout)
        self.cl.off.assert_called_once()
        self.cl.on.assert_not_called()

    def test_optim_judge_get_daily_judge_factors_fail(self):
        self.cl.judge_date = datetime.now()
        self.cl._get_daily_judge_factors = MagicMock()
        self.cl._get_daily_judge_factors.return_value = False

        with self.assertRaises(RuntimeError):
            self.cl.optim_judge()

        job = self.cl.scheduler.get_job("optim_judge")

        stdout = self.stdio.getvalue()
        self.assertIn("Failed to get judge factors", stdout)
        self.assertIsNotNone(job)

    def _setup_judge(self, not_cloudy=True, sunset_hours=3):
        """
        Configure the common state and mocks used by the optim_judge tests: a
        judge date, stubbed daily judge factors, weather data and stubbed
        strategies.

        Args:
            not_cloudy (bool, optional): The daily weather flag.
                                         Defaults to True.
            sunset_hours (int, optional): How many hours from now the sun sets.
                                          Negative values put sunset in the
                                          past. Defaults to 3.
        """
        self.cl.judge_date = datetime.now()
        self.cl._get_daily_judge_factors = MagicMock(return_value=True)
        self.cl.optim_strategy_day = MagicMock(return_value=True)
        self.cl.optim_strategy_night = MagicMock(return_value=True)
        self.cl.not_cloudy = not_cloudy
        self.cl.weather_data = {
            "sunrise_time": (datetime.now() - timedelta(hours=3)).timestamp(),
            "sunset_time": (
                datetime.now() + timedelta(hours=sunset_hours)
            ).timestamp(),
            "sunrise_tomorrow_time": datetime.now() + timedelta(hours=18),
        }
        # Jobs added to a stopped scheduler have no next run time, which
        # scheduler_list_jobs reads.
        self.cl.scheduler.start()

    def test_optim_judge_sunny_day_strategy(self):
        self._setup_judge(not_cloudy=True)

        self.cl.optim_judge()

        stdout = self.stdio.getvalue()
        self.assertIn("It'll be sunny day", stdout)
        self.assertIsNotNone(self.cl.scheduler.get_job("optim_strategy_day"))
        self.assertIsNone(self.cl.scheduler.get_job("optim_strategy_night"))

    def test_optim_judge_cloudy_night_strategy(self):
        self._setup_judge(not_cloudy=False, sunset_hours=-3)

        self.cl.optim_judge()

        stdout = self.stdio.getvalue()
        self.assertIn("It'll be cloudy day", stdout)
        self.assertIsNotNone(self.cl.scheduler.get_job("optim_strategy_night"))
        self.assertIsNone(self.cl.scheduler.get_job("optim_strategy_day"))

    def test_optim_judge_schedules_tomorrow_judge(self):
        self._setup_judge()
        expected_judge_date = self.cl.weather_data["sunrise_tomorrow_time"]

        self.cl.optim_judge()

        job = self.cl.scheduler.get_job("optim_judge")

        stdout = self.stdio.getvalue()
        self.assertIn("Scheduling tomorrow's optimization judge", stdout)
        self.assertIn("List of jobs", stdout)
        self.assertIsNotNone(job)
        self.assertEqual(self.cl.judge_date, expected_judge_date)

    @patch("optimshine.optim_shine.datetime")
    def test_optim_main_schedules_judge(self, datetime_mock):
        self.cl._shine_setup = MagicMock()
        # Keep the scheduler inert. optim_main only needs to record the judge
        # date and exit; starting the real background thread would race with
        # teardown because the mocked clock puts the run date in the past.
        self.cl.scheduler = MagicMock()
        self.cl.scheduler.get_jobs.return_value = None
        time_now = datetime.now().replace(
            hour=3, minute=6, second=0, microsecond=0,
        ) + timedelta(days=1)
        datetime_mock.now.return_value = time_now

        expected_judge_date = (
            time_now.astimezone(ZoneInfo("UTC")) + timedelta(minutes=1)
        )

        with self.assertRaises(SystemExit) as test_exit:
            self.cl.optim_main()

        stdout = self.stdio.getvalue()
        self.assertIn(
            "Scheduling optimization judge to "
            f"{expected_judge_date.astimezone().strftime('%d-%m-%Y %H:%M')}",
            stdout
        )
        self.assertIn("No jobs scheduled. Exiting...", stdout)
        self.cl._shine_setup.assert_called_once()
        self.assertEqual(expected_judge_date, self.cl.judge_date)
        self.assertEqual(test_exit.exception.code, 1)

    @patch("optimshine.optim_shine.time")
    @patch("optimshine.optim_shine.datetime")
    def test_optim_main_loop(self, datetime_mock, mock_time):
        self.cl._shine_setup = MagicMock()
        # Inert scheduler: see test_optim_main_schedules_judge.
        self.cl.scheduler = MagicMock()
        self.cl.scheduler.get_jobs.side_effect = [True, None]
        self.cl.notifier.notify = MagicMock()
        time_now = datetime.now().replace(
            hour=7, minute=6, second=0, microsecond=0,
        ) + timedelta(days=1)
        datetime_mock.now.return_value = time_now

        expected_judge_date = (
            time_now.astimezone(ZoneInfo("UTC")) + timedelta(minutes=1)
        )

        with self.assertRaises(SystemExit):
            self.cl.optim_main()

        stdout = self.stdio.getvalue()
        self.assertIn(
            "Scheduling optimization judge to "
            f"{expected_judge_date.astimezone().strftime('%d-%m-%Y %H:%M')}",
            stdout
        )
        self.assertEqual(expected_judge_date, self.cl.judge_date)
        self.cl.notifier.notify.assert_called_once_with("WATCHDOG=1")
        mock_time.sleep.assert_called_once_with(5)


if __name__ == "__main__":
    unittest.main()
