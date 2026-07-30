# Optim Shine

Optim Shine is a tool designed to optimize energy storage systems (ESS)
for efficient energy management using the FelicitySolar Shine API.
It retrieves weather data and energy prices to define an optimization strategy.

It can also drive a Canaan Avalon Q crypto miner, using surplus energy to mine
whenever that is worth more than selling the energy to the grid.

In the base strategy, each day the tool:
1. Checks the weather.
2. Judge if optimization is needed based on cloud level for plant location.
3. Gets RCE energy prices.
4. Sets charging strategy for energy storage systems.
5. Decides whether the miner should run, and in which operating mode.

The strategy is then re-evaluated every 15 minutes, using a separate daytime
and nighttime pass:

* **Day.** Combines the current RCE price, the cloud cover, the battery state
  of charge and the PV production. A negative energy price means fast charging
  and mining in Super mode. Otherwise the battery is charged according to how
  full it is and how close sunset is, and the miner runs only when mining beats
  the current RCE price and the PV production covers a mode's consumption.
* **Night.** Mines in Eco mode while the battery is above 35%, otherwise the
  miner is stopped.

Mining profitability is compared against the RCE price per operating mode. Among
the modes that beat the grid price, the least profitable one is chosen, so the
miner runs in the most conservative mode that is still worth running.

## Project Setup

1. Clone the project
```bash
git clone git@github.com:Asiderr/optimshine.git
cd optimshine
```

2. Create a python virtual environment
```bash
python -m venv venv
```

3. Activate the virtual environment
```bash
source venv/bin/activate
```

4. Install dependencies
```bash
pip install -r requirements.txt
```

5. Create your own `.env` configuration file based on
  [tests/.testenv](tests/.testenv) file.
  * Required Variables:
    - **SHINE_USER:** The username for accessing the SHINE system.
    - **SHINE_PASSWORD:** The password for the SHINE user.
    - **COINGECKO_API_KEY:** API key used to fetch the BTC price in PLN, needed
      to compute mining profitability.
    - **MINER_IP:** The IPv4 address of the Avalon Q miner.
  * Optional Variables:
    - **SHINE_PLANT:** The plant identifier for the SHINE system.
      Not required if you have only one plant.
    - **MINER_PORT:** The CGMiner API TCP port of the miner.
      Defaults to `4028` when unset.

  `.env` is listed in `.gitignore`, so your credentials stay out of the
  repository. Keep them there rather than in `tests/.testenv`, which is
  committed.


## Example usage

Use following command to run the program
```bash
python -m optimshine.optim_shine
```

You can also create your own linux service based on the following example:
[examples/optim-shine.service.example](examples/optim-shine.service.example).

## Testing

To test the project use a unittest module
```
python -m unittest discover
```

You can test single module using following command
```
python -m unittest -v tests.test_api_weather
```

The suite also runs under pytest, which gives shorter output:
```
python -m pytest tests/ -q
```

All tests use mocks, so no network access or hardware is required. One test is
skipped by default: the real-hardware integration test described below. Use
`-rs` to see the skip reason.

### Testing against a real miner

`TestApiMinerIntegration` in [tests/test_api_miner.py](tests/test_api_miner.py)
talks to an actual Avalon Q instead of a mocked socket. It is skipped unless a
non-empty `MINER_IP` is present in the environment.

Because the guard is evaluated at import time and `load_dotenv` does not
override already-set variables, pass the values on the command line:
```
MINER_IP=192.168.1.10 COINGECKO_API_KEY=cg-your-key python -m pytest tests/ -q
```

To run only the hardware test, with log output visible:
```
MINER_IP=192.168.1.10 COINGECKO_API_KEY=cg-your-key \
  python -m pytest tests/test_api_miner.py -k TestApiMinerIntegration -v -s
```

Both variables are required. `COINGECKO_API_KEY` is validated before the miner
address, so a missing key fails the test before any connection is attempted.

Note that this test writes to the miner: it sends a real `set_mode` command. It
reads the active mode first and targets that same mode, restoring it afterwards,
so on a healthy miner it is close to a no-op. If the active mode cannot be
determined the test falls back to `Standard` and does not restore, so it is
worth confirming the mode afterwards.

### Coverage

To check test coverage use
```
coverage run --source=optimshine -m unittest discover
coverage report -m
```

To generate the browsable HTML report in `htmlcov/`
```
coverage html
```

## License

This project is licensed under the GNU Lesser General Public License v3.0
or later (LGPL-3.0-or-later).

You are free to use, modify, and redistribute this software under the terms
of the license. See the [COPYING](./COPYING) file or visit
[https://www.gnu.org/licenses/lgpl-3.0.html](https://www.gnu.org/licenses/lgpl-3.0.html)
for full details.

