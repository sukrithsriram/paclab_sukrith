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
import itertools
import queue
import multiprocessing as mp
import pandas as pd
import scipy.signal


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

class Noise:
    """Class to define bandpass filtered white noise."""
    def __init__(self, blocksize=1024, fs=192000, duration = 0.01, amplitude=0.01, channel=None, 
        highpass=None, lowpass=None, attenuation_file=None, **kwargs):
        """Initialize a new white noise burst with specified parameters.
        
        The sound itself is stored as the attribute `self.table`. This can
        be 1-dimensional or 2-dimensional, depending on `channel`. If it is
        2-dimensional, then each channel is a column.
        
        Args:
            duration (float): duration of the noise
            amplitude (float): amplitude of the sound as a proportion of 1.
            channel (int or None): which channel should be used
                If 0, play noise from the first channel
                If 1, play noise from the second channel
                If None, send the same information to all channels ("mono")
            highpass (float or None): highpass the Noise above this value
                If None, no highpass is applied
            lowpass (float or None): lowpass the Noise below this value
                If None, no lowpass is applied       
            attenuation_file (string or None)
                Path to where a pd.Series can be loaded containing attenuation
            **kwargs: extraneous parameters that might come along with instantiating us
        """
        # Set duraiton and amplitude as float
        self.blocksize = blocksize
        self.fs = fs
        self.duration = float(duration)
        self.amplitude = float(amplitude)
        
        # Save optional parameters - highpass, lowpass, channel
        if highpass is None:
            self.highpass = None
        else:
            self.highpass = float(highpass)
        
        if lowpass is None:
            self.lowpass = None
        else:
            self.lowpass = float(lowpass)
        
        # Save attenuation
        if attenuation_file is not None:
            self.attenuation = pd.read_table(
                attenuation_file, sep=',').set_index('freq')['atten']
        else:
            self.attenuation = None        
        
        # Save channel
        # Currently only mono or stereo sound is supported
        if channel is None:
            self.channel = None
        try:
            self.channel = int(channel)
        except TypeError:
            self.channel = channel
        
        if self.channel not in [0, 1]:
            raise ValueError(
                "audio channel must be 0 or 1, not {}".format(
                self.channel))

        # Initialize the sound itself
        self.chunks = None
        self.initialized = False
        self.init_sound()

    def init_sound(self):
        """Defines `self.table`, the waveform that is played. 
        
        The way this is generated depends on `self.server_type`, because
        parameters like the sampling rate cannot be known otherwise.
        
        The sound is generated and then it is "chunked" (zero-padded and
        divided into chunks). Finally `self.initialized` is set True.
        """
        # Calculate the number of samples
        self.nsamples = int(np.rint(self.duration * self.fs))
        
        # Generate the table by sampling from a uniform distribution
        # The shape of the table depends on `self.channel`
        # The table will be 2-dimensional for stereo sound
        # Each channel is a column
        # Only the specified channel contains data and the other is zero
        data = np.random.uniform(-1, 1, self.nsamples)
        
        # Highpass filter it
        if self.highpass is not None:
            bhi, ahi = scipy.signal.butter(
                2, self.highpass / (self.fs / 2), 'high')
            data = scipy.signal.filtfilt(bhi, ahi, data)
        
        # Lowpass filter it
        if self.lowpass is not None:
            blo, alo = scipy.signal.butter(
                2, self.lowpass / (self.fs / 2), 'low')
            data = scipy.signal.filtfilt(blo, alo, data)
        
        # Assign data into table
        self.table = np.zeros((self.nsamples, 2))
        assert self.channel in [0, 1]
        self.table[:, self.channel] = data
        
        # Scale by the amplitude
        self.table = self.table * self.amplitude
        
        # Convert to float32
        self.table = self.table.astype(np.float32)
        
        # Apply attenuation
        if self.attenuation is not None:
            # To make the attenuated sounds roughly match the original
            # sounds in loudness, multiply table by np.sqrt(10) (10 dB)
            # Better solution is to encode this into attenuation profile,
            # or a separate "gain" parameter
            self.table = self.table * np.sqrt(10)
            
            # Apply the attenuation to each column
            for n_column in range(self.table.shape[1]):
                self.table[:, n_column] = apply_attenuation(
                    self.table[:, n_column], self.attenuation, self.fs)
        
        # Break the sound table into individual chunks of length blocksize
        self.chunk()

        # Flag as initialized
        self.initialized = True

    def chunk(self):
        """Break the sound in self.table into chunks of length blocksize
        
        The sound in self.table is zero-padded to a length that is a multiple
        of `self.blocksize`. Then it is broken into `self.chunks`, a list 
        of chunks each of length `blocksize`.
        
        TODO: move this into a superclass, since the same code can be used
        for other sounds.
        """
        # Zero-pad the self.table to a new length that is multiple of blocksize
        oldlen = len(self.table)
        
        # Calculate how many blocks we need to contain the sound
        n_blocks_needed = int(np.ceil(oldlen / self.blocksize))
        
        # Calculate the new length
        newlen = n_blocks_needed * self.blocksize

        # Pad with 2d array of zeros
        to_concat = np.zeros(
            (newlen - oldlen, self.table.shape[1]), 
            np.float32)

        # Zero pad
        padded_sound = np.concatenate([self.table, to_concat])
        
        # Start of each chunk
        start_samples = range(0, len(padded_sound), self.blocksize)
        
        # Break the table into chunks
        self.chunks = [
            padded_sound[start_sample:start_sample + self.blocksize, :] 
            for start_sample in start_samples]

