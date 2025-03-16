import time
import sys
import board
import displayio
import busio
import digitalio
from adafruit_bitmap_font import bitmap_font
from adafruit_display_text.label import Label
from adafruit_display_shapes.rect import Rect
import adafruit_touchscreen
from adafruit_pyportal import PyPortal
import adafruit_lidarlite
import adafruit_ltr390
from adafruit_button import Button
import json
import adafruit_requests as requests
import terminalio
import gc
try:
    from secrets import secrets
except ImportError:
    raise

cwd = ("/" + __file__).rsplit('/', 1)[0]
sys.path.append(cwd)

# Define NOAA endpoints for solar wind data
SOLAR_DATA_SOURCE = "https://services.swpc.noaa.gov/products/solar-wind/plasma-5-minute.json"
SOLAR_MAG_DATA_SOURCE = "https://services.swpc.noaa.gov/products/solar-wind/mag-5-minute.json"

pyportal = PyPortal()

stardate_set = False

# Global variables
button_active = True
last_connection_attempt = 0
CONNECTION_COOLDOWN = 5

# Calibration globals
calibration_active = False
calibration_group = None
calibration_elements = {}

# Pocket Geiger Setup
SIGNAL_PIN = board.D3
HISTORY_LENGTH = 60
HISTORY_UNIT = 1  # seconds (adjustable)
K_ALPHA = 53.032  # Calibration constant (adjustable)

radiation_count = 0
count_history = [0] * HISTORY_LENGTH
history_index = 0
history_length = 0
last_history_time = time.monotonic()

# Fonts
font_greek = bitmap_font.load_font("fonts/Greek03-Regular-25.bdf")
font_trek = bitmap_font.load_font("fonts/LeagueSpartan-Bold-16.bdf")

last_button_flash = 0
BUTTON_FLASH_INTERVAL = 1.0

# Setup digital input for Geiger counter
try:
    signal_pin = digitalio.DigitalInOut(SIGNAL_PIN)
    signal_pin.direction = digitalio.Direction.INPUT
    signal_pin.pull = digitalio.Pull.UP
    geiger_found = True
except Exception as e:
    geiger_found = False

# LIDAR setup
lidar_found = False
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    lidar = adafruit_lidarlite.LIDARLite(i2c)
    lidar_found = True
except Exception as e:
    lidar_found = False

# UV Sensor setup
try:
    ltr = adafruit_ltr390.LTR390(i2c)
    ltr.integration_time = 200
    ltr.gain = 1
    uv_sensor_found = True
except Exception as e:
    uv_sensor_found = False

# Network Connection
def try_connect_wifi():
    try:
        if pyportal.network._wifi.is_connected:
            return True
        print("Attempt Subspace connection")
        pyportal.network.connect()  # No timeout parameter supported
        start = time.monotonic()
        timeout = 10  # seconds
        while not pyportal.network._wifi.is_connected:
            if time.monotonic() - start > timeout:
                print("Subspace connection timed out.")
                return False
            time.sleep(0.5)
        print("Connected")
        return True
    except Exception as e:
        print("Subspace connection error:", e)
        return False

# Display & Sound Setup
display = board.DISPLAY

def update_time():
    global stardate_set
    try:
        print("Fetching current time...")
        time_str = pyportal.fetch("http://worldtimeapi.org/api/timezone/America/New_York")
        time_json = json.loads(time_str)
        dt = time_json["datetime"]
        date_part, time_part = dt.split("T")
        year, month, day = map(int, date_part.split("-"))
        time_part = time_part.split(".")[0]
        hour, minute, second = map(int, time_part.split(":"))
        stardate_int = f"1{month:02d}{day:02d}"
        stardate_decimal = f"{hour:02d}{minute:02d}"
        stardate_label.text = f"STARDATE {stardate_int}.{stardate_decimal}"
        stardate_set = True  # Mark that the stardate has been set.
        print("Stardate updated:", stardate_label.text)
    except Exception as e:
        print("Error fetching time:", e)

