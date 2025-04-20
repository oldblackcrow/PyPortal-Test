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

# NOAA endpoints for solar wind data (for telemetry)
SOLAR_DATA_SOURCE = "https://services.swpc.noaa.gov/products/solar-wind/plasma-5-minute.json"
SOLAR_MAG_DATA_SOURCE = "https://services.swpc.noaa.gov/products/solar-wind/mag-5-minute.json"

pyportal = PyPortal()

# Global variables
button_active = True
last_connection_attempt = 0
CONNECTION_COOLDOWN = 5

# Calibration globals
calibration_active = False
calibration_group = None  # Will be built once at startup.
calibration_elements = {}

# Pocket Geiger Setup
SIGNAL_PIN = board.D3
HISTORY_LENGTH = 60
HISTORY_UNIT = 1  # seconds (adjustable)
K_ALPHA = 53.032  # Calibration constant

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
except Exception:
    geiger_found = False

# LIDAR setup Make sure to use the adafruit_lidarlite.PY file instead of the adafruit_lidarlite.MPY
lidar_found = False
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    # Use the V4‑LED driver class for your V4 module
    lidar = adafruit_lidarlite.LIDARLiteV4LED(i2c)
    lidar_found = True
except Exception:
    lidar_found = False

# UV Sensor setup
try:
    ltr = adafruit_ltr390.LTR390(i2c)
    ltr.integration_time = 200
    ltr.gain = 1
    uv_sensor_found = True
except Exception:
    uv_sensor_found = False

# Network Connection
def try_connect_wifi():
    try:
        if pyportal.network._wifi.is_connected:
            return True
        pyportal.network.connect()
        start = time.monotonic()
        timeout = 10  # seconds
        while not pyportal.network._wifi.is_connected:
            if time.monotonic() - start > timeout:
                return False
            time.sleep(0.5)
        return True
    except Exception:
        return False

# Display & Sound Setup
display = board.DISPLAY

# Create the main splash group and set its background.
splash = displayio.Group()
display.root_group = splash
# This background rect provides a black background for the display.
bg_rect = Rect(0, 0, 320, 240, fill=0x000000)
splash.append(bg_rect)

# Create a group for the normal UI elements.
normal_ui = displayio.Group()
splash.append(normal_ui)

# Add UI elements into normal_ui

# Panels and Top Bar
left_panel = Rect(0, 0, 50, 200, fill=0x165FC5)
normal_ui.append(left_panel)
right_panel = Rect(315, 1, 5, 200, fill=0xFDCD06)
normal_ui.append(right_panel)
top_panel = Rect(0, 1, 320, 35, fill=0x165FC5)
normal_ui.append(top_panel)

# (Stardate components removed)

# Tab Buttons (Radiation, Proximity, UV, Probes)
buttons = []
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
    normal_ui.append(b)

# Create a group for the content area (tab contents)
content_group = displayio.Group()
normal_ui.append(content_group)

view_radiation = displayio.Group()
radiation_label = Label(font=font_trek, text="CPM: --", color=0x00FFFF, scale=1)
radiation_label.x = 70
radiation_label.y = 80

# Header for Radiation Tab
top_left_label = Label(font=font_trek, text="GAMMA SCAN", color=0xFFFFFF, scale=1)
top_left_label.x = 10   # Adjust x coordinate as needed
top_left_label.y = 20   # Adjust y coordinate as needed
view_radiation.append(top_left_label)
view_radiation.append(radiation_label)
dose_label = Label(font=font_trek, text="DOSE: -- µSv/h", color=0xFFFF00, scale=1)
dose_label.x = 70
dose_label.y = 115
view_radiation.append(dose_label)
sensor_warning_label = Label(font=font_trek, text="", color=0xFF0000, scale=1)
sensor_warning_label.x = 70
sensor_warning_label.y = 145
view_radiation.append(sensor_warning_label)
button_cal = Button(x=50, y=35, width=40, height=30,
                    label="C", label_font=font_trek, fill_color=0xBF0F0F)
view_radiation.append(button_cal)

# Distance Tab UI
view_distance = displayio.Group()
# Add a top left label for the Proximity tab
top_left_label_distance = Label(font=font_trek, text="PROXIMITY", color=0xFFFFFF, scale=1)
top_left_label_distance.x = 10   # Adjust x coordinate as desired
top_left_label_distance.y = 20   # Adjust y coordinate as desired
view_distance.append(top_left_label_distance)

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
# Add a top left label for the UV tab
top_left_label_uv = Label(font=font_trek, text="ULTRA VIOLET", color=0xFFFFFF, scale=1)
top_left_label_uv.x = 10   # Adjust x coordinate as desired
top_left_label_uv.y = 20   # Adjust y coordinate as desired
view_uv.append(top_left_label_uv)

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
solar_header = Label(font=font_trek, text="SOLAR WEATHER", color=0xFFFFFF, scale=1)
solar_header.x = 10
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

