import brickpi3 # import the BrickPi3 drivers
import time
import math
import sys
import logging
import threading
from di_sensors.easy_mutex import ifMutexAcquire, ifMutexRelease 
from di_sensors.inertial_measurement_unit import InertialMeasurementUnit
from di_sensors.temp_hum_press import TempHumPress
#DO I NEED TO USE MUTEX???

NOREADING = 3000 #just using 3000 to represent no reading
MAGNETIC_DECLINATION = 11 #i believe this is correct for Brisbane
USEMUTEX = True #avoid threading issues using the IMU sensorm might need to use this for thermal sensor

#Created a Class to wrap the robot functionality, one of the features is the idea of keeping track of the CurrentCommand, this is important when more than one process is running...
class BrickPiInterface():

    #Initialise log and timelimit
    def __init__(self, timelimit=20):
        self.logger = logging.getLogger(__name__) #default logger
        self.CurrentCommand = "loading"
        self.BP = brickpi3.BrickPi3() # Create an instance of the BrickPi3
        self.timelimit = timelimit
        self.imu_status = 0 
        self.set_ports()
        self.CurrentCommand = "loaded" #when the device is ready for a new instruction it will be set to stop
        return

    #--- Initialise Ports --------#
    def set_ports(self):
        bp = self.BP
        self.rightmotor = bp.PORT_A
        self.leftmotor = bp.PORT_B
        self.largemotors = bp.PORT_A + bp.PORT_B
        self.mediummotor = bp.PORT_C
        self.thermal = bp.PORT_1 #Thermal infrared Sensor
        self.colour = bp.PORT_2 #Colour Sensor
        self.ultra = bp.PORT_4 #ultraSonic Sensor
        self.claw_closed = False #Current state of the claw
        self.thermal_thread = None #DO NOT REMOVE THIS - USED LATER
        #self.gyro = bp.PORT_3  #lego Gyro Sensor - replaced with IMU sensor
        #self.thp = TempHumPress() #port is the I2c Grove
        self.configure_sensors()
        return

    #-- Configure Sensors ---------#
    def configure_sensors(self):
        bp = self.BP
        bp.set_sensor_type(self.colour, bp.SENSOR_TYPE.EV3_COLOR_COLOR)
        #bp.set_sensor_type(self.gyro, bp.SENSOR_TYPE.EV3_GYRO_ABS_DPS)
        bp.set_sensor_type(self.ultra, bp.SENSOR_TYPE.EV3_ULTRASONIC_CM)
        bp.set_sensor_type(self.thermal, bp.SENSOR_TYPE.I2C, [0, 20])
        self.imu = InertialMeasurementUnit()
        time.sleep(4)
        bp.set_motor_limits(self.mediummotor, 100, 600) #set power / speed limit 
        self.start_thermal_infrared_thread()
        return

    #-- Start Infrared I2c Thread ---------#
    def start_thermal_infrared_thread(self):
        self.thermal_thread = threading.Thread(target=self.__update_thermal_sensor_thread, args=(1,))
        self.thermal_thread.daemon = True
        self.thermal_thread.start()
        return

    #changes the logger
    def set_log(self, logger):
        self.logger=logger
        return

    #-----------SENSOR COMMAND----------------#
    #get the current voltage - need to work out how to determine battery life
    def get_battery(self):
        return self.BP.get_voltage_battery()

    #self.log out a complete output from the IMU sensor
    def calibrate_imu(self, timelimit=20):
        self.stop_all() #stop everything while calibrating...
        self.CurrentCommand = "calibrate_imu"
        self.log("Move around the robot to calibrate the Compass Sensor...")
        self.imu_status = 0
        elapsed = 0; start = time.time()
        timelimit = start + timelimit #maximum of 20 seconds to calibrate compass sensor
        
        while self.imu_status != 3 and time.time() < timelimit:
            newtime = time.time()
            newelapsed = int(newtime - start)
            if newelapsed > elapsed:
                elapsed = newelapsed
                self.log("Calibrating IMU. Status: " + str(self.imu_status) + " Time: " + str(elapsed))
            
            ifMutexAcquire(USEMUTEX)
            try:
                self.imu_status = self.imu.BNO055.get_calibration_status()[3]
                time.sleep(0.01)
            except Exception as error:
                self.log("IMU Calibration Error: " + str(error))
            finally:
                ifMutexRelease(USEMUTEX)
        if self.imu_status == 3:
            self.log("IMU Compass Sensor has been calibrated")
            return True
        else:
            self.log("Calibration unsucessful")
            return 
        
        return

   #returns the compass value from the IMU sensor - note if the IMU is placed near a motor it can be affected -SEEMS TO RETURN A VALUE BETWEEN -180 and 180. 
    def get_compass_IMU(self):
        heading = NOREADING
        ifMutexAcquire(USEMUTEX)
        try:
            (x, y, z)  = self.imu.read_magnetometer()
            time.sleep(0.01)
            heading = int(math.atan2(y, x)*(180/math.pi)) + MAGNETIC_DECLINATION 
            #make it 0 - 360 degrees
            if heading < 0:
                heading += 360
            elif heading > 360:
                heading -= 360
        except Exception as error:
            self.logger.error("IMU: " + str(error))
        finally:
            ifMutexRelease(USEMUTEX)
        return heading

    #returns the absolute orientation value using euler rotations, I think this is calilbrated from the compass sensor and therefore requires calibration
    def get_orientation_IMU(self):
        readings = (NOREADING,NOREADING,NOREADING)
        ifMutexAcquire(USEMUTEX)
        try:
            readings = self.imu.read_euler()
            time.sleep(0.01)
        except Exception as error:
            self.logger.error("IMU Orientation: " + str(error))
        finally:
            ifMutexRelease(USEMUTEX)
        return readings  
    
    #returns the acceleration from the IMU sensor - could be useful for detecting collisions or an involuntary stop
    def get_linear_acceleration_IMU(self):
        readings = (NOREADING,NOREADING,NOREADING)
        ifMutexAcquire(USEMUTEX)
        try:
            #readings = self.imu.read_accelerometer()
            readings = self.imu.read_linear_acceleration()
            readings = tuple([int(i*100) for i in readings])
            time.sleep(0.01)
        except Exception as error:
            self.logger.error("IMU Acceleration: " + str(error)) 
        finally:
            ifMutexRelease(USEMUTEX)   
        return readings

    #get the gyro sensor angle/seconds acceleration from IMU sensor
    def get_gyro_sensor_IMU(self):
        gyro_readings = (NOREADING,NOREADING,NOREADING)
        ifMutexAcquire(USEMUTEX)
        try:
            gyro_readings = self.imu.read_gyroscope() #degrees/s
            time.sleep(0.01)
        except Exception as error:
            self.logger.error("IMU GYRO: " + str(error))
            self.CurrentCommand = "stop"
        finally:
            ifMutexRelease(USEMUTEX)
        return gyro_readings

    #gets the temperature using the IMU sensor
    def get_temperature_IMU(self):
        temp = NOREADING
        ifMutexAcquire(USEMUTEX)
        try:
            temp = self.imu.read_temperature()
            time.sleep(0.01)
        except Exception as error:
            self.logger.error("IMU Temp: " + str(error))
            self.CurrentCommand = "stop"
        finally:
            ifMutexRelease(USEMUTEX)
        return temp

    #The EV3 gyro sensor sends an absolute rotation value
    def get_gyro_sensor_EV3(self):
        bp = self.BP
        degrees = 0
        try:
            degrees = bp.get_sensor(self.gyro)[0]
            time.sleep(0.01)
        except brickpi3.SensorError as error:
            self.logger.error("EV3 GYRO: " + str(error))
            self.CurrentCommand = "stop"
        return degrees    

    #get the ultrasonic sensor
    def get_ultra_sensor(self):
        distance = NOREADING
        bp = self.BP
        try:
            distance = bp.get_sensor(self.ultra)
            time.sleep(0.3)
        except brickpi3.SensorError as error:
            self.logger.error("ULTRASONIC: " + str(error))
            self.CurrentCommand = "stop"
        return distance

    #read temp and humidity from the I2C port, you need an I2C temp sensor - #disabled currently
    def get_temp_humidity_press_I2C(self):
        temp, hum, press = (NOREADING,NOREADING,NOREADING)
        #ifMutexAcquire(USEMUTEX)
        try:
            temp = self.thp.get_temperature_celsius()
            hum = self.thp.get_humidity()
            press = self.thp.get_pressure()
            time.sleep(0.01)
        except brickpi3.SensorError as error:
            self.logger.error("TEMP HUMIDY PRESSURE: " + str(error))
            return (0,0,0)
        finally:
            pass
            #ifMutexRelease(USEMUTEX)
        return(temp,hum,press) #return a tuple containing temp,hum,press'''

    #returns the colour current sensed - "none", "Black", "Blue", "Green", "Yellow", "Red", "White", "Brown"
    def get_colour_sensor(self):
        bp = self.BP
        value = 0
        colours = ["NOREADING", "Black", "Blue", "Green", "Yellow", "Red", "White", "Brown"]
        try: 
            value = bp.get_sensor(self.colour) 
            time.sleep(0.01)
        except brickpi3.SensorError as error:
            self.logger.error("COLOUR: " + str(error))    
        return colours[value]

    #updates the thermal sensor by making continual I2C transactions through a thread
    def __update_thermal_sensor_thread(self, name):
        while self.CurrentCommand != "exit":
            self.update_thermal_sensor()
        return

    #updates the thermal sensor by making a single I2C transaction
    def update_thermal_sensor(self):
        bp = self.BP
        TIR_I2C_ADDR        = 0x0E      # TIR I2C device address 
        TIR_AMBIENT         = 0x00      # Ambient Temp
        TIR_OBJECT          = 0x01      # Object Temp
        TIR_SET_EMISSIVITY  = 0x02      
        TIR_GET_EMISSIVITY  = 0x03
        TIR_CHK_EMISSIVITY  = 0x04
        TIR_RESET           = 0x05
        #ifMutexAcquire(USEMUTEX)
        try:
            bp.transact_i2c(self.thermal, TIR_I2C_ADDR, [TIR_OBJECT], 2)
            time.sleep(0.01)
        except Exception as error:
            self.logger.error("THERMAL UPDATE: " + str(error))
        finally:
            pass
            #ifMutexRelease(USEMUTEX)
        return

    #return the infrared temperature - if usethread=True - it uses the thread set up in init
    def get_thermal_sensor(self, usethread=True):
        bp = self.BP
        temp = 0
        if not usethread:
            self.update_thermal_sensor() #not necessary if thread is running
        #ifMutexAcquire(USEMUTEX)
        try:
            value = bp.get_sensor(self.thermal) # read the sensor values
            time.sleep(0.01)
            temp = (float)((value[1] << 8) + value[0]) # join the MSB and LSB part
            temp = temp * 0.02 - 0.01                  # Converting to Celcius
            temp = temp - 273.15                       
        except Exception as error:
            self.logger.error("THERMAL READ: " + str(error))
        finally:
            pass
            #ifMutexRelease(USEMUTEX)    
        return float("%3.f" % temp)

    #disable thermal sensor - might be needed to reenable motors (they disable for some reason when thermal sensor is active)
    def disable_thermal_sensor(self):
        bp = self.BP
        bp.set_sensor_type(self.thermal, bp.SENSOR_TYPE.NONE) 
        return

    #--------------MOTOR COMMANDS-----------------#
    #simply turns motors on
    def move_power(self, power):
        bp = self.BP
        self.CurrentCommand = "move_power"
        self.BP.set_motor_power(self.largemotors, power)
        return

    #moves for the specified time (seconds) and power - use negative power to reverse
    def move_power_time(self, power, t):
        bp = self.BP
        self.CurrentCommand = "move_power_time"
        timelimit = time.time() + t
        while time.time() < timelimit and self.CurrentCommand != "stop":
            bp.set_motor_power(self.largemotors, power)
        self.CurrentCommand = "stop"
        self.BP.set_motor_power(self.largemotors, 0)
        return
    
    #moves with power until obstruction and return time travelled
    def move_power_untildistanceto(self, power, distanceto):
        self.CurrentCommand = "move_power_untildistanceto"
        bp = self.BP
        distancedetected = 300 # to set an inital distance detected before loop
        elapsedtime = 0;  start = time.time()
        #ultra sonic sensors can sometimes return 0
        bp.set_motor_power(self.largemotors, power)
        timelimit = time.time() + self.timelimit
        while ((distancedetected > distanceto or distancedetected == 0.0) and (self.CurrentCommand != "stop") and (time.time() < timelimit)):
            distancedetected = self.get_ultra_sensor()
            self.logger.info("MOVING - Distance detected: " + str(distancedetected))
        self.CurrentCommand = "stop"
        elapsedtime = time.time() - start
        bp.set_motor_power(self.largemotors, 0)
        return elapsedtime

    #Rotate power and time, -power to reverse
    def rotate_power_time(self, power, t):
        if self.CurrentCommand != 'stop':
            return
        self.CurrentCommand = "rotate_power_time"
        bp = self.BP
        target = time.time() + t
        while time.time() < target and self.CurrentCommand != 'stop':
            bp.set_motor_power(self.rightmotor, -power)
            bp.set_motor_power(self.leftmotor, power)
        bp.set_motor_power(self.largemotors, 0) #stop
        return
        
    #Rotates robot with power and degrees using EV3 Gyro sensor. Negative degrees = left. 
    def rotate_power_degrees_EV3(self, power, degrees):
        self.CurrentCommand = "rotate_power_degrees_EV3"
        bp = self.BP
        currentdegrees = self.get_gyro_sensor()
        targetdegrees = currentdegrees + degrees
        #Complex code - need to reverse if statements based on left or right turn
        symbol = '>' if degrees < 0 else '<'  #shorthand if statement
        power = -(power) if degrees < 0 else power
        expression = 'currentdegrees' + symbol + 'targetdegrees'
        #assuming of robot rotation for longer than 20seconds there is an error and stop
        timelimit = time.time() + self.timelimit
        while eval(expression) and self.CurrentCommand != "stop" and time.time() < timelimit:
            bp.set_motor_power(self.rightmotor, -power)
            bp.set_motor_power(self.leftmotor, power)
            self.log("Gyro degrees remaining: " + str(targetdegrees - currentdegrees))
            currentdegrees = self.get_gyro_sensor()
        self.CurrentCommand = "stop"
        bp.set_motor_power(self.largemotors, 0) #stop
        return
        
    #Rotates the robot with power and degrees using the IMU sensor. Negative degrees = left.
    #the larger the number of degrees and the low the power, the more accurate
    #you can set a margin of error if its a little off
    def rotate_power_degrees_IMU(self, power, degrees, marginoferror=3):
        self.CurrentCommand = "rotate_power_degrees_IMU"
        bp = self.BP
        symbol = '<'; limit = 0
        if degrees == 0:
            return
        elif degrees < 0:
            symbol = '>='; limit = degrees+marginoferror
        else:
            symbol = '<='; limit = degrees-marginoferror; power = -power
        totaldegreesrotated = 0; lastrun = 0
        timelimit = time.time() + self.timelimit #useful if time is exceeded
        self.log("target degrees: " + str(degrees))
        self.log(str(totaldegreesrotated) + str(symbol) + str(limit))
        while eval("totaldegreesrotated" + str(symbol) + "limit") and (self.CurrentCommand != "stop") and (time.time() < timelimit):
            lastrun = time.time()
            bp.set_motor_power(self.rightmotor, power)
            bp.set_motor_power(self.leftmotor, -power)
            self.log("Total degrees rotated: " + str(totaldegreesrotated))
            gyrospeed = self.get_gyro_sensor_IMU()[2] #roate around z-axis
            totaldegreesrotated += (time.time() - lastrun)*gyrospeed
        self.CurrentCommand = "stop"
        bp.set_motor_power(self.largemotors, 0) #stop
        return

    #rotates the robot until faces targetheading - only works for a heading between 0 - 360
    def rotate_power_heading_IMU(self, power, targetheading, marginoferror=3):
        bp = self.BP
        self.CurrentCommand = "rotate_power_heading"
        if targetheading < 0:
            targetheading += 360
        elif targetheading > 360:
            targetheading -= 360
        heading = self.get_compass_IMU()
        if heading == targetheading:
            return
        symbol = '<'; limit = 0
        if heading < targetheading:
            symbol = '<='; limit = targetheading-marginoferror; power = -power
        else:
            symbol = '>='; limit = targetheading+marginoferror; 
        expression = 'heading' + symbol + 'limit'
        self.log('heading'+symbol+str(limit))
        timelimit = time.time() + self.timelimit

        while ((eval(expression) and (self.CurrentCommand != "stop") and time.time() < timelimit)):
            bp.set_motor_power(self.rightmotor, -power)
            bp.set_motor_power(self.leftmotor, power)
            heading = self.get_compass_IMU()
            self.log("Current heading: " + str(heading))
        self.CurrentCommand = "stop"
        bp.set_motor_power(self.largemotors, 0) #stop
        return

    #moves the target class to the target degrees
    def __move_claw_targetdegrees(self, degrees):
        self.CurrentCommand = "move_claw_targetdegrees"
        degrees = -degrees #reversing 
        bp = self.BP
        if degrees == 0:
            return
        bp.offset_motor_encoder(self.mediummotor, bp.get_motor_encoder(self.mediummotor)) #reset encoder
        limit = 0; symbol ='<'
        currentdegrees = 0 
        if degrees > 0:
            symbol = '<'; limit = degrees - 5
        else:
            symbol = '>'; limit = degrees + 5
        expression = 'currentdegrees' + symbol + 'limit'
        currentdegrees = bp.get_motor_encoder(self.mediummotor)

        timelimit = time.time() + self.timelimit/2
        while (eval(expression) and (self.CurrentCommand != "stop") and (time.time() < timelimit)):
            currentdegrees = bp.get_motor_encoder(self.mediummotor) #where is the current angle
            bp.set_motor_position(self.mediummotor, degrees)
            currentdegrees = bp.get_motor_encoder(self.mediummotor) #ACCURACY PROBLEM
        self.CurrentCommand = "stop"
        bp.set_motor_power(self.mediummotor, 0)
        return

    #open the claw
    def open_claw(self, degrees=-1100):
        if self.claw_closed == True:
            self.__move_claw_targetdegrees(degrees)
            self.claw_closed = False
        return

    #close the claw
    def close_claw(self, degrees=1100):
        if self.claw_closed == False:
            self.__move_claw_targetdegrees(degrees)
            self.claw_closed = True   
        return

    #log out whatever !!!!!THIS IS NOT WORKING UNLESS FLASK LOG USED, DONT KNOW WHY!!!!!
    def log(self, message):
        self.logger.info(message)
        return

    #stop all motors and set command to stop
    def stop_all(self):
        bp = self.BP
        bp.set_motor_power(self.largemotors+self.mediummotor, 0)
        self.CurrentCommand = "stop"
        return      

    #returns the current command
    def get_current_command(self):
        return self.CurrentCommand

    #returns a dictionary of all current sensors
    def get_all_sensors(self):
        sensordict = {} #create a dictionary for the sensors
        sensordict['battery'] = self.get_battery()
        sensordict['colour'] = self.get_colour_sensor()
        sensordict['ultrasonic'] = self.get_ultra_sensor()
        sensordict['thermal'] = self.get_thermal_sensor()
        sensordict['acceleration'] = self.get_linear_acceleration_IMU()
        sensordict['compass'] = self.get_compass_IMU()
        sensordict['gyro'] = self.get_gyro_sensor_IMU()
        sensordict['temperature'] = self.get_temperature_IMU()
        sensordict['orientation'] = self.get_orientation_IMU()
        #to do need to get temperature from IMU sensor
        return sensordict

    #---EXIT--------------#
    # call this function to turn off the motors and exit safely.
    def safe_exit(self):
        bp = self.BP
        self.stop_all() #stop all motors
        self.logger.info("Exiting")
        bp.reset_all() # Unconfigure the sensors, disable the motors
        time.sleep(2) #gives time to reset??
        return
    
#--------------------------------------------------------------------
#Only execute if this is the main file, good for testing code
if __name__ == '__main__':
    robot = Robot(timelimit=10)
    robot.calibrate_imu()
    print(robot.get_all_sensors())
    #robot.rotate_power_degrees_IMU(20,90)
    #robot.move_power_untildistanceto(30,10)
    #robot.move_power_time(40,1)
    #robot.test_calibrate_imu()
    #robot.rotate_power_time(30, 3)
    #robot.close_claw()
    #robot.rotate_power_heading_IMU(20,90)
    #robot.safe_exit()
    #robot.CurrentCommand = "stop" 
    robot.safe_exit()
    exit()
    #robot.disable_thermal_sensor() -- could also enable and disable thermal sensor when needed'''
