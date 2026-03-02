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
import pytz
import pyemvue
from pyemvue.enums import Scale, Unit

HA_TOKEN = os.getenv('HA_TOKEN')
if not HA_TOKEN:
    print('App cannot start without an HA_TOKEN.')
    exit(1)
WEATHER_TOKEN = os.getenv('WEATHER_TOKEN')
if not WEATHER_TOKEN:
    print('App cannot start without a WEATHER_TOKEN.')
    exit(1)
PLEX_TOKEN = os.getenv('PLEX_TOKEN')
if not PLEX_TOKEN:
    print('App cannot start without a PLEX_TOKEN.')
    exit(1)
EMPORIA_USERNAME = os.getenv('EMPORIA_USERNAME')
if not EMPORIA_USERNAME:
    print('App cannot start without an EMPORIA_USERNAME.')
    exit(1)
EMPORIA_PASSWORD = os.getenv('EMPORIA_PASSWORD')
if not EMPORIA_PASSWORD:
    print('App cannot start without an EMPORIA_PASSWORD.')
    exit(1)

### Global Vars
APP_NAME = 'statd'
DEBUG    = False
RUN      = True
HA_API   = 'https://mccormicom.com:8123/api'
PLEX_API = 'http://mccormicom.com:32400/'
HEADERS  = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "content-type": "application/json"
    }

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
plex = {}
emporia = {}
poll_world_weather = True

### Global Functions
def start_threads():
    # There is a good chance that HomeAssistant is restarting along with statd.
    # Pause for a moment to give HA time to wake up.
    time.sleep(1)
    wuptime = None
    while RUN:
        #hthread = threading.Thread(target=fetch_ha_states)
        #hthread.start()
        empthread = threading.Thread(target=refresh_emporia_data)
        empthread.start()
        psthread = threading.Thread(target=refresh_plex_streams, args=(PLEX_TOKEN,))
        psthread.start()
        prthread = threading.Thread(target=refresh_plex_recently_added, args=(PLEX_TOKEN,))
        prthread.start()
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
        time.sleep(5)

def convert_to_central_time(utc_string):
    utc_time = datetime.datetime.fromisoformat(utc_string)
    chicago = pytz.timezone('America/Chicago')
    chicago_time = utc_time.replace(tzinfo=pytz.utc).astimezone(chicago)
    return chicago_time

def gen_timestamp():
    now = datetime.datetime.now()
    return now.isoformat().split('T')[1].split('.')[0]