class SoundQueue:
    """This is a class used to continuously generate frames of audio and add them to a queue. 
    It also handles updating the parameters of the sound to be played. """
    def __init__(self, stage_block):
    ## Stages
        # Only one stage
        self.stages = itertools.cycle([self.play])
        self.stage_block = stage_block
        
        ## Initialize sounds
        # Each block/frame is about 5 ms
        # Longer is more buffer against unexpected delays
        # Shorter is faster to empty and refill the queue
        self.target_qsize = 200

        # Some counters to keep track of how many sounds we've played
        self.n_frames = 0

        # Instancing noise parameters
        self.blocksize = 1024
        self.fs = 192000
        self.amplitude = -0.075
        self.target_rate = 4
        self.target_temporal_log_std = -1.5
        self.center_freq = 10000
        self.bandwidth = 3000
        self.target_lowpass = self.center_freq + (self.bandwidth / 2)
        self.target_highpass = self.center_freq - (self.bandwidth / 2)
        
        # State of channels
        self.left_on = False
        self.right_on = False
        
        # Fill the queue with empty frames
        # Sounds aren't initialized till the trial starts
        # Using False here should work even without sounds initialized yet
        self.initialize_sounds(self.blocksize, self.fs, self.amplitude, self.target_highpass,  self.target_lowpass)
        self.set_sound_cycle()

        # Use this to keep track of generated sounds
        self.current_audio_times_df = None
    
    """Object to choose the sounds and pauses for this trial"""
    def update_parameters(self, rate_min, rate_max, irregularity_min, irregularity_max, amplitude_min, amplitude_max, center_freq_min, center_freq_max, bandwidth):
        """Method to update sound parameters dynamically"""
        self.target_rate = random.uniform(rate_min, rate_max)
        self.target_temporal_log_std = random.uniform(irregularity_min, irregularity_max)
        self.amplitude = random.uniform(amplitude_min, amplitude_max)
        self.center_freq = random.uniform(center_freq_min, center_freq_max)
        self.bandwidth = bandwidth
        self.target_lowpass = self.center_freq + (self.bandwidth / 2)
        self.target_highpass = self.center_freq - (self.bandwidth / 2)

        # Debug message
        parameter_message = (
            f"Current Parameters - Amplitude: {self.amplitude}, "
            f"Rate: {self.target_rate} s, "
            f"Irregularity: {self.target_temporal_log_std} s, "
            f"Center Frequency: {self.center_freq} Hz, "
            f"Bandwidth: {self.bandwidth}"
            )

        print(parameter_message)
        return parameter_message

    """Method to choose which sound to initialize based on the target channel"""
    def initialize_sounds(self, blocksize, fs, target_amplitude, target_highpass,  target_lowpass):
        """Defines sounds that will be played during the task"""
        ## Define sounds
        # Left and right target noise bursts
        self.left_target_stim = Noise(blocksize, fs,
            duration=0.01, amplitude= self.amplitude, channel=0, 
            lowpass=self.target_lowpass, highpass=self.target_highpass
            )       
        
        self.right_target_stim = Noise(blocksize, fs,
            duration=0.01, amplitude= self.amplitude, channel=1, 
            lowpass=self.target_lowpass, highpass=self.target_highpass
            )  


    def set_sound_cycle(self):
        """Define self.sound_cycle, to go through sounds
        
        params : dict
            This comes from a message on the net node.
            Possible keys:
                left_on
                right_on
                left_mean_interval
                right_mean_interval
        """
        # Array to attach chunked sounds
        self.sound_block = []

        # Helper function
        def append_gap(gap_chunk_size=30):
            """Append `gap_chunk_size` silent chunks to sound_block"""
            for n_blank_chunks in range(gap_chunk_size):
                self.sound_block.append(
                    np.zeros((1024, 2), dtype='float32'))

        # Extract params or use defaults
        left_on = self.left_on
        right_on = self.right_on
        left_target_rate = self.target_rate 
        right_target_rate = self.target_rate 
        
        print(self.target_rate)
        print(left_on)
        print(right_on)
        
        # Global params
        target_temporal_std = 10 ** self.target_temporal_log_std 
        
        ## Generate intervals 
        # left target
        if left_on and left_target_rate > 1e-3:
            # Change of basis
            mean_interval = 1 / left_target_rate
            var_interval = target_temporal_std ** 2

            # Change of basis
            gamma_shape = (mean_interval ** 2) / var_interval
            gamma_scale = var_interval / mean_interval

            # Draw
            left_target_intervals = np.random.gamma(
                gamma_shape, gamma_scale, 100)
        else:
            left_target_intervals = np.array([])

        # right target
        if right_on and right_target_rate > 1e-3:
            # Change of basis
            mean_interval = 1 / right_target_rate
            var_interval = target_temporal_std ** 2

            # Change of basis
            gamma_shape = (mean_interval ** 2) / var_interval
            gamma_scale = var_interval / mean_interval

            # Draw
            right_target_intervals = np.random.gamma(
                gamma_shape, gamma_scale, 100)
        else:
            right_target_intervals = np.array([])              
        
        print(left_target_intervals)
        print(right_target_intervals)

        
        ## Sort all the drawn intervals together
        # Turn into series
        left_target_df = pd.DataFrame.from_dict({
            'time': np.cumsum(left_target_intervals),
            'side': ['left'] * len(left_target_intervals),
            'sound': ['target'] * len(left_target_intervals),
            })
        right_target_df = pd.DataFrame.from_dict({
            'time': np.cumsum(right_target_intervals),
            'side': ['right'] * len(right_target_intervals),
            'sound': ['target'] * len(right_target_intervals),
            })

        # Concatenate them all together and resort by time
        both_df = pd.concat([
            left_target_df, right_target_df], axis=0).sort_values('time')

        # Calculate the gap between sounds
        both_df['gap'] = both_df['time'].diff().shift(-1)
        
        # Drop the last row which has a null gap
        both_df = both_df.loc[~both_df['gap'].isnull()].copy()

        # Keep only those below the sound cycle length
        both_df = both_df.loc[both_df['time'] < 10].copy()
        
        # Nothing should be null
        assert not both_df.isnull().any().any() 

        # Calculate gap size in chunks
        both_df['gap_chunks'] = (both_df['gap'] * (self.fs / self.blocksize))
        both_df['gap_chunks'] = both_df['gap_chunks'].round().astype(int)
        
        # Floor gap_chunks at 1 chunk, the minimal gap size
        # This is to avoid distortion
        both_df.loc[both_df['gap_chunks'] < 1, 'gap_chunks'] = 1
        
        # Save
        self.current_audio_times_df = both_df.copy()
        self.current_audio_times_df = self.current_audio_times_df.rename(
            columns={'time': 'relative_time'})

        
        ## Depends on how long both_df is
        # If both_df has a nonzero but short length, results will be weird,
        # because it might just be one noise burst repeating every ten seconds
        # This only happens with low rates ~0.1Hz
        print(both_df)
        if len(both_df) == 0:
            # If no sound, then just put gaps
            append_gap(100)
        else:
            # Iterate through the rows, adding the sound and the gap
            # TODO: the gap should be shorter by the duration of the sound,
            # and simultaneous sounds should be possible
            for bdrow in both_df.itertuples():
                # Append the sound
                if bdrow.side == 'left' and bdrow.sound == 'target':
                    for frame in self.left_target_stim.chunks:
                        self.sound_block.append(frame)
                        print(frame.shape)
                        assert frame.shape == (1024, 2)
                elif bdrow.side == 'right' and bdrow.sound == 'target':
                    for frame in self.right_target_stim.chunks:
                        self.sound_block.append(frame)
                        print(frame.shape)
                        assert frame.shape == (1024, 2)                        
                else:
                    raise ValueError(
                        "unrecognized side and sound: {} {}".format(
                        bdrow.side, bdrow.sound))
                
                # Append the gap
                append_gap(bdrow.gap_chunks)
        
        
        ## Cycle so it can repeat forever
        self.sound_cycle = itertools.cycle(self.sound_block)        

    def play(self):
        """A single stage"""
        # Don't want to do a "while True" here, because we need to exit
        # this method eventually, so that it can respond to END
        # But also don't want to change stage too frequently or the debug
        # messages are overwhelming
        for n in range(10):
            # Add stimulus sounds to queue as needed
            self.append_sound_to_queue_as_needed()

            # Don't want to iterate too quickly, but rather add chunks
            # in a controlled fashion every so often
            time.sleep(0.1)
        
        ## Extract any recently played sound info
        sound_data_l = []
        with nb_lock:
            while True:
                try:
                    data = nonzero_blocks.get_nowait()
                except queue.Empty:
                    break
                sound_data_l.append(data)
    
        ## Continue to the next stage (which is this one again)
        # If it is cleared, then nothing happens until the next message
        # from the Parent (not sure why)
        # If we never end this function, then it won't respond to END
        self.stage_block.set()
    
    def append_sound_to_queue_as_needed(self):
        """Dump frames from `self.sound_cycle` into queue

        The queue is filled until it reaches `self.target_qsize`

        This function should be called often enough that the queue is never
        empty.
        """        
        # TODO: as a figure of merit, keep track of how empty the queue gets
        # between calls. If it's getting too close to zero, then target_qsize
        # needs to be increased.
        # Get the size of queue now
        qsize = sound_queue.qsize()

        # Add frames until target size reached
        while qsize < self.target_qsize:
            with qlock:
                # Add a frame from the sound cycle
                frame = next(self.sound_cycle)
                #frame = np.random.uniform(-.01, .01, (1024, 2)) 
                sound_queue.put_nowait(frame)
                
                # Keep track of how many frames played
                self.n_frames = self.n_frames + 1
            
            # Update qsize
            qsize = sound_queue.qsize()
            
    def empty_queue(self, tosize=0):
        """Empty queue"""
        while True:
            # I think it's important to keep the lock for a short period
            # (ie not throughout the emptying)
            # in case the `process` function needs it to play sounds
            # (though if this does happen, there will be an artefact because
            # we just skipped over a bunch of frames)
            with qlock:
                try:
                    data = sound_queue.get_nowait()
                except queue.Empty:
                    break
            
            # Stop if we're at or below the target size
            qsize = sound_queue.qsize()
            if qsize < tosize:
                break
        
        qsize = sound_queue.qsize()
    
    def set_channel(self, mode):
        """Controlling which channel the sound is played from """
        if mode == 'none':
            self.left_on = False
            self.right_on = False
        if mode == 'left':
            self.left_on = True
            self.right_on = False
        if mode == 'right':
            self.left_on = False
            self.right_on = True

