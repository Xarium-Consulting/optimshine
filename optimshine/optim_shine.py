#!/usr/bin/env python
#
# Copyright 2025 Norbert Kamiński <norbert.kaminski@xarium.world>
#
# SPDX-License-Identifier: LGPL-3.0-or-later
#

import os
import sys
import time
import sdnotify

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from optimshine.api_common import MARKET_TIMEZONE
from optimshine.api_shine import ApiShine
from optimshine.api_weather import ApiWeather
from optimshine.api_pse import ApiPse
from optimshine.api_miner import (ApiMiner, WORKMODE_MAP,
                                  WORKMODE_POWER_CONSUMPTION)
from optimshine.optim_config import OptimConfig


CHARGE_MODES = {
    "no_charge": 1,
    "slow_charge": 30,
    "normal_charge": 60,
    "fast_charge": 90,
}


class OptimShine(OptimConfig, ApiPse, ApiShine, ApiWeather, ApiMiner):
    """
    OptimShine is a class that manages the optimization of battery charging
    based on various factors such as weather conditions, plant data, and
    pricing information.
    """
    def __init__(self, envpath='.env'):
        """
        Initializes the OptimShine instance.

        Notifies systemd that the service is ready, sets up the logger, loads
        the environment variables from the given env file and initializes the
        job scheduler.

        Args:
            envpath (str, optional): Path to the env file with the
                                     configuration. Defaults to '.env'.
        """
        self.judge_date: datetime = None
        self.soc_check_date: datetime = None
        self.optim = False
        self.optim_date: datetime = None
        self.dry_run = False

        self.notifier = sdnotify.SystemdNotifier()
        self.notifier.notify("READY=1")
        self.logger_setup()
        self.envs_setup(envpath=envpath)
        self.scheduler_setup()

    def _shine_setup(self):
        """
        Sets up the connection to the Shine API and retrieves the list of
        inverters for the selected plant.

        Exits the program with a critical error message if any of the steps
        fail.
        """
        self.log.info("Trying to login to Shine API")
        if not self.login_shine():
            self.log.critical("Failed to login to Shine API. Exiting...")
            sys.exit(1)

        self.log.info("Trying to get plant list")
        if not self.get_plant_list():
            self.log.critical("Getting plant list failed. Exiting...")
            sys.exit(1)

        if not self.plants_id:
            self.log.critical("Plants list is empty. Exiting...")
            sys.exit(1)

        shine_plant = os.getenv("SHINE_PLANT")

        if shine_plant:
            try:
                self.plant = self.plants_id[shine_plant]
            except (KeyError, TypeError):
                self.log.critical(f"{shine_plant} not found in the plant "
                                  "list. Check your plant name in Monitoring->"
                                  "Plant. Exiting...")
                sys.exit(1)
        elif not shine_plant and len(self.plants_id) == 1:
            self.plant = next(iter(self.plants_id.values()))
        else:
            self.log.critical("You must set SHINE_PLANT if you have more than"
                              " one plant. Exiting...")
            sys.exit(1)

        self.log.info("Trying to get inverter list")
        if not self.get_device_list(self.plant["id"], "INV"):
            self.log.critical("Failed to get list of inverters. Exiting...")
            sys.exit(1)

        if not self.device_list:
            self.log.critical("No inverters found. Exiting...")
            sys.exit(1)

        self.inverters = self.device_list.copy()
        self.device_list = None
        self.log.info("API Shine setup was successful")

    def _check_weather(self, latitude, longitude, date):
        """
        Checks the weather conditions for a given latitude, longitude,
        and date.

        Args:
            latitude (float): The latitude of the location to check.
            longitude (float): The longitude of the location to check.
            date (str): The date for which to check the weather,
                        in YYYY-MM-DD format.

        Returns:
            bool: True if the weather data is available and processed,
                  otherwise False.
        """
        self.not_cloudy = False
        not_cloudy_hours = 0

        if not self.get_weather_data(latitude, longitude, date):
            self.log.error("Weather forecast is not available")
            return False

        for sample in self.weather_data["low_clouds_data"]:
            if sample < 0.75:
                not_cloudy_hours += 1

        if not_cloudy_hours > len(self.weather_data["low_clouds_data"])/2:
            self.not_cloudy = True

        return True

    def _check_current_weather(self, date, time):
        """
        Checks whether it is cloudy at the given date and time.

        Picks the low clouds forecast sample that matches the requested hour
        and sets ``self.cloudy_now`` to True when the cloud cover exceeds 75%.

        Args:
            date (str): The date to check, in YYYY-MM-DD format.
            time (str): The time to check, in "%I:%M:%S %p" format.

        Returns:
            bool: True if the current weather was determined, False when no
                  weather data is available or the requested hour is outside
                  the forecast range.
        """
        self.cloudy_now = False

        if not hasattr(self, "weather_data"):
            self.log.error("No weather data available!")
            return False

        hour_ts = self.get_timestamp_hour(date, time)
        sample_number = (
            int((hour_ts - self.weather_data["first_sample_time"])
                / self.weather_data["interval"])
            )
        if sample_number >= len(self.weather_data["low_clouds_data"]):
            self.log.error("Sample number out of range")
            return False

        if self.weather_data["low_clouds_data"][sample_number] > 0.75:
            self.cloudy_now = True
            return True

        return True

    def _get_current_judge_factors(self):
        """
        Gathers the plant-wide factors used to judge the optimization strategy.

        Collects whether it is night, whether it is cloudy right now, the
        current quarter RCE price, and the miner profitability per operating
        mode. The gathered values are stored on the instance:

            - self.if_night: True when the sun is below the horizon
            - self.cloudy_now: set by ``_check_current_weather``
            - self.current_rce_price: current quarter RCE price (PLN/kWh)
            - self.miner_profitability: {mode: PLN/kWh} for each mode, the
              single source of truth consumed by ``_compare_miner_to_pse``

        Returns:
            bool: True if all factors were gathered successfully, False
                  otherwise.
        """
        self.if_night = False
        self.current_rce_price = None

        if not hasattr(self, "weather_data"):
            self.log.error("No weather data available!")
            return False

        if not hasattr(self, "rce_prices"):
            self.log.error("No RCE prices available!")
            return False

        time_now = datetime.now().timestamp()
        self.log.debug("Checking if token is valid")
        if self.token_ttl < time_now and not self.login_shine():
            self.log.error("Authorization token has expired. "
                           "Failed to login to Shine API")
            return False

        # The two lookups below are indexed on different clocks., so each gets
        # the wall clock it expects instead of the host's local one:
        #   - RCE quarters are settled on market local time.
        #   - Weather samples are keyed by get_timestamp_hour, which resolves
        #     in UTC, matching the forecast timestamps.
        date_now = datetime.now(tz=timezone.utc)
        market_now = date_now.astimezone(MARKET_TIMEZONE)
        market_date = market_now.strftime("%Y-%m-%d")
        market_time = market_now.strftime("%I:%M:%S %p")
        utc_date = date_now.strftime("%Y-%m-%d")
        utc_time = date_now.strftime("%I:%M:%S %p")
        date_ts = date_now.timestamp()
        quarter_ts = self.get_timestamp_quarter(market_date, market_time)

        if (self.weather_data["sunrise_time"] > date_ts
                or self.weather_data["sunset_time"] < date_ts):
            self.if_night = True
        elif not self._check_current_weather(utc_date, utc_time):
            self.log.error("Checking current weather failed!")
            return False

        try:
            self.current_rce_price = self.rce_prices[quarter_ts]/1000
            self.log.debug(f"Current PSE price: {self.current_rce_price}")
        except KeyError:
            self.log.error("Current quarter not found in RCE prices")
            return False

        self.log.debug("Getting miner profitability")
        self.miner_profitability = {}
        for mode in WORKMODE_MAP:
            if not self.get_current_miner_profitability(mode):
                self.log.error("Getting miner profitability failed")
                return False
            self.miner_profitability[mode] = self.profitability
        self.log.debug(f"Miner profitability: {self.miner_profitability}")

        self.log.info("Successfully obtained current judge factors")
        return True

    def _get_daily_judge_factors(self):
        """
        Retrieves judge factors based on plant information and weather data and
        RCE energy prices.

        Returns:
            bool: True if the judge factors are successfully obtained,
                  False otherwise.
        """
        if not hasattr(self, "plant"):
            self.log.error("No plant info available")
            return False

        date = datetime.now(tz=timezone.utc).astimezone(
            MARKET_TIMEZONE
        ).strftime("%Y-%m-%d")

        self.log.debug("Trying to get weather data")
        if not self._check_weather(self.plant["latitude"],
                                   self.plant["longitude"],
                                   date):
            self.log.error("Failed to check weather")
            return False
        self.log.debug(f"not_cloudy flag: {self.not_cloudy}")

        self.log.debug("Trying to get PSE data")
        if not self.get_pse_data(date):
            self.log.error("Failed to get RCE prices")
            return False

        self.min_price = next(iter(self.rce_prices.values()))
        for quarter, price in self.rce_prices.items():
            if price < self.min_price:
                self.min_price_timestamp = quarter
                self.min_price = price

        self.log.debug(f"min_price_timestamp: {self.min_price_timestamp}")
        self.log.debug(f"min_price: {self.min_price}")

        self.log.info("Successfully obtained judge factors")
        return True

    def _get_inverter_judge_factors(self, inverter, night=False):
        """
        Reads the per-inverter factors used to judge the optimization strategy.

        Always reads the battery state of charge. The PV production is read
        only during the day, since it is always zero at night.

        Args:
            inverter (object): The inverter to read the values from.
            night (bool, optional): When True the PV production read is
                                    skipped. Defaults to False.

        Returns:
            tuple: ``(state_of_charge, pv_production)`` on success. The PV
                   production is None when ``night`` is True. Returns
                   ``(None, None)`` when reading a value failed.
        """
        self.log.debug("Getting battery state of charge")
        if not self.get_device_value(inverter, "battery_soc"):
            self.log.error("Getting battery state of charge failed")
            return (None, None)
        current_soc = float(self.device_value)
        self.device_value = None
        self.log.debug(f"Battery SOC: {current_soc}%")

        if night:
            self.log.debug("It's night. Omitting PV production")
            return (current_soc, None)
        self.log.debug("Getting PV production")
        if not self.get_device_value(inverter, "pv_power"):
            self.log.error("Getting PV production failed")
            return (None, None)
        current_pv_power = float(self.device_value)
        self.device_value = None
        self.log.debug(f"PV production: {current_pv_power} W")
        return (current_soc, current_pv_power)

    def _compare_miner_to_pse(self):
        """
        Compares the current PSE (RCE) energy price against the miner
        profitability for each operating mode and decides which use of the
        energy is more valuable.

        Reads the per-mode profitability (PLN/kWh) gathered by
        ``_get_current_judge_factors`` into ``self.miner_profitability`` and
        compares each mode to the current PSE price. Among the modes that beat
        the PSE price the least profitable one is chosen, so the miner runs in
        the most conservative mode that is still worth running. When no mode
        beats the PSE price, selling to the grid (PSE) wins.

        ``_get_current_judge_factors`` must have run successfully first, since
        it provides both the PSE price and the profitability figures.

        Returns:
            str or None: The operating mode when the miner is more profitable,
                         the string ``"pse"`` when the PSE price is better, or
                         None if the current PSE price or the profitability
                         figures are unavailable.
        """
        if not hasattr(self, "current_rce_price") or \
                self.current_rce_price is None:
            self.log.error("No current PSE price available!")
            return None

        if not getattr(self, "miner_profitability", None):
            self.log.error("No miner profitability available!")
            return None

        chosen_mode = None
        chosen_profitability = None
        for mode, profitability in self.miner_profitability.items():
            self.log.debug(
                f"'{mode}' profitability: {profitability} PLN/kWh, "
                f"current PSE price: {self.current_rce_price} PLN/kWh"
            )

            if profitability > self.current_rce_price and (
                chosen_profitability is None
                or profitability < chosen_profitability
            ):
                chosen_profitability = profitability
                chosen_mode = mode

        if chosen_mode is not None:
            self.log.info(f"Miner is more profitable in '{chosen_mode}' mode")
            return chosen_mode

        self.log.info("PSE price is more profitable")
        return "pse"

    def _compare_miner_to_pv_prod(self, inverter_pv):
        """
        Compares the miner power consumption of each operating mode against the
        available PV production and selects the most demanding mode the PV
        production can still cover.

        For every mode in WORKMODE_POWER_CONSUMPTION the power consumption is
        compared to ``inverter_pv``. The mode with the highest consumption that
        is still fully covered by the PV production is chosen.

        Args:
            inverter_pv (float): The available PV production.

        Returns:
            str: The most demanding operating mode the PV production can cover,
                 or the string ``"TOO_LOW"`` when no mode is covered.
        """
        chosen_mode = None
        chosen_consumption = None
        for mode, consumption in WORKMODE_POWER_CONSUMPTION.items():
            self.log.debug(
                f"'{mode}' power consumption: {consumption}, "
                f"PV production: {inverter_pv}"
            )
            if consumption <= inverter_pv and (
                chosen_consumption is None
                or consumption > chosen_consumption
            ):
                chosen_consumption = consumption
                chosen_mode = mode

        if chosen_mode is not None:
            self.log.info(f"PV production covers '{chosen_mode}' mode")
            return chosen_mode

        self.log.info("PV production is too low for any miner mode")
        return "TOO_LOW"

    def optim_charge_battery(self, inverter, mode):
        """
        Optimizes the battery charging current based on the specified mode.

        Args:
            inverter (object): The inverter object to interact with.
            mode (str): The charging mode to apply, which determines the target
                        charge current.

        Returns:
            bool: True if the battery charging optimization was successful,
                  False otherwise.

        Raises:
            RuntimeError: If there is an issue with authorization, getting
                          settings, or setting the charge current.
            AttributeError: If the provided mode is unknown.
        """
        time_now = datetime.now().timestamp()
        self.log.debug("Checking if token is valid")
        if self.token_ttl < time_now and not self.login_shine():
            self.log.error("Authorization token has expired. "
                           "Failed to login to Shine API")
            raise RuntimeError

        self.log.debug(f"Battery charging mode: {mode}")
        try:
            target_charge_current = CHARGE_MODES[mode]
        except (KeyError, TypeError):
            self.log.error(f"{mode} charge mode unknown")
            raise AttributeError

        self.log.debug("Getting battery charge current value")
        if not self.get_setting_value(inverter, "battery_charge_current"):
            self.log.error("Getting battery charge current failed")
            raise RuntimeError

        setting_charge_current = self.setting_value/10
        self.setting_value = None
        self.log.debug("Battery charge current value: "
                       f"{setting_charge_current} A")

        if setting_charge_current == target_charge_current:
            self.log.info("Correct charge current value is already set. "
                          "Battery charging optimization was successful")
            return True

        if not self.set_charge_current(inverter, target_charge_current):
            self.log.error("Failed to set battery charge current")
            raise RuntimeError

        if not self.get_setting_value(inverter, "battery_charge_current"):
            self.log.error("Getting battery charge current failed "
                           "(Validation)")
            raise RuntimeError

        setting_charge_current = self.setting_value/10
        self.setting_value = None
        self.log.debug("Battery charge current value: "
                       f"{setting_charge_current} A")

        if not setting_charge_current == target_charge_current:
            self.log.error("Failed to set battery charge current. "
                           "Wrong current value")
            raise RuntimeError
        self.log.info("Battery charging optimization was successful")
        return True

    def optim_strategy_night(self):
        """
        Sets up the optimization strategy for nighttime.

        Hands over to the day strategy when the sun is already up. Otherwise it
        reads the battery state of charge of every inverter and either stops
        mining (state of charge at or below 35%) or mines in Eco mode. The next
        night optimization run is scheduled 15 minutes ahead.

        Returns:
            bool: True when the day strategy was scheduled instead. None is
                  returned after a regular night optimization pass.

        Raises:
            RuntimeError: If the inverter list or the weather data is missing,
                          or if reading the inverter values failed.
        """
        if not hasattr(self, "inverters") or not self.inverters:
            self.log.error("No inverter list found")
            raise RuntimeError

        if not hasattr(self, "weather_data"):
            self.log.error("No weather data available")
            raise RuntimeError

        time_now = datetime.now().timestamp()

        if (self.weather_data["sunrise_tomorrow_time"].timestamp() < time_now
            or (self.weather_data["sunset_time"] > time_now and
                self.weather_data["sunrise_time"] < time_now)):
            self.log.info("It's day. Run day optimization.")
            self.scheduler.add_job(
                self.optim_strategy_day,
                trigger="date",
                run_date=(datetime.now() + timedelta(seconds=15)),
                id="optim_strategy_day",
                replace_existing=True
            )
            return True

        for inverter in self.inverters:
            inverter_soc = None
            inverter_soc, _ = (
                self._get_inverter_judge_factors(inverter, night=True)
            )
            if inverter_soc is None:
                self.log.error("Failed to get inverter values")
                self.scheduler.add_job(
                    self.optim_strategy_night,
                    trigger="date",
                    run_date=(datetime.now() + timedelta(minutes=15)),
                    id="optim_strategy_night",
                    replace_existing=True
                )
                raise RuntimeError

            if inverter_soc <= 35:
                self.log.debug("Battery state low. Not mining until it's"
                               " at least 35%.")
                self.off()
            else:
                self.log.debug("Mining in eco mode.")
                self.on()
                time.sleep(20)
                self.set_mode("Eco")

        self.log.info("Setting optimization strategy was successful")
        self.scheduler.add_job(
            self.optim_strategy_night,
            trigger="date",
            run_date=(datetime.now() + timedelta(minutes=15)),
            id="optim_strategy_night",
            replace_existing=True
        )
        self.log.info("Scheduling next night optimization in 15 minutes")
        self.scheduler_list_jobs()

    def optim_strategy_day(self):
        """
        Determines and applies the daytime optimization strategy.

        Hands over to the night strategy after sunset. Otherwise, for every
        inverter, it combines the current RCE price, the cloud cover, the
        battery state of charge and the PV production to decide the battery
        charge mode and whether the miner should run, and in which mode:

            - negative RCE price: fast charge and mine in Super mode
            - cloudy, low battery: fast charge, miner off
            - cloudy, full battery: mine when it beats the PSE price and the PV
              production covers a mode, otherwise sell the energy
            - sunny, low battery: fast charge, miner off
            - sunny, high RCE price: no charge, miner off
            - sunny otherwise: slow charge (fast charge close to sunset) and
              mine when it beats the PSE price and PV production allows it

        The next day optimization run is scheduled 15 minutes ahead.

        Returns:
            bool: True when the night strategy was scheduled instead or when a
                  negative price pass finished early. None is returned after a
                  regular day optimization pass.

        Raises:
            RuntimeError: If the inverter list, the weather data or the daily
                          weather info is missing, or if getting the judge
                          factors or the inverter values failed.
        """
        if not hasattr(self, "inverters") or not self.inverters:
            self.log.error("No inverter list found")
            raise RuntimeError

        if not hasattr(self, "weather_data"):
            self.log.error("No weather data available")
            raise RuntimeError

        if not hasattr(self, "not_cloudy"):
            self.log.error("No daily weather info")
            raise RuntimeError

        if datetime.now().timestamp() > self.weather_data["sunset_time"]:
            self.log.info("It's night. Run night optimization.")
            self.scheduler.add_job(
                self.optim_strategy_night,
                trigger="date",
                run_date=(datetime.now() + timedelta(seconds=15)),
                id="optim_strategy_night",
                replace_existing=True
            )
            self.scheduler_list_jobs()
            return True

        if not self._get_current_judge_factors():
            self.log.error("Failed to get current judge factors")
            self.scheduler.add_job(
                self.optim_strategy_day,
                trigger="date",
                run_date=(datetime.now() + timedelta(minutes=15)),
                id="optim_strategy_day",
                replace_existing=True
            )
            self.scheduler_list_jobs()
            raise RuntimeError

        for inverter in self.inverters:
            inverter_soc = None
            inverter_pv = None
            inverter_soc, inverter_pv = (
                self._get_inverter_judge_factors(inverter)
            )
            if inverter_soc is None or inverter_pv is None:
                self.log.error("Failed to get inverter values")
                self.scheduler.add_job(
                    self.optim_strategy_day,
                    trigger="date",
                    run_date=(datetime.now() + timedelta(minutes=15)),
                    id="optim_strategy_day",
                    replace_existing=True
                )
                self.scheduler_list_jobs()
                raise RuntimeError

            if self.current_rce_price < 0:
                self.log.info("Negative energy price. "
                              "Charging battery and mining")
                self.optim_charge_battery(inverter, "fast_charge")
                self.on()
                time.sleep(20)
                self.set_mode("Super")
                self.scheduler.add_job(
                    self.optim_strategy_day,
                    trigger="date",
                    run_date=(datetime.now() + timedelta(minutes=15)),
                    id="optim_strategy_day",
                    replace_existing=True
                )
                return True
            if self.cloudy_now:
                if inverter_soc < 80:
                    self.log.info("Cloudy weather, low battery")
                    self.optim_charge_battery(inverter, "fast_charge")
                    self.off()
                else:
                    self.log.info("Cloudy weather, full battery")
                    consumption_mode = self._compare_miner_to_pv_prod(
                        inverter_pv
                    )
                    mode = self._compare_miner_to_pse()
                    if mode == "pse":
                        self.log.info("Charging battery and selling energy")
                        self.off()
                    elif consumption_mode == "TOO_LOW":
                        self.log.info("Too low production to mine, charging "
                                      "battery and selling energy")
                        self.off()
                    else:
                        self.log.info(f"Mining in {consumption_mode} mode.")
                        self.on()
                        time.sleep(20)
                        self.set_mode(consumption_mode)
            else:
                buffor_time = (datetime.now() + timedelta(hours=3)).timestamp()
                if inverter_soc < 35:
                    self.log.info("Sunny weather. Low battery.")
                    self.optim_charge_battery(inverter, "fast_charge")
                    self.off()
                elif self.weather_data["sunset_time"] > buffor_time:
                    if self.current_rce_price > 0.6:
                        self.log.info("Sunny weather. High PSE price:"
                                      f" {self.current_rce_price}")
                        self.optim_charge_battery(inverter, "no_charge")
                        self.off()
                    else:
                        self.optim_charge_battery(inverter, "slow_charge")
                        self.log.info("Sunny weather.")
                        consumption_mode = self._compare_miner_to_pv_prod(
                            inverter_pv
                        )
                        mode = self._compare_miner_to_pse()
                        if mode == "pse":
                            self.log.info("Charging battery and selling"
                                          " energy")
                            self.off()
                        elif consumption_mode == "TOO_LOW":
                            self.log.info("Too low production to mine, "
                                          "charging battery and selling "
                                          "energy")
                            self.off()
                        else:
                            self.log.info(f"Mining in {consumption_mode} mode")
                            self.on()
                            time.sleep(20)
                            self.set_mode(consumption_mode)
                else:
                    self.log.info("Sunny weather. Almost dark,"
                                  " charging battery.")
                    self.optim_charge_battery(inverter, "fast_charge")
                    consumption_mode = self._compare_miner_to_pv_prod(
                        inverter_pv
                    )
                    mode = self._compare_miner_to_pse()
                    if mode == "pse":
                        self.log.info("Charging battery and selling"
                                      " energy")
                        self.off()
                    elif consumption_mode == "TOO_LOW":
                        self.log.info("Too low production to mine, charging"
                                      " battery and selling energy")
                        self.off()
                    else:
                        self.log.info(f"Mining in {consumption_mode} mode")
                        self.on()
                        time.sleep(20)
                        self.set_mode(consumption_mode)

        self.log.info("Setting optimization strategy was successful")
        self.scheduler.add_job(
            self.optim_strategy_day,
            trigger="date",
            run_date=(datetime.now() + timedelta(minutes=15)),
            id="optim_strategy_day",
            replace_existing=True
        )
        self.log.info("Scheduling next day optimization in 15 minutes")
        self.scheduler_list_jobs()

    def optim_judge(self):
        """
        Evaluates weather data and energy prices to determine
        the optimization strategy.

        Gets the daily judge factors and starts either the day or the night
        strategy depending on whether the judge ran before sunset. Tomorrow's
        judge is then scheduled based on tomorrow's sunrise time. When getting
        the judge factors fails, the judge is rescheduled 30 minutes ahead.

        Raises:
            RuntimeError: If judge factors retrieval fails.
        """
        self.log.info("Getting weather data and energy prices")
        if not self._get_daily_judge_factors():
            self.log.warning("Failed to get judge factors")
            self.judge_date += timedelta(minutes=30)
            self.log.info(
                "Rescheduling optimization judge to "
                f"{self.judge_date.astimezone().strftime('%d-%m-%Y %H:%M')}"
            )
            self.scheduler.add_job(
                self.optim_judge,
                trigger="date",
                run_date=self.judge_date,
                id="optim_judge",
                replace_existing=True)
            raise RuntimeError

        if self.not_cloudy:
            # https://www.youtube.com/watch?v=-Hv8fj8hQlE
            self.log.info("It'll be sunny day")
        else:
            # https://www.youtube.com/watch?v=aSLZFdqwh7E
            self.log.info("It'll be cloudy day")

        self.log.info("Setting up optimization strategy")
        if self.judge_date.timestamp() < self.weather_data["sunset_time"]:
            self.scheduler.add_job(
                self.optim_strategy_day,
                trigger="date",
                run_date=(datetime.now() + timedelta(seconds=10)),
                id="optim_strategy_day",
                replace_existing=True
            )
        else:
            self.scheduler.add_job(
                self.optim_strategy_night,
                trigger="date",
                run_date=(datetime.now() + timedelta(seconds=10)),
                id="optim_strategy_night",
                replace_existing=True
            )

        self.log.info("Scheduling tomorrow's optimization judge")
        # Based on tomorrow sunrise time

        self.judge_date = self.weather_data["sunrise_tomorrow_time"]
        self.scheduler.add_job(
            self.optim_judge,
            trigger="date",
            run_date=self.judge_date,
            id="optim_judge",
            replace_existing=True
        )
        self.scheduler_list_jobs()

    def optim_main(self):
        """
        Main function to set up and schedule the optimization judge.

        Sets up the Shine API connection, schedules the first optimization
        judge one minute ahead and starts the scheduler. Keeps notifying the
        systemd watchdog while there are scheduled or running jobs.

        Raises:
            SystemExit: Exits the program if no jobs are scheduled.
        """
        self._shine_setup()

        time_now = datetime.now().astimezone(ZoneInfo("UTC"))
        self.judge_date = time_now + timedelta(minutes=1)

        self.log.info(
            "Scheduling optimization judge to "
            f"{self.judge_date.astimezone().strftime('%d-%m-%Y %H:%M')}"
        )
        self.scheduler.add_job(
            self.optim_judge,
            trigger="date",
            run_date=self.judge_date,
            id="optim_judge",
        )
        self.scheduler.start()

        while self.scheduler.get_jobs() or self.running_jobs:
            self.notifier.notify("WATCHDOG=1")
            time.sleep(5)

        self.scheduler.shutdown()
        self.log.critical("No jobs scheduled. Exiting...")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    cls_optim = OptimShine()
    cls_optim.optim_main()
