## Main script that runs on each Pi to run behavior

import zmq
import pigpio
import numpy as np
import os
import jack
import time
import threading
import random
import json
import socket as sc


## Killing previous pigpiod and jackd background processes
os.system('sudo killall pigpiod')
os.system('sudo killall jackd')

# Wait long enough to make sure they are killed
time.sleep(1)


## Starting pigpiod and jackd background processes
# Start pigpiod
# TODO: document these parameters
os.system('sudo pigpiod -t 0 -l -x 1111110000111111111111110000')
time.sleep(1)

# Start jackd
# TODO: document these parameters
# TODO: Use subprocess to keep track of these background processes
os.system(
    'jackd -P75 -p16 -t2000 -dalsa -dhw:sndrpihifiberry -P -r192000 -n3 -s &')
time.sleep(1)


## Load parameters for this pi
# Get the hostname of this pi and use that as its name
pi_hostname = sc.gethostname()
pi_name = str(pi_hostname)

# Load the config parameters for this pi
# TODO: document everything in params
param_directory = f"configs/pis/{pi_name}.json"
with open(param_directory, "r") as p:
    params = json.load(p)    


## Define a JackClient, which will play sounds in the background
# TODO: rename this SoundPlayer or similar to avoid confusion with jack.Client
# TODO: move this to another file and import it
class JackClient:
    """Object to play sounds"""
    def __init__(self, name='jack_client', outchannels=None):
        """Initialize a new JackClient

        This object contains a jack.Client object that actually plays audio.
        It provides methods to send sound to its jack.Client, notably a 
        `process` function which is called every 5 ms or so.
        
        name : str
            Required by jack.Client
        
        outchannels : None
            TODO: remove this functionality, we will always have stereo
        
        Presently, this object can have its acoustic properties set by
        external code, and it will constantly generate sound and send it 
        to its jack.Client. It will also send messages to poke_socket.
        
        TODO
        * Decouple the sound generation into another object. 
        * Decouple the networking messages into another object.
        * Implement more precise logging of exactly when the sound comes out.
        
        This object should focus only on playing sound as precisely as
        possible.
        """
        ## Store provided parameters
        self.name = name
        
        ## Acoustic parameters of the sound
        # TODO: define these elsewhere -- these should not be properties of
        # this object, because this object should be able to play many sounds
        
        # This determines which channel plays sound
        self.set_channel = 'none'  # 'left', 'right', or 'none'
        
        # Lock for thread-safe set_channel() updates
        self.lock = threading.Lock()  
        
        # Duration of each chunk (noise burst) in seconds
        self.chunk_duration = 0.01  
        
        # Pause duration between chunk in seconds
        self.pause_duration = random.uniform(0.05, 0.2)  
        
        # Amplitude of the sound
        self.amplitude = random.uniform(0.005, 0.02)
        
        # Variable to store the time of the last burst
        self.last_chunk_time = time.time()  

        
        ## Create the contained jack.Client
        # Creating a jack client
        self.client = jack.Client(self.name)

        # Pull these values from the initialized client
        # These come from the jackd daemon
        # `blocksize` is the number of samples to provide on each `process`
        # call
        self.blocksize = self.client.blocksize
        
        # `fs` is the sampling rate
        self.fs = self.client.samplerate
        
        # Debug message
        # TODO: add control over verbosity of debug messages
        print("Received blocksize {} and fs {}".format(self.blocksize, self.fs))

        
        ## Set up outchannels
        # TODO: outchannels should always be [0, 1] and mono_output should
        # always be False
        
        # Set the number of output channels
        if outchannels is None:
            self.outchannels = [0, 1]
        else:
            self.outchannels = outchannels

        # Set mono_output
        if len(self.outchannels) == 1:
            self.mono_output = True
        else:
            self.mono_output = False

        # Register outports
        if self.mono_output:
            # One single outport
            self.client.outports.register('out_0')
        else:
            # One outport per provided outchannel
            for n in range(len(self.outchannels)):
                self.client.outports.register('out_{}'.format(n))


        ## Set up the process callback
        # This will be called on every block and must provide data
        self.client.set_process_callback(self.process)

        
        ## Activate the client
        self.client.activate()


        ## Hook up the outports (data sinks) to physical ports
        # Get the actual physical ports that can play sound
        target_ports = self.client.get_ports(
            is_physical=True, is_input=True, is_audio=True)

        # Depends on whether we're in mono mode
        # TODO: Assume always stereo and simplify this
        if self.mono_output:
            ## Mono mode
            # Hook up one outport to all channels
            for target_port in target_ports:
                self.client.outports[0].connect(target_port)
        
        else:
            ## Not mono mode
            # Error check
            if len(self.outchannels) > len(target_ports):
                raise ValueError(
                    "Cannot connect {} ports, only {} available".format(
                    len(self.outchannels),
                    len(target_ports),))
            
            # Hook up one outport to each channel
            for n in range(len(self.outchannels)):
                # This is the channel number the user provided in OUTCHANNELS
                index_of_physical_channel = self.outchannels[n]
                
                # This is the corresponding physical channel
                # I think this will always be the same as index_of_physical_channel
                physical_channel = target_ports[index_of_physical_channel]
                
                # Connect virtual outport to physical channel
                self.client.outports[n].connect(physical_channel)

    def update_parameters(self, chunk_min, chunk_max, pause_min, pause_max, 
        amplitude_min, amplitude_max):
        """Method to update sound parameters dynamically"""
        self.chunk_duration = random.uniform(chunk_min, chunk_max)
        self.pause_duration = random.uniform(pause_min, pause_max)
        self.amplitude = random.uniform(amplitude_min, amplitude_max)

        # Debug message
        parameter_message = (
            f"Current Parameters - Amplitude: {self.amplitude}, "
            f"Chunk Duration: {self.chunk_duration} s, "
            f"Pause Duration: {self.pause_duration}"
            )
        print(parameter_message)
        
        # Send the parameter message
        # TODO: break this out of this object. This object should not have
        # to know about ZMQ messages
        # TODO: what does this do? Why is it called poke_socket? Why does
        # the parameter message need to be sent?
        poke_socket.send_string(parameter_message)  
    
    def process(self, frames):
        """Process callback function (used to play sound)
        
        TODO: reimplement this to use a queue instead
        The current implementation uses time.time(), but we need to be more
        precise.
        """
        # Making process() thread-safe (so that multiple calls don't try to
        # write to the outports at the same time)
        with self.lock: 
            # Get the current time
            current_time = time.time()

            # Initialize data with zeros (silence)
            data = np.zeros((self.blocksize, 2), dtype='float32')

            # Check if time for chunk or gap
            if current_time - self.last_chunk_time >= self.chunk_duration + self.pause_duration:
                # It has been long enough that it is time for a new noise burst
                # Updating the last chunk time to now
                self.last_chunk_time = current_time  
            
            elif current_time - self.last_chunk_time >= self.chunk_duration:
                # We are in the silent period between sounds
                # So play silence
                pass
            
            else:
                # Generate random noise for the chunks
                # Play sound from left channel
                if self.set_channel == 'left': 
                    # Random noise using numpy
                    data = (self.amplitude * 
                        np.random.uniform(-1, 1, (self.blocksize, 2))) 
                    
                    # Blocking out the right channel 
                    data[:, 1] = 0  
                
                elif self.set_channel == 'right':
                    # Random noise using numpy
                    data = (self.amplitude * 
                        np.random.uniform(-1, 1, (self.blocksize, 2)))
                    
                    # Blocking out the left channel
                    data[:, 0] = 0  

            # Write
            self.write_to_outports(data)

    def write_to_outports(self, data):
        """Write data to outports"""
        # TODO: rewrite this to be always stereo, and then combine this
        # into process function above
        if data.ndim == 1:
            ## 1-dimensional sound provided
            # Write the same data to each channel
            for outport in self.client.outports:
                buff = outport.get_array()
                buff[:] = data

        elif data.ndim == 2:
            # Error check
            # Making sure the number of channels in data matches the number of outports
            if data.shape[1] != len(self.client.outports):
                raise ValueError(
                    "data has {} channels "
                    "but only {} outports in pref OUTCHANNELS".format(
                    data.shape[1], len(self.client.outports)))

            # Write one column to each channel
            for n_outport, outport in enumerate(self.client.outports):
                buff = outport.get_array()
                buff[:] = data[:, n_outport]

        else:
            raise ValueError("data must be 1D or 2D") 

    def set_set_channel(self, mode):
        """Set which channel to play sound from"""
        # Why is it necessary to get the lock here?
        with self.lock:
            self.set_channel = mode


