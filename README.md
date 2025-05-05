This CircuitPython sketch shows 3 tabs; Gamma (radiation), Delta, and Probes.
Gamma is data pulled from the PocketGeiger from Radiation-watch.com
Delta is from the Adafruit LTR390 UV Light Sensor
Probes has a "connect" button to connect to wifi. It then pulls solar weather data from NOAA (Speed, Density, and Mag). I want to add the Planetary K Index (https://www.swpc.noaa.gov/products/planetary-k-index) but I'm up against RAM limits. It will start pulling the data and then it reboots the Pynt. 

***PLEASE NOTE***
If you downloaded this before 5/5/2025, please note that the LIDAR is no longer supported in this and future work. The library is not robust and Garmin (or someone) needs to really test the crap out of this before it's used en masse. Here's the report ticket on GitHub and please note the latest post by @Danh. https://github.com/adafruit/Adafruit_CircuitPython_LIDARLite/issues/14 | If you are a programmer and want to contribute to convert the adafruit_lidarlite.py to adafruit_lidarlite.mpy, so it can ship with future versions. Your contributions are deeply appreciated!

Adafruit, if you're listening, Please update the PyPortal Pynt to 3 or 4 times the RAM, change the USB to type C, and add a battery connector please! :-)

Anyway, please feel free to fork the F out of this and have fun! ... but please share your work!