def calc_wind_arrow(bearing):
    if bearing > 330:
        dir = 'North'
    elif bearing > 300:
        dir = 'Northwest'
    elif bearing > 240:
        dir = 'West'
    elif bearing > 200:
        dir = 'Southwest'
    elif bearing > 150:
        dir = 'South'
    elif bearing > 120:
        dir = 'Southeast'
    elif bearing > 70:
        dir = 'East'
    elif bearing > 20:
        dir = 'Northeast'
    else:
        dir = 'North'

    if dir == 'West':
        return '\u2190'
    elif dir == 'North':
        return '\u2191'
    elif dir == 'East':
        return '\u2192'
    elif dir == 'South':
        return '\u2193'
    elif dir == 'Northwest':
        return '\u2196'
    elif dir == 'Northeast':
        return '\u2197'
    elif dir == 'Southeast':
        return '\u2198'
    elif dir == 'Southwest':
        return '\u2199'

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
    timestamp = datetime.datetime.now().isoformat().split('.')[0]
    today_date = timestamp.split('T')[0]

    # Fetch states
    log.info('Fetching states from HomeAssistant.')
    url = HA_API + '/states'
    resp = requests.request('GET', url, headers=HEADERS)
    state_list = json.loads(resp.text)

    # Process states
    for item in state_list:
        # Sun and Weather
        if item['entity_id'] == 'sensor.sun_next_rising':
            chicago_time = convert_to_central_time(item['state'])
            next_dawn = chicago_time.isoformat().split('T')[1].split('-')[0]
            states['next_dawn'] = next_dawn
        if item['entity_id'] == 'sensor.sun_next_setting':
            chicago_time = convert_to_central_time(item['state'])
            next_dusk = chicago_time.isoformat().split('T')[1].split('-')[0]
            states['next_dusk'] = next_dusk
        if item['entity_id'] == 'sun.sun':
            states['sun_status'] = item['state']
        if item['entity_id'] == 'weather.forecast_home':
            states['weather'] = item['state']
            temperat = str(item['attributes']['temperature']) + item['attributes']['temperature_unit']
            states['temperature'] = temperat
            hum = str(item['attributes']['humidity']) + '%'
            states['humidity'] = hum
            uv = str(item['attributes']['uv_index'])
            states['uv'] = uv
            pressure = str(item['attributes']['pressure']) + item['attributes']['pressure_unit']
            states['pressure'] = pressure
            wind_speed = str(item['attributes']['wind_speed']) + item['attributes']['wind_speed_unit']
            wind_arrow = calc_wind_arrow(int(item['attributes']['wind_bearing']))
            wind = wind_speed + ' ' + wind_arrow + str(int(item['attributes']['wind_bearing']))
            states['wind'] = wind
        if item['entity_id'] == 'calendar.united_states_mo':
            holiday = item['attributes']['message']
            holiday_start = item['attributes']['start_time']
            holiday_start_trim = holiday_start.split(' ')[0]
            if today_date == holiday_start_trim:
                holiday_flashy = f"* {holiday} *"
                holiday_trim = holiday_flashy
                states['holiday'] = holiday_trim
        # Laundry
        if item['entity_id'] == 'switch.switch_washer':
            states['washer_switch'] = item['state']
        if item['entity_id'] == 'switch.switch_dryer':
            states['dryer_switch'] = item['state']
        if item['entity_id'] == 'sensor.washer_1min':
            rounded_reading = float(item['state']) // 1
            msg = str(rounded_reading) + 'W/min'
            states['washer_1min'] = msg
        if item['entity_id'] == 'sensor.washer_1mon':
            rounded_reading = float(item['state']) // 1
            msg = str(rounded_reading) + 'KWh/mon'
            states['washer_1mon'] = msg
            washer_cost = round(rounded_reading * 0.092, 2)
            cost_msg = '$' + str(washer_cost) + '/mon'
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
            dryer_cost_msg = '$' + str(dryer_cost) + '/mon'
            states['dryer_1mon_cost'] = dryer_cost_msg
        # Indoor Conditions and Air
        if item['entity_id'] == 'switch.air_filter':
            states['air_filter'] = item['state']
        if item['entity_id'] == 'sensor.air_detector_battery':
            states['air_detector_battery'] = str(int(float(item['state']))) + '%'
        if item['entity_id'] == 'sensor.air_detector_humidity':
            states['indoor_humidity'] = str(int(float(item['state']))) + '%'
        if item['entity_id'] == 'sensor.air_detector_temperature':
            states['indoor_temperature'] = item['state'] + item['attributes']['unit_of_measurement']
        if item['entity_id'] == 'sensor.air_detector_carbon_dioxide':
            states['air_detector_carbon_dioxide'] = item['state'] + item['attributes']['unit_of_measurement']
        if item['entity_id'] == 'sensor.air_detector_formaldehyde':
            states['air_detector_formaldehyde'] = item['state'] + item['attributes']['unit_of_measurement']
        if item['entity_id'] == 'sensor.air_detector_pm2_5':
            states['air_detector_pm2_5'] = item['state'] + item['attributes']['unit_of_measurement']
        if item['entity_id'] == 'sensor.air_detector_vocs':
            states['air_detector_vocs'] = item['state'] + item['attributes']['unit_of_measurement']
        # Devices
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
        if item['entity_id'] == 'switch.fan':
            states['fan_switch'] = item['state']
        if item['entity_id'] == 'switch.living_room_nw_corner':
            states['living_room_lights_nw_corner'] = item['state']
        if item['entity_id'] == 'switch.living_room_sw_corner':
            states['living_room_lights_sw_corner'] = item['state']
        if item['entity_id'] == 'sensor.canon_lbp632c_canon_cartridge_067_black_toner':
            states['printer_black_toner'] = item['state'] + '%'
        if item['entity_id'] == 'sensor.canon_lbp632c_canon_cartridge_067_cyan_toner':
            states['printer_cyan_toner'] = item['state'] + '%'
        if item['entity_id'] == 'sensor.canon_lbp632c_canon_cartridge_067_magenta_to':
            states['printer_magenta_toner'] = item['state'] + '%'
        if item['entity_id'] == 'sensor.canon_lbp632c_canon_cartridge_067_yellow_ton':
            states['printer_yellow_toner'] = item['state'] + '%'
        if item['entity_id'] == 'switch.main_tv':
            states['main_tv_status'] = item['state']
        # Automations
        if item['entity_id'] == 'automation.notify_when_laundry_washer_is_done':
            initial_timestamp = item['attributes']['last_triggered']
            chicago_time = convert_to_central_time(initial_timestamp)
            timestamp = chicago_time.isoformat().split('.')[0]
            states['washer_done_last_fired'] = timestamp
        if item['entity_id'] == 'automation.notify_when_laundry_dryer_is_done':
            initial_timestamp = item['attributes']['last_triggered']
            chicago_time = convert_to_central_time(initial_timestamp)
            timestamp = chicago_time.isoformat().split('.')[0]
            states['dryer_done_last_fired'] = timestamp
        # Media
        if item['entity_id'] == 'sensor.beastnas_plex':
            states['plex_stream_count'] = item['state']
        if item['entity_id'] == 'sensor.sabnzbd_status':
            states['sab_status'] = item['state']
        if item['entity_id'] == 'number.sabnzbd_speedlimit':
            states['sab_speedlimit'] = item['state']
        if item['entity_id'] == 'sensor.sabnzbd_speed':
            speed = str(round(float(item['state']), 1))
            unit = item['attributes']['unit_of_measurement']
            states['sab_speed'] = f'{speed} {unit}'
        if item['entity_id'] == 'sensor.sabnzbd_queue_count':
            states['sab_queue'] = item['state']
        if item['entity_id'] == 'sensor.sabnzbd_total_disk_space':
            total_disk = round(float(item['state']) / 1000, 2)
            states['sab_total_disk'] = total_disk
        if item['entity_id'] == 'sensor.sabnzbd_free_disk_space':
            rounded_reading = round(float(item['state']) / 1000, 2)
            rounded_reading_str = str(rounded_reading)
            total_disk_str = str(states['sab_total_disk'])
            states['nas_free_disk'] = f'{rounded_reading_str}/{total_disk_str}TB'
        if item['entity_id'] == 'sensor.deluge_download_speed':
            states['deluge_download_speed'] = item['state'] + item['attributes']['unit_of_measurement']
        if item['entity_id'] == 'sensor.deluge_upload_speed':
            states['deluge_upload_speed'] = item['state'] + item['attributes']['unit_of_measurement']
        if item['entity_id'] == 'sensor.deluge_status':
            states['deluge_status'] = item['state']

