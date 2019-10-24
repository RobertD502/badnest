import requests
import logging

API_URL = "https://home.nest.com"
CAMERA_WEBAPI_BASE = "https://webapi.camera.home.nest.com"
CAMERA_URL = "https://nexusapi-us1.camera.home.nest.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_5) " \
             "AppleWebKit/537.36 (KHTML, like Gecko) " \
             "Chrome/75.0.3770.100 Safari/537.36"
URL_JWT = "https://nestauthproxyservice-pa.googleapis.com/v1/issue_jwt"

_LOGGER = logging.getLogger(__name__)


class NestAPI:
    def __init__(self,
                 email,
                 password,
                 issue_token,
                 cookie,
                 api_key,
                 device_id=None):
        self._user_id = None
        self._access_token = None
        self._session = requests.Session()
        self._session.headers.update({"Referer": "https://home.nest.com/"})
        self._device_id = device_id
        self._email = email
        self._password = password
        self._issue_token = issue_token
        self._cookie = cookie
        self._api_key = api_key
        self.login()

    def login(self):
        if not self._email and not self._password:
            self._login_google(self._issue_token, self._cookie, self._api_key)
        else:
            self._login_nest(self._email, self._password)

    def _login_nest(self, email, password):
        r = self._session.post(
            f"{API_URL}/session", json={"email": email, "password": password}
        )
        self._user_id = r.json()["userid"]
        self._access_token = r.json()["access_token"]

    def _login_google(self, issue_token, cookie, api_key):
        headers = {
            'Sec-Fetch-Mode': 'cors',
            'User-Agent': USER_AGENT,
            'X-Requested-With': 'XmlHttpRequest',
            'Referer': 'https://accounts.google.com/o/oauth2/iframe',
            'cookie': cookie
        }
        r = requests.get(url=issue_token, headers=headers)
        access_token = r.json()['access_token']

        headers = {
            'Authorization': 'Bearer ' + access_token,
            'User-Agent': USER_AGENT,
            'x-goog-api-key': api_key,
            'Referer': 'https://home.nest.com'
        }
        params = {
            "embed_google_oauth_access_token": True,
            "expire_after": '3600s',
            "google_oauth_access_token": access_token,
            "policy_id": 'authproxy-oauth-policy'
        }
        r = requests.post(url=URL_JWT, headers=headers, params=params)
        self._user_id = r.json()['claims']['subject']['nestId']['id']
        self._access_token = r.json()['jwt']


