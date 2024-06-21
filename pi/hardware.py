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
        """Initalize a WheelListener using pigpio connection pigpio_conn
        
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
        # TODO: document these, and limit their growth
        self.event_log = []
        self.state_log = []

        
        ## Private attributes
        # Keep track of the state of A and B
        self._a_state = 0
        self._b_state = 0
        
        
        ## Set up callbacks
        # One call back for rising and one for falling on A and B
        self._pigpio_conn.callback(
            self._dio_A, pigpio.RISING_EDGE, self._pulseA_up)
        self._pigpio_conn.callback(
            self._dio_B, pigpio.RISING_EDGE, self._pulseB_up)
        self._pigpio_conn.callback(
            self._dio_A, pigpio.FALLING_EDGE, self._pulseA_down)
        self._pigpio_conn.callback(
            self._dioB, pigpio.FALLING_EDGE, self._pulseB_down)
        
    def _pulseA_up(self, pin, level, tick):
        """Called whenever A rises"""
        # Set A's state
        self._a_state = 1
        
        # Effect on position depends on B's state
        if self._b_state == 0:
            self.position += 1
        else:
            self.position -= 1
        
        # Log
        self.event_log.append('A')
        self.state_log.append(
            '{}{}_{}'.format(self._a_state, self._b_state, self.position))

    def _pulseB_up(self, pin, level, tick):
        """Called whenever B rises"""
        # Set B's state
        self._b_state = 1
        
        # Effect on position depends on A's state
        if self._a_state == 0:
            self.position -= 1
        else:
            self.position += 1
        
        # Log
        self.event_log.append('B')
        self.state_log.append(
            '{}{}_{}'.format(self._a_state, self._b_state, self.position))

    def _pulseA_down(self, pin, level, tick):
        """Called whenever A falls"""
        # Set A's state
        self._a_state = 0
        
        # Effect on position depends on B's state
        if self._b_state == 0:
            self.position -= 1
        else:
            self.position += 1

        # Log
        self.event_log.append('a')
        self.state_log.append(
            '{}{}_{}'.format(self._a_state, self._b_state, self.position))

    def _pulseB_down(self, pin, level, tick):
        """Called whenever B rises"""
        # Set B's state        
        self._b_state = 0

        # Effect on position depends on A's state
        if self._a_state == 0:
            self.position += 1
        else:
            self.position -= 1
        
        # Log
        self.event_log.append('b')
        self.state_log.append(
            '{}{}_{}'.format(self._a_state, self._b_state, self.position))

    def print_position(self):
        """Prints debug messages about current position and state history"""
        print("current position: {}".format(self.position))
        print(''.join(self.event_log[-60:]))
        print('\t'.join(self.state_log[-4:]))

class TouchListener(object):
    """Receives signals about touches and stores touch state.
    
    This object receives signals on two DIO lines and uses them to store
    the touch status (touched or not touched) of two sensors.
    
    The status of the sensor is in `self.touched`
    
    Methods
    -------
        __init__: Create a new instance
        report: Prints position and debug info to stdout
    
    Attributes
    ----------
        last_touch: datetime of last touch
        touch_state: bool
    """    
    def __init__(self, pigpio_conn, dio_touch0=16, dio_touch1=None):
        """Initalize a TouchListener using pigpio connection pigpio_conn
        
        Arguments
        ---------
            pigpio_conn: `pigpio.pi` object or None
                Connection to pigpio returned by pigpio.pi()
                If None, we will instantiate one here
            dio_touch0: int (default 16)
                GPIO pin number that first sensor is connected to
                All pin numbers are BCM number, not a BOARD (plug) number
            dio_touch0: currently not implemented, ignore
        """        
        ## Save provided variables
        # Pigpio connection
        if pigpio_conn is None:
            self._pigpio_conn = pigpio.pi()
        else:
            self._pigpio_conn = pigpio_conn
        
        # Pins
        self._dio_touch0 = dio_touch0
        self._dio_touch1 = dio_touch1
        
        
        ## Public attributes
        self.last_touch = datetime.datetime.now()
        self.touch_state = False


        ## Set pin as input
        self._pigpio_conn.set_mode(dio_touch0, pigpio.INPUT)

    
        ## Set callbacks
        # Rising
        self._pigpio_conn.callback(
            _dio_touch0, pigpio.RISING_EDGE, self.touch_happened)
        
        # Falling
        self._pigpio_conn.callback(
            _dio_touch0, pigpio.FALLING_EDGE, self.touch_stopped)

    def touch_happened(self, pin, level, tick):
        """Called whenever a touch happens and pin goes high"""
        # Get time of touch
        touch_time = datetime.datetime.now()
        
        # Depends on how long it's been
        if touch_time - self.last_touch > datetime.timedelta(seconds=1):
            # It's been a while: set touch_state to True and store touch_time
            print('touch start received tick={} dt={}'.format(
                tick, touch_time))
            
            self.last_touch = touch_time
            self.touch_state = True
        
        else:
            # It hasn't been long enough: ignore this event
            print('touch start ignored tick={} dt={}'.format(
                tick, touch_time))
    
    def touch_stopped(self, pin, level, tick):
        """Called whenever a touch stops and pin goes low"""
        # Get time of touch
        touch_time = datetime.datetime.now()
        
        # Depends on how long it's been
        if touch_time - self.last_touch > datetime.timedelta(seconds=1):
            # It's been a while: set touch_state to False and store touch_time
            print('touch stop  received tick={} dt={}'.format(
                tick, touch_time))
            
            self.last_touch = touch_time
            self.touch_state = False
        
        else:
            # It hasn't been long enough: ignore this event
            # TODO: fix this, for a single brief touch the offset will never
            # be detected
            print('touch stop  ignored tick={} dt={}'.format(
                tick, touch_time))    

    def report(self):
        """Print debug message about status of touch"""
        print("touch state={}; last_touch={}".format(
            self.touch_state, self.last_touch))
