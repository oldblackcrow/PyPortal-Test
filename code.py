# Import necessary libraries
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
import storage
import adafruit_sdcard
import json
import adafruit_requests as requests
import terminalio
try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py")
    raise

cwd = ("/"+__file__).rsplit('/', 1)[0]  # Current working directory
sys.path.append(cwd)

# Let PyPortal initialize its own SPI bus and other resources
pyportal = PyPortal()

# Add this with your other global variables
button_active = True  # Track if the connect button can be pressed
last_connection_attempt = 0  # Track when we last tried to connect
CONNECTION_COOLDOWN = 5  # Minimum seconds between connection attempts

# ------------- Pocket Geiger Setup ------------- #
SIGNAL_PIN = board.D3  # Geiger Counter signal pin
HISTORY_LENGTH = 60  # Store last 60 readings (1 min history)
HISTORY_UNIT = 1  # seconds
PROCESS_PERIOD = 0.160  # seconds
K_ALPHA = 53.032  # Calibration constant

# Radiation count variables
radiation_count = 0
count_history = [0] * HISTORY_LENGTH
history_index = 0
history_length = 0
last_process_time = time.monotonic()
last_history_time = time.monotonic()

#fonts
font_greek = bitmap_font.load_font("fonts/Greek03-Regular-25.bdf")
font_trek = bitmap_font.load_font("fonts/LeagueSpartan-Bold-16.bdf")  # Rename to be clearer

last_button_flash = 0  # Initialize to 0 instead of time.monotonic()
BUTTON_FLASH_INTERVAL = 1.0

# Set up digital input pin for Geiger counter
try:
    signal_pin = digitalio.DigitalInOut(SIGNAL_PIN)
    signal_pin.direction = digitalio.Direction.INPUT
    signal_pin.pull = digitalio.Pull.UP
    geiger_found = True
except Exception as e:
    print(f"Geiger sensor not found: {e}")
    geiger_found = False

# LIDAR setup
lidar_found = False
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    lidar = adafruit_lidarlite.LIDARLite(i2c)
    lidar_found = True
except Exception as e:
    print(f"LIDAR sensor not found: {e}")
    lidar_found = False

# UV Sensor setup
try:
    ltr = adafruit_ltr390.LTR390(i2c)
    # Set integration time and gain to coax some life from the sensor.
    ltr.integration_time = 200  # Increase integration time (in milliseconds, if supported)
    ltr.gain = 1  # Adjust gain as needed
    uv_sensor_found = True
except Exception as e:
    print(f"UV sensor not found: {e}")
    uv_sensor_found = False

# ------------- Network Connection ------------- #
def try_connect_wifi():
    print("\n=== WiFi Connection Attempt ===")
    print("Time: 2025-03-05 15:12:30 UTC")
    
    try:
        # Check if already connected
        if pyportal.network._wifi.is_connected:
            print("Already connected!")
            return True
            
        # Basic connection attempt
        print(f"Attempting connection to: {secrets['ssid']}")
        pyportal.network.connect()  # No timeout parameter
        
        # Monitor connection
        start = time.monotonic()
        dots = 0
        while (time.monotonic() - start) < 20:  # 20 second monitoring window
            try:
                if pyportal.network._wifi.is_connected:
                    print("\nConnection successful!")
                    ip = pyportal.network._wifi.ip_address
                    print(f"IP Address: {ip}")
                    return True
            except Exception:
                pass
            print("." if dots < 3 else "", end="")
            dots = (dots + 1) % 4
            time.sleep(1)
        
        print("\nConnection failed after 20 seconds")
        print("\nSince this worked 3 days ago, try:")
        print("1. Full reset sequence:")
        print("   a) Turn off phone hotspot")
        print("   b) Unplug PyPortal USB")
        print("   c) On phone: forget saved networks")
        print("   d) Wait 30 seconds")
        print("   e) Plug in PyPortal")
        print("   f) Wait for boot")
        print("   g) Turn on phone hotspot")
        print("   h) Wait 30 seconds")
        print("   i) Try connecting")
        return False
        
    except Exception as e:
        print(f"\nError: {e}")
        return False