def calculate_stardate():
    now = time.localtime()
    # Extract month and day (now[1] is month, now[2] is day)
    month = now[1]
    day = now[2]
    # Format the first part as: 1 (for 21st century) followed by two-digit month and day.
    stardate_int = f"1{month:02d}{day:02d}"

    # Extract hour and minute (now[3] is hour, now[4] is minute)
    hour = now[3]
    minute = now[4]
    # Format the decimal portion as a 4-digit number: HHMM
    stardate_decimal = f"{hour:02d}{minute:02d}"

    return f"STARDATE {stardate_int}.{stardate_decimal}"

ts = adafruit_touchscreen.Touchscreen(
    board.TOUCH_XL, board.TOUCH_XR, board.TOUCH_YD, board.TOUCH_YU,
    calibration=((5200, 59000), (5800, 57000)),
    size=(display.width, display.height)
)
display.rotation = 0
splash = displayio.Group()
display.root_group = splash

# TOS-Style UI Setup
bg_rect = Rect(0, 0, 320, 240, fill=0x000000)
splash.append(bg_rect)

left_panel = Rect(0, 0, 50, 200, fill=0x165FC5)
splash.append(left_panel)

# Replace gradient right panel with a solid yellow vertical line (saves memory)
right_panel = Rect(315, 1, 5, 200, fill=0xFDCD06)
splash.append(right_panel)

top_panel = Rect(0, 1, 320, 35, fill=0x165FC5)
splash.append(top_panel)

buttons = []
stardate_label = Label(font=terminalio.FONT, text="STARDATE 41234.5", color=0xFFFFFF, scale=1)
stardate_label.x = 200
stardate_label.y = 15
splash.append(stardate_label)

# Tab Buttons (using Adafruit Button for main UI)
button_radiation = Button(x=15, y=200, width=70, height=30,
                          label="γ", label_font=font_greek, fill_color=0xB9C92F)
button_distance = Button(x=90, y=200, width=70, height=30,
                         label="Prox", label_font=font_trek, fill_color=0xBF0F0F)
button_uv = Button(x=163, y=200, width=70, height=30,
                   label="Δ", label_font=font_greek, fill_color=0xBF0F0F)
button_probes = Button(x=236, y=200, width=70, height=30,
                       label="Probes", label_font=font_trek, fill_color=0xBF0F0F)
buttons.extend([button_radiation, button_distance, button_uv, button_probes])
for b in buttons:
    splash.append(b)

content_group = displayio.Group()
splash.append(content_group)

# Radiation Tab UI
view_radiation = displayio.Group()
radiation_label = Label(font=font_trek, text="CPM: --", color=0x00FFFF, scale=1)
radiation_label.x = 70
radiation_label.y = 80
view_radiation.append(radiation_label)
dose_label = Label(font=font_trek, text="DOSE: -- µSv/h", color=0xFFFF00, scale=1)
dose_label.x = 70
dose_label.y = 115
view_radiation.append(dose_label)
sensor_warning_label = Label(font=font_trek, text="", color=0xFF0000, scale=1)
sensor_warning_label.x = 70
sensor_warning_label.y = 145
view_radiation.append(sensor_warning_label)
button_cal = Button(x=5, y=85, width=40, height=30,
                    label="C", label_font=font_trek, fill_color=0xBF0F0F)
view_radiation.append(button_cal)

# Distance Tab UI
view_distance = displayio.Group()
distance_label = Label(font=font_trek, text="Distance: -- m", color=0x00FFFF, scale=1)
distance_label.x = 70
distance_label.y = 80
view_distance.append(distance_label)
no_data_label = Label(font=font_trek, text="Sensor offline", color=0xFF0000, scale=1)
no_data_label.x = 70
no_data_label.y = 130
view_distance.append(no_data_label)

