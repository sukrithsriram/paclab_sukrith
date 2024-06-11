import zmq
import pigpio
import numpy as np
import os
import jack
import time
import threading
import random
import json

# Killing previous pigpiod and jackd background processes
os.system('sudo killall pigpiod')
os.system('sudo killall jackd')
time.sleep(1)

# Starting pigpiod and jackd background processes
os.system('sudo pigpiod -t 0 -l -x 1111110000111111111111110000')
time.sleep(1)
os.system('jackd -P75 -p16 -t2000 -dalsa -dhw:sndrpihifiberry -P -r192000 -n3 -s &')
time.sleep(1)

class JackClient:
    def __init__(self, name='jack_client', outchannels=None):
        self.name = name
        self.set_channel = 'none'  # 'left', 'right', or 'none'
        self.lock = threading.Lock()  # Lock for thread-safe set_channel() updates
        self.chunk_duration = random.uniform(0.01, 0.05)  # Duration of each chunk in seconds
        self.pause_duration = random.uniform(0.05, 0.2)  # Pause duration between chunk in seconds
        self.amplitude = random.uniform(0.005, 0.02)
        #print(f"Current Parameters - Amplitude:{amplitude}, Chunk Duration: {chunk_duration} s, Pause Duration: {pause_duration}"
        self.last_chunk_time = time.time()  # Variable to store the time of the last burst

        # Creating a jack client
        self.client = jack.Client(self.name)

        # Pull these values from the initialized client
        # These come from the jackd daemon
        self.blocksize = self.client.blocksize
        self.fs = self.client.samplerate
        print("Received blocksize {} and fs {}".format(self.blocksize, self.fs))

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

        # Process callback to self.process
        self.client.set_process_callback(self.process)

        # Activate the client
        self.client.activate()

        ## Hook up the outports (data sinks) to physical ports
        # Get the actual physical ports that can play sound
        target_ports = self.client.get_ports(
            is_physical=True, is_input=True, is_audio=True)

        # Depends on whether we're in mono mode
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

    
    # Method to update sound parameters dynamically
    def update_parameters(self, chunk_min, chunk_max, pause_min, pause_max, amplitude_min, amplitude_max):
        self.chunk_duration = random.uniform(chunk_min, chunk_max)
        self.pause_duration = random.uniform(pause_min, pause_max)
        self.amplitude = random.uniform(amplitude_min, amplitude_max)

        parameter_message = f"Current Parameters - Amplitude: {self.amplitude}, Chunk Duration: {self.chunk_duration} s, Pause Duration: {self.pause_duration}"
        print(parameter_message)
        poke_socket.send_string(parameter_message)  # Send the parameter message
    
    # Process callback function (used to play sound)
    def process(self, frames):
        with self.lock: # Making process() thread-safe
            current_time = time.time()

            # Initialize data with zeros (silence)
            data = np.zeros((self.blocksize, 2), dtype='float32')

            # Check if time for chunk or gap
            if current_time - self.last_chunk_time >= self.chunk_duration + self.pause_duration:
                self.last_chunk_time = current_time  # Updating the last chunk time
            elif current_time - self.last_chunk_time >= self.chunk_duration:
                pass  # Silence is playing
            else:
                # Generate random noise for the chunks
                if self.set_channel == 'left': # Play sound from left channel
                    data = self.amplitude * np.random.uniform(-1, 1, (self.blocksize, 2)) # Random noise using numpy
                    data[:, 1] = 0  # Blocking out the right channel 
                elif self.set_channel == 'right':
                    data = self.amplitude * np.random.uniform(-1, 1, (self.blocksize, 2))
                    data[:, 0] = 0  # Blocking out the left channel

            # Write
            self.write_to_outports(data)

    def write_to_outports(self, data):
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

    # Function to set which channel to play sound from
    def set_set_channel(self, mode):
        with self.lock:
            self.set_channel = mode

# Define a client to play sounds
jack_client = JackClient(name='jack_client')

# Raspberry Pi's identity (Change this to the identity of the Raspberry Pi you are using)
pi_identity = b"rpi22"

# Creating a ZeroMQ context and socket for communication with the central system
poke_context = zmq.Context()
poke_socket = poke_context.socket(zmq.DEALER)
poke_socket.identity = pi_identity # Setting the identity of the socket

# Creating a ZeroMQ context and socket for receiving JSON files
json_context = zmq.Context()
json_socket = json_context.socket(zmq.SUB)

# Connect to the server
router_ip = "tcp://192.168.0.207:5555" # Connecting to Laptop IP address (192.168.0.99 for laptop, 192.168.0.207 for seaturtle)
poke_socket.connect(router_ip) 
poke_socket.send_string("rpi22") # Send the identity of the Raspberry Pi to the server
print(f"Connected to router at {router_ip}")  # Print acknowledgment

#JSON socket
router_ip2 = "tcp://192.168.0.207:5556"
json_socket.connect(router_ip2) 

# Subscribe to all incoming messages
json_socket.subscribe(b"")

print(f"Connected to router at {router_ip2}")  # Print acknowledgment

# Pigpio configuration
a_state = 0
count = 0
nosepoke_pinL = 8
nosepoke_pinR = 15

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
        pi.write(17, 1)

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
        pi.write(10, 1)

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
    nosepoke_idL = 5  # Set the left nosepoke_id here according to the pi
    pi.set_mode(17, pigpio.OUTPUT)
    pi.write(17, 0)
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
    nosepoke_idR = 7  # Set the right nosepoke_id here according to the pi
    pi.set_mode(10, pigpio.OUTPUT)
    pi.write(10, 0)
    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idR}") 
        poke_socket.send_string(str(nosepoke_idR))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

