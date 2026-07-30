#!/usr/bin/env python
#
# Copyright 2025 Norbert Kamiński <norbert.kaminski@xarium.world>
#
# SPDX-License-Identifier: LGPL-3.0-or-later
#

import io
import logging
import unittest

import optimshine.api_weather as api
import optimshine.optim_config as config
import tests.test_api_weather_data as api_data

from datetime import datetime
from optimshine.api_common import MARKET_TIMEZONE
from unittest.mock import patch
from zoneinfo import ZoneInfo

# _get_solar_sunrise_sunset_time normally sets this attribute. The tests that
# mock it out have to provide it themselves.
SUNRISE_TOMORROW = datetime(
    2025, 5, 21, 2, 29, 57, tzinfo=ZoneInfo("UTC")
).astimezone()


class TestPseApi(unittest.TestCase):
    def setUp(self):
        cls_optim_config = config.OptimConfig()
        cls_optim_config.logger_setup()
        self.log = cls_optim_config.log
        cls_optim_config.envs_setup("tests/.testenv")

    def tearDown(self):
        self.log.handlers.clear()

    def test_get_timestamp_hour(self):
        cls_api_weather = api.ApiWeather(self.log)
        timestamp = cls_api_weather.get_timestamp_hour("2025-04-14",
                                                       "2:29:54 AM")

        self.assertEqual(timestamp, 1744596000)

    def test_get_timestamp_quarter(self):
        cls_api_weather = api.ApiWeather(self.log)

        # The date and time are resolved in the market timezone, not the
        # host's, because the result indexes RCE prices whose quarters are
        # settled on market local time.
        for time, minute in (
            ("2:00:00 AM", 0),
            ("2:14:59 AM", 0),
            ("2:15:00 AM", 15),
            ("2:29:54 AM", 15),
            ("2:30:00 AM", 30),
            ("2:44:59 AM", 30),
            ("2:45:00 AM", 45),
            ("2:59:59 AM", 45),
        ):
            with self.subTest(time=time):
                expected = int(
                    datetime(2025, 4, 14, 2, minute,
                             tzinfo=MARKET_TIMEZONE).timestamp()
                )
                self.assertEqual(
                    cls_api_weather.get_timestamp_quarter("2025-04-14", time),
                    expected
                )

    def test_get_timestamp_quarter_is_host_timezone_independent(self):
        cls_api_weather = api.ApiWeather(self.log)

        # A fixed market wall clock must always map to the same instant,
        # whatever timezone the host is configured for.
        expected = int(
            datetime(2025, 4, 14, 14, 15,
                     tzinfo=MARKET_TIMEZONE).timestamp()
        )

        self.assertEqual(
            cls_api_weather.get_timestamp_quarter("2025-04-14",
                                                  "2:20:00 PM"),
            expected
        )

    def test_get_timestamp_quarter_is_divisible_by_quarter(self):
        cls_api_weather = api.ApiWeather(self.log)

        timestamp = cls_api_weather.get_timestamp_quarter("2025-04-14",
                                                          "2:29:54 AM")

        self.assertEqual(timestamp % 900, 0)

    @patch("optimshine.api_common.ApiCommon.api_get_request")
    def test_get_solar_sunrise_sunset_time_none_response(self,
                                                         mock_api_get_request):
        stdio = io.StringIO()
        mock_api_get_request.return_value = None

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        status = cls_api_weather._get_solar_sunrise_sunset_time(
            "36.7201600",
            "-33.86882",
            "2025-04-14"
        )
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Getting today sunrise/sunset data failed!", stdout)

    @patch("optimshine.api_common.ApiCommon.api_get_request")
    def test_get_solar_sunrise_sunset_time_wrong_response(
        self,
        mock_api_get_request
    ):
        stdio = io.StringIO()
        mock_api_get_request.return_value = {"data": "test issue"}

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        status = cls_api_weather._get_solar_sunrise_sunset_time(
            "36.7201600",
            "-33.86882",
            "2025-04-14"
        )
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Getting weather data failed. {'data': 'test issue'}",
                      stdout)

    @patch("optimshine.api_common.ApiCommon.api_get_request")
    def test_get_solar_sunrise_sunset_time_tomorrow_none_response(
        self,
        mock_api_get_request
    ):
        stdio = io.StringIO()
        # Today's request succeeds, tomorrow's returns nothing.
        mock_api_get_request.side_effect = [api_data.sunrise_response, None]

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        status = cls_api_weather._get_solar_sunrise_sunset_time(
            "36.7201600",
            "-33.86882",
            "2025-04-14"
        )
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Getting tomorrow sunrise/sunset data failed!", stdout)
        self.assertIsNone(cls_api_weather.sunrise_tomorrow)

    @patch("optimshine.api_common.ApiCommon.api_get_request")
    def test_get_solar_sunrise_sunset_time_tomorrow_wrong_response(
        self,
        mock_api_get_request
    ):
        stdio = io.StringIO()
        # Today's request succeeds, tomorrow's payload has no results.
        mock_api_get_request.side_effect = [
            api_data.sunrise_response,
            {"data": "test issue"},
        ]

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        status = cls_api_weather._get_solar_sunrise_sunset_time(
            "36.7201600",
            "-33.86882",
            "2025-04-14"
        )
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Getting weather data failed. {'data': 'test issue'}",
                      stdout)
        self.assertIsNone(cls_api_weather.sunrise_tomorrow)

    @patch("optimshine.api_common.ApiCommon.api_get_request")
    def test_get_solar_sunrise_sunset_time_pass(self,
                                                mock_api_get_request):
        mock_api_get_request.return_value = api_data.sunrise_response

        cls_api_weather = api.ApiWeather(self.log)
        status = cls_api_weather._get_solar_sunrise_sunset_time(
            "36.7201600",
            "-33.86882",
            "2025-04-14"
        )

        self.assertTrue(status)
        self.assertTrue(hasattr(cls_api_weather, "sunrise"))
        self.assertTrue(hasattr(cls_api_weather, "sunset"))
        self.assertEqual(cls_api_weather.sunrise, "2:29:57 AM")
        self.assertEqual(cls_api_weather.sunset, "6:53:59 PM")
        # Tomorrow's sunrise is parsed as UTC and converted to local time.
        self.assertEqual(
            cls_api_weather.sunrise_tomorrow,
            datetime(2025, 4, 15, 2, 29, 57,
                     tzinfo=ZoneInfo("UTC")).astimezone()
        )

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    def test_get_weather_data_sunset_false(self,
                                           mock_api_weather):
        stdio = io.StringIO()
        mock_api_weather.return_value = False

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-04-14")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Error during obtaining sunrise or sunset", stdout)

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    def test_get_weather_data_sunset_none(self,
                                          mock_api_weather):
        stdio = io.StringIO()
        mock_api_weather.return_value = True

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        cls_api_weather.sunrise = None
        cls_api_weather.sunset = None
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-04-14")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Sunrise or sunset cannot be none!", stdout)

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_weather_data_response_none(self, mock_api_post_request,
                                            mock_api_weather):
        stdio = io.StringIO()
        mock_api_weather.return_value = True
        mock_api_post_request.return_value = None

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        cls_api_weather.sunrise = "2:29:57 AM"
        cls_api_weather.sunset = "6:53:59 PM"
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-04-14")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Getting weather data failed!", stdout)

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_weather_data_response_wrong_data(self, mock_api_post_request,
                                                  mock_api_weather):
        stdio = io.StringIO()
        mock_api_weather.return_value = True
        mock_api_post_request.return_value = {"data": "Test issue"}

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        cls_api_weather.sunrise = "2:29:57 AM"
        cls_api_weather.sunset = "6:53:59 PM"
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-04-14")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Getting weather data failed. {'data': 'Test issue'}",
                      stdout)

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_weather_data_response_wrong_sunrise(self,
                                                     mock_api_post_request,
                                                     mock_api_weather):
        stdio = io.StringIO()
        mock_api_weather.return_value = True
        mock_api_post_request.return_value = {
            "data": {
                "cldlow_aver": {
                    "first_timestamp": "1747659600",
                    "interval": 3600,
                    "data": [12.1, 11.725, 11.475]
                }
            }
        }

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        cls_api_weather.sunrise = "2:29:57 AM"
        cls_api_weather.sunset = "6:53:59 PM"
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-04-14")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Wrong sunrise time!", stdout)

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_weather_data_response_none_clouds_data(self,
                                                        mock_api_post_request,
                                                        mock_api_weather):
        stdio = io.StringIO()
        mock_api_weather.return_value = True
        mock_api_post_request.return_value = {
            "data": {
                "cldlow_aver": {
                    "first_timestamp": "1747659600",
                    "interval": 3600,
                    "data": []
                }
            }
        }

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        cls_api_weather.sunrise = "2:29:57 AM"
        cls_api_weather.sunset = "6:53:59 PM"
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-05-20")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("No cloud data available!", stdout)

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_weather_data_response_non_int_first_sample(
        self,
        mock_api_post_request,
        mock_api_weather
    ):
        stdio = io.StringIO()
        mock_api_weather.return_value = True
        mock_api_post_request.return_value = {
            "data": {
                "cldlow_aver": {
                    "first_timestamp": "1747659600",
                    "interval": 3500,
                    "data": [12.1, 11.725, 11.475]
                }
            }
        }

        handler = logging.StreamHandler(stream=stdio)
        self.log.addHandler(handler)
        cls_api_weather = api.ApiWeather(self.log)
        cls_api_weather.sunrise = "2:29:57 AM"
        cls_api_weather.sunset = "6:53:59 PM"
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-05-20")
        stdout = stdio.getvalue()

        self.assertFalse(status)
        self.assertIn("Timestamps must be divisible by interval", stdout)

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_weather_data_response_pass_polar(self, mock_api_post_request,
                                                  mock_api_weather):
        mock_api_weather.return_value = True
        mock_api_post_request.return_value = api_data.devmgramapi_response

        cls_api_weather = api.ApiWeather(self.log)
        cls_api_weather.sunrise = "2:29:57 AM"
        cls_api_weather.sunset = "2:29:57 AM"
        cls_api_weather.sunrise_tomorrow = SUNRISE_TOMORROW
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-05-20")

        self.assertTrue(status)
        self.assertTrue(hasattr(cls_api_weather, "weather_data"))
        self.assertEqual(cls_api_weather.weather_data["first_sample_time"],
                         1747702800)
        self.assertEqual(cls_api_weather.weather_data["date"],
                         "2025-05-20")
        self.assertEqual(cls_api_weather.weather_data["interval"],
                         3600)
        self.assertEqual(
            cls_api_weather.weather_data["low_clouds_data"],
            api_data.devmgramapi_response["data"]["cldlow_aver"]["data"][:24]
        )
        self.assertEqual(
            cls_api_weather.weather_data["sunrise_tomorrow_time"],
            SUNRISE_TOMORROW
        )

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_weather_data_response_pass_sunset(self, mock_api_post_request,
                                                   mock_api_weather):
        mock_api_weather.return_value = True
        mock_api_post_request.return_value = api_data.devmgramapi_response

        cls_api_weather = api.ApiWeather(self.log)
        cls_api_weather.sunrise = "2:29:57 AM"
        cls_api_weather.sunset = "1:29:57 AM"
        cls_api_weather.sunrise_tomorrow = SUNRISE_TOMORROW
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-05-20")

        self.assertTrue(status)
        self.assertTrue(hasattr(cls_api_weather, "weather_data"))
        self.assertEqual(cls_api_weather.weather_data["first_sample_time"],
                         1747706400)
        self.assertEqual(cls_api_weather.weather_data["date"],
                         "2025-05-20")
        self.assertEqual(cls_api_weather.weather_data["interval"],
                         3600)
        self.assertEqual(
            cls_api_weather.weather_data["low_clouds_data"],
            api_data.devmgramapi_response["data"]["cldlow_aver"]["data"][1:25]
        )

    @patch("optimshine.api_weather.ApiWeather._get_solar_sunrise_sunset_time")
    @patch("optimshine.api_common.ApiCommon.api_post_request")
    def test_get_weather_data_response_pass(self, mock_api_post_request,
                                            mock_api_weather):
        mock_api_weather.return_value = True
        mock_api_post_request.return_value = api_data.devmgramapi_response

        cls_api_weather = api.ApiWeather(self.log)
        cls_api_weather.sunrise = "2:29:57 AM"
        cls_api_weather.sunset = "10:29:57 PM"
        cls_api_weather.sunrise_tomorrow = SUNRISE_TOMORROW
        status = cls_api_weather.get_weather_data("36.7201600",
                                                  "-33.86882",
                                                  "2025-05-20")

        self.assertTrue(status)
        self.assertTrue(hasattr(cls_api_weather, "weather_data"))
        self.assertEqual(cls_api_weather.weather_data["first_sample_time"],
                         1747706400)
        self.assertEqual(cls_api_weather.weather_data["date"],
                         "2025-05-20")
        self.assertEqual(cls_api_weather.weather_data["interval"],
                         3600)
        self.assertEqual(
            cls_api_weather.weather_data["low_clouds_data"],
            api_data.devmgramapi_response["data"]["cldlow_aver"]["data"][1:22]
        )
        self.assertEqual(
            cls_api_weather.weather_data["sunrise_tomorrow_time"],
            SUNRISE_TOMORROW
        )
        self.assertEqual(cls_api_weather.weather_data["sunrise_time"],
                         1747706400)


if __name__ == "__main__":
    unittest.main()
