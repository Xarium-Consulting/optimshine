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

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from optimshine.api_shine import ApiShine
from optimshine.api_weather import ApiWeather
from optimshine.api_pse import ApiPse
from optimshine.api_miner import ApiMiner, WORKMODE_MAP
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
        self.judge_date: datetime = None
        self.soc_check_date: datetime = None
        self.optim = False
        self.optim_date: datetime = None

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

    def _get_current_judge_factors(self, inverter):
        """
        Gathers the current factors used to judge the optimization strategy.

        Collects the current battery state of charge, PV production, whether
        the next hour is expected to be cloudy, the current RCE price, and the
        miner profitability per operating mode. The gathered values are stored
        on the instance:

            - self.current_soc: battery state of charge (float, %)
            - self.current_pv_power: PV production (float, W)
            - self.if_night / self.not_cloudy_now: weather flags
            - self.current_rce_price: current quarter RCE price
            - self.miner_profitability: {mode: PLN/kWh} for each mode

        Args:
            inverter (str): The serial number of the inverter to read the SoC
                            and PV production from.

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

        date_now = datetime.now()
        date = date_now.strftime("%Y-%m-%d")
        time = date_now.strftime("%I:%M:%S %p")
        date_ts = date_now.timestamp()
        quarter_ts = self.get_timestamp_quarter(date, time)

        if (self.weather_data["sunrise_time"] > date_ts
                or self.weather_data["sunset_time"] < date_ts):
            self.if_night = True
        elif not self._check_current_weather(date, time):
            self.log.error("Checking current weather failed!")
            return False

        try:
            self.current_rce_price = self.rce_prices[quarter_ts]/1000
        except KeyError:
            self.log.error("Current quarter not found in RCE prices")
            return False

        self.log.debug("Getting battery state of charge")
        if not self.get_device_value(inverter, "battery_soc"):
            self.log.error("Getting battery state of charge failed")
            return False
        self.current_soc = float(self.device_value)
        self.device_value = None
        self.log.debug(f"Battery SOC: {self.current_soc}%")

        self.log.debug("Getting PV production")
        if not self.get_device_value(inverter, "pv_power"):
            self.log.error("Getting PV production failed")
            return False
        self.current_pv_power = float(self.device_value)
        self.device_value = None
        self.log.debug(f"PV production: {self.current_pv_power} W")

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

        date = datetime.now().strftime("%Y-%m-%d")

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
            self.scheduler_list_jobs()
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
        self.scheduler_list_jobs()
        self.log.info("Battery charging optimization was successful")
        return True

    def optim_soc_check(self, inverter):
        """
        Checks the state of charge (SOC) of the battery connected to the
        specified inverter. If the SOC is below 50%, it initiates a slow
        charge. If the SOC is sufficient, it sets the battery to no charge
        mode and prepares for optimization.
        Args:
            inverter (str): The identifier for the inverter to check.

        Returns:
            bool: True if the battery is ready for optimization or if the SOC
                   check was successfully scheduled.

        Raises:
            RuntimeError: If there is an issue with authorization, or if
                          retrieving the battery state of charge fails.
        """
        time_now = datetime.now().timestamp()
        self.log.debug("Checking if token is valid")
        if self.token_ttl < time_now and not self.login_shine():
            self.log.error("Authorization token has expired. "
                           "Failed to login to Shine API")
            raise RuntimeError

        self.log.debug("Getting battery state of charge")
        if not self.get_device_value(inverter, "battery_soc"):
            self.log.error("Getting battery state of charge failed")
            raise RuntimeError

        soc_value = float(self.device_value)
        self.device_value = None
        self.log.debug(f"Battery SOC: {soc_value}%")

        if soc_value < 50:
            self.log.info("Battery needs to be charge before optimization")
            self.optim_charge_battery(inverter, "slow_charge")
        else:
            self.optim_charge_battery(inverter, "no_charge")
            self.log.info("Battery is ready for optimization. "
                          "No charge mode set")
            return True

        self.log.info("Scheduling next soc check in 30 minutes")
        next_soc_check_date = time_now + 1800
        if next_soc_check_date < (self.optim_date.timestamp()-180):
            self.soc_check_date = datetime.fromtimestamp(next_soc_check_date)
            self.scheduler.add_job(
                self.optim_soc_check,
                trigger="date",
                run_date=self.soc_check_date,
                id=f"optim_soc_check_inv_{inverter}",
                replace_existing=True,
                kwargs={"inverter": inverter}
            )
        self.scheduler_list_jobs()
        return True

    def _optim_strategy(self):
        """
        Determines and sets the optimization strategy for battery charging
        based on various conditions such as optimization status, dates,
        minimum price, and inverter availability. It schedules jobs for
        optimizing state of charge (SOC) checks and battery charging based
        on the current time and weather data.

        Returns:
            bool: True if the optimization strategy was set successfully or
                  if optimization is not needed, False if there are issues
                  with the optimization parameters.
        """
        if not self.optim:
            self.log.info("Optimization not needed")
            return True

        if not self.optim_date or not self.soc_check_date:
            self.log.error("Optimization dates not set")
            return False

        if not self.min_price:
            self.log.error("RCE minimal price price not set")
            return False

        if not hasattr(self, "inverters") or not self.inverters:
            self.log.error("No inverter list found")
            return False

        if self.min_price < 0:
            charging_mode = "fast_charge"
        else:
            charging_mode = "normal_charge"

        time_now = datetime.now().timestamp()
        if time_now > self.optim_date.timestamp():
            self.log.warning("Optimization time was missed")
            self.optim = False
            self.soc_check_date = None
            self.optim_date = None
            return True

        if time_now > self.soc_check_date.timestamp():
            self.soc_check_date = (datetime.fromtimestamp(time_now) +
                                   timedelta(seconds=30))

        for inverter in self.inverters:
            self.log.info("Setting optimization strategy for inverter nr"
                          f" {inverter}")
            if not (self.soc_check_date.timestamp() >
                    (self.optim_date.timestamp()-180)):
                self.scheduler.add_job(
                    self.optim_soc_check,
                    trigger="date",
                    run_date=self.soc_check_date,
                    id=f"optim_soc_check_inv_{inverter}",
                    replace_existing=True,
                    kwargs={"inverter": inverter}
                )
            self.scheduler.add_job(
                self.optim_charge_battery,
                trigger="date",
                run_date=self.optim_date,
                id=f"optim_charge_battery_inv_{inverter}",
                replace_existing=True,
                kwargs={"inverter": inverter, "mode": charging_mode}
            )
            if not (self.weather_data["sunrise_time"] >=
                    self.weather_data["sunset_time"]):
                self.scheduler.add_job(
                    self.optim_charge_battery,
                    trigger="date",
                    run_date=datetime.fromtimestamp(
                        self.weather_data["sunset_time"]
                    ),
                    id=f"eod_charge_battery_inv_{inverter}",
                    replace_existing=True,
                    kwargs={
                        "inverter": inverter,
                        "mode": "slow_charge",
                    }
                )
        self.log.info("Setting optimization strategy was successful")
        return True

    def optim_judge(self):
        """
        Evaluates weather data and energy prices to determine
        the optimization strategy.

        Raises:
            RuntimeError: If judge factors retrieval or optimization
                          strategy setup fails.
        """
        self.log.info("Getting weather data and energy prices")
        if not self._get_daily_judge_factors():
            self.log.warning("Failed to get judge factors")
            self.judge_date += timedelta(minutes=15)
            self.log.info(
                "Rescheduling optimization judge to "
                f"{self.judge_date.strftime('%d-%m-%Y %H:%M')}"
            )
            self.scheduler.add_job(
                self.optim_judge,
                trigger="date",
                run_date=self.judge_date,
                id="optim_judge",
                replace_existing=True)
            raise RuntimeError

        if self.judge_date.timestamp() > self.weather_data["sunrise_time"]:
            self.soc_check_date = self.judge_date + timedelta(minutes=2)
        else:
            self.soc_check_date = datetime.fromtimestamp(
                self.weather_data["sunrise_time"]
            )

        if self.not_cloudy:
            # https://www.youtube.com/watch?v=-Hv8fj8hQlE
            self.log.info("It'll be sunny day")
            self.optim = True
            self.optim_date = datetime.fromtimestamp(self.min_price_timestamp)
        else:
            # https://www.youtube.com/watch?v=aSLZFdqwh7E
            self.log.info("It'll be cloudy day")
            self.optim = False
            self.optim_date = None
            self.soc_check_date = None

        self.log.debug(f"Optim flag: {self.optim}")
        self.log.debug(f"Optim date: {self.optim_date}")
        self.log.debug(f"State of charge check date: {self.soc_check_date}")
        self.log.info("Setting up optimization strategy")
        if not self._optim_strategy():
            self.log.error("Setting optimization strategy failed")
            raise RuntimeError

        self.log.info("Scheduling tomorrow's optimization judge")
        # Based on publication dates tomorrow 4:06AM UTC

        self.judge_date = (
            datetime.now().astimezone(ZoneInfo("UTC")).replace(
                hour=4, minute=6, second=0, microsecond=0
            ) + timedelta(days=1)
        )
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

        Raises:
            SystemExit: Exits the program if no jobs are scheduled.
        """
        self._shine_setup()

        time_now = datetime.now().astimezone(ZoneInfo("UTC"))
        self.judge_date = time_now.replace(
            hour=4, minute=6, second=0, microsecond=0
        )
        if time_now.timestamp() > self.judge_date.timestamp():
            self.judge_date += timedelta(days=1)

        self.log.info("Scheduling optimization judge to "
                      f"{self.judge_date.strftime('%d-%m-%Y %H:%M')}")
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
