import numpy as np
import queue as queue
import sys
from threading import Thread
import jack
import zmq
import pigpio
import multiprocessing as mp
import copy
from collections import deque
import typing
import gc
import time
import datetime
import pandas as pd
import itertools

class Noise:
    def __init__(self, duration, fs=192000, amplitude=0.01):
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
    def __init__(self,
                 name='jack_client',
                 outchannels: typing.Optional[list] = None,
                 play_q_size:int=2048,
                 disable_gc=False):

        super(JackClient, self).__init__()

        self.name = name
        if outchannels is None:
            self.outchannels = [0,1]
        else:
            self.outchannels = outchannels
        self.q = mp.Queue() #Queue for audio data
        self.q_lock = mp.Lock() #Queue lock
        self.q2 = mp.Queue() #Queue2
        self.q2_lock = mp.Lock()
        self.q_nonzero_blocks = mp.Queue()
        self.q_nonzero_blocks_lock = mp.Lock()
        self._play_q = deque(maxlen=play_q_size)
        self.play_evt = mp.Event()
        self.stop_evt = mp.Event()
        self.quit_evt = mp.Event()
        self.play_started = mp.Event()

        # Jack client
        self.client = jack.Client(self.name)
        self.blocksize = self.client.blocksize
        self.fs = 192000
        self.zero_arr = np.zeros((self.blocksize,1),dtype='float32')

        # Continuous playback
        self.continuous = mp.Event()
        self.continuous_q = mp.Queue()
        self.continuous_loop = mp.Event()
        self.continuous_cycle = None

        # References to values in the module
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

        self.querythread = None
        self.wait_until = None
        self.alsa_nperiods = 3 # Number of buffer periods in ALSA
        if self.alsa_nperiods is None:
            self.alsa_nperiods = 1

        self._disable_gc = disable_gc # Disable garbage collection

    def boot_server(self):
        self.client = jack.Client(self.name)
        self.blocksize = self.client.blocksize
        self.fs = 192000

        # Silence
        self.zero_arr = np.zeros((self.blocksize,1),dtype='float32')

        # Process callback to `self.process`
        self.client.set_process_callback(self.process)

        # Activate the client
        self.client.activate()    

    def run(self):
        self.boot_server()

        if self._disable_gc:
            gc.disable()
        try:
            self.quit_evt.clear()
            self.quit_evt.wait()
        except KeyboardInterrupt:
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
    
    # def play_sound(self):
    #     for n in range(10):
    #         # Add stimulus sounds to queue 1 as needed
    #         self.append_sound_to_queue1_as_needed()
    #         time.sleep(.1)

    #     ## Extract any recently played sound info
    #     sound_data_l = []
    #     with JackClient.QUEUE_NONZERO_BLOCKS_LOCK:
    #         while True:
    #             try:
    #                 data = JackClient.QUEUE_NONZERO_BLOCKS.get_nowait()
    #             except queue.Empty:
    #                 break
    #             sound_data_l.append(data)
        
    #     if len(sound_data_l) > 0:
    #         # DataFrame it
    #         # This has to match code in jackclient.py
    #         # And it also has to match task_class.ChunkData_SoundsPlayed
    #         payload = pd.DataFrame.from_records(
    #             sound_data_l,
    #             columns=['hash', 'last_frame_time', 'frames_since_cycle_start', 'equiv_dt'],
    #             )
    #         self.send_chunk_of_sound_played_data(payload)
        
    #     time_so_far = (datetime.datetime.now() - self.dt_start).total_seconds()
    #     frame_rate = self.n_frames / time_so_far

    #     self.stage_block.set()

    def play_noise(self, jack_client, outport_index):
            if outport_index == 0:
                self.left_target_stim.generate_noise()
                self.play_sound(jack_client, outport_index)
            elif outport_index == 1:
                self.right_target_stim.generate_noise()
                self.play_sound(jack_client, outport_index)
            else:
                raise ValueError("Invalid outport index")

    def empty_queue1(self, tosize=0):
        while True:
            with JackClient.Q_LOCK:
                try:
                    data = JackClient.QUEUE.get_nowait()
                except queue.Empty:
                    break
            
            # Stop if we're at or below the target size
            qsize = JackClient.QUEUE.qsize()
            if qsize < tosize:
                break
        
        qsize = JackClient.QUEUE.qsize()

    def empty_queue2(self):
        while True:
            with JackClient.Q2_LOCK:
                try:
                    data = JackClient.QUEUE2.get_nowait()
                except queue.Empty:
                    break

    def append_sound_to_queue1_as_needed(self):
        qsize = JackClient.QUEUE.qsize()

        # Add frames until target size reached
        while qsize < self.target_qsize:
            with JackClient.Q_LOCK:
                # Add a frame from the sound cycle
                frame = next(self.sound_cycle)
                JackClient.QUEUE.put_nowait(frame)
                
                # Keep track of how many frames played
                self.n_frames = self.n_frames + 1
            
            # Update qsize
            qsize = JackClient.QUEUE.qsize()  


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
noise = Noise(duration=0.1)
jack_client = JackClient()
sound = Sound()

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
                    # Play noise on outport 0
                    sound.play_noise(jack_client, 0)

                    # Update the current LED
                    current_pin = reward_pin

                elif value == 7:
                    # Manipulate pins for case 2
                    reward_pin = 9  # Example pin for case 2
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, 1)
                    pi.set_PWM_dutycycle(reward_pin, 50)
                    print("Turning Nosepoke 7 Green")
                    # Play noise on outport 0
                    sound.play_noise(jack_client, 1)

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