## Define a client to play sounds
jack_client = JackClient(name='jack_client')

# Raspberry Pi's identity (Change this to the identity of the Raspberry Pi you are using)
# TODO: what is the difference between pi_identity and pi_name? # They are functionally the same, this line is from before I imported 
pi_identity = params['identity']


## Creating a ZeroMQ context and socket for communication with the central system
# TODO: what information travels over this socket? Clarify: do messages on
# this socket go out or in?

poke_context = zmq.Context()
poke_socket = poke_context.socket(zmq.DEALER)

# Setting the identity of the socket in bytes
poke_socket.identity = bytes(f"{pi_identity}", "utf-8") 


## Creating a ZeroMQ context and socket for receiving JSON files
# TODO: what information travels over this socket? Clarify: do messages on
# this socket go out or in?
#  - This socket only receives messages sent from the GUI regarding the parameters 
json_context = zmq.Context()
json_socket = json_context.socket(zmq.SUB)


## Connect to the server
# Connecting to IP address (192.168.0.99 for laptop, 192.168.0.207 for seaturtle)
router_ip = "tcp://" + f"{params['gui_ip']}" + f"{params['poke_port']}" 
poke_socket.connect(router_ip) 

# Send the identity of the Raspberry Pi to the server
poke_socket.send_string(f"{pi_identity}") 

