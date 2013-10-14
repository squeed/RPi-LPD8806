#!/usr/bin/env python
import colorsys
import math
import collections

"""
LPD8806.py: Raspberry Pi library for LPD8806 based RGB light strips
Initial code from: https://github.com/Sh4d/LPD8806

Provides the ability to drive a LPD8806 based strand of RGB leds from the
Raspberry Pi

Colors are provided as RGB and converted internally to the strip's 7 bit
values.


Wiring:
	Pi MOSI -> Strand DI
	Pi SCLK -> Strand CI

Most strips use around 10W per meter (for ~32 LEDs/m) or 2A at 5V.
The Raspberry Pi cannot even come close to this so a larger power supply is required, however, due to voltage loss along long runs you will need to put in a new power supply at least every 5 meters. Technically you can power the Raspberry Pi through the GPIO pins and use the same supply as the strips, but I would recommend just using the USB power as it's a much safer option.

Also, while it *should* work without it to be safe you should add a level converter between the Raspberry Pi and the strip's data lines. This will also help you have longer runs.

Example:
	>> import LPD8806
	>> led = LPD8806.LEDStrip()
	>> led.fill(255, 0, 0)
"""

#Not all LPD8806 strands are created equal.
#Some, like Adafruit's use GRB order and the other common order is GRB
#Library defaults to GRB but you can call strand.setChannelOrder(ChannelOrder) 
#to set the order your strands use
class ChannelOrder:
	RGB = [0,1,2] #Probably not used, here for clarity
	
	GRB = [1,0,2] #Strands from Adafruit and some others (default)
	BRG = [1,2,0] #Strands from many other manufacturers
	
	
	
	
	
#Main color object used by all methods
class Color:
	
	#Initialize Color object with option of passing RGB values and brightness
	def __init__(self, r=0.0, g=0.0, b=0.0, bright=1.0):
		if(r > 255.0 or r < 0.0 or g > 255.0 or g < 0.0 or b > 255.0 or b < 0.0):
			raise ValueError('RGB values must be between 0 and 255')
		if(bright > 1.0 or bright < 0.0):
			raise ValueError('Brightness must be between 0.0 and 1.0')
		self.R = r * bright
		self.G = g * bright
		self.B = b * bright
		
	#gets ColorHSV object
	def getColorHSV(self):
		h, s, v = colorsys.rgb_to_hsv(self.R / 255.0, self.G / 255.0, self.B / 255.0)
		return ColorHSV(h * 360, s, v)
	
	def getRGB(self):
		"""Return RGB 3-tuple"""
		return (self.R, self.G, self.B)

	def __str__( self ):
		return "%d,%d,%d" % (self.R, self.G, self.B)
		
#useful for natural color transitions. Increment hue to sweep through the colors
#must call getColorRGB() before passing to any of the methods
class ColorHSV(Color):
	def __init__(self, h=360.0, s=1.0, v=1.0):
		if(h > 360.0 or h < 0.0):
			raise ValueError('Hue value must be between 0.0 and 360.0')
		if(s > 1.0 or s < 0.0):
			raise ValueError('Saturation must be between 0.0 and 1.0')
		if(v > 1.0 or v < 0.0):
			raise ValueError('Value must be between 0.0 and 1.0')
		
		self.H = h
		self.S = s
		self.V = v

	#gets Color object (RGB)
	def getColorRGB(self):
		r, g, b = colorsys.hsv_to_rgb(self.H / 360.0, self.S, self.V)
		return Color(r * 255.0, g * 255.0, b * 255.0)
	
	def getRGB(self):
		"""Return RGB 3-tuple"""
		return colorsys.hsv_to_rgb(self.H / 360.0, self.S, self.V)

	def __str__( self ):
		return "%0.2f,%0.2f,%0.2f" % (self.H, self.S, self.V)
		

