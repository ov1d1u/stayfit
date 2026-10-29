"""Constants for the StayFit integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "stayfit"

API_BASE_URL: Final = "https://api.upfit.cloud"
API_PROJECT: Final = "STAYFITGYM"
API_LANGUAGE_ID: Final = "2"
API_APP_VERSION: Final = "4.2606.33"
API_TIME_ZONE: Final = "Europe/Bucharest"

CONF_TOKEN: Final = "token"
CONF_MEMBER_ID: Final = "member_id"
CONF_DISPLAY_NAME: Final = "display_name"

UPDATE_INTERVAL: Final = timedelta(hours=1)