# UV Sensor Tab UI
view_uv = displayio.Group()
uv_index_label = Label(font=font_trek, text="UV Index: --", color=0x00FFFF, scale=1)
uv_index_label.x = 70
uv_index_label.y = 80
view_uv.append(uv_index_label)
uv_intensity_label = Label(font=font_trek, text="UV I: --", color=0xFFFF00, scale=1)
uv_intensity_label.x = 70
uv_intensity_label.y = 115
view_uv.append(uv_intensity_label)
no_uv_label = Label(font=font_trek, text="Sensor offline", color=0xFF0000, scale=1)
no_uv_label.x = 70
no_uv_label.y = 150
view_uv.append(no_uv_label)

# Probes Tab UI
view_probes = displayio.Group()
probes_status_label = Label(font=font_trek, text="Network Status:", color=0x00FFFF)
probes_status_label.x = 70
probes_status_label.y = 80
view_probes.append(probes_status_label)
probes_connection_label = Label(font=font_trek, text="Not Connected", color=0xFF0000)
probes_connection_label.x = 70
probes_connection_label.y = 100
view_probes.append(probes_connection_label)
solar_frame = Rect(52, 45, 225, 150, fill=0x000022)
view_probes.append(solar_frame)
solar_header = Label(font=terminalio.FONT, text="SOLAR WEATHER", color=0x00FFFF, scale=2)
solar_header.x = 20
solar_header.y = 20
view_probes.append(solar_header)
wind_speed = Label(font=terminalio.FONT, text="SPEED: - km/s", color=0x00FF00, scale=2)
wind_speed.x = 60
wind_speed.y = 70
view_probes.append(wind_speed)
wind_density = Label(font=terminalio.FONT, text="DENSITY: - p/cm³", color=0x00FF00, scale=2)
wind_density.x = 60
wind_density.y = 100
view_probes.append(wind_density)
mag_field = Label(font=terminalio.FONT, text="MAG FIELD: - nT", color=0x00FF00, scale=2)
mag_field.x = 60
mag_field.y = 130
view_probes.append(mag_field)
status_label = Label(font=terminalio.FONT, text="", color=0xFFFF00)
status_label.x = 60
status_label.y = 165
view_probes.append(status_label)
connect_button = Button(x=165, y=160, width=90, height=30,
                        label="CONNECT", label_font=terminalio.FONT,
                        label_color=0xFDCD06, fill_color=0x11709F)
view_probes.append(connect_button)

# Radiation Processing
def process_radiation():
    global last_history_time, radiation_count, history_index, history_length
    current_time = time.monotonic()
    if geiger_found and not signal_pin.value:
        radiation_count += 1
    if current_time - last_history_time >= HISTORY_UNIT:
        last_history_time = current_time
        count_history[history_index] = radiation_count
        radiation_count = 0
        history_index = (history_index + 1) % HISTORY_LENGTH
        history_length = min(history_length + 1, HISTORY_LENGTH)
        cpm = (sum(count_history) * 60) / (history_length * HISTORY_UNIT) if history_length else 0
        dose = cpm / K_ALPHA if geiger_found else 0

def calculate_cpm():
    return (sum(count_history) * 60) / (history_length * HISTORY_UNIT) if history_length else 0

def calculate_uSvh():
    return calculate_cpm() / K_ALPHA if geiger_found else 0

# Custom Calibration Button Helpers
def create_calibration_button(x, y, width, height, text, fill_color=0xBF0F0F, text_color=0xFFFFFF, scale=1):
    grp = displayio.Group()
    rect = Rect(x, y, width, height, fill=fill_color)
    grp.append(rect)
    label = Label(font=terminalio.FONT, text=text, color=text_color, scale=scale)
    label.x = x + 3
    label.y = y + 3
    grp.append(label)
    return {"group": grp, "x": x, "y": y, "width": width, "height": height, "label": label}

def in_button(touch, button):
    x, y = touch
    bx = button["x"]
    by = button["y"]
    bw = button["width"]
    bh = button["height"]
    return (bx <= x <= bx + bw) and (by <= y <= by + bh)