# Print acknowledgment
print(f"Connected to router at {router_ip}")  


## Connect to json socket
router_ip2 = "tcp://" + f"{params['gui_ip']}" + f"{params['config_port']}"
json_socket.connect(router_ip2) 

# Subscribe to all incoming messages
json_socket.subscribe(b"")

# Print acknowledgment
print(f"Connected to router at {router_ip2}")  


## Pigpio configuration
# TODO: move these methods into a Nosepoke object. That object should be
# defined in another script and imported here
a_state = 0
count = 0
nosepoke_pinL = 8
nosepoke_pinR = 15
nosepokeL_id = params['nosepokeL_id']
nospokeR_id = params['nosepokeR_id']

# Global variables for which nospoke was detected
left_poke_detected = False
right_poke_detected = False

# Callback function for nosepoke pin (When the nosepoke is completed)
def poke_inL(pin, level, tick):
    global a_state, left_poke_detected
    a_state = 0
    if left_poke_detected:
        # Write to left pin
        print("Left poke detected!")
        pi.set_mode(17, pigpio.OUTPUT)
        if params['nosepokeL_type'] == "901":
            pi.write(17, 1)
        elif params['nosepokeL_type'] == "903":
            pi.write(17, 0)
    # Reset poke detected flags
    left_poke_detected = False

# Callback function for nosepoke pin (When the nosepoke is completed)
def poke_inR(pin, level, tick):
    global a_state, right_poke_detected
    a_state = 0
    if right_poke_detected:
        # Write to left pin
        print("Right poke detected!")
        pi.set_mode(10, pigpio.OUTPUT)
        if params['nosepokeR_type'] == "901":
            pi.write(10, 1)
        elif params['nosepokeR_type'] == "903":
            pi.write(10, 0)
            
    # Reset poke detected flags
    right_poke_detected = False

# Callback functions for nosepoke pin (When the nosepoke is detected)
def poke_detectedL(pin, level, tick): 
    global a_state, count, left_poke_detected
    a_state = 1
    count += 1
    left_poke_detected = True
    print("Poke Completed (Left)")
    print("Poke Count:", count)
    nosepoke_idL = params['nosepokeL_id']  # Set the left nosepoke_id here according to the pi
    pi.set_mode(17, pigpio.OUTPUT)
    if params['nosepokeL_type'] == "901":
        pi.write(17, 0)
    elif params['nosepokeL_type'] == "903":
        pi.write(17, 1)
        
    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idL}") 
        poke_socket.send_string(str(nosepoke_idL))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

