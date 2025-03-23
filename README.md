This CircuitPython sketch shows 4 tabs; Gamma (radiation), Proximity, Delta, and Probes.
Gamma is data pulled from the PocketGeiger from Radiation-watch.com
Proximity is distance data from the Garmin LIDAR Lite 4.0
Delta is from the Adafruit LTR390 UV Light Sensor
Probes has a "connect" button to connect to wifi. It then pulls solar weather data from NOAA (Speed, Density, and Mag). I want to add the Planetary K Index (https://www.swpc.noaa.gov/products/planetary-k-index) but I'm up against RAM limits. It will start pulling the data and then it reboots the Pynt. 

Adafruit, if you're listening, Please update the PyPortal Pynt to 3 or 4 times the RAM, change the USB to type C, and add a battery connector please! :-)

Anyway, please feel free to fork the F out of this and have fun! ... but please share your work! 