# Calibration Window Functions using custom buttons
def show_calibration_window():
    global calibration_active, calibration_group, calibration_elements
    if content_group in splash:
        splash.remove(content_group)
    calibration_active = True
    calibration_group = displayio.Group()

    # Layout updated for easier tapping:
    title_label = Label(font=terminalio.FONT, text="Calibration", color=0x00FFFF, scale=2)
    title_label.x = 50
    title_label.y = 20
    calibration_group.append(title_label)

    label_k = Label(font=terminalio.FONT, text="K: {:.3f}".format(K_ALPHA), color=0xFFFFFF, scale=2)
    label_k.x = 60
    label_k.y = 50
    calibration_group.append(label_k)

    button_k_minus = create_calibration_button(70, 65, 30, 20, "-", fill_color=0xBF0F0F, text_color=0xFFFFFF, scale=2)
    button_k_plus  = create_calibration_button(140, 65, 30, 20, "+", fill_color=0xB9C92F, text_color=0x11709F, scale=2)
    calibration_group.append(button_k_minus["group"])
    calibration_group.append(button_k_plus["group"])
    button_k_minus["label"].x = button_k_minus["x"] + 10  # New horizontal offset for K -
    button_k_minus["label"].y = button_k_minus["y"] + 9   # New vertical offset for K -
    button_k_plus["label"].x  = button_k_plus["x"]  + 10   # New horizontal offset for K +
    button_k_plus["label"].y  = button_k_plus["y"]  + 9    # New vertical offset for K +

    label_t = Label(font=terminalio.FONT, text="Time: {}".format(HISTORY_UNIT), color=0xFFFFFF, scale=2)
    label_t.x = 60
    label_t.y = 105
    calibration_group.append(label_t)

    button_t_minus = create_calibration_button(70, 120, 30, 20, "-", fill_color=0xBF0F0F, text_color=0xFFFFFF, scale=2)
    button_t_plus  = create_calibration_button(140, 120, 30, 20, "+", fill_color=0xB9C92F, text_color=0x11709F, scale=2)
    calibration_group.append(button_t_minus["group"])
    calibration_group.append(button_t_plus["group"])
    button_t_minus["label"].x = button_t_minus["x"] + 10  # New horizontal offset
    button_t_minus["label"].y = button_t_minus["y"] + 9  # New vertical offset
    button_t_plus["label"].x = button_t_plus["x"] + 10    # New horizontal offset
    button_t_plus["label"].y = button_t_plus["y"] + 9    # New vertical offset

    button_done = create_calibration_button(140, 160, 70, 30, "DONE", fill_color=0x11709F, scale=2)
    calibration_group.append(button_done["group"])
    button_done["label"].x = button_done["x"] + 15  # New horizontal offset
    button_done["label"].y = button_done["y"] + 15  # New vertical offset

    calibration_elements = {
        "label_k": label_k,
        "button_k_minus": button_k_minus,
        "button_k_plus": button_k_plus,
        "label_t": label_t,
        "button_t_minus": button_t_minus,
        "button_t_plus": button_t_plus,
        "button_done": button_done
    }

    splash.append(calibration_group)

def hide_calibration_window():
    global calibration_active, calibration_group
    if calibration_group is not None:
        splash.remove(calibration_group)
    calibration_group = None
    calibration_active = False
    splash.append(content_group)

def calibrate_pocketgeiger():
    show_calibration_window()