def poke_detectedR(pin, level, tick): 
    global a_state, count, right_poke_detected
    a_state = 1
    count += 1
    right_poke_detected = True
    print("Poke Completed (Right)")
    print("Poke Count:", count)
    nosepoke_idR = params['nosepokeR_id']  # Set the right nosepoke_id here according to the pi
    pi.set_mode(10, pigpio.OUTPUT)
    if params['nosepokeR_type'] == "901":
        pi.write(10, 0)
    elif params['nosepokeR_type'] == "903":
        pi.write(10, 1)

    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idR}") 
        poke_socket.send_string(str(nosepoke_idR))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

def open_valve(port):
    """Open the valve for port
    
    port : TODO document what this is
    TODO: reward duration needs to be a parameter of the task or mouse # It is in the test branch
    """
    reward_value = config_data['reward_value']
    if port == int(params['nosepokeL_id']):
        pi.set_mode(6, pigpio.OUTPUT)
        pi.write(6, 1)
        time.sleep(reward_value)
        pi.write(6, 0)
    
    if port == int(params['nosepokeR_id']):
        pi.set_mode(26, pigpio.OUTPUT)
        pi.write(26, 1)
        time.sleep(reward_value)
        pi.write(26, 0)

# TODO: document this function
def flash():
    pi.set_mode(22, pigpio.OUTPUT)
    pi.write(22, 1)
    pi.set_mode(11, pigpio.OUTPUT)
    pi.write(11, 1)
    time.sleep(0.5)
    pi.write(22, 0)
    pi.write(11, 0)  


## Set up pigpio and callbacks
# TODO: rename this variable to pig or something; "pi" is ambiguous
pi = pigpio.pi()
pi.callback(nosepoke_pinL, pigpio.FALLING_EDGE, poke_inL)
pi.callback(nosepoke_pinL, pigpio.RISING_EDGE, poke_detectedL)
pi.callback(nosepoke_pinR, pigpio.FALLING_EDGE, poke_inR)
pi.callback(nosepoke_pinR, pigpio.RISING_EDGE, poke_detectedR)

## Create a Poller object
# TODO: document .. What is this?
poller = zmq.Poller()
poller.register(poke_socket, zmq.POLLIN)
poller.register(json_socket, zmq.POLLIN)

## Initialize variables for sound parameters
# These are not sound parameters .. TODO document
pwm_frequency = 1
pwm_duty_cycle = 50

# Duration of sounds
chunk_min = 0.0
chunk_max = 0.0

# Duration of pauses
pause_min = 0.0
pause_max = 0.0

# Range of amplitudes
# TODO: these need to be received from task, not specified here # These were all initial values set incase a task was not selected
amplitude_min = 0.0
amplitude_max = 0.0