# ------------- Display & Sound Setup ------------- #
display = board.DISPLAY

def calculate_stardate():
    now = time.localtime()
    year = now[0]
    day_of_year = now[7]
    hour = now[3]
    stardate = (year - 2323) * 1000 + (day_of_year + hour/24)
    return f"STARDATE {stardate:.1f}"

# Initialize touchscreen
ts = adafruit_touchscreen.Touchscreen(
    board.TOUCH_XL,
    board.TOUCH_XR,
    board.TOUCH_YD,
    board.TOUCH_YU,
    calibration=((5200, 59000), (5800, 57000)),
    size=(display.width, display.height),
)
display.rotation = 0
splash = displayio.Group()
display.root_group = splash  # Set as active display group

print("Display Test Passed!")

# ------------- SD Card Logging Setup ------------- #
sd_found = False
log_file_path = ""
try:
    sd_cs = digitalio.DigitalInOut(board.SD_CS)  # Use board.SD_CS for chip select
    # Use PyPortal's internal SPI bus (a sad, little private attribute)
    sdcard = adafruit_sdcard.SDCard(pyportal._spi, sd_cs)
    vfs = storage.VfsFat(sdcard)
    storage.mount(vfs, "/sd")
    sd_found = True
    log_file_path = "/sd/data_log.csv"
    # Create file header if it doesn't exist
    try:
        with open(log_file_path, "r") as f:
            pass
    except OSError:
        with open(log_file_path, "w") as f:
            f.write("timestamp,cpm,dose\n")
    print("SD card logging enabled.")
except Exception as e:
    print("SD card not found or initialization error:", e)

def log_data(cpm, dose):
    """Append a new line with timestamp, CPM, and dose to the log file."""
    if sd_found:
        try:
            with open(log_file_path, "a") as f:
                f.write("{:.2f},{:.1f},{:.3f}\n".format(time.monotonic(), cpm, dose))
        except Exception as e:
            print("Error writing to SD card:", e)

# ------------- TOS-Style UI ------------- #
bg_rect = Rect(0, 0, 320, 240, fill=0x000000)  # Black background
splash.append(bg_rect)

# **Side Panels vertical bar**
left_panel = Rect(0, 0, 50, 200, fill=0x003366)
splash.append(left_panel)

# Create a gradient for the right side panel using a Bitmap and Palette
panel_width = 10
panel_height = 240  # Keep the full height
color_steps = 64    # Use 64 colors instead of 240

right_bitmap = displayio.Bitmap(panel_width, panel_height, color_steps)  # Use color_steps instead of panel_height
right_palette = displayio.Palette(color_steps)  # Reduce palette to 64 colors