def open_valve(port):
    if port == 5:
        pi.set_mode(6, pigpio.OUTPUT)
        pi.write(6, 1)
        time.sleep(0.05)
        pi.write(6, 0)
    if port == 7:
        pi.set_mode(26, pigpio.OUTPUT)
        pi.write(26, 1)
        time.sleep(0.05)
        pi.write(26, 0)
        
def flash():
    pi.set_mode(22, pigpio.OUTPUT)
    pi.write(22, 1)
    pi.set_mode(11, pigpio.OUTPUT)
    pi.write(11, 1)
    time.sleep(0.05)
    pi.write(22, 0)
    pi.write(11, 0)  

# Set up pigpio and callbacks
pi = pigpio.pi()
pi.callback(nosepoke_pinL, pigpio.FALLING_EDGE, poke_inL)
pi.callback(nosepoke_pinL, pigpio.RISING_EDGE, poke_detectedL)
pi.callback(nosepoke_pinR, pigpio.FALLING_EDGE, poke_inR)
pi.callback(nosepoke_pinR, pigpio.RISING_EDGE, poke_detectedR)

# Create a Poller object
poller = zmq.Poller()
poller.register(poke_socket, zmq.POLLIN)
poller.register(json_socket, zmq.POLLIN)

# Initialize variables for sound parameters
pwm_frequency = 1
pwm_duty_cycle = 50
chunk_min = 0.01
chunk_max = 0.05
pause_min = 0.05
pause_max = 0.2
amplitude_min = 0.005
amplitude_max = 0.02

# Main loop to keep the program running and exit when it receives an exit command
try:
    # Initialize reward_pin variable
    reward_pin = None
    current_pin = None  # Track the currently active LED
    prev_port = None
    
    while True:
        # Wait for events on registered sockets
        socks = dict(poller.poll())
        
        # Check for incoming messages on json_socket
        if json_socket in socks and socks[json_socket] == zmq.POLLIN:
            json_data = json_socket.recv_json()  # Blocking receive
            # Deserialize JSON data
            config_data = json.loads(json_data)
            print(config_data)

            #if 'chunk_min' in config_data and 'pause_duration' in config_data and 'amplitude_min' in config_data and 'amplitude_max' in config_data:
            
            # Update parameters from JSON data
            chunk_min = config_data['chunk_min']
            chunk_max = config_data['chunk_max']
            pause_min = config_data['pause_min']
            pause_max = config_data['pause_max']
            amplitude_min = config_data['amplitude_min']
            amplitude_max = config_data['amplitude_max']
            jack_client.update_parameters(chunk_min, chunk_max, pause_min, pause_max, amplitude_min, amplitude_max)
            print("Parameters updated")
            
        # Check for incoming messages on poke_socket
        if poke_socket in socks and socks[poke_socket] == zmq.POLLIN:
            flash()
            msg = poke_socket.recv_string()  # Blocking receive #flags=zmq.NOBLOCK)  # Non-blocking receive
            if msg == 'exit': # Condition to terminate the main loop
                pi.write(17, 0)
                pi.write(10, 0)
                pi.write(27, 0)
                pi.write(9, 0)
                print("Received exit command. Terminating program.")
                
                # Stop the Jack client
                jack_client.client.deactivate()
                
                # Wait for the client to finish processing any remaining chunks
                time.sleep(jack_client.chunk_duration + jack_client.pause_duration)
                
                break  # Exit the loop
            
            elif msg.startswith("Reward Port:"):    
                print(msg)
                # Extract the integer part from the message
                msg_parts = msg.split()
                if len(msg_parts) != 3 or not msg_parts[2].isdigit():
                    print("Invalid message format.")
                    continue
                
                value = int(msg_parts[2])  # Extract the integer part
                
                # Reset the previously active LED if any
                if current_pin is not None:
                    pi.write(current_pin, 0)
                
                # Manipulate pin values based on the integer value
                if value == 5:
                    reward_pin = 27  # Example pin for case 1 
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, pwm_frequency)
                    pi.set_PWM_dutycycle(reward_pin, pwm_duty_cycle)
                    # Playing sound from the left speaker
                    jack_client.set_set_channel('left')
                    print("Turning Nosepoke 5 Green")

                    prev_port = value
                    current_pin = reward_pin

                elif value == 7:
                    reward_pin = 9  # Example pin for case 2
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, pwm_frequency)
                    pi.set_PWM_dutycycle(reward_pin, pwm_duty_cycle)
                    # Playing sound from the right speaker
                    jack_client.set_set_channel('right')
                    print("Turning Nosepoke 7 Green")

                    prev_port = value
                    current_pin = reward_pin

                else:
                    print(f"Current Reward Port: {value}") # Current Reward Port
            
            elif msg == "Reward Poke Completed":
                # Opening Solenoid Valve
                open_valve(prev_port)
                
                # Updating Parameters
                jack_client.update_parameters(chunk_min, chunk_max, pause_min, pause_max, amplitude_min, amplitude_max)
                #Turn off the currently active LED
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
    pi.stop()
finally:
    poke_socket.close()
    poke_context.term()
    json_socket.close()
    json_context.term()
        
    

