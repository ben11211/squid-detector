# bin/

Run from the repo root with the venv active (`source .venv/bin/activate`).

## Local config

`~/.config/homelab/`, one value per file, mode 600:

| File | Used by | Value |
|---|---|---|
| `ha_host` | both | HA IP or hostname (InfluxDB add-on runs there); `HA_HOST` env overrides |
| `ha_token` | `hactl.py` | HA long-lived access token of an **admin** user (HA → Profile → Security) |
| `wifi_ssid`, `wifi_password` | `make_secrets.sh` | 2.4 GHz Wi-Fi |
| `esphome_api_key`, `ota_password`, `influx_esp_password` | `make_secrets.sh` | `noise-indoor` |
| `outdoor_esphome_api_key`, `outdoor_ota_password`, `influx_esp_outdoor_password` | `make_secrets.sh` | `noise-outdoor` |

Generate keys:

```bash
openssl rand -base64 32 > ~/.config/homelab/esphome_api_key   # ESPHome API encryption key
openssl rand -hex 12 > ~/.config/homelab/ota_password           # OTA / Influx passwords
chmod 600 ~/.config/homelab/*
```

## make_secrets.sh

Writes `esphome/secrets.yaml` (git-ignored) from the files above. Never prints values. Alternative: fill in `esphome/secrets.example.yaml` by hand.

```bash
bin/make_secrets.sh
```

## hactl.py

Admin for HA, its Supervisor and add-ons from the terminal. Reads `ha_host` and `ha_token`.

| Command | Does |
|---|---|
| `bin/hactl.py influx "QUERY" [--db DB]` | InfluxQL as InfluxDB admin (via the add-on's Chronograf proxy) |
| `bin/hactl.py supervisor METHOD ENDPOINT [JSON]` | HA Supervisor API (relayed over HA's WebSocket) |
| `bin/hactl.py addon SLUG METHOD PATH [JSON\|@file]` | an add-on's web API through HA ingress |
| `bin/hactl.py add-esphome HOST KEY_FILE` | add an ESPHome device to HA with its API key |

Add-on slugs: `bin/hactl.py supervisor get /addons`. Defaults used here: InfluxDB `a0d7b954_influxdb`, Grafana `a0d7b954_grafana`, ESPHome `5c53de3b_esphome`.

### InfluxDB

```bash
bin/hactl.py influx "SHOW DATABASES"
bin/hactl.py influx "CREATE USER esp WITH PASSWORD '$(cat ~/.config/homelab/influx_esp_password)'"
bin/hactl.py influx "GRANT WRITE ON noise TO esp"
bin/hactl.py influx "SELECT count(laeq_1s) FROM noise WHERE time > now() - 5m GROUP BY location" --db noise
```

### Supervisor

```bash
bin/hactl.py supervisor get /core/info                                  # HA version, update available
bin/hactl.py supervisor get /addons/a0d7b954_influxdb/info              # add-on state, options, ports
bin/hactl.py supervisor post /store/addons/a0d7b954_grafana/install     # install an add-on
bin/hactl.py supervisor post /addons/a0d7b954_grafana/options '{"boot": "auto", "watchdog": true}'
```

### Grafana (add-on API via ingress; ingress user is admin)

Data source:

```bash
bin/hactl.py addon a0d7b954_grafana post /api/datasources '{
  "name": "InfluxDB noise", "uid": "influx-noise", "type": "influxdb", "access": "proxy",
  "url": "http://a0d7b954-influxdb:8086", "user": "grafana",
  "jsonData": {"dbName": "noise", "httpMode": "POST"},
  "secureJsonData": {"password": "..."}}'
```

Import a v1 dashboard:

```bash
python3 -c 'import json; print(json.dumps({"dashboard": json.load(open("grafana/road-noise.json")), "overwrite": True}))' > /tmp/dash.json
bin/hactl.py addon a0d7b954_grafana post /api/dashboards/db @/tmp/dash.json
```

Import a v2 dashboard (tabs; Grafana 12+):

```bash
bin/hactl.py addon a0d7b954_grafana post /apis/dashboard.grafana.app/v2/namespaces/default/dashboards @grafana/road-noise-all.json
```

Export (after editing in Grafana):

```bash
bin/hactl.py addon a0d7b954_grafana get /apis/dashboard.grafana.app/v2/namespaces/default/dashboards/road-noise-all > grafana/road-noise-all.json
```

### ESPHome device → HA

```bash
bin/hactl.py add-esphome noise-outdoor.local ~/.config/homelab/outdoor_esphome_api_key
```
