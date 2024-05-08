import zmq
import pigpio
import numpy as np
import os
import jack
import multiprocessing as mp
import typing
import time
import queue as queue

os.system('sudo killall pigpiod')
os.system('sudo killall jackd')
time.sleep(1)
os.system('sudo pigpiod -t 0 -l -x 1111110000111111111111110000')
time.sleep(1)
os.system('jackd -P75 -p16 -t2000 -dalsa -dhw:sndrpihifiberry -P -r192000 -n3 -s &')
time.sleep(1)

class Noise:
    def __init__(self, duration, fs=192000, amplitude=0.05):
        self.duration = duration
        self.fs = fs
        self.amplitude = amplitude

    def generate_noise(self):
        nsamples = int(self.fs * self.duration)
        data = np.random.uniform(-1, 1, nsamples)
        return data * self.amplitude
    
    def chunk(self, chunk_size=1024):
        noise = self.generate_noise()
        self.chunks = np.array_split(noise, len(noise) // chunk_size)

class JackClient(mp.Process):
    def __init__(self, name='jack_client', outchannels: typing.Optional[list] = None, play_q_size:int=2048):
        self.name = name
        self.client = jack.Client(self.name)
        self.blocksize = self.client.blocksize
        self.fs = self.client.samplerate
        self.zero_arr = np.zeros((self.blocksize,1),dtype='float32') # Silence
        if outchannels is None:
            self.outchannels = [0,1]
        else:
            self.outchannels = outchannels
        self.q = mp.Queue()
        self.q_lock = mp.Lock() # Queue lock
        self.q2 = mp.Queue()
        self.q2_lock = mp.Lock()

        if self.outchannels == '':
            # Mono mode
            listified_outchannels = []
            self.mono_output = True
        elif not isinstance(self.outchannels, list):
            # Must be a single integer-like thing
            listified_outchannels = [int(self.outchannels)]
            self.mono_output = False
        else:
            # Already a list
            listified_outchannels = self.outchannels
            self.mono_output = False

        # Register outports
        if self.mono_output:
            # One single outport
            self.client.outports.register('out_0') #include this
        else:
            # One outport per provided outchannel
            for n in range(len(listified_outchannels)):
                self.client.outports.register('out_{}'.format(n))

        # Process callback to self.process
        self.client.set_process_callback(self.process)

        # Activate the client
        self.client.activate()

    def process(self, frames):
        # Try to get data from the first queue
        try:
            with self.q_lock:
                data = self.q.get_nowait()
        except queue.Empty:
            data = np.transpose([
                np.zeros(self.blocksize, dtype='float32'),
                np.zeros(self.blocksize, dtype='float32'),
                ])

        # Try to get data from the second queue
        try:
            with self.q2_lock:
                data2 = self.q2.get_nowait()
        except queue.Empty:
            data2 = np.transpose([
                np.zeros(self.blocksize, dtype='float32'),
                np.zeros(self.blocksize, dtype='float32'),
                ])
        
        # Force to stereo
        if data.ndim == 1:
            data = np.transpose([data, data])
        if data2.ndim == 1:
            data2 = np.transpose([data2, data2])

        # Add
        data = data + data2

        # Write
        self.write_to_outports(data)

    def write_to_outports(self, data): 
        data = data.squeeze()   
        if data.ndim == 1:
                ## 1-dimensional sound provided
                # Write the same data to each channel
                for outport in self.client.outports:
                    buff = outport.get_array()
                    buff[:] = data
                
        elif data.ndim == 2:
                # Error check
                if data.shape[1] != len(self.client.outports):
                    raise ValueError(
                        "data has {} channels "
                        "but only {} outports in pref OUTCHANNELS".format(
                        data.shape[1], len(self.client.outports)))
                
                # Write one column to each channel
                for n_outport, outport in enumerate(self.client.outports):
                    buff = outport.get_array()
                    buff[:] = data[:, n_outport]

class Sound:
    def __init__(self, jack_client):
        self.left_target_stim = None
        self.right_target_stim = None
        self.jack_client = jack_client

    def initialize_sounds(self, target_amplitude):
        # Defining sounds to be played in the task for left and right target noise bursts
        self.left_target_stim = Noise(duration=10, amplitude=target_amplitude)       
        self.right_target_stim = Noise(duration=10, amplitude=target_amplitude)
    
    def chunk_sounds(self):
        if not self.left_target_stim.chunks:
            self.left_target_stim.chunk()
        if not self.right_target_stim.chunks:
            self.right_target_stim.chunk()

# Raspberry Pi's identity (Change this to the identity of the Raspberry Pi you are using)
pi_identity = b"rpi22"

# Creating a ZeroMQ context and socket for communication with the central system
context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.identity = pi_identity

# Connect to the server
router_ip = "tcp://192.168.0.194:5555" # Connecting to Laptop IP address (192.168.0.99 for lab setup)
socket.connect(router_ip)
socket.send_string("rpi22")
print(f"Connected to router at {router_ip}")  # Print acknowledgment

# Pigpio configuration
a_state = 0
count = 0
nosepoke_pinL = 8
nosepoke_pinR = 15

# Global variables for which nospoke was detected
left_poke_detected = False
right_poke_detected = False

jack_client = JackClient(name='jack_client')
sound_player = Sound(jack_client)

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
    # Your existing poke_detectedL code here
    print("Poke Completed (Left)")
    print("Poke Count:", count)
    nosepoke_idL = 5  # Set the left nosepoke_id here according to the pi
    pi.set_mode(17, pigpio.OUTPUT)
    pi.write(17, 0)
    try:
        print(f"Sending nosepoke_id = {nosepoke_idL} to the Laptop") 
        socket.send_string(str(nosepoke_idL))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

def poke_detectedR(pin, level, tick): 
    global a_state, count, right_poke_detected
    a_state = 1
    count += 1
    right_poke_detected = True
    # Your existing poke_detectedR code here
    print("Poke Completed (Right)")
    print("Poke Count:", count)
    nosepoke_idR = 7  # Set the right nosepoke_id here according to the pi
    pi.set_mode(10, pigpio.OUTPUT)
    pi.write(10, 0)
    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idR} to the Laptop") 
        socket.send_string(str(nosepoke_idR))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