# Update Display Function
def update_display():
    current_time = time.monotonic()
    global stardate_set
    if not stardate_set:
        stardate_label.text = calculate_stardate()
    if view_live == "Radiation":
        if sum(count_history) == 0:
            radiation_label.text = "CPM: --"
            dose_label.text = "DOSE: -- µSv/h"
            sensor_warning_label.text = "Sensor offline"
        else:
            radiation_label.text = f"CPM: {calculate_cpm():.1f}"
            dose_label.text = f"DOSE: {calculate_uSvh():.3f} µSv/h"
            sensor_warning_label.text = ""
    elif view_live == "Distance":
        if lidar_found:
            distance = lidar.distance
            distance_label.text = f"Distance: {distance/100:.2f} m"
            no_data_label.text = ""
        else:
            distance_label.text = "Distance: -- m"
            no_data_label.text = "Sensor offline"
    elif view_live == "UV":
        if uv_sensor_found:
            uv_index_label.text = f"UV Index: {ltr.uvi:.2f}"
            uv_intensity_label.text = f"UV I: {ltr.lux:.2f}"
            no_uv_label.text = ""
        else:
            uv_index_label.text = "UV Index: --"
            uv_intensity_label.text = "UV I: --"
            no_uv_label.text = "Sensor offline"
    elif view_live == "Probes":
        try:
            if pyportal.network._wifi.is_connected:
                probes_connection_label.text = "Connected"
                probes_connection_label.color = 0x00FF00
                # Do not update connect_button.label here; it's updated in the touch handler.
                connect_button.fill_color = 0x11709F
            else:
                probes_connection_label.text = "Not Connected"
                probes_connection_label.color = 0xFF0000
                # Leave connect_button.label unchanged here.
                connect_button.fill_color = 0x11709F
        except Exception as e:
            probes_connection_label.text = "Status Unknown"
            probes_connection_label.color = 0xFF0000
            connect_button.fill_color = 0x11709F

def switch_view(new_view):
    global view_live
    pyportal.play_file("/sounds/tab.wav")
    if content_group:
        content_group.pop()
    for view in (view_radiation, view_distance, view_uv, view_probes):
        try:
            view.remove(delta_logo)
        except Exception:
            pass
    view_live = new_view
    if new_view == "Radiation":
        content_group.append(view_radiation)
        view_radiation.append(delta_logo)
        button_radiation.fill_color = 0xB9C92F
        button_distance.fill_color = 0xBF0F0F
        button_uv.fill_color = 0xBF0F0F
        button_probes.fill_color = 0xBF0F0F
    elif new_view == "Distance":
        content_group.append(view_distance)
        view_distance.append(delta_logo)
        button_radiation.fill_color = 0xBF0F0F
        button_distance.fill_color = 0xB9C92F
        button_uv.fill_color = 0xBF0F0F
        button_probes.fill_color = 0xBF0F0F
    elif new_view == "UV":
        content_group.append(view_uv)
        view_uv.append(delta_logo)
        button_radiation.fill_color = 0xBF0F0F
        button_distance.fill_color = 0xBF0F0F
        button_uv.fill_color = 0xB9C92F
        button_probes.fill_color = 0xBF0F0F
    elif new_view == "Probes":
        content_group.append(view_probes)
        view_probes.append(delta_logo)
        button_radiation.fill_color = 0xBF0F0F
        button_distance.fill_color = 0xBF0F0F
        button_uv.fill_color = 0xBF0F0F
        button_probes.fill_color = 0xB9C92F
    update_display()

def check_network_status():
    try:
        return pyportal.network.check_connectivity()
    except Exception as e:
        return False

try:
    delta_bitmap = displayio.OnDiskBitmap("/delta.bmp")
    delta_logo = displayio.TileGrid(delta_bitmap, pixel_shader=delta_bitmap.pixel_shader)
    delta_logo.x = 272
    delta_logo.y = 140
    view_radiation.append(delta_logo)
except Exception as e:
    pass

