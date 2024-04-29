import zmq

try:
 import pigpio
 PIGPIO_AVAILABLE = True
except ModuleNotFoundError:
    PIGPIO_AVAILABLE = False

import datetime
import time
import typing
import multiprocessing as mp
import queue as queue
import numpy as np
from copy import copy
import itertools
import pandas as pd
from queue import Empty
from threading import Thread
from collections import deque
import numpy as np
import gc

import jack

if typing.TYPE_CHECKING:
    pass

# allows us to access the audio server and some sound attributes
SERVER = None
FS = None
BLOCKSIZE = None
QUEUE = None
QUEUE2 = None
PLAY = None
STOP = None
Q_LOCK = None
Q2_LOCK = None
CONTINUOUS = None
CONTINUOUS_QUEUE = None
CONTINUOUS_LOOP = None

class JackClient(mp.Process):
    def __init__(self,
                 name='jack_client',
                 outchannels: typing.Optional[list] = None,
                 debug_timing:bool=False,
                 play_q_size:int=2048,
                 disable_gc=False):
  
        super(JackClient, self).__init__()

        # TODO: If global client variable is set, just return that one.

        self.name = name
        if outchannels is None:
            self.outchannels = [0,1]
        else:
            self.outchannels = outchannels

        #self.pipe = pipe
        self.q = mp.Queue()
        self.q_lock = mp.Lock()
        
        # A second one
        self.q2 = mp.Queue()
        self.q2_lock = mp.Lock()
        
        # This is for transferring the frametimes that audio was played
        self.q_nonzero_blocks = mp.Queue()
        self.q_nonzero_blocks_lock = mp.Lock()

        self._play_q = deque(maxlen=play_q_size)

        self.play_evt = mp.Event()
        self.stop_evt = mp.Event()
        self.quit_evt = mp.Event()
        self.play_started = mp.Event()

        # we make a client that dies now so we can stash the fs and etc.
        self.client = jack.Client(self.name)
        self.blocksize = self.client.blocksize
        self.fs = self.client.samplerate
        self.zero_arr = np.zeros((self.blocksize,1),dtype='float32')

        # a few objects that control continuous/background sound.
        # see descriptions in module variables
        self.continuous = mp.Event()
        self.continuous_q = mp.Queue()
        self.continuous_loop = mp.Event()
        self.continuous_cycle = None
        self.continuous.clear()
        self.continuous_loop.clear()
        self._continuous_sound = None 
        self._continuous_dehydrated = None

        # store the frames of the continuous sound and cycle through them if set in continous mode
        self.continuous_cycle = None

        # Something calls process() before boot_server(), so this has to
        # be initialized
        self.mono_output = True

        self._disable_gc = disable_gc

        # store a reference to us and our values in the module
        globals()['SERVER'] = self
        globals()['FS'] = copy(self.fs)
        globals()['BLOCKSIZE'] = copy(self.blocksize)
        globals()['QUEUE'] = self.q
        globals()['Q_LOCK'] = self.q_lock
        globals()['QUEUE2'] = self.q2
        globals()['Q2_LOCK'] = self.q2_lock
        globals()['QUEUE_NONZERO_BLOCKS'] = self.q_nonzero_blocks
        globals()['QUEUE_NONZERO_BLOCKS_LOCK'] = self.q_nonzero_blocks_lock
        globals()['PLAY'] = self.play_evt
        globals()['STOP'] = self.stop_evt
        globals()['CONTINUOUS'] = self.continuous
        globals()['CONTINUOUS_QUEUE'] = self.continuous_q
        globals()['CONTINUOUS_LOOP'] = self.continuous_loop

        self.debug_timing = debug_timing
        self.querythread = None
        self.wait_until = None
        self.alsa_nperiods = 3
        if self.alsa_nperiods is None:
            self.alsa_nperiods = 1

        ## Also boot pigpio so we can pulse pins when sound plays
        # Hopefully external.start_pigpiod() has already been called by
        # someone else
        if PIGPIO_AVAILABLE:
            self.pig = pigpio.pi()
        else:
            self.pig = None

    def boot_server(self):
        ## Parse OUTCHANNELS into listified_outchannels and set `self.mono_output`
        
        # This generates `listified_outchannels`, which is always a list
        # It also sets `self.mono_output` if outchannels is None
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
        
        ## Initalize self.client
        # Initalize a new Client and store some its properties
        # I believe this is how downstream code knows the sample rate
        self.client = jack.Client(self.name)
        self.blocksize = self.client.blocksize
        self.fs = 192000 #self.client.samplerate
        
        # This is used for writing silence
        self.zero_arr = np.zeros((self.blocksize,1),dtype='float32')

        # Set the process callback to `self.process`
        # This gets called on every chunk of audio data
        self.client.set_process_callback(self.process)

        # Register virtual outports
        # This is something we can write data into
        if self.mono_output:
            # One single outport
            self.client.outports.register('out_0')
        else:
            # One outport per provided outchannel
            for n in range(len(listified_outchannels)):
                self.client.outports.register('out_{}'.format(n))

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
            if len(listified_outchannels) > len(target_ports):
                raise ValueError(
                    "cannot connect {} ports, only {} available".format(
                    len(listified_outchannels),
                    len(target_ports),))
            
            # Hook up one outport to each channel
            for n in range(len(listified_outchannels)):
                # This is the channel number the user provided in OUTCHANNELS
                index_of_physical_channel = listified_outchannels[n]
                
                # This is the corresponding physical channel
                # I think this will always be the same as index_of_physical_channel
                physical_channel = target_ports[index_of_physical_channel]
                
                # Connect virtual outport to physical channel
                self.client.outports[n].connect(physical_channel)

    def run(self):
        self.boot_server()

        if self._disable_gc:
            gc.disable()

        if self.debug_timing:
            self.querythread = Thread(target=self._query_timebase)
            self.querythread.start()

        # we are just holding the process open, so wait to quit
        try:
            self.quit_evt.clear()
            self.quit_evt.wait()
        except KeyboardInterrupt:
            # just want to kill the process, so just continue from here
            self.quit_evt.set()

    def quit(self):
        self.quit_evt.set()

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
        
        # Store the frame times where sound is played
        # A loud sound has data_std .03
        data_std = data.std()
        if data_std > 1e-12:
            # Pulse the pin
            # Use BCM 23 (board 16) = LED - C - Blue because we're not using it
            self.pig.write(23, True)
            
            # This is only an approximate hash because it excludes the
            # middle of the data
            data_hash = hash(str(data))
            
            # Get the current time
            # lft is the only precise one, and it's at the start of the process
            # block
            # fscs is approx number of frames since then until now
            # dt is about now
            lft = self.client.last_frame_time
            fscs = self.client.frames_since_cycle_start
            dt = datetime.datetime.now().isoformat()
            with self.q_nonzero_blocks_lock:
                self.q_nonzero_blocks.put_nowait((data_hash, lft, fscs, dt))
        else:
            # Unpulse the pin
            self.pig.write(23, False)
        
        # Add
        data = data + data2

        # Write
        self.write_to_outports(data)
    
    def write_to_outports(self, data):
        data = data.squeeze()

        ## Write the output to each outport
        if self.mono_output:
            ## Mono mode - Write the same data to all channels
            if data.ndim == 1:
                # Write data to one outport, which is hooked up to all channels
                buff = self.client.outports[0].get_array()
                buff[:] = data
            
            else:
                # Stereo data provided, this is an error
                raise ValueError(
                    "pref OUTCHANNELS indicates mono mode, but "
                    "data has shape {}".format(data.shape))
            
        else:
            ## Multi-channel mode - Write a column to each channel
            if data.ndim == 1:
                ## 1-dimensional sound provided
                # Write the same data to each channel
                for outport in self.client.outports:
                    buff = outport.get_array()
                    buff[:] = data
                
            elif data.ndim == 2:
                ## Multi-channel sound provided
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
                
            else:
                ## What would a 3d sound even mean?
                raise ValueError(
                    "data must be 1 or 2d, not {}".format(data.shape))

    def _pad_continuous(self, data:np.ndarray) -> np.ndarray:
        # if sound was not padded, fill remaining with continuous sound or silence
        n_from_end = self.blocksize - data.shape[0]
        if self.continuous.is_set():
            try:
                cont_data = next(self.continuous_cycle)
                data = np.concatenate((data, cont_data[-n_from_end:]),
                                      axis=0)
            except Exception as e:
                pad_with = [(0, n_from_end)]
                pad_with.extend([(0, 0) for i in range(len(data.ndim-1))])
                data = np.pad(data, pad_with, 'constant')
        else:
            pad_with = [(0, n_from_end)]
            pad_with.extend([(0, 0) for i in range(len(data.ndim - 1))])
            data = np.pad(data, pad_with, 'constant')

        return data

    def _wait_for_end(self):
        try:
            while self.wait_until is None or self.client.frame_time < self.wait_until:
                time.sleep(0.000001)
        finally:
            self.stop_evt.set()
            self.querythread = None
            self.wait_until = None

    def _query_timebase(self):
        while not self.quit_evt.is_set():
            state, pos = self.client.transport_query()
            time.sleep(0.00001)