# Set up the touchscreen.
ts = adafruit_touchscreen.Touchscreen(
    board.TOUCH_XL, board.TOUCH_XR, board.TOUCH_YD, board.TOUCH_YU,
    calibration=((5200, 59000), (5800, 57000)),
    size=(display.width, display.height)
)
display.rotation = 0

# --- Calibration Window ---
def create_calibration_button(x, y, width, height, text, fill_color=0xBF0F0F, text_color=0xFFFFFF, scale=1):
    grp = displayio.Group()
    rect = Rect(x, y, width, height, fill=fill_color)
    grp.append(rect)
    label = Label(font=terminalio.FONT, text=text, color=text_color, scale=scale)
    label.x = x + 3
    label.y = y + 3
    grp.append(label)
    return {"group": grp, "x": x, "y": y, "width": width, "height": height, "label": label}

def build_calibration_window():
    grp = displayio.Group()
    title_label = Label(font=terminalio.FONT, text="Calibration", color=0x00FFFF, scale=2)
    title_label.x = 50
    title_label.y = 20
    grp.append(title_label)
    
    label_k = Label(font=terminalio.FONT, text="K: {:.3f}".format(K_ALPHA), color=0xFFFFFF, scale=2)
    label_k.x = 60
    label_k.y = 50
    grp.append(label_k)
    
    button_k_minus = create_calibration_button(70, 65, 30, 20, "-", fill_color=0xBF0F0F, text_color=0xFFFFFF, scale=2)
    button_k_plus  = create_calibration_button(140, 65, 30, 20, "+", fill_color=0xB9C92F, text_color=0x11709F, scale=2)
    grp.append(button_k_minus["group"])
    grp.append(button_k_plus["group"])
    
    button_k_minus["label"].x = button_k_minus["x"] + 10
    button_k_minus["label"].y = button_k_minus["y"] + 9
    button_k_plus["label"].x  = button_k_plus["x"] + 10
    button_k_plus["label"].y  = button_k_plus["y"] + 9
    
    label_t = Label(font=terminalio.FONT, text="Time: {}s".format(HISTORY_UNIT), color=0xFFFFFF, scale=2)
    label_t.x = 60
    label_t.y = 105
    grp.append(label_t)
    
    button_t_minus = create_calibration_button(70, 120, 30, 20, "-", fill_color=0xBF0F0F, text_color=0xFFFFFF, scale=2)
    button_t_plus  = create_calibration_button(140, 120, 30, 20, "+", fill_color=0xB9C92F, text_color=0x11709F, scale=2)
    grp.append(button_t_minus["group"])
    grp.append(button_t_plus["group"])
    
    button_t_minus["label"].x = button_t_minus["x"] + 10
    button_t_minus["label"].y = button_t_minus["y"] + 9
    button_t_plus["label"].x = button_t_plus["x"] + 10
    button_t_plus["label"].y = button_t_plus["y"] + 9
    
    button_done = create_calibration_button(140, 160, 70, 30, "DONE", fill_color=0x11709F, scale=2)
    grp.append(button_done["group"])
    button_done["label"].x = button_done["x"] + 15
    button_done["label"].y = button_done["y"] + 15
    
    elements = {
        "label_k": label_k,
        "button_k_minus": button_k_minus,
        "button_k_plus": button_k_plus,
        "label_t": label_t,
        "button_t_minus": button_t_minus,
        "button_t_plus": button_t_plus,
        "button_done": button_done
    }
    return grp, elements

# Build the calibration window once at startup.
calibration_group, calibration_elements = build_calibration_window()

# Show/hide the calibration window by swapping the normal UI and calibration UI.
def show_calibration_window():
    global calibration_active
    if normal_ui in splash:
        splash.remove(normal_ui)
    if calibration_group not in splash:
        splash.append(calibration_group)
    calibration_active = True
    gc.collect()

def hide_calibration_window():
    global calibration_active
    if calibration_group in splash:
        splash.remove(calibration_group)
    if normal_ui not in splash:
        splash.append(normal_ui)
    calibration_active = False
    gc.collect()