# Define a JackClient, which will play sounds in the background
# Rename to SoundPlayer to avoid confusion with jack.Client
class SoundPlayer(object):
    """Object to play sounds"""
    def __init__(self, name='jack_client'):
        """Initialize a new JackClient

        This object contains a jack.Client object that actually plays audio.
        It provides methods to send sound to its jack.Client, notably a 
        `process` function which is called every 5 ms or so.
        
        name : str
            Required by jack.Client
        # 
        audio_cycle : iter
            Should produce a frame of audio on request
        
        This object should focus only on playing sound as precisely as
        possible.
        """
        ## Store provided parameters
        self.name = name
        
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
        self.client.outports.register('out_0')
        self.client.outports.register('out_1')
        
        ## Set up the process callback
        # This will be called on every block and must provide data
        self.client.set_process_callback(self.process)

        ## Activate the client
        self.client.activate()

        ## Hook up the outports (data sinks) to physical ports
        # Get the actual physical ports that can play sound
        target_ports = self.client.get_ports(
            is_physical=True, is_input=True, is_audio=True)
        assert len(target_ports) == 2

        # Connect virtual outport to physical channel
        self.client.outports[0].connect(target_ports[0])
        self.client.outports[1].connect(target_ports[1])
    
    def process(self, frames):
        """Process callback function (used to play sound)
        
        TODO: reimplement this to use a queue instead
        The current implementation uses time.time(), but we need to be more
        precise.
        """
        # Check if the queue is empty
        if sound_queue.empty():
            # No sound to play, so play silence 
            # Although this shouldn't be happening

            for n_outport, outport in enumerate(self.client.outports):
                buff = outport.get_array()
                buff[:] = np.zeros(self.blocksize, dtype='float32')
            
        else:
            # Queue is not empty, so play data from it
            data = sound_queue.get()
            if data.shape != (self.blocksize, 2):
                print(data.shape)
            assert data.shape == (self.blocksize, 2)

            # Write one column to each channel
            for n_outport, outport in enumerate(self.client.outports):
                buff = outport.get_array()
                buff[:] = data[:, n_outport]