class NestThermostatAPI(NestAPI):
    def __init__(self,
                 email,
                 password,
                 issue_token,
                 cookie,
                 api_key,
                 device_id=None):
        super(NestThermostatAPI, self).__init__(
            email,
            password,
            issue_token,
            cookie,
            api_key,
            device_id)
        self._czfe_url = None
        self._compressor_lockout_enabled = None
        self._compressor_lockout_time = None
        self._hvac_ac_state = None
        self._hvac_heater_state = None
        self.mode = None
        self._time_to_target = None
        self._fan_timer_timeout = None
        self.can_heat = None
        self.can_cool = None
        self.has_fan = None
        self.fan = None
        self.current_temperature = None
        self.target_temperature = None
        self.target_temperature_high = None
        self.target_temperature_low = None
        self.current_humidity = None
        self.update()

    def get_devices(self):
        try:
            r = self._session.post(
                f"{API_URL}/api/0.1/user/{self._user_id}/app_launch",
                json={
                    "known_bucket_types": ["buckets"],
                    "known_bucket_versions": [],
                },
                headers={"Authorization": f"Basic {self._access_token}"},
            )
            devices = []
            buckets = r.json()['updated_buckets'][0]['value']['buckets']
            for bucket in buckets:
                if bucket.startswith('device.'):
                    devices.append(bucket.replace('device.', ''))

            return devices
        except requests.exceptions.RequestException as e:
            _LOGGER.error(e)
            _LOGGER.error('Failed to get devices, trying again')
            return self.get_devices()
        except KeyError:
            _LOGGER.debug('Failed to get devices, trying to log in again')
            self.login()
            return self.get_devices()

    def get_action(self):
        if self._hvac_ac_state:
            return "cooling"
        elif self._hvac_heater_state:
            return "heating"
        else:
            return "off"

    def update(self):
        try:
            r = self._session.post(
                f"{API_URL}/api/0.1/user/{self._user_id}/app_launch",
                json={
                    "known_bucket_types": ["shared", "device"],
                    "known_bucket_versions": [],
                },
                headers={"Authorization": f"Basic {self._access_token}"},
            )

            self._czfe_url = r.json()["service_urls"]["urls"]["czfe_url"]

            temp_mode = None
            for bucket in r.json()["updated_buckets"]:
                if bucket["object_key"] \
                        .startswith(f"shared.{self._device_id}"):
                    thermostat_data = bucket["value"]
                    self.current_temperature = \
                        thermostat_data["current_temperature"]
                    self.target_temperature = \
                        thermostat_data["target_temperature"]
                    self._compressor_lockout_enabled = thermostat_data[
                        "compressor_lockout_enabled"
                    ]
                    self._compressor_lockout_time = thermostat_data[
                        "compressor_lockout_timeout"
                    ]
                    self._hvac_ac_state = thermostat_data["hvac_ac_state"]
                    self._hvac_heater_state = \
                        thermostat_data["hvac_heater_state"]
                    if temp_mode is None:
                        temp_mode = thermostat_data["target_temperature_type"]
                    self.target_temperature_high = thermostat_data[
                        "target_temperature_high"
                    ]
                    self.target_temperature_low = \
                        thermostat_data["target_temperature_low"]
                    self.can_heat = thermostat_data["can_heat"]
                    self.can_cool = thermostat_data["can_cool"]
                elif bucket["object_key"] \
                        .startswith(f"device.{self._device_id}"):
                    thermostat_data = bucket["value"]
                    self._time_to_target = thermostat_data["time_to_target"]
                    self._fan_timer_timeout = \
                        thermostat_data["fan_timer_timeout"]
                    self.has_fan = thermostat_data["has_fan"]
                    self.fan = thermostat_data["fan_timer_timeout"] > 0
                    self.current_humidity = thermostat_data["current_humidity"]
                    if thermostat_data["eco"]["mode"] == 'manual-eco' or \
                            thermostat_data["eco"]["mode"] == 'auto-eco':
                        temp_mode = 'eco'
            self.mode = temp_mode
        except requests.exceptions.RequestException as e:
            _LOGGER.error(e)
            _LOGGER.error('Failed to update, trying again')
            self.update()
        except KeyError:
            _LOGGER.debug('Failed to update, trying to log in again')
            self.login()
            self.update()

    def set_temp(self, temp, temp_high=None):
        if temp_high is None:
            self._session.post(
                f"{self._czfe_url}/v5/put",
                json={
                    "objects": [
                        {
                            "object_key": f'shared.{self._device_id}',
                            "op": "MERGE",
                            "value": {"target_temperature": temp},
                        }
                    ]
                },
                headers={"Authorization": f"Basic {self._access_token}"},
            )
        else:
            self._session.post(
                f"{self._czfe_url}/v5/put",
                json={
                    "objects": [
                        {
                            "object_key": f'shared.{self._device_id}',
                            "op": "MERGE",
                            "value": {
                                "target_temperature_low": temp,
                                "target_temperature_high": temp_high,
                            },
                        }
                    ]
                },
                headers={"Authorization": f"Basic {self._access_token}"},
            )

    def set_mode(self, mode):
        self._session.post(
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'shared.{self._device_id}',
                        "op": "MERGE",
                        "value": {"target_temperature_type": mode},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

    def set_fan(self, date):
        self._session.post(
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'device.{self._device_id}',
                        "op": "MERGE",
                        "value": {"fan_timer_timeout": date},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

    def set_eco_mode(self, state):
        mode = 'manual-eco' if state else 'schedule'
        self._session.post(
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'device.{self._device_id}',
                        "op": "MERGE",
                        "value": {"eco": {"mode": mode}},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )


class NestTemperatureSensorAPI(NestAPI):
    def __init__(self,
                 email,
                 password,
                 issue_token,
                 cookie,
                 api_key,
                 device_id=None):
        super(NestTemperatureSensorAPI, self).__init__(
            email,
            password,
            issue_token,
            cookie,
            api_key,
            device_id)
        self.temperature = None
        self._device_id = device_id
        self.update()

    def get_devices(self):
        try:
            r = self._session.post(
                f"{API_URL}/api/0.1/user/{self._user_id}/app_launch",
                json={
                    "known_bucket_types": ["buckets"],
                    "known_bucket_versions": [],
                },
                headers={"Authorization": f"Basic {self._access_token}"},
            )
            devices = []
            buckets = r.json()['updated_buckets'][0]['value']['buckets']
            for bucket in buckets:
                if bucket.startswith('kryptonite.'):
                    devices.append(bucket.replace('kryptonite.', ''))

            return devices
        except requests.exceptions.RequestException as e:
            _LOGGER.error(e)
            _LOGGER.error('Failed to get devices, trying again')
            return self.get_devices()
        except KeyError:
            _LOGGER.debug('Failed to get devices, trying to log in again')
            self.login()
            return self.get_devices()

    def update(self):
        try:
            r = self._session.post(
                f"{API_URL}/api/0.1/user/{self._user_id}/app_launch",
                json={
                    "known_bucket_types": ["kryptonite"],
                    "known_bucket_versions": [],
                },
                headers={"Authorization": f"Basic {self._access_token}"},
            )

            for bucket in r.json()["updated_buckets"]:
                if bucket["object_key"].startswith(
                        f"kryptonite.{self._device_id}"):
                    sensor_data = bucket["value"]
                    self.temperature = sensor_data["current_temperature"]
                    self.battery_level = sensor_data["battery_level"]
        except requests.exceptions.RequestException as e:
            _LOGGER.error(e)
            _LOGGER.error('Failed to update, trying again')
            self.update()
        except KeyError:
            _LOGGER.debug('Failed to update, trying to log in again')
            self.login()
            self.update()


class NestCameraAPI(NestAPI):
    def __init__(self,
                 email,
                 password,
                 issue_token,
                 cookie,
                 api_key,
                 device_id=None):
        super(NestCameraAPI, self).__init__(
            email,
            password,
            issue_token,
            cookie,
            api_key,
            device_id)
        # log into dropcam
        self._session.post(
            f"{API_URL}/dropcam/api/login",
            data={"access_token": self._access_token}
        )
        self._device_id = device_id
        self.location = None
        self.name = "Nest Camera"
        self.online = None
        self.is_streaming = None
        self.battery_voltage = None
        self.ac_voltge = None
        self.data_tier = None
        self.update()

    def update(self):
        if self._device_id:
            props = self.get_properties()
            self._location = None
            self.name = props["name"]
            self.online = props["is_online"]
            self.is_streaming = props["is_streaming"]
            self.battery_voltage = props["rq_battery_battery_volt"]
            self.ac_voltge = props["rq_battery_vbridge_volt"]
            self.location = props["location"]
            self.data_tier = props["properties"]["streaming.data-usage-tier"]

    def _set_properties(self, property, value):
        r = self._session.post(
            f"{CAMERA_WEBAPI_BASE}/api/dropcams.set_properties",
            data={property: value, "uuid": self._device_id},
        )

        return r.json()["items"]

    def get_properties(self):
        r = self._session.get(
            f"{API_URL}/dropcam/api/cameras/{self._device_id}"
        )
        return r.json()[0]

    def get_cameras(self):
        r = self._session.get(
            f"{CAMERA_WEBAPI_BASE}/api/cameras."
            + "get_owned_and_member_of_with_properties"
        )
        return r.json()["items"]

    # def set_upload_quality(self, quality):
    #     quality = str(quality)
    #     return self._set_properties("streaming.data-usage-tier", quality)

    def turn_off(self):
        return self._set_properties("streaming.enabled", "false")

    def turn_on(self):
        return self._set_properties("streaming.enabled", "true")

    def get_image(self, now):
        r = self._session.get(
            f"{CAMERA_URL}/get_image?uuid={self._device_id}&cachebuster={now}"
        )

        return r.content
