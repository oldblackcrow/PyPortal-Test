# SPDX-FileCopyrightText: 2018 ladyada for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
`adafruit_lidarlite`
====================================================

A CircuitPython & Python library for Garmin LIDAR Lite V4 LED over I2C

* Author(s): ladyada, dastels

Implementation Notes
--------------------

**Hardware:**


**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://github.com/adafruit/circuitpython/releases

* Adafruit's Bus Device library: https://github.com/adafruit/Adafruit_CircuitPython_BusDevice

"""

# imports
import time
from adafruit_bus_device.i2c_device import I2CDevice
from digitalio import Direction
from micropython import const

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_LIDARLite.git"


_ADDR_DEFAULT = const(0x62)
_REG_ACQ_COMMAND = const(0x00)
_REG_STATUS = const(0x01)
_REG_ACQUISITION_COUNT = const(0x05)
_REG_QUICK_TERMINATION = const(0xE5)
_REG_DISTANCE_LOW = const(0x10)
_REG_CP_VER_LOW = const(0x72)
_REG_HARDWARE_VER = const(0xE1)

_CMD_DISTANCENOBIAS = const(3)
_CMD_DISTANCEWITHBIAS = const(4)

CONFIG_DEFAULT = 0
CONFIG_BALANCED = 1
CONFIG_SHORTFAST = 2
CONFIG_MIDFAST = 3
CONFIG_MAXRANGE = 4
CONFIG_SHORTFASTSLOPPY = 5

STATUS_BUSY = 0x01
STATUS_SIGNAL_OVERFLOW = 0x02
STATUS_REF_OVERFLOW = 0x04
STATUS_LOW_POWER_MODE = 0x08
STATUS_DC_NOISE_BIAS_CORRECTION_DONE = 0x10
STATUS_DC_NOISE_BIAS_ERROR = 0x20

# The various configuration register values, from arduino library
# (acquisition count, quick termination)
_LIDAR_CONFIGS = (
    (0xFF, 0x08),  # default
    (0x80, 0x08),  # balanced
    (0x18, 0x08),  # short range, high speed
    (0x80, 0x00),  # mid range, higher speed on short range targets
    (0xFF, 0x00),  # maximum range, higher speed on short range targets
    (0x04, 0x00),  # very short range, higher speed, high error
)


class LIDARLiteV4LED:
    """
    A driver for the Garmin LIDAR Lite laser distance sensor.
    :param i2c_bus: The `busio.I2C` object to use. This is the only
    required parameter.
    :param int address: (optional) The I2C address of the device to set after initialization.
    """

    def __init__(
        self,
        i2c_bus,
        *,
        configuration=CONFIG_DEFAULT,
        address=_ADDR_DEFAULT
    ):
        """Initialize the hardware for the LIDAR over I2C. You can pass in an
        optional reset_pin for when you call reset(). There are a few common
        configurations Garmin suggests: CONFIG_DEFAULT, CONFIG_BALANCED,
        CONFIG_SHORTFAST,CONFIG_MIDFAST, CONFIG_MAXRANGE, CONFIG_SHORTFASTSLOPPY.
        For the I2C address, the default is 0x62 but if you pass a different
        number in, we'll try to change the address so multiple LIDARs can be
        connected. (Note all but one need to be in reset for this to work!)"""
        self.i2c_device = I2CDevice(i2c_bus, address)
        self._buf = bytearray(2)
        self._bias_count = 0
        time.sleep(0.5)
        self.configure(configuration)


    def configure(self, config):
        """Set the LIDAR desired style of measurement. There are a few common
        configurations Garmin suggests: CONFIG_DEFAULT, CONFIG_BALANCED,
        CONFIG_SHORTFAST,CONFIG_MIDFAST, CONFIG_MAXRANGE, CONFIG_SHORTFASTSLOPPY."""
        settings = _LIDAR_CONFIGS[config]
        self._write_reg(_REG_ACQUISITION_COUNT, settings[0])
        self._write_reg(_REG_QUICK_TERMINATION, settings[1])


    def read_distance(self, bias=False):
        """Perform a distance reading with or without 'bias'. It's recommended
        to take a bias measurement every 100 non-bias readings (they're slower)"""
        if bias:
            self._write_reg(_REG_ACQ_COMMAND, _CMD_DISTANCEWITHBIAS)
        else:
            self._write_reg(_REG_ACQ_COMMAND, _CMD_DISTANCENOBIAS)
        self.wait_while_busy()
        # Get the reading
        dist = self._read_reg(_REG_DISTANCE_LOW, 2)
        return dist[1] << 8 | dist[0]

    @property
    def distance(self):
        """The measured distance in cm. Will take a bias reading every 100 calls"""
        self._bias_count -= 1
        if self._bias_count < 0:
            self._bias_count = 100  # every 100 reads, check bias
        return self.read_distance(self._bias_count == 0)

    @property
    def status(self):
        """The status byte, check datasheet for bitmask"""
        buf = bytearray([_REG_STATUS])
        with self.i2c_device as i2c:
            i2c.write_then_readinto(buf, buf)
        return buf[0]

    @property
    def firmware_version(self):
        """Fetch the coprocessor firmware version"""
        ver = self._read_reg(_REG_CP_VER_LOW, 2)
        return ver[1] << 8 | ver[0]

    @property
    def hardware_version(self):
        """Fetch the board hardware version"""
        ver = self._read_reg(_REG_HARDWARE_VER, 1)
        return ver[0]

    def wait_while_busy(self):
        while self.status & STATUS_BUSY:
            pass

    def _write_reg(self, reg, value):
        self._buf[0] = reg
        self._buf[1] = value
        with self.i2c_device as i2c:
            # print("Writing: ", [hex(i) for i in self._buf])
            i2c.write(self._buf)
        time.sleep(0.001)  # there's a delay in arduino library

    def _read_reg(self, reg, num):
        self._buf[0] = reg
        with self.i2c_device as i2c:
            i2c.write_then_readinto(self._buf, self._buf, out_end=1, in_end=num)
        # print("Read from ", hex(reg), [hex(i) for i in self._buf])
        return self._buf