for i in range(color_steps):
    if i < color_steps // 2:
        # Top half: interpolate from blue (0x003366) to yellow (255,255,0)
        ratio = i / (color_steps // 2)
        r = int(255 * ratio)               # from 0 to 255
        g = int(51 * (1 - ratio) + 255 * ratio)  # from 51 to 255
        b = int(102 * (1 - ratio))           # from 102 to 0
    else:
        # Bottom half: from yellow to red
        ratio = (i - (color_steps // 2)) / (color_steps // 2)
        r = 255                            # stays 255
        g = int(255 * (1 - ratio))         # from 255 down to 0
        b = 0                              # stays 0
    color = (r << 16) | (g << 8) | b
    right_palette[i] = color

for x in range(panel_width):
    for y in range(panel_height):
        color_index = int((y * (color_steps - 1)) / (panel_height - 1))
        right_bitmap[x, y] = color_index

right_panel_tilegrid = displayio.TileGrid(right_bitmap, pixel_shader=right_palette, x=310, y=0)
splash.append(right_panel_tilegrid)

# Add horizontal bar at the top of the screen (same color as vertical bars)
top_panel = Rect(0, 0, 320, 35, fill=0x003366)
splash.append(top_panel)

# **Blinking "SCANNING" Label**
font_trek = bitmap_font.load_font("fonts/LeagueSpartan-Bold-16.bdf")
scanning_label = Label(font=font_trek, text="SCANNING", color=0xFFFF00, scale=1)
scanning_label.x = 180
scanning_label.y = 50
splash.append(scanning_label)

# **Tab Buttons**
buttons = []

#Stardate Label
stardate_label = Label(
    font=terminalio.FONT,
    text="STARDATE 41234.5",
    color=0x00FFFF,
    scale=1  # We can safely use scale=2 with terminalio.FONT since it's quite small
)
stardate_label.x = 210
stardate_label.y = 15
splash.append(stardate_label)

# Adjusted x positions to fit four buttons
button_radiation = Button(x=15, y=200, width=70, height=30,
                         label="γ", label_font=font_greek, fill_color=0xFFFFFF)
button_distance = Button(x=90, y=200, width=70, height=30,
                        label="Prox", label_font=font_trek, fill_color=0xFFFFFF)
button_uv = Button(x=163, y=200, width=70, height=30,
                   label="Δ", label_font=font_greek, fill_color=0xFFFFFF)
button_ship = Button(x=236, y=200, width=70, height=30,
                    label="Ship", label_font=font_trek, fill_color=0x800000)

button_radiation.fill_color = 0x00FF00  # Active
button_distance.fill_color = 0x800000   # Inactive
button_uv.fill_color = 0x800000        # Inactive
button_ship.fill_color = 0x800000      # Inactive

buttons.append(button_radiation)
buttons.append(button_distance)
buttons.append(button_uv)
buttons.append(button_ship)
splash.append(button_radiation)
splash.append(button_distance)
splash.append(button_uv)
splash.append(button_ship)

# ------------- UI Containers (Only This Switches) ------------- #
content_group = displayio.Group()
splash.append(content_group)

# ------------- Radiation Tab UI ------------- #
view_radiation = displayio.Group()
radiation_label = Label(font=font_trek, text="CPM: --", color=0x00FFFF, scale=1)
radiation_label.x = 70
radiation_label.y = 80
view_radiation.append(radiation_label)

dose_label = Label(font=font_trek, text="DOSE: -- µSv/h", color=0xFFFF00, scale=1)
dose_label.x = 70
dose_label.y = 115
view_radiation.append(dose_label)

# Add a sensor warning label for the "Sensor not found" message
sensor_warning_label = Label(font=font_trek, text="", color=0xFF0000, scale=1)
sensor_warning_label.x = 70
sensor_warning_label.y = 145  # Adjust the y-coordinate as needed
view_radiation.append(sensor_warning_label)

# ------------- Distance Tab UI (Prox) ------------- #
view_distance = displayio.Group()
distance_label = Label(font=font_trek, text="Distance: -- m", color=0x00FFFF, scale=1)
distance_label.x = 70
distance_label.y = 80
view_distance.append(distance_label)

no_data_label = Label(font=font_trek, text="Sensor not detected.", color=0xFF0000, scale=1)
no_data_label.x = 70
no_data_label.y = 130
view_distance.append(no_data_label)

# ------------- UV Sensor Tab UI (Δ) ------------- #
view_uv = displayio.Group()
uv_index_label = Label(font=font_trek, text="UV Index: --", color=0x00FFFF, scale=1)
uv_index_label.x = 70
uv_index_label.y = 80
view_uv.append(uv_index_label)

uv_intensity_label = Label(font=font_trek, text="UV I: --", color=0xFFFF00, scale=1)
uv_intensity_label.x = 70
uv_intensity_label.y = 115
view_uv.append(uv_intensity_label)

no_uv_label = Label(font=font_trek, text="No sensor detected.", color=0xFF0000, scale=1)
no_uv_label.x = 70
no_uv_label.y = 150
view_uv.append(no_uv_label)

# ------------- Ship Tab UI ------------- #
view_ship = displayio.Group()

# Network status labels
ship_status_label = Label(font=font_trek, text="Network Status:", color=0x00FFFF)
ship_status_label.x = 70
ship_status_label.y = 80
view_ship.append(ship_status_label)

ship_connection_label = Label(font=font_trek, text="Not Connected", color=0xFF0000)
ship_connection_label.x = 70
ship_connection_label.y = 100
view_ship.append(ship_connection_label)

solar_frame = Rect(52, 45, 225, 150, fill=0x000022, outline=0x00FFFF)
view_ship.append(solar_frame)

solar_header = Label(font=font_trek, text="SOLAR WEATHER", color=0x00FFFF)
solar_header.x = 10
solar_header.y = 15  # Centered in the 35px high top bar
view_ship.append(solar_header)

wind_speed = Label(font=terminalio.FONT, text="SPEED: - km/s", color=0x00FF00, scale=2)
wind_speed.x = 60
wind_speed.y = 70
view_ship.append(wind_speed)

wind_density = Label(font=terminalio.FONT, text="DENSITY: - p/cm³", color=0x00FF00, scale=2)
wind_density.x = 60
wind_density.y = 100
view_ship.append(wind_density)

mag_field = Label(font=terminalio.FONT, text="MAG FIELD: - nT", color=0x00FF00, scale=2)
mag_field.x = 60
mag_field.y = 130
view_ship.append(mag_field)

status_label = Label(font=terminalio.FONT, text="", color=0xFFFF00)
status_label.x = 60
status_label.y = 165
view_ship.append(status_label)

# Add connect button
connect_button = Button(
    x=180,
    y=160,
    width=90,
    height=30,
    label="Connect to WiFi",
    label_font=terminalio.FONT,
    label_color=0x00FF00,
    fill_color=0x222222
)
view_ship.append(connect_button)

# ------------- Radiation Processing ------------- #
def process_radiation():
    global last_process_time, last_history_time, radiation_count, history_index, history_length

    current_time = time.monotonic()

    if geiger_found and not signal_pin.value:
        radiation_count += 1

    if current_time - last_history_time >= HISTORY_UNIT:
        last_history_time = current_time
        count_history[history_index] = radiation_count
        radiation_count = 0
        history_index = (history_index + 1) % HISTORY_LENGTH
        history_length = min(history_length + 1, HISTORY_LENGTH)
        # Log data after updating history
        cpm = calculate_cpm()
        dose = calculate_uSvh()
        log_data(cpm, dose)

def calculate_cpm():
    return (sum(count_history) * 60) / (history_length * HISTORY_UNIT) if history_length else 0

def calculate_uSvh():
    return calculate_cpm() / K_ALPHA if geiger_found else 0

def update_display():
    global last_button_flash  # Must be at start of function
    current_time = time.monotonic()  # Move this here so it's available for all views
    stardate_label.text = calculate_stardate()
    # For Radiation and UV views, update the scanning label to blink when the sensor is active.
    if view_live == "Radiation":
        if sum(count_history) == 0:
            radiation_label.text = "CPM: --"
            dose_label.text = "DOSE: -- µSv/h"
            sensor_warning_label.text = "Sensor not found"
            scanning_label.text = ""
        else:
            radiation_label.text = f"CPM: {calculate_cpm():.1f}"
            dose_label.text = f"DOSE: {calculate_uSvh():.3f} µSv/h"
            sensor_warning_label.text = ""
            scanning_label.text = "SCANNING"
            scanning_label.color = 0xFFFF00 if int(time.monotonic() % 2) == 0 else 0x000000
    elif view_live == "Distance":
        if lidar_found:
            distance = lidar.distance  # assume in cm, converting to m
            distance_label.text = f"Distance: {distance/100:.2f} m"
            no_data_label.text = ""
        else:
            distance_label.text = "Distance: -- m"
            no_data_label.text = "Sensor not detected."
        scanning_label.text = ""  # No scanning on distance view.
    elif view_live == "UV":
        if uv_sensor_found:
            uv_index_label.text = f"UV Index: {ltr.uvi:.2f}"
            uv_intensity_label.text = f"UV I: {ltr.lux:.2f}"
            no_uv_label.text = ""
            scanning_label.text = "SCANNING"
            scanning_label.color = 0xFFFF00 if int(time.monotonic() % 2) == 0 else 0x000000
        else:
            uv_index_label.text = "UV Index: --"
            uv_intensity_label.text = "UV I: --"
            no_uv_label.text = "No sensor detected."
            scanning_label.text = ""
    elif view_live == "Ship":
        scanning_label.text = ""
        try:
            wifi_status = pyportal.network._wifi.is_connected
            if wifi_status:
                ship_connection_label.text = "Connected"
                ship_connection_label.color = 0x00FF00  # Green
                connect_button.label = "Reconnect"
                connect_button.fill_color = 0x222222  # Normal color
            else:
                ship_connection_label.text = "Not Connected"
                ship_connection_label.color = 0xFF0000  # Red
                
                # Only flash if button is active
                if button_active:
                    if current_time - last_button_flash >= BUTTON_FLASH_INTERVAL:
                        if connect_button.label == "Connecting...":
                            connect_button.label = "Connect to WiFi"
                        connect_button.label = "" if connect_button.label == "Connect to WiFi" else "Connect to WiFi"
                        last_button_flash = current_time
                else:
                    # If button is not active, keep "Connecting..." visible
                    connect_button.label = "Connecting..."
                    connect_button.fill_color = 0x404040  # Darker color
                    
        except Exception as e:
            print(f"Network status check error: {e}")
            ship_connection_label.text = "Status Unknown"
            ship_connection_label.color = 0xFF0000  # Red
            connect_button.fill_color = 0x222222  # Normal color
def switch_view(new_view):
    global view_live
    pyportal.play_file("/sounds/tab.wav")
    if content_group:
        content_group.pop()
    
    # Safely remove delta logo from any previous view
    try:
        view_radiation.remove(delta_logo)
    except:
        pass
    try:
        view_distance.remove(delta_logo)
    except:
        pass
    try:
        view_uv.remove(delta_logo)
    except:
        pass
    try:
        view_ship.remove(delta_logo)
    except:
        pass
        
    view_live = new_view
    if new_view == "Radiation":
        content_group.append(view_radiation)
        view_radiation.append(delta_logo)
        button_radiation.fill_color = 0x00FF00
        button_distance.fill_color = 0x800000
        button_uv.fill_color = 0x800000
        button_ship.fill_color = 0x800000
    elif new_view == "Distance":
        content_group.append(view_distance)
        view_distance.append(delta_logo)
        button_radiation.fill_color = 0x800000
        button_distance.fill_color = 0x00FF00
        button_uv.fill_color = 0x800000
        button_ship.fill_color = 0x800000
    elif new_view == "UV":
        content_group.append(view_uv)
        view_uv.append(delta_logo)
        button_radiation.fill_color = 0x800000
        button_distance.fill_color = 0x800000
        button_uv.fill_color = 0x00FF00
        button_ship.fill_color = 0x800000
    elif new_view == "Ship":
        content_group.append(view_ship)
        view_ship.append(delta_logo)
        button_radiation.fill_color = 0x800000
        button_distance.fill_color = 0x800000
        button_uv.fill_color = 0x800000
        button_ship.fill_color = 0x00FF00

    update_display()

def check_network_status():
    """Check if PyPortal has network connectivity"""
    try:
        return pyportal.network.check_connectivity()
    except Exception as e:
        print(f"Network check error: {e}")
        return False


# ------------- Load and display the Star Trek delta logo AFTER defining all views ------------- #
try:
    print("Attempting to load delta.bmp...")
    delta_bitmap = displayio.OnDiskBitmap("/delta.bmp")

    # Create one instance
    delta_logo = displayio.TileGrid(delta_bitmap, pixel_shader=delta_bitmap.pixel_shader)
    delta_logo.x = 272
    delta_logo.y = 140

    print("✅ Delta logo loaded successfully!")
    print(f"Bitmap size: {delta_bitmap.width}x{delta_bitmap.height}")

    # Add to initial view
    view_radiation.append(delta_logo)  # Since "Radiation" is our default view

    print("✅ Delta logo added to initial screen!")

except Exception as e:
    print(f"❌ Failed to load delta.bmp: {e}")

def update_solar_wind():
    try:
        # NOAA's space weather API endpoint
        url = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"
        response = requests.get(url)
        data = response.json()

        # Get the most recent measurement (last item in the array)
        latest = data[-1]

        # Update display labels
        wind_speed.text = f"SPEED: {float(latest[1]):.1f} km/s"
        wind_density.text = f"DENSITY: {float(latest[2]):.1f} p/cm³"

        # Get magnetic field data from separate endpoint
        mag_url = "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json"
        mag_response = requests.get(mag_url)
        mag_data = mag_response.json()
        latest_mag = mag_data[-1]

        mag_field.text = f"MAG FIELD: {float(latest_mag[6]):.1f} nT"

        # Update status based on solar wind speed
        speed = float(latest[1])
        if speed > 800:
            status_label.text = "WARNING: SOLAR STORM"
            status_label.color = 0xFF0000  # Red
        elif speed > 500:
            status_label.text = "ELEVATED ACTIVITY"
            status_label.color = 0xFFFF00  # Yellow
        else:
            status_label.text = "NOMINAL"
            status_label.color = 0x00FF00  # Green

    except Exception as e:
        print(f"Solar wind update error: {e}")
        status_label.text = "DATA UNAVAILABLE"
        status_label.color = 0xFF0000

last_solar_update = time.monotonic()
SOLAR_UPDATE_INTERVAL = 300  # Update every 5 minutes

# ------------- Main Loop ------------- #
view_live = "Radiation"
content_group.append(view_radiation)

while True:
    touch = ts.touch_point
    if touch:
        # Handle tab buttons
        for i, button in enumerate(buttons):
            if button.contains(touch):
                switch_view(["Radiation", "Distance", "UV", "Ship"][i])
                break

        # Handle Ship tab connect button
        if view_live == "Ship" and connect_button.contains(touch):
            current_time = time.monotonic()
            # Only allow new connection attempts after cooldown
            if button_active and (current_time - last_connection_attempt) >= CONNECTION_COOLDOWN:
                print("\n=== Button Press Debug ===")
                print("Connect button pressed at:", current_time)
                
                # Store attempt time and disable button temporarily
                last_connection_attempt = current_time
                button_active = False
                connect_button.label = "Connecting..."
                connect_button.fill_color = 0x404040  # Darker color while connecting
                
                # Update display once to show "Connecting..."
                update_display()
                
                # Attempt connection
                success = try_connect_wifi()
                
                # Reset button state
                button_active = True
                connect_button.fill_color = 0x222222  # Restore original color
                connect_button.label = "Reconnect" if success else "Connect to WiFi"
                
                print("=== End Button Press ===\n")
                
    process_radiation()
    update_display()

# Update solar wind data periodically
    current_time = time.monotonic()
    if current_time - last_solar_update >= SOLAR_UPDATE_INTERVAL:
        if view_live == "Ship" and pyportal.network._wifi.is_connected:
            # Add a small delay to ensure connection is stable
            time.sleep(0.5)
            if pyportal.network._wifi.is_connected:  # Double-check connection
                update_solar_wind()
                last_solar_update = current_time
