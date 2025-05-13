### Imports
import datetime
import json
import logging
import os
import socket
import subprocess
import threading
import time
from xml.etree import ElementTree
# end stdlib
import requests
from flask import Flask
from flask_wtf.csrf import CSRFProtect

HA_TOKEN = os.getenv('HA_TOKEN')
if not HA_TOKEN:
    print('App cannot start without an HA_TOKEN.')
    exit(1)
WEATHER_TOKEN = os.getenv('WEATHER_TOKEN')
if not WEATHER_TOKEN:
    print('App cannot start without a WEATHER_TOKEN.')
    exit(1)

### Global Vars
APP_NAME = 'statd'
DEBUG = False
HA_API = 'https://mccormicom.com:8123/api'
HEADERS = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "content-type": "application/json"
    }
RUN = True

## Init
# Pull current time and timezone.
now = time.localtime()
if now.tm_isdst:
    tz = time.tzname[1]
else:
    tz = time.tzname[0]

# Set up the logger.
format = "%(asctime)s [" + APP_NAME + "] %(levelname)s %(message)s"
datefmt = "[%Y-%m-%dT%H:%M:%S " + tz + "]"
log = logging.getLogger(APP_NAME)
formatter = logging.Formatter(format, datefmt=datefmt)
consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(formatter)
log.addHandler(consoleHandler)
log.setLevel(logging.INFO)
log.propagate = False
if DEBUG:
    log.setLevel(logging.DEBUG)
else:
    flask_log = logging.getLogger('werkzeug')
    flask_log.disabled = False

app = Flask(__name__)
csrf = CSRFProtect()
csrf.init_app(app)
states = {}
weather = {}
poll_world_weather = True

### Global Functions
def gen_timestamp():
    now = datetime.datetime.now()
    return now.isoformat().split('T')[1].split('.')[0]

def start_threads():
    wuptime = None
    while RUN:
        hthread = threading.Thread(target=fetch_ha_states)
        hthread.start()
        now = datetime.datetime.now()
        if wuptime:
            delta = now.timestamp() - wuptime.timestamp()
            if delta > 899:
                wthread = threading.Thread(target=refresh_worldweather)
                wthread.start()
                wuptime = datetime.datetime.now()
        if not wuptime:
            wthread = threading.Thread(target=refresh_worldweather)
            wthread.start()
            wuptime = datetime.datetime.now()
        time.sleep(30)

def refresh_worldweather():
    global poll_world_weather
    if not poll_world_weather:
        return
    log.info('Fetching states from WeatherWorld.')
    zipcode = 63021
    url = f'https://api.worldweatheronline.com/premium/v1/weather.ashx?key={WEATHER_TOKEN}&q={zipcode}'
    resp = requests.request('GET', url)
    if resp.status_code == 429:
        log.error('WorldWeather API calls used up for the day.')
        poll_world_weather = False
        return
    xml_data = ElementTree.fromstring(resp.text)
    weather['timestamp'] = datetime.datetime.now().isoformat().split('.')[0]
    weather['today_date'] = weather['timestamp'].split('T')[0]
    tomorrow_timestamp = datetime.datetime.now() + datetime.timedelta(days=1)
    weather['tomorrow_timestamp'] = tomorrow_timestamp.isoformat().split('.')[0]
    weather['tomorrow_date'] = weather['tomorrow_timestamp'].split('T')[0]
    plus_2_timestamp = datetime.datetime.now() + datetime.timedelta(days=2)
    weather['plus_2_timestamp'] = plus_2_timestamp.isoformat().split('.')[0]
    weather['plus_2_date'] = weather['plus_2_timestamp'].split('T')[0]
    plus_3_timestamp = datetime.datetime.now() + datetime.timedelta(days=3)
    weather['plus_3_timestamp'] = plus_3_timestamp.isoformat().split('.')[0]
    weather['plus_3_date'] = weather['plus_3_timestamp'].split('T')[0]
    for branch in xml_data:
        if branch.tag == 'weather':
            for branch_l2 in branch:
                if branch_l2.tag == 'date' and branch_l2.text == weather['today_date']:
                    today_weather = branch
                elif branch_l2.tag == 'date' and branch_l2.text == weather['tomorrow_date']:
                    tomorrow_weather = branch
                elif branch_l2.tag == 'date' and branch_l2.text == weather['plus_2_date']:
                    plus_2_weather = branch
                elif branch_l2.tag == 'date' and branch_l2.text == weather['plus_3_date']:
                    plus_3_weather = branch
    for branch in today_weather:
        if branch.tag == 'mintempF':
            weather['today_low_temp'] = branch.text
        if branch.tag == 'maxtempF':
            weather['today_high_temp'] = branch.text
        if branch.tag == 'sunHour':
            weather['today_sunhours'] = branch.text
    for branch in tomorrow_weather:
        if branch.tag == 'mintempF':
            weather['tomorrow_low_temp'] = branch.text
        if branch.tag == 'maxtempF':
            weather['tomorrow_high_temp'] = branch.text
        if branch.tag == 'sunHour':
            weather['tomorrow_sunhours'] = branch.text
    for branch in plus_2_weather:
        if branch.tag == 'mintempF':
            weather['plus_2_low_temp'] = branch.text
        if branch.tag == 'maxtempF':
            weather['plus_2_high_temp'] = branch.text
        if branch.tag == 'sunHour':
            weather['plus_2_sunhours'] = branch.text
    for branch in plus_3_weather:
        if branch.tag == 'mintempF':
            weather['plus_3_low_temp'] = branch.text
        if branch.tag == 'maxtempF':
            weather['plus_3_high_temp'] = branch.text
        if branch.tag == 'sunHour':
            weather['plus_3_sunhours'] = branch.text

    return weather

