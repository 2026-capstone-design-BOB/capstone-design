from .app_control import open_app, close_app, maximize_window, minimize_window, show_desktop
from .web import open_url, web_search, youtube_search, map_search
from .filesystem import create_file, create_folder, find_file, open_recent_file
from .system import (
    volume_up, volume_down, set_volume, mute_toggle,
    brightness_up, brightness_down, take_screenshot,
    get_battery_status, get_current_time, get_running_apps,
)