def refresh_plex_recently_added(PLEX_TOKEN):
    log.info('Refreshing plex recently added.')
    headers = {'X-Plex-Token': PLEX_TOKEN}
    try:
        plex_recently_added_xml = requests.get(PLEX_API + 'library/sections/2/newest', headers=headers)
    except ConnectionError:
        log.warning('Plex appears to be down.')
        return
    tv_xml = ElementTree.fromstring(plex_recently_added_xml.text)

    tvshows = []
    for item in tv_xml:
        new_episode = {}
        new_episode['season_name'] = item.attrib['parentTitle'].replace('Season ', 'S')
        new_episode['episode_number'] = item.attrib['index']
        if 'updatedAt' in item.attrib.keys():
            new_episode['epoch_updated'] = item.attrib['updatedAt']
        new_episode['epoch_added'] = item.attrib['addedAt']
        new_episode['show_name'] = item.attrib['grandparentTitle']
        tvshows.append(new_episode)

    try:
        plex_recently_added_xml = requests.get(PLEX_API + 'library/sections/1/newest', headers=headers)
    except ConnectionError:
        log.warning('Connection to Plex failed.')
        return
    movie_xml = ElementTree.fromstring(plex_recently_added_xml.text)

    movies = []
    for item in movie_xml:
        new_movie = {}
        new_movie['title'] = item.attrib['title']
        new_movie['year'] = item.attrib['year']
        new_movie['epoch_added'] = item.attrib['addedAt']
        movies.append(new_movie)

    movies = sorted(movies, key=lambda d: d['epoch_added'], reverse=True)
    tvshows = sorted(tvshows, key=lambda d: d['epoch_added'], reverse=True)

    plex['new'] = {}
    if len(movies) == 0:
        plex['new']['movies'] = []
    elif len(movies) == 1:
        new_movie = movies[0]['year'] + ' ' + movies[0]['title']
        plex['new']['movies'] = new_movie
    elif len(movies) == 2:
        new_movie = movies[0]['year'] + ' ' + movies[0]['title']
        new_movie2 = movies[1]['year'] + ' ' + movies[1]['title']
        plex['new']['movies'] = new_movie + '\n' + new_movie2
    else:
        new_movie = movies[0]['year'] + ' ' + movies[0]['title']
        new_movie2 = movies[1]['year'] + ' ' + movies[1]['title']
        new_movie3 = movies[2]['year'] + ' ' + movies[2]['title']
        plex['new']['movies'] = new_movie + '\n' + new_movie2 + '\n' + new_movie3
    if len(tvshows) == 0:
        plex['new']['episodes'] = []
    elif len(tvshows) == 1:
        new_episode =  tvshows[0]['show_name'] + ' ' + tvshows[0]['season_name'] + 'E' + tvshows[0]['episode_number']
        plex['new']['episodes'] = new_episode
    elif len(tvshows) == 2:
        new_episode =  tvshows[0]['show_name'] + ' ' + tvshows[0]['season_name'] + 'E' + tvshows[0]['episode_number']
        new_episode2 = tvshows[1]['show_name'] + ' ' + tvshows[1]['season_name'] + 'E' + tvshows[1]['episode_number']
        plex['new']['episodes'] = new_episode + '\n' + new_episode2
    else:
        new_episode =  tvshows[0]['show_name'] + ' ' + tvshows[0]['season_name'] + 'E' + tvshows[0]['episode_number']
        new_episode2 = tvshows[1]['show_name'] + ' ' + tvshows[1]['season_name'] + 'E' + tvshows[1]['episode_number']
        new_episode3 = tvshows[2]['show_name'] + ' ' + tvshows[2]['season_name'] + 'E' + tvshows[2]['episode_number']
        plex['new']['episodes'] = new_episode + '\n' + new_episode2 + '\n' + new_episode3
    log.info('Finished refreshing plex recently added.')