def fetch_ha_states():
    # Fetch states
    log.info('Fetching states from HomeAssistant.')
    url = HA_API + '/states'
    resp = requests.request('GET', url, headers=HEADERS)
    state_list = json.loads(resp.text)

    # Process states
    for item in state_list:
        if item['entity_id'] == 'sensor.washer_1min':
            rounded_reading = float(item['state']) // 1
            msg = str(rounded_reading) + 'W/min'
            states['washer_1min'] = msg
        if item['entity_id'] == 'sensor.washer_1mon':
            rounded_reading = float(item['state']) // 1
            msg = str(rounded_reading) + 'KWh/mon'
            states['washer_1mon'] = msg
            washer_cost = round(rounded_reading * 0.092, 2)
            cost_msg = str(washer_cost) + '/mon'
            states['washer_1mon_cost'] = cost_msg
        if item['entity_id'] == 'sensor.dryer_1min':
            rounded_reading = float(item['state']) // 1
            msg = str(rounded_reading) + 'W/min'
            states['dryer_1min'] = msg
        if item['entity_id'] == 'sensor.dryer_1mon':
            rounded_reading = float(item['state']) // 1
            msg = str(rounded_reading) + 'KWh/mon'
            states['dryer_1mon'] = msg
            dryer_cost = round(rounded_reading * 0.092, 2)
            dryer_cost_msg = str(dryer_cost) + '/mon'
            states['dryer_1mon_cost'] = dryer_cost_msg
        if item['entity_id'] == 'weather.forecast_home':
            states['weather'] = item['state']
            temperat = str(item['attributes']['temperature']) + item['attributes']['temperature_unit']
            states['temperature'] = temperat
            hum = str(item['attributes']['humidity']) + '%'
            states['humidity'] = hum
            uv = str(item['attributes']['uv_index'])
            states['uv'] = uv
        if item['entity_id'] == 'sensor.air_detector_humidity':
            states['indoor_humidity'] = str(int(float(item['state']))) + '%'
        if item['entity_id'] == 'sensor.air_detector_temperature':
            states['indoor_temperature'] = item['state'] + item['attributes']['unit_of_measurement']
        if item['entity_id'] == 'vacuum.roomba':
            states['roomba_status'] = item['state']
            if 'battery_level' in item['attributes']:
                states['roomba_battery'] = str(item['attributes']['battery_level']) + '%'
            else:
                states['roomba_battery'] = '0%'
            if 'bin_full' in item['attributes']:
                states['roomba_bin_full'] = str(item['attributes']['bin_full'])
            else:
                states['roomba_bin_full'] = '?'

@app.route('/')
def hello():
    return('OK')

@app.route('/states/all')
def states_all():
    return states | weather

### Main
if __name__ == "__main__":
    thread = threading.Thread(target=start_threads)
    thread.start()
    app.run(host='0.0.0.0')