# Defining a common queue to be used by both classes 
# Initializing queues to be used by sound player
sound_queue = mp.Queue()
nonzero_blocks = mp.Queue()

# Lock for thread-safe set_channel() updates
qlock = mp.Lock()
nb_lock = mp.Lock()

# Define a client to play sounds
stage_block = threading.Event()
sound_chooser = SoundQueue(stage_block)
sound_player = SoundPlayer(name='sound_player')

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

# Function with logic to stop session
def stop_session():
    global reward_pin, current_pin, prev_port
    flash()
    current_pin = None
    prev_port = None
    pi.write(17, 0)
    pi.write(10, 0)
    pi.write(27, 0)
    pi.write(9, 0)
    sound_chooser.set_channel('none')

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
rate_min = 0.0
rate_max = 0.0

# Duration of pauses
irregularity_min = 0.0
irregularity_max = 0.0

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
            rate_min = config_data['rate_min']
            rate_max = config_data['rate_max']
            irregularity_min = config_data['irregularity_min']
            irregularity_max = config_data['irregularity_max']
            amplitude_min = config_data['amplitude_min']
            amplitude_max = config_data['amplitude_max']
            center_freq_min = config_data['center_freq_min']
            center_freq_max = config_data['center_freq_max']
            bandwidth = config_data['bandwidth']
            
            # Update the jack client with the new acoustic parameters
            sound_chooser.update_parameters(
                rate_min, rate_max, irregularity_min, irregularity_max, 
                amplitude_min, amplitude_max, center_freq_min, center_freq_max, bandwidth)
            sound_chooser.set_sound_cycle()
            
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
                ##time.sleep(sound_player.noise.target_rate + sound_player.noise.target_temporal_log_std)
                
                # Stop the Jack client
                # TODO: Probably want to leave this running for the next
                # session
                sound_player.client.deactivate()
                
                # Exit the loop
                break  
            
            # Receiving message from stop button 
            if msg == 'stop':
                stop_session()
                
                # Sending stop signal wirelessly to stop update function
                try:
                    poke_socket.send_string("stop")
                except Exception as e:
                    print("Error stopping session", e)

                print("Stop command received. Stopping sequence.")
                continue

            # Communicating with start button to restart session
            if msg == 'start':
                try:
                    poke_socket.send_string("start")
                except Exception as e:
                    print("Error stopping session", e)
            
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
                    sound_chooser.empty_queue()
                    sound_chooser.set_channel('left')
                    sound_chooser.set_sound_cycle()
                    sound_chooser.play()

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
                    sound_chooser.empty_queue()
                    sound_chooser.set_channel('right')
                    sound_chooser.set_sound_cycle()
                    sound_chooser.play()

                    
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
                # TODO: fix this; rate_min etc are not necessarily defined
                # yet, or haven't changed recently
                # Reset play mode to 'none'
                sound_chooser.set_channel('none')
                sound_chooser.update_parameters(
                    rate_min, rate_max, irregularity_min, irregularity_max, 
                    amplitude_min, amplitude_max, center_freq_min, center_freq_max, bandwidth)
                sound_chooser.empty_queue()

                #sound_chooser.set_sound_cycle()
                
                # Turn off the currently active LED
                if current_pin is not None:
                    pi.write(current_pin, 0)
                    print("Turning off currently active LED.")
                    current_pin = None  # Reset the current LED
                else:
                    print("No LED is currently active.")
           
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
        
    























        
    