def refresh_plex_streams(PLEX_TOKEN):
    log.info('Fetching stream states from plex.')
    headers = {'X-Plex-Token': PLEX_TOKEN}
    try:
        plex_sessions_xml = requests.get(PLEX_API + 'status/sessions', headers=headers)
    except ConnectionError:
        log.warning('Plex appears to be down.')
        return
    xml_tree = ElementTree.fromstring(plex_sessions_xml.text)
    streams = []
    for stream in xml_tree:
        stream_item = {}
        stream_item['type'] = stream.attrib['type']
        stream_item['title'] = stream.attrib['title']
        if 'parentTitle' in stream.attrib.keys():
            if stream_item['type'] == 'episode':
                stream_item['season'] = stream.attrib['parentTitle']
            elif stream_item['type'] == 'track':
                stream_item['album'] = stream.attrib['parentTitle']
        if 'grandparentTitle' in stream.attrib.keys():
            if stream_item['type'] == 'episode':
                stream_item['tv_show'] = stream.attrib['grandparentTitle']
            elif stream_item['type'] == 'track':
                stream_item['artist'] = stream.attrib['grandparentTitle']
            else:
                stream_item['grandparent'] = stream.attrib['grandparentTitle']
        for child in stream:
            if child.tag == 'User' and 'title' in child.attrib.keys():
                stream_item['user'] = child.attrib['title']
            if child.tag == 'Media' and 'videoResolution' in child.attrib.keys():
                stream_item['video_resolution'] = child.attrib['videoResolution']
            if child.tag == 'Session' and 'location' in child.attrib.keys():
                stream_item['location'] = child.attrib['location']
            if child.tag == 'Player' and 'state' in child.attrib.keys():
                stream_item['state'] = child.attrib['state']
            if child.tag == 'Player' and 'remotePublicAddress' in child.attrib.keys():
                remote_ip = child.attrib['remotePublicAddress']
                if '127.0.0.1' not in remote_ip and '192.168.' not in remote_ip:
                    stream_item['ip'] = remote_ip
        streams.append(stream_item)
    clean_streams = []
    for stream in streams:
        if stream['type'] == 'track':
            s = f"{stream['user']} \u266c {stream['artist']}."
            clean_streams.append(s)
        elif stream['type'] == 'movie':
            s = f"{stream['user']} \u2680 {stream['title']}."
            clean_streams.append(s)
        elif stream['type'] == 'episode':
            season = stream['season'].replace('Season ', 'S')
            title = stream['title']
            s = f"{stream['user']} \u30ed {stream['tv_show']} {season} - {title}."
            clean_streams.append(s)
    plex['streams'] = clean_streams