## Main loop to keep the program running and exit when it receives an exit command
try:
    ## TODO: document these variables and why they are tracked
    # Initialize reward_pin variable
    reward_pin = None
    
    # Track the currently active LED
    current_pin = None  
    
    # Track prev_port
    prev_port = None
    
    
    ## Loop forever
    while True:
        ## Wait for events on registered sockets
        # TODO: how long does it wait? # Can be set, currently not sure
        socks = dict(poller.poll(1))
        
        
        ## Check for incoming messages on json_socket
        # If so, use it to update the acoustic parameters
        if json_socket in socks and socks[json_socket] == zmq.POLLIN:
            ## Data was received on json_socket
            # Receive the data (this is blocking) # Forgot to remove comment after implementing poller
            # TODO: what does blocking mean here? How long does it block?
            json_data = json_socket.recv_json()
            
            # Deserialize JSON data
            config_data = json.loads(json_data)
            
            # Debug print
            print(config_data)

            # Update parameters from JSON data
            chunk_min = config_data['chunk_min']
            chunk_max = config_data['chunk_max']
            pause_min = config_data['pause_min']
            pause_max = config_data['pause_max']
            amplitude_min = config_data['amplitude_min']
            amplitude_max = config_data['amplitude_max']
            
            # Update the jack client with the new acoustic parameters
            jack_client.update_parameters(
                chunk_min, chunk_max, pause_min, pause_max, 
                amplitude_min, amplitude_max)
            
            # Debug print
            print("Parameters updated")
            
        
        ## Check for incoming messages on poke_socket
        # TODO: document the types of messages that can be sent on poke_socket 
        if poke_socket in socks and socks[poke_socket] == zmq.POLLIN:
            # Blocking receive: #flags=zmq.NOBLOCK)  
            # Non-blocking receive
            msg = poke_socket.recv_string()  
    
            # Different messages have different effects
            if msg == 'exit': 
                # Condition to terminate the main loop
                # TODO: why are these pi.write here? # To turn the LEDs on the Pi off when the GUI is closed
                pi.write(17, 0)
                pi.write(10, 0)
                pi.write(27, 0)
                pi.write(9, 0)
                print("Received exit command. Terminating program.")
                
                # Wait for the client to finish processing any remaining chunks
                # TODO: why is this here? It's already deactivated 
                time.sleep(jack_client.chunk_duration + jack_client.pause_duration)
                
                # Stop the Jack client
                # TODO: Probably want to leave this running for the next
                # session
                jack_client.client.deactivate()
                
                # Exit the loop
                break  
            
            if msg == 'stop':
                pi.write(17, 0)
                pi.write(10, 0)
                pi.write(27, 0)
                pi.write(9, 0)
                jack_client.set_set_channel('none')
                print("Stop command received. Stopping sequence.")
            
            elif msg.startswith("Reward Port:"):    
                ## This specifies which port to reward
                # Debug print
                print(msg)
                
                # Extract the integer part from the message
                msg_parts = msg.split()
                if len(msg_parts) != 3 or not msg_parts[2].isdigit():
                    print("Invalid message format.")
                    continue
                
                # Extract the integer part
                value = int(msg_parts[2])  
                
                # Turn off the previously active LED if any
                if current_pin is not None:
                    pi.write(current_pin, 0)
                
                # Manipulate pin values based on the integer value
                if value == int(params['nosepokeL_id']):
                    # Reward pin for left
                    # TODO: these reward pins need to be stored as a parameter,
                    # not hardcoded here
                    reward_pin = 27  
                    
                    # TODO: what does this do? Why not just have reward pin
                    # always be set to output? # These are for the LEDs to blink
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, pwm_frequency)
                    pi.set_PWM_dutycycle(reward_pin, pwm_duty_cycle)
                    
                    # Playing sound from the left speaker
                    jack_client.set_set_channel('left')
                    
                    # Debug message
                    print("Turning Nosepoke 5 Green")

                    # Keep track of which port is rewarded and which pin
                    # is rewarded
                    prev_port = value
                    current_pin = reward_pin

                elif value == int(params['nosepokeR_id']):
                    # Reward pin for right
                    # TODO: these reward pins need to be stored as a parameter,
                    # not hardcoded here                    
                    reward_pin = 9
                    
                    # TODO: what does this do? Why not just have reward pin
                    # always be set to output? # LED blinking
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, pwm_frequency)
                    pi.set_PWM_dutycycle(reward_pin, pwm_duty_cycle)
                    
                    # Playing sound from the right speaker
                    jack_client.set_set_channel('right')
                    
                    # Debug message
                    print("Turning Nosepoke 7 Green")

                    # Keep track of which port is rewarded and which pin
                    # is rewarded
                    prev_port = value
                    current_pin = reward_pin

                else:
                    # TODO: document why this happens
                    # Current Reward Port
                    print(f"Current Reward Port: {value}") 
            
            elif msg == "Reward Poke Completed":
                # This seems to occur when the GUI detects that the poked
                # port was rewarded. This will be too slow. The reward port
                # should be opened if it knows it is the rewarded pin. 
                
                # Opening Solenoid Valve
                open_valve(prev_port)
                flash()
                
                # Updating Parameters
                # TODO: fix this; chunk_min etc are not necessarily defined
                # yet, or haven't changed recently
                jack_client.update_parameters(
                    chunk_min, chunk_max, pause_min, pause_max, 
                    amplitude_min, amplitude_max)
                
                # Turn off the currently active LED
                if current_pin is not None:
                    pi.write(current_pin, 0)
                    print("Turning off currently active LED.")
                    current_pin = None  # Reset the current LED
                else:
                    print("No LED is currently active.")

                # Reset play mode to 'none'
                jack_client.set_set_channel('none')
           
            else:
                print("Unknown message received:", msg)

except KeyboardInterrupt:
    # Stops the pigpio connection
    pi.stop()

finally:
    # Close all sockets and contexts
    poke_socket.close()
    poke_context.term()
    json_socket.close()
    json_context.term()
        
    