def calibrate_pocketgeiger():
    show_calibration_window()

def in_button(touch, button):
    x, y = touch
    bx = button["x"]
    by = button["y"]
    bw = button["width"]
    bh = button["height"]
    return (bx <= x <= bx + bw) and (by <= y <= by + bh)

# --- Radiation Processing ---
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

def calculate_cpm():
    return (sum(count_history) * 60) / (history_length * HISTORY_UNIT) if history_length else 0

def calculate_uSvh():
    return calculate_cpm() / K_ALPHA if geiger_found else 0

# --- Update Display ---
def update_display():
    # (Removed stardate update)
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
        try:
            dist_mm = lidar.distance
            distance_label.text = f"Distance: {dist_mm/100:.2f} m"
            no_data_label.text  = ""
        except Exception:
            distance_label.text = "Distance: -- m"
            no_data_label.text  = "Measurement error"
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
                connect_button.fill_color = 0x11709F
            else:
                probes_connection_label.text = "Not Connected"
                probes_connection_label.color = 0xFF0000
                connect_button.fill_color = 0x11709F
        except Exception:
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
    except Exception:
        return False

# --- Delta Logo ---
try:
    delta_bitmap = displayio.OnDiskBitmap("/delta.bmp")
    delta_logo = displayio.TileGrid(delta_bitmap, pixel_shader=delta_bitmap.pixel_shader)
    delta_logo.x = 272
    delta_logo.y = 140
    view_radiation.append(delta_logo)
except Exception:
    pass

def update_solar_wind():
    try:
        plasma_str = pyportal.fetch(SOLAR_DATA_SOURCE)
        if isinstance(plasma_str, str):
            plasma_data = json.loads(plasma_str)
        else:
            plasma_data = plasma_str
        if len(plasma_data) < 2:
            raise Exception("Plasma data too short")
        latest = plasma_data[-1]
        wind_density.text = f"DENSITY: {float(latest[1]):.1f} p/cm³"
        wind_speed.text = f"SPEED: {float(latest[2]):.1f} km/s"
        mag_str = pyportal.fetch(SOLAR_MAG_DATA_SOURCE)
        if isinstance(mag_str, str):
            mag_data = json.loads(mag_str)
        else:
            mag_data = mag_str
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
    except Exception:
        status_label.text = "DATA UNAVAILABLE"
        status_label.color = 0xFF0000

last_solar_update = time.monotonic()
gc.collect()
SOLAR_UPDATE_INTERVAL = 45

view_live = "Radiation"
content_group.append(view_radiation)

# --- Main Loop ---
while True:
    # Process Calibration Window Input (if active)
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
                pyportal.play_file("/sounds/tos_keypress3.wav")
                hide_calibration_window()
                time.sleep(0.3)
        continue

    # Process normal touch events for switching tabs or triggering calibration.
    touch = ts.touch_point
    if touch:
        for i, button in enumerate(buttons):
            if button.contains(touch):
                switch_view(["Radiation", "Distance", "UV", "Probes"][i])
                break
        # Calibrate button on Radiation Tab.
        if view_live == "Radiation" and button_cal.contains(touch):
            pyportal.play_file("/sounds/tos_keypress3.wav")
            calibrate_pocketgeiger()
            time.sleep(0.3)
    # Process Connect button on Probes Tab.
    if view_live == "Probes" and connect_button.contains(ts.touch_point or (0, 0)):
        if ts.touch_point:
            pyportal.play_file("/sounds/tos_keypress3.wav")
            current_time = time.monotonic()
            if button_active and (current_time - last_connection_attempt) >= CONNECTION_COOLDOWN:
                last_connection_attempt = current_time
                button_active = False
                connect_button.label = "Connecting..."
                connect_button.fill_color = 0x11709F
                success = try_connect_wifi()
                if success:
                    # Removed time update (stardate not needed)
                    update_solar_wind()
                    last_solar_update = time.monotonic()
                    gc.collect()
                button_active = True
                connect_button.fill_color = 0x11709F
                connect_button.label = "Reconnect" if success else "CONNECT"
                if success and connect_button.label == "Reconnect":
                    pyportal.play_file("/sounds/tos_keypress3.wav")
    process_radiation()
    update_display()
    current_time = time.monotonic()
    if current_time - last_solar_update >= SOLAR_UPDATE_INTERVAL:
        if view_live == "Probes" and pyportal.network._wifi.is_connected:
            time.sleep(0.5)
            if pyportal.network._wifi.is_connected:
                update_solar_wind()
                last_solar_update = current_time
