# sound-level-logger

ESP32 + INMP441 (A-weighted dB) + BME280 → InfluxDB 1.x (1 s) + Home Assistant (10 min) → Grafana.

## Units

| Name | Influx tag | HA entities | Influx user |
|---|---|---|---|
| `noise-indoor` | `location=indoor` | `sensor.noise_indoor_*` | `esp` |
| `noise-outdoor` | `location=outdoor` | `sensor.noise_outdoor_*` | `esp_outdoor` |

## Wiring

| Sensor | ESP32 |
|---|---|
| INMP441 VDD / GND / L/R | 3V3 / GND / GND |
| INMP441 WS / SCK / SD | GPIO18 / GPIO23 / GPIO19 |
| BME280 VCC / GND / SDA / SCL | 3V3 / GND / GPIO21 / GPIO22 (I²C 0x76) |

## Layout

| Path | |
|---|---|
| `esphome/noise-common.yaml` | all firmware logic |
| `esphome/noise-{indoor,outdoor}.yaml` | name, tag, credentials |
| `esphome/secrets.yaml` | generated, git-ignored |
| `esphome/secrets.example.yaml` | template for `secrets.yaml` |
| `bin/make_secrets.sh` | builds `secrets.yaml` from `~/.config/homelab/*` |
| `bin/homelab.py` | CLI: `influx` (InfluxQL as admin), `supervisor` (HA Supervisor API), `addon` (add-on web API via ingress), `add-esphome` |
| `grafana/*.json` | dashboard exports (`road-noise`, `road-noise-all`) |

## Local config (`~/.config/homelab/`, mode 600, not in repo)

| File | Used for |
|---|---|
| `ha_host` | HA / InfluxDB host (IP or name); `HA_HOST` env overrides |
| `ha_token` | HA long-lived access token (admin) |
| `wifi_ssid`, `wifi_password` | 2.4 GHz Wi-Fi |
| `esphome_api_key`, `ota_password` | `noise-indoor` API key (32 B base64), OTA |
| `outdoor_esphome_api_key`, `outdoor_ota_password` | `noise-outdoor` |
| `influx_esp_password`, `influx_esp_outdoor_password` | Influx write users |

ESPHome CLI: `~/.venvs/esphome/bin/esphome` (`python3 -m venv ~/.venvs/esphome && ~/.venvs/esphome/bin/pip install esphome websockets`).
Requires HA add-ons: ESPHome, InfluxDB (1.x), Grafana. Influx users: `esp`/`esp_outdoor` WRITE `noise`; Grafana: READ.

## Data

| Store | Contents | Retention |
|---|---|---|
| Influx `noise` | `noise` measurement: `laeq_1s`, `lafmax_1s`, tag `location` | 2 y |
| Influx `homeassistant` | all HA entities, measurement = unit, tag `entity_id`, field `value` | 180 d |
| HA | LAeq/LAmax/LAmin 10 min, loud events (>75 dBA), temp/hum/pressure, Wi-Fi, backlog | recorder |

Influx write: `http://<ha_host>:8086/write?db=noise&precision=s`, `Authorization: Basic` header (not URL; ESPHome logs URLs on error).

## Commands

```bash
bin/make_secrets.sh                                           # regenerate secrets.yaml
cd esphome
~/.venvs/esphome/bin/esphome config noise-outdoor.yaml        # validate
~/.venvs/esphome/bin/esphome run noise-outdoor.yaml --device /dev/cu.usbserial-0001   # first flash (USB)
~/.venvs/esphome/bin/esphome run noise-outdoor.yaml --device noise-outdoor.local --no-logs   # OTA
~/.venvs/esphome/bin/esphome logs noise-outdoor.yaml --device noise-outdoor.local     # live log
~/.venvs/esphome/bin/python ../bin/homelab.py influx 'SELECT * FROM noise ORDER BY time DESC LIMIT 5' --db noise
```

Change to `noise-common.yaml` → OTA both units.

## Config

| Setting | Value |
|---|---|
| Sample rate | 48 kHz, 32-bit, I²S `channel: left` |
| Upload | every 15 s, ≤300 points/series |
| Offline buffer | 2400 s |
| Loud event | LAFmax ≥ 75 dBA, 3 dB hysteresis |
| `mic_offset` | 0 dB (uncalibrated) |