def refresh_emporia_data():
    log.info('Fetching Emporia data.')
    vue = pyemvue.PyEmVue()
    login_response = vue.login(EMPORIA_USERNAME, EMPORIA_PASSWORD, token_storage_file='keys.json')
    if not login_response:
        log.warning('Failed to authenticate to Emporia.')
        return
    devices = vue.get_devices()
    for device in devices:
        if device.device_name == 'Washer':
            washer = device
        if device.device_name == 'Dryer':
            dryer = device
    washer_usage_dict = vue.get_device_list_usage(deviceGids=washer.device_gid, instant=None, scale=Scale.SECOND.value, unit=Unit.KWH.value)
    dryer_usage_dict  = vue.get_device_list_usage(deviceGids=dryer.device_gid,  instant=None, scale=Scale.SECOND.value, unit=Unit.KWH.value)
    emporia['Washer'] = {}
    emporia['Dryer']  = {}
    washer_usage_watt = washer_usage_dict[washer.device_gid].channels['1,2,3'].usage * 3600 * 1000
    dryer_usage_watt  = dryer_usage_dict[dryer.device_gid].channels['1,2,3'].usage * 3600 * 1000
    emporia['Washer']['Usage'] = str(round(washer_usage_watt, 3)) + 'W'
    emporia['Dryer']['Usage'] = str(round(dryer_usage_watt, 3)) + 'W'

@app.route('/')
def hello():
    return('OK')

@app.route('/states/all')
def states_all():
    resp = {}
    resp['ha'] = states
    resp['weather'] = weather
    resp['plex'] = plex
    resp['emporia'] = emporia
    return json.dumps(resp)

@app.route('/states/plex')
def states_plex():
    return json.dumps(plex)

### Main
if __name__ == "__main__":
    thread = threading.Thread(target=start_threads)
    thread.start()
    app.run(host='0.0.0.0')