class LEDStrip:

	def __init__(self, num_leds, dev="/dev/spidev0.0"):
		#Variables:
		#	num_leds -- strand size
		#	dev -- spi device
		
		self.c_order = ChannelOrder.GRB
		self.dev = dev
		self.spi = open(self.dev, "wb")
		self.num_leds = num_leds
		self.latch_bytes = int((num_leds + 31) / 32)
		self.gamma = bytearray(256)
		self.buffer = [bytearray(3) for x in range(self.num_leds )]
		
		self.masterBrightness = 1.0

		#anim step vars
		self.rainbowStep = 0
		self.rainbowCycleStep = 0
		self.wipeStep = 0
		self.chaseStep = 0
		self.larsonStep = 0
		self.larsonDir = -1
		self.larsonLast = 0
		self.waveStep = 0
		
		for i in range(256):
			# Color calculations from
			# http://learn.adafruit.com/light-painting-with-raspberry-pi
			self.gamma[i] = 0x80 | int(
				pow(float(i) / 255.0, 2.5) * 127.0 + 0.5
			)

		#Do a latch to get the LED to a known-good state
		self._latch()

		#Update each buffer to off
		self[0:] =  [ [0,0,0] ] * self.num_leds

	#Allows for easily using LED strands with different channel orders
	def setChannelOrder(self, order):
		self.c_order = order
	
	#Set the master brightness for the LEDs 0.0 - 1.0
	def setMasterBrightness(self, bright):
		if(bright > 1.0 or bright < 0.0):
			raise ValueError('Brightness must be between 0.0 and 1.0')
		self.masterBrightness = bright
	
	def _latch(self):
		self.spi.write(bytearray( b'\x00' * self.latch_bytes ))
		self.spi.flush()
		
		
	#Push new data to strand
	def update(self):
		for entry in self.buffer: 
			self.spi.write(entry)
		self._latch()
		
	###
	## implement the container protocol
	###

	def __len__(self):
		return len(self.buffer)
	
	#return the (r,g,b) 3-tuple
	def __getitem__ (self, key):
		return self.buffer[key]
	
	def __setitem__(self, key, value):
		"""Set a particular pixel.

		Value can be either a Color object or a (r,g,b) 3-tuple
		"""

		if isinstance(key, slice):
			i = key.start
			stop = key.stop
			step = key.step
			if not stop:
				stop = self.num_leds
			if not step:
				step = 1

			while i < stop:
				v = value.pop(0)
				if isinstance(v, Color):
					v = v.getRGB()
				if len(v) != 3:
					raise ValueError("Input must be Color or 3-tuple")
				self[i] = v
				i += step
			return

		if isinstance(value, Color):
			value = value.getRGB()
		if len(value) != 3:
			raise ValueError("Input must be Color or 3-tuple")

		for dest, val in zip(self.c_order, value):
			self.buffer[key][dest] = self.gamma[int(val * self.masterBrightness)]

	
	def __delitem__(self, key):
		del self.buffer[key]
	

	#####
	##
	## Some utility functions
	##
	####
	
	#Fill the strand (or a subset) with a single color using a Color object
	def fill(self, color, start = 0, end = None):
		if end == None:
			end = self.num_leds
		self[start:end] = [ color] * (end - start)
	

	#Fill the strand (or a subset) with a single color using RGB values
	def fillRGB(self, r, g, b, start=0, end=None):
		if end == None:
			end = self.num_leds

		self[start:end] = [[r,g,b]] * (end - start)
		
	#Fill the strand (or a subset) with a single color using HSV values
	def fillHSV(self, h, s, v, start=0, end=None):
		self.fill(ColorHSV(h ,s, v), start=start, end=end)


	#Fill the strand (or a subset) with a single color using a Hue value. 
	#Saturation and Value components of HSV are set to max.
	def fillHue(self, hue, start=0, end=None):
		self.fill(ColorHSV(hue), start=start, end=end)
		
	def fillOff(self, start=0, end=None):
		self.fill(Color(0,0,0), start=start, end=end)

	#Set single pixel to Color value
	def set(self, pixel, color):
		self[pixel] = color

	#Set single pixel to RGB value
	def setRGB(self, pixel, r, g, b):
		self[pixel] = (r, g, b)
		
	#Set single pixel to HSV value
	def setHSV(self, pixel, h, s, v):
		self[pixel] = ColorHSV(h, s, v)

	#Set single pixel to Hue value.
	#Saturation and Value components of HSV are set to max.
	def setHue(self, pixel, hue):
		self[pixel] =  ColorHSV(hue)
		
	#turns off the desired pixel
	def setOff(self, pixel):
		self[pixel] = (0, 0, 0)

	#Turn all LEDs off.
	def all_off(self):
		self.fillOff()
		self.update()
		self.fillOff()
		self.update()

	#Get color from wheel value (0 - 384)
	def wheel_color(self, wheelpos):
		if wheelpos < 0:
			wheelpos = 0
		if wheelpos > 384:
			wheelpos = 384
			
		if wheelpos < 128:
			r = 127 - wheelpos % 128
			g = wheelpos % 128
			b = 0
		elif wheelpos < 256:
			g = 127 - wheelpos % 128
			b = wheelpos % 128
			r = 0
		else:
			b = 127 - wheelpos % 128
			r = wheelpos % 128
			g = 0
			
		color = Color(r, g, b)
		return color

	#generate rainbow
	def anim_rainbow(self, start=0, end=0):
		if end == 0 or end > self.num_leds:
			end = self.num_leds
		size = end - start 
		
		for i in range(size):
			color = (i + self.rainbowStep) % 384
			c = self.wheel_color(color)
			hue = (i + self.larsonStep) % 360
			self.set(start + i, c)
		
		self.rainbowStep += 1
		if self.rainbowStep > 384:
			self.rainbowStep = 0
		
	#Generate rainbow wheel equally distributed over strip
	def anim_rainbow_cycle(self, start=0, end=0):
		if end == 0 or end > self.num_leds:
			end = self.num_leds
		size = end - start 
		
		for i in range(size):
			color = (i * (384 / size) + self.rainbowCycleStep) % 384
			c = self.wheel_color(color)
			self.set(start + i, c)

		self.rainbowCycleStep += 1
		if self.rainbowCycleStep > 384:
			self.rainbowCycleStep = 0
		
	#fill the dots progressively along the strip
	def anim_color_wipe(self, color, start=0, end=0):
		if end == 0 or end > self.num_leds:
			end = self.num_leds
			
		if(self.wipeStep == 0):
			self.fillOff()
		
		self.set(start + self.wipeStep, color)
		
		self.wipeStep += 1
		if start + self.wipeStep >= end:
			self.wipeStep = 0
		
	#chase one pixel down the strip
	def anim_color_chase(self, color, start=0, end=0):
		if end == 0 or end > self.num_leds:
			end = self.num_leds
			
		if(self.chaseStep == 0):
			self.setOff(end - 1)
		else:
			self.setOff(start + self.chaseStep )
			
		self.set(start + self.chaseStep, color)

		self.chaseStep += 1
		if start + self.chaseStep >= end:
			self.chaseStep = 0
		
	#larson scanner (i.e. Cylon Eye or K.I.T.T.)
	def anim_larson_scanner(self, color, tail=2, fade=0.75, start=0, end=0):
		if end == 0 or end > self.num_leds:
			end = self.num_leds
		size = end - start 
		
		tail += 1 #makes tail math later easier
		if tail >= size / 2:
			tail = (size / 2) - 1
		
		self.larsonLast = start + self.larsonStep;
		self.set(self.larsonLast, color)
		
		tl = tail
		if(self.larsonLast + tl >= end):
			tl = end - self.larsonLast
		tr = tail
		if(self.larsonLast - tr < start):
			tr = self.larsonLast - start
			
		for l in range(0, tl):
			level = (float(tail - l) / float(tail)) * fade
			self.setRGB(self.larsonLast + l, color.R * level, color.G * level, color.B * level)

		if(self.larsonLast + tl <= end):
			self.setOff(self.larsonLast + tl)
			
		for r in range(0, tr):
			level = (float(tail - r) / float(tail)) * fade
			self.setRGB(self.larsonLast - r, color.R * level, color.G * level, color.B * level)

			
		if(self.larsonLast - tr  >= start):
			self.setOff(self.larsonLast - tr - 1)
		
		if start + self.larsonStep == end:
			self.larsonDir = -self.larsonDir
		elif self.larsonStep == 0:
			self.larsonDir = -self.larsonDir
			
		self.larsonStep += self.larsonDir
		
	#larson scanner (i.e. Cylon Eye or K.I.T.T.) but Rainbow
	def anim_larson_rainbow(self, tail=2, fade=0.75, start=0, end=0):
		if end == 0 or end > self.num_leds:
			end = self.num_leds
		size = end - start 
		
		hue = (self.larsonStep * (360 / size))
		
		self.anim_larson_scanner(ColorHSV(hue).getColorRGB(), tail, fade, start, end)
		
	#Sine wave animation
	PI = 3.14159265
	def anim_wave(self, color, cycles, start=0, end=0):
		if end == 0 or end > self.num_leds:
			end = self.num_leds
		size = end - start 
		
		c2 = Color()
		for i in range(size):
			y = math.sin(self.PI * float(cycles) * float(self.waveStep * i) / float(size))
			if(y >= 0.0):
				#Peaks of sine wave are white
				y = 1.0 - y #Translate Y to 0.0 (top) to 1.0 (center)
				c2 = Color(255 - float(255 - color.R) * y, 255 - float(255 - color.G) * y, 255 - float(255 - color.B) * y) 
			else:
				#Troughs of sine wave are black
				y += 1.0 #Translate Y to 0.0 (bottom) to 1.0 (center)
				c2 = Color(float(color.R) * y, float(color.G) * y, float(color.B) * y)
			self.set(start + i, c2)
		
		self.waveStep += 1