class Noise:
    def __init__(self, duration, fs=44100, amplitude=0.01):
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

    
class Sound:
    def __init__(self):
        self.left_target_stim = None
        self.right_target_stim = None

    def initialize_sounds(self, target_amplitude):
        # Defining sounds to be played in the task for left and right target noise bursts
        self.left_target_stim = Noise(duration=10, amplitude=target_amplitude)       
        self.right_target_stim = Noise(duration=10, amplitude=target_amplitude)
    
    def chunk_sounds(self):
        if not self.left_target_stim.chunks:
            self.left_target_stim.chunk()
        if not self.right_target_stim.chunks:
            self.right_target_stim.chunk()

    def set_sound_cycle(self, params):
        # This is just a left sound, gap, then right sound, then gap
        # And use a cycle to repeat forever
        self.sound_block = []

        # Helper function
        def append_gap(gap_chunk_size=30):
            for n_blank_chunks in range(gap_chunk_size):
                self.sound_block.append(
                    np.zeros(JackClient.BLOCKSIZE, dtype='float32'))

        # Extract params or use defaults
        left_on = params.get('left_on', False)
        right_on = params.get('right_on', False)
        left_mean_interval = params.get('left_mean_interval', 0)
        right_mean_interval = params.get('right_mean_interval', 0)
        
        # Generate intervals 
        if left_on:
            left_intervals = np.full(100, left_mean_interval)
        else:
            left_intervals = np.array([])

        if right_on:
            right_intervals = np.full(100, right_mean_interval)
        else:
            right_intervals = np.array([])

        # Sort all the drawn intervals together
        left_df = pd.DataFrame.from_dict({
            'time': np.cumsum(left_intervals),
            'side': ['left'] * len(left_intervals),
            })
        right_df = pd.DataFrame.from_dict({
            'time': np.cumsum(right_intervals),
            'side': ['right'] * len(right_intervals),
            })

        # Concatenate them all together and resort by time
        both_df = pd.concat([left_df, right_df], axis=0).sort_values('time')

        # Calculate the gap between sounds
        both_df['gap'] = both_df['time'].diff().shift(-1)
        
        # Drop the last row which has a null gap
        both_df = both_df.loc[~both_df['gap'].isnull()].copy()

        # Calculate gap size in chunks
        both_df['gap_chunks'] = (both_df['gap'] * 192000 / JackClient.BLOCKSIZE)
        both_df['gap_chunks'] = both_df['gap_chunks'].round().astype(np.int)
        
        # Floor gap_chunks at 1 chunk, the minimal gap size
        # This is to avoid distortion
        both_df.loc[both_df['gap_chunks'] < 1, 'gap_chunks'] = 1
                
        # Save
        self.current_audio_times_df = both_df.copy()
        self.current_audio_times_df = self.current_audio_times_df.rename(
            columns={'time': 'relative_time'})

        # Iterate through the rows, adding the sound and the gap
        for bdrow in both_df.itertuples():
            # Append the sound
            if bdrow.side == 'left':
                for frame in self.left_target_stim.chunks:
                    self.sound_block.append(frame) 
            elif bdrow.side == 'right':
                for frame in self.right_target_stim.chunks:
                    self.sound_block.append(frame) 
            else:
                raise ValueError(
                    "unrecognized side: {}".format(bdrow.side))
            
            # Append the gap
            append_gap(bdrow.gap_chunks)
        
        # Cycle so it can repeat forever
        self.sound_cycle = itertools.cycle(self.sound_block)

## still adding play, recv play and empty queue functions


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
                    print("Turning Nosepoke 5 Green")

                    # Update the current LED
                    current_pin = reward_pin

                elif value == 7:
                    # Manipulate pins for case 2
                    reward_pin = 9  # Example pin for case 2
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, 1)
                    pi.set_PWM_dutycycle(reward_pin, 50)
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
