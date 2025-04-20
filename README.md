This CircuitPython sketch shows 4 tabs; Gamma (radiation), Proximity, Delta, and Probes.
Gamma is data pulled from the PocketGeiger from Radiation-watch.com
Proximity is distance data from the Garmin LIDAR Lite V4
Delta is from the Adafruit LTR390 UV Light Sensor
Probes has a "connect" button to connect to wifi. It then pulls solar weather data from NOAA (Speed, Density, and Mag). I want to add the Planetary K Index (https://www.swpc.noaa.gov/products/planetary-k-index) but I'm up against RAM limits. It will start pulling the data and then it reboots the Pynt. 

***VITALLY IMPORTANT***
You MUST use the Garmin LIDAR Lite V4 library in this library file. If you use the one in CircuitPython, I believe every version, it simply won't work. I don't know why. This version was custom modified by @dastels on Adafruit back in 2021ish. Here's the report ticket on GitHub and please note the latest post by @Danh. https://github.com/adafruit/Adafruit_CircuitPython_LIDARLite/issues/14 | If you are a programmer and want to contribute to convert the adafruit_lidarlite.py to adafruit_lidarlite.mpy, so it can ship with future versions. Your contributions are deeply appreciated!

Adafruit, if you're listening, Please update the PyPortal Pynt to 3 or 4 times the RAM, change the USB to type C, and add a battery connector please! :-)

Anyway, please feel free to fork the F out of this and have fun! ... but please share your work! 