def update_solar_wind():
    try:
        print("Fetching plasma data...")
        plasma_str = pyportal.fetch(SOLAR_DATA_SOURCE)
        # If the fetched data is a string, parse it into a Python object:
        if isinstance(plasma_str, str):
            plasma_data = json.loads(plasma_str)
        else:
            plasma_data = plasma_str
        print("Plasma data received:", plasma_data)
        print("Type of plasma_data:", type(plasma_data), "Length:", len(plasma_data))
        if len(plasma_data) < 2:
            raise Exception("Plasma data too short")
        latest = plasma_data[-1]
        wind_density.text = f"DENSITY: {float(latest[1]):.1f} p/cm³"
        wind_speed.text = f"SPEED: {float(latest[2]):.1f} km/s"

        print("Fetching magnetic field data ...")
        mag_str = pyportal.fetch(SOLAR_MAG_DATA_SOURCE)
        if isinstance(mag_str, str):
            mag_data = json.loads(mag_str)
        else:
            mag_data = mag_str
        print("Magnetic field data received:", mag_data)
        if len(mag_data) < 2:
            raise Exception("Mag data too short")
        latest_mag = mag_data[-1]
        if len(latest_mag) < 5:
            raise Exception("Mag data row too short")
        mag_field.text = f"MAG FIELD: {float(latest_mag[4]):.1f} nT"

        speed = float(latest[2])
        if speed > 800:
            status_label.text = "WARNING: SOLAR STORM"
            status_label.color = 0xFF0000
        elif speed > 500:
            status_label.text = "ELEVATED ACTIVITY"
            status_label.color = 0xFFFF00
        else:
            status_label.text = "NOMINAL"
            status_label.color = 0x00FF00

        print("update_solar_wind() complete.")
    except Exception as e:
        status_label.text = "DATA UNAVAILABLE"
        status_label.color = 0xFF0000
        print("Error in update_solar_wind:", e)

last_solar_update = time.monotonic()
gc.collect()
SOLAR_UPDATE_INTERVAL = 45

view_live = "Radiation"
content_group.append(view_radiation)

while True:
    if calibration_active:
        touch = ts.touch_point
        if touch:
            if in_button((touch[0], touch[1]), calibration_elements["button_k_minus"]):
                K_ALPHA -= 0.1
                calibration_elements["label_k"].text = "K: {:.3f}".format(K_ALPHA)
                time.sleep(0.3)
            elif in_button((touch[0], touch[1]), calibration_elements["button_k_plus"]):
                K_ALPHA += 0.1
                calibration_elements["label_k"].text = "K: {:.3f}".format(K_ALPHA)
                time.sleep(0.3)
            elif in_button((touch[0], touch[1]), calibration_elements["button_t_minus"]):
                if HISTORY_UNIT > 0.5:
                    HISTORY_UNIT -= 0.5
                calibration_elements["label_t"].text = "Time: {}s".format(HISTORY_UNIT)
                time.sleep(0.3)
            elif in_button((touch[0], touch[1]), calibration_elements["button_t_plus"]):
                HISTORY_UNIT += 0.5
                calibration_elements["label_t"].text = "Time: {}s".format(HISTORY_UNIT)
                time.sleep(0.3)
            elif in_button((touch[0], touch[1]), calibration_elements["button_done"]):
                hide_calibration_window()
                time.sleep(0.3)
        continue

    touch = ts.touch_point
    if touch:
        for i, button in enumerate(buttons):
            if button.contains(touch):
                switch_view(["Radiation", "Distance", "UV", "Probes"][i])
                break
        if view_live == "Radiation" and button_cal.contains(touch):
            calibrate_pocketgeiger()
            time.sleep(0.3)
    if view_live == "Probes" and connect_button.contains(touch):
        current_time = time.monotonic()
        if button_active and (current_time - last_connection_attempt) >= CONNECTION_COOLDOWN:
            last_connection_attempt = current_time
            button_active = False
            connect_button.label = "Connecting..."
            connect_button.fill_color = 0x11709F
            success = try_connect_wifi()
            if success:
                # Immediately update time and solar data upon connection:
                update_time()
                update_solar_wind()
                last_solar_update = time.monotonic()
            button_active = True
            connect_button.fill_color = 0x11709F
            connect_button.label = "Reconnect" if success else "CONNECT"

    process_radiation()
    update_display()
    current_time = time.monotonic()
    if current_time - last_solar_update >= SOLAR_UPDATE_INTERVAL:
        if view_live == "Probes" and pyportal.network._wifi.is_connected:
            time.sleep(0.5)
            if pyportal.network._wifi.is_connected:
                update_solar_wind()
                last_solar_update = current_time