# Set up pigpio and callbacks
pi = pigpio.pi()
pi.callback(nosepoke_pinL, pigpio.FALLING_EDGE, poke_inL)
pi.callback(nosepoke_pinL, pigpio.RISING_EDGE, poke_detectedL)
pi.callback(nosepoke_pinR, pigpio.FALLING_EDGE, poke_inR)
pi.callback(nosepoke_pinR, pigpio.RISING_EDGE, poke_detectedR)

# Main loop to keep the program running and exit when it receives an exit command
try:
    # Initialize reward_pin variable
    reward_pin = None
    current_pin = None  # Track the currently active LED
    
    while True:
        
        # Check for incoming messages
        try:
            msg = socket.recv_string(zmq.NOBLOCK)
            if msg == 'exit':
                pi.write(17, 0)
                pi.write(10, 0)
                pi.write(27, 0)
                pi.write(9, 0)
                print("Received exit command. Terminating program.")
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
                    #print("Turning off green LED.")
                
                # Manipulate pin values based on the integer value
                if value == 5:
                    # Manipulate pins for case 1
                    reward_pin = 27  # Example pin for case 1 (Change this to the actual)
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, 1)
                    pi.set_PWM_dutycycle(reward_pin, 50)
                    data = sound_player.left_target_stim.chunks.pop(0)
                    jack_client.q.put(data)
                    print("Turning Nosepoke 5 Green")

                    # Update the current LED
                    current_pin = reward_pin

                elif value == 7:
                    # Manipulate pins for case 2
                    reward_pin = 9  # Example pin for case 2
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, 1)
                    pi.set_PWM_dutycycle(reward_pin, 50)
                    data = sound_player.right_target_stim.chunks.pop(0)
                    jack_client.q2.put(data)
                    print("Turning Nosepoke 7 Green")

                    # Update the current LED
                    current_pin = reward_pin

                else:
                    print(f"Current Port: {value}")
            
            elif msg == "Reward Poke Completed":
                # Turn off the currently active LED
                if current_pin is not None:
                    pi.write(current_pin, 0)
                    print("Turning off currently active LED.")
                    current_pin = None  # Reset the current LED
                else:
                    print("No LED is currently active.")
            else:
                print("Unknown message received:", msg)

        except zmq.Again:
            pass  # No messages received
        
except KeyboardInterrupt:
    pi.stop()
finally:
    socket.close()
    context.term()
