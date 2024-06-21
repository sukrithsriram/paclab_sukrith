"""Classes for controlling different hardware.

Currently implemented:
* WheelListener - Detects the position of a rotary encoder
* TouchListener - Detects touches
"""
import pigpio

class WheelListener(object):
    """Receives signals from a rotary encoder and stores wheel position.
    
    This object receives signals on three DIO lines and uses them to store
    the position of a rotary encoder. We use a Kübler 05.2400.1122.1024
    rotary encoder recommended by IBL. 
    Datasheet: https://drive.google.com/file/d/1Y95cqs52OjytGU67Y5xVW1t9NaVyPEWe/view
    
    The current position of the wheel is computed and stored in the variable
    "self.position". This is an integer that starts at zero when this object
    is initialized and increase for ?? rotation and decreases for ?? rotation.
    
    Methods
    -------
        __init__: Create a new instance
        print_position: Prints position and debug info to stdout
    
    Attributes
    ----------
        position: Current position
    
    Operation
    ---------
    This devices provides takes two inputs (ground and 5V power) and provides
    three outputs that we use:
        * A (green wire). 
        * B (gray wire).
        * O (blue wire). 
    We generally ignore the inverting outputs. 
    
    The state AB of the rotary encoder can take one of four values:
    00 10
    01 11
    
    In this arrangement:
    When A goes up, move right. When A goes down, move left.
    When B goes up, move down. When B goes down, move up.
    When the state moves clockwise, increment position.
    When the state moves counter-clockwise, decrement position.
    
    Input O is not implemented yet, but I think this goes high when the wheel
    is in the home position. So this could be used to get its absolute position,
    but we probably don't need that.
    """
    def __init__(self, pigpio_conn=None, dio_A=17, dio_B=27, dio_O=None):
        """Initalize a WheelListener using pigpio connection pi
        
        Arguments
        ---------
            pigpio_conn: `pigpio.pi` object or None
                Connection to pigpio returned by pigpio.pi()
                If None, we will instantiate one here
            dio_A: int (default 17)
                GPIO pin number that A is connected to
                All pin numbers are BCM number, not a BOARD (plug) number
            dio_B: int (default 27)
                GPIO pin number that B is connected to
            dio_O: currently not implemented, ignore
        """
        ## Save provided variables
        # Pigpio connection
        if pigpio_conn is None:
            self._pigpio_conn = pigpio.pi()
        else:
            self._pigpio_conn = pigpio_conn
        
        # Pins
        self._dio_A = dio_A
        self._dio_B = dio_B
        
        
        ## Public attributes
        # Current position (initialized to zero)
        self.position = 0
        
        # Log the events and states for debugging
        self.event_log = []
        self.state_log = []

        
        ## Private attributes
        # Keep track of the state of A and B
        self._a_state = 0
        self._b_state = 0
        
        
        ## Set up callbacks
        self.pigpio_conn.callback(self._dio_A, pigpio.RISING_EDGE, self.pulseA_detected)
        self.pigpio_conn.callback(27, pigpio.RISING_EDGE, self.pulseB_detected)
        self.pigpio_conn.callback(17, pigpio.FALLING_EDGE, self.pulseA_down)
        self.pigpio_conn.callback(27, pigpio.FALLING_EDGE, self.pulseB_down)
        
    def pulseA_detected(self, pin, level, tick):
        self.event_log.append('A')
        self.a_state = 1
        if self.b_state == 0:
            self.position += 1
        else:
            self.position -= 1
        self.state_log.append(
            '{}{}_{}'.format(self.a_state, self.b_state, self.position))

    def pulseB_detected(self, pin, level, tick):
        self.event_log.append('B')
        self.b_state = 1
        if self.a_state == 0:
            self.position -= 1
        else:
            self.position += 1
        self.state_log.append(
            '{}{}_{}'.format(self.a_state, self.b_state, self.position))

    def pulseA_down(self, pin, level, tick):
        self.event_log.append('a')
        self.a_state = 0
        if self.b_state == 0:
            self.position -= 1
        else:
            self.position += 1
        self.state_log.append(
            '{}{}_{}'.format(self.a_state, self.b_state, self.position))

    def pulseB_down(self, pin, level, tick):
        self.event_log.append('b')
        self.b_state = 0
        if self.a_state == 0:
            self.position += 1
        else:
            self.position -= 1
        self.state_log.append(
            '{}{}_{}'.format(self.a_state, self.b_state, self.position))

    def print_position(self):
        print("current position: {}".format(self.position))
        print(''.join(self.event_log[-60:]))
        print('\t'.join(self.state_log[-4:]))

class TouchListener(object):
    def __init__(self, pi):
        # Global variables
        self.pigpio_conn = pi
        self.last_touch = datetime.datetime.now()
        self.touch_state = False

        self.pigpio_conn.set_mode(16, pigpio.INPUT)
        self.pigpio_conn.callback(16, pigpio.RISING_EDGE, self.touch_happened)
        self.pigpio_conn.callback(16, pigpio.FALLING_EDGE, self.touch_stopped)

    def touch_happened(self, pin, level, tick):
        touch_time = datetime.datetime.now()
        if touch_time - self.last_touch > datetime.timedelta(seconds=1):
            print('touch start received tick={} dt={}'.format(tick, touch_time))
            self.last_touch = touch_time
            self.touch_state = True
        else:
            print('touch start ignored tick={} dt={}'.format(tick, touch_time))
    
    def touch_stopped(self, pin, level, tick):
        touch_time = datetime.datetime.now()
        if touch_time - self.last_touch > datetime.timedelta(seconds=1):
            print('touch stop  received tick={} dt={}'.format(tick, touch_time))
            self.last_touch = touch_time
            self.touch_state = False
        else:
            print('touch stop  ignored tick={} dt={}'.format(tick, touch_time))    

    def report(self):
        print("touch state={}; last_touch={}".format(self.touch_state, self.last_touch))
