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

## KILLING PREVIOUS / EXISTING BACKGROUND PROCESSES
os.system('sudo killall pigpiod')
os.system('sudo killall jackd')

# Wait long enough to make sure they are killed
time.sleep(1)

## STARTING PIGPIOD AND JACKD BACKGROUND PROCESSES 

# Start pigpiod
""" 
Daemon Parameters:    
    -t 0 : use PWM clock (otherwise messes with audio)
    -l : disable remote socket interface (not sure why)
    -x : mask the GPIO which can be updated (not sure why; taken from autopilot)
 Runs in background by default (no need for &)
 """
os.system('sudo pigpiod -t 0 -l -x 1111110000111111111111110000')
time.sleep(1)

# Start jackd
"""
Daemon Parameters:
 -P75 : set realtime priority to 75 
 -p16 : --port-max, this seems unnecessary
 -t2000 : client timeout limit in milliseconds
 -dalsa : driver ALSA

ALSA backend options:
 -dhw:sndrpihifiberry : device to use
 -P : provide only playback ports (which suppresses a warning otherwise)
 -r192000 : set sample rate to 192000
 -n3 : set the number of periods of playback latency to 3
 -s : softmode, ignore xruns reported by the ALSA driver
 -p : size of period in frames (e.g., number of samples per chunk)
      Must be power of 2.
      Lower values will lower latency but increase probability of xruns.
 & : run in background

"""
# TODO: Use subprocess to keep track of these background processes
os.system(
    'jackd -P75 -p16 -t2000 -dalsa -dhw:sndrpihifiberry -P -r192000 -n3 -s &')
time.sleep(1)


## LOADING PARAMETERS FOR THE PI 

# Get the hostname of this pi and use that as its name
pi_hostname = sc.gethostname()
pi_name = str(pi_hostname)

# Load the config parameters for this pi
"""
Parameters for each pi in the behavior box
   identity: The name of the pi (set according to its hostname)
   gui_ip: The IP address of the computer that runs the GUI 
   poke_port: The network port dedicated to receiving information about pokes
   config_port: The network port used to send all the task parameters for any saved mouse
   nosepoke_type (L/R): This parameter is to specify the type of nosepoke sensor. Nosepoke sensors are of two types 
        OPB901L55 and OPB903L55 - 903 has an inverted rising edge/falling edge which means that the functions
        being called back to on the triggers need to be inverted.   
   nosepoke_id (L/R): The number assigned to the left and right ports of each pi 
"""
param_directory = f"pi/configs/pis/{pi_name}.json"
with open(param_directory, "r") as p:
    params = json.load(p)    

# Loading pin values 
"""
Note: If the code does not work when 'pins' is called then refer to the code from 'main' branch where all values are hardcoded (I had a problem with this. Not sure if fully fixed)
"""
pin_directory = f"pi/configs/pins.json"
with open(pin_directory, "r") as n:
    pins = json.load(n)

"""
Note: A lot of the comments/documentation of the Noise, SoundQueue and SoundPlayer classes are from the previous autopilot code

"""
## SETTING UP CLASSES USED TO GENERATE AUDIO

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
        
        ## I think this can be removed because mono isn't being used(?)
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
            # for n_column in range(self.table.shape[1]):
            #     self.table[:, n_column] = apply_attenuation(
            #         self.table[:, n_column], self.attenuation, self.fs)
        
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
    def __init__(self):
        
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
        
        # State variable to stop appending frames 
        self.running = False
        
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
        
        ## Debug Prints
        #print(self.target_rate)
        #print(left_on)
        #print(right_on)
        
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
        
        #print(left_target_intervals)
        #print(right_target_intervals)

        
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
        #print(both_df)
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
                        #print(frame.shape)
                        assert frame.shape == (1024, 2)
                elif bdrow.side == 'right' and bdrow.sound == 'target':
                    for frame in self.right_target_stim.chunks:
                        self.sound_block.append(frame)
                        #print(frame.shape)
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
            #time.sleep(0.1)
    
        ## Continue to the next stage (which is this one again)
        # If it is cleared, then nothing happens until the next message
        # from the Parent (not sure why)
        # If we never end this function, then it won't respond to END
        #self.stage_block.set()
    
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
        while self.running ==True and qsize < self.target_qsize:
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
        sound_queue : mp.Queue
            Should produce a frame of audio on request after filling up to qsize
        
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
        Fills frames of sound into the queue and plays stereo output from either the right or left channel
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

            # Write one column to each channel for stereo
            for n_outport, outport in enumerate(self.client.outports):
                buff = outport.get_array()
                buff[:] = data[:, n_outport]



# Defining a common queue tto be used by SoundPlayer and SoundChooser
# Initializing queues 
sound_queue = mp.Queue()
nonzero_blocks = mp.Queue()

# Lock for thread-safe set_channel() updates
qlock = mp.Lock()
nb_lock = mp.Lock()

# Define a client to play sounds
sound_chooser = SoundQueue()
sound_player = SoundPlayer(name='sound_player')

# Raspberry Pi's identity (Interchangeable with pi_name. This implementation is from before I was using the Pis host name)
pi_identity = params['identity']

## INITIALIZING NETWORK CONNECTION
"""
In order to communicate with the GUI, we create two sockets: poke_socket and json_socket
Both these sockets use different ZMQ contexts and are used in different parts of the code, this is why two network ports need to be used 
    * poke_socket: Used to send and receive poke-related information.
        - Sends: Poked Port, Poke Times 
        - Receives: Reward Port for each trial, Commands to Start/Stop the session, Exit command to end program
    * json_socket: Used to strictly receive task parameters from the GUI (so that audio parameters can be set for each trial)
"""
# Creating a DEALER socket for communication regarding poke and poke times
poke_context = zmq.Context()
poke_socket = poke_context.socket(zmq.DEALER)

# Setting the identity of the socket in bytes
poke_socket.identity = bytes(f"{pi_identity}", "utf-8") 

# Creating a SUB socket and socket for receiving task parameters (stored in json files)
json_context = zmq.Context()
json_socket = json_context.socket(zmq.SUB)

## Connect to the server
# Connecting to the GUI IP address stored in params
router_ip = "tcp://" + f"{params['gui_ip']}" + f"{params['poke_port']}" 
poke_socket.connect(router_ip) 

# Send the identity of the Raspberry Pi to the server
poke_socket.send_string(f"{pi_identity}") 

# Print acknowledgment
print(f"Connected to router at {router_ip}")  

# Connecting to json socket
router_ip2 = "tcp://" + f"{params['gui_ip']}" + f"{params['config_port']}"
json_socket.connect(router_ip2) 

# Subscribe to all incoming messages containing task parameters 
json_socket.subscribe(b"")

# Print acknowledgment
print(f"Connected to router at {router_ip2}")

# Creating a poller object for both sockets that will be used to continuously check for incoming messages
poller = zmq.Poller()
poller.register(poke_socket, zmq.POLLIN)
poller.register(json_socket, zmq.POLLIN)

## CONFIGURING PIGPIO AND RELATED FUNCTIONS 

# TODO: move these methods into a Nosepoke object. That object should be
# defined in another script and imported here

a_state = 0 # I think a_state used to be active state, which is what I was using to before I had to differentiate left and right pokes (might be safe to remove)
count = 0 # Count used to display how many pokes have happened on the pi terminal

# Assigning pins to variables 
nosepoke_pinL = pins['nosepoke_L']
nosepoke_pinR = pins['nosepoke_r']
led_red_l = pins['led_red_l']
led_red_r = pins['led_red_r']
led_blue_l = pins['led_blue_l']
led_blue_r = pins['led_blue_r']
led_green_l = pins['led_green_l']
led_green_r = pins['led_green_r']
valve_l = pins['solenoid_l']
valve_r = pins['solenoid_r']

# Assigning the port number for left and right ports
nosepokeL_id = params['nosepokeL_id']
nospokeR_id = params['nosepokeR_id']

# Global variables for which port the poke was detected at
left_poke_detected = False
right_poke_detected = False

"""
Currently, this version still uses messages from the GUI to determine when to reward correct pokes. 
I included this variable to track the port being poked to make the pi able to reward independent of the GUI. 
I was working on implementing this in another branch but have not finished it yet. Can work on it if needed
"""
current_port_poked = None

"""
Setting callback functions to run everytime a rising edge or falling edge is detected 
"""
# Callback functions for nosepoke pin (When the nosepoke is detected)
# Poke at Left Port 
def poke_detectedL(pin, level, tick): 
    global a_state, count, left_poke_detected, current_port_poked
    a_state = 1
    count += 1
    left_poke_detected = True
    print("Poke Completed (Left)")
    print("Poke Count:", count)
    nosepoke_idL = nosepoke_pinL  # Set the left nosepoke_id here according to the pi 
    current_port_poked = nosepoke_idL
    
    # Making red LED turn on when a poke is detected for troubleshooting
    pig.set_mode(led_red_l, pigpio.OUTPUT)
    if params['nosepokeL_type'] == "901":
        pig.write(led_red_l, 0)
    elif params['nosepokeL_type'] == "903":
        pig.write(led_red_l, 1)
        
    # Sending nosepoke_id to the GUI wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idL}") 
        poke_socket.send_string(str(nosepoke_idL))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

# Poke at Right Port
def poke_detectedR(pin, level, tick): 
    global a_state, count, right_poke_detected, current_port_poked
    a_state = 1
    count += 1
    right_poke_detected = True
    print("Poke Completed (Right)")
    print("Poke Count:", count)
    nosepoke_idR = nosepoke_pinR  # Set the right nosepoke_id here according to the pi
    current_port_poked = nosepoke_idR
    
    # Making red LED turn on when a poke is detected for troubleshooting
    pig.set_mode(led_red_r, pigpio.OUTPUT)
    if params['nosepokeR_type'] == "901":
        pig.write(led_red_r, 0)
    elif params['nosepokeR_type'] == "903":
        pig.write(led_red_r, 1)

    # Sending nosepoke_id to the GUI wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idR}") 
        poke_socket.send_string(str(nosepoke_idR))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

# Callback function for nosepoke pin (When the nosepoke is completed)
def poke_inL(pin, level, tick):
    global a_state, left_poke_detected
    a_state = 0
    if left_poke_detected:
        # Write to left pin
        print("Left poke detected!")
        pig.set_mode(led_red_l, pigpio.OUTPUT)
        if params['nosepokeL_type'] == "901":
            pig.write(led_red_l, 1)
        elif params['nosepokeL_type'] == "903":
            pig.write(led_red_l, 0)
    # Reset poke detected flags
    left_poke_detected = False

# Callback function for nosepoke pin (When the nosepoke is completed)
def poke_inR(pin, level, tick):
    global a_state, right_poke_detected
    a_state = 0
    if right_poke_detected:
        # Write to right pin
        print("Right poke detected!")
        pig.set_mode(led_red_r, pigpio.OUTPUT)
        if params['nosepokeR_type'] == "901":
            pig.write(led_red_r, 1)
        elif params['nosepokeR_type'] == "903":
            pig.write(led_red_r, 0)
            
    # Reset poke detected flags
    right_poke_detected = False

def open_valve(port):
    """Open the solenoid valve for port to deliver reward
    *port : port number to be rewarded (1,2,3..etc.)
    *reward_value: how long the valve should be open (in seconds) [imported from task parameters sent to the pi] 
    """
    reward_value = config_data['reward_value']
    if port == int(nosepoke_pinL):
        pig.set_mode(valve_l, pigpio.OUTPUT)
        pig.write(valve_l, 1) # Opening valve
        time.sleep(reward_value)
        pig.write(valve_l, 0) # Closing valve
    
    if port == int(nosepoke_pinR):
        pig.set_mode(valve_r, pigpio.OUTPUT)
        pig.write(valve_r, 1)
        time.sleep(reward_value)
        pig.write(valve_r, 0)

# TODO: document this function
def flash():
    """
    Flashing all the LEDs whenever a trial is completed 
    """
    pig.set_mode(led_blue_l, pigpio.OUTPUT)
    pig.write(led_blue_l, 1) # Turning LED on
    pig.set_mode(led_blue_r, pigpio.OUTPUT)
    pig.write(led_blue_r, 1) 
    time.sleep(0.5)
    pig.write(led_blue_l, 0) # Turning LED off
    pig.write(led_blue_r, 0)  

def stop_session():
    """
    This function contains the logic that needs to be executed whenever a session is stopped.
    It turns off all active LEDs, resets all the variables used for tracking to None, stops playing sound
    and empties the queue
    """
    global led_pin, current_led_pin, prev_port
    flash()
    current_led_pin = None
    prev_port = None
    pig.write(led_red_l, 0)
    pig.write(led_red_r, 0)
    pig.write(led_green_l, 0)
    pig.write(led_green_r, 0)
    sound_chooser.set_channel('none')
    sound_chooser.empty_queue()
    sound_chooser.running = False

# Initializing pigpio and assigning the defined functions 
pig = pigpio.pi()
pig.callback(nosepoke_pinL, pigpio.FALLING_EDGE, poke_inL) # Excutes when there is a falling edge on the voltage of the pin (when poke is completed)
pig.callback(nosepoke_pinL, pigpio.RISING_EDGE, poke_detectedL) # Executes when there is a rising edge on the voltage of the pin (when poke is detected) 
pig.callback(nosepoke_pinR, pigpio.FALLING_EDGE, poke_inR)
pig.callback(nosepoke_pinR, pigpio.RISING_EDGE, poke_detectedR)

# Setting up LED parameters
pwm_frequency = 1
pwm_duty_cycle = 50

## Initializing variables for the sound parameters (that will be changed when json file is sent to the Pi)
# Range of rates at which sound has to be played
rate_min = 0.0 
rate_max = 0.0

# Range of irregularity for each trial
irregularity_min = 0.0
irregularity_max = 0.0

# Range of amplitudes
amplitude_min = 0.0
amplitude_max = 0.0

## MAIN LOOP

# Loop to keep the program running and exit when it receives an exit string
try:
    ## TODO: document these variables and why they are tracked
    # Initialize led_pin to set what LED to write to
    led_pin = None
    
    # Variable used to track the pin of the currently blinking LED 
    current_led_pin = None  
    
    # Tracking the reward port for each trial; does not update until reward is completed 
    prev_port = None
    
    # Loop forever
    while True:
        # Wait for events on registered sockets. Currently polls every 100ms to check for messages 
        socks = dict(poller.poll(100))
        
        # Used to continuously add frames of sound to the queue until the program stops
        sound_chooser.append_sound_to_queue_as_needed()
        
        ## Check for incoming messages on json_socket
        # If so, use it to update the acoustic parameters
        """
        Socket is primarily used to import task parameters sent by the GUI
        Sound Parameters being updated: rate, irregularity, amplitude, center frequency        
        """
        if json_socket in socks and socks[json_socket] == zmq.POLLIN:
            # Setting up json socket to wait to receive messages from the GUI
            json_data = json_socket.recv_json()
            
            # Deserialize JSON data
            config_data = json.loads(json_data)
            
            # Debug print
            print(config_data)

            # Updating parameters from the JSON data sent by GUI
            rate_min = config_data['rate_min']
            rate_max = config_data['rate_max']
            irregularity_min = config_data['irregularity_min']
            irregularity_max = config_data['irregularity_max']
            amplitude_min = config_data['amplitude_min']
            amplitude_max = config_data['amplitude_max']
            center_freq_min = config_data['center_freq_min']
            center_freq_max = config_data['center_freq_max']
            bandwidth = config_data['bandwidth']
            
            
            # Update the Sound Queue with the new acoustic parameters
            sound_chooser.update_parameters(
                rate_min, rate_max, irregularity_min, irregularity_max, 
                amplitude_min, amplitude_max, center_freq_min, center_freq_max, bandwidth)
            sound_chooser.initialize_sounds(sound_player.blocksize, sound_player.fs, 
                sound_chooser.amplitude, sound_chooser.target_highpass, sound_chooser.target_lowpass)
            sound_chooser.set_sound_cycle()
            
            # Debug print
            print("Parameters updated")
            
        ## Check for incoming messages on poke_socket
        """
        poke_socket handles messages received from the GUI that are used to control the main loop. 
        The functions of the different messages are as follows:
        'exit' : terminates the program completely whenever received and closes it on all Pis for a particular box
        'stop' : stops the current session and sends a message back to the GUI to stop plotting. The program waits until it can start next session 
        'start' : used to start a new session after the stop message pauses the main loop
        'Reward Port' : this message is sent by the GUI to set the reward port for a trial.
        The Pis will receive messages of ports of other Pis being set as the reward port, however will only continue if the message contains one of the ports listed in its params file
        'Reward Poke Completed' : Currently 'hacky' logic used to signify the end of the trial. If the string sent to the GUI matches the reward port set there it
        clears all sound parameters and opens the solenoid valve for the assigned reward duration. The LEDs also flash to show a trial was completed 
        """        
        if poke_socket in socks and socks[poke_socket] == zmq.POLLIN:
            # Waiting to receive message strings that control the main loop
            msg = poke_socket.recv_string()  
    
            # Different messages have different effects
            if msg == 'exit': 
                # Condition to terminate the main loop
                stop_session()
                print("Received exit command. Terminating program.")
                
                # Deactivating the Sound Player before closing the program
                sound_player.client.deactivate()
                
                # Exit the loop
                break  
            
            # Receiving message from the GUI to stop the current session 
            if msg == 'stop':
                # Stopping all currently active elements and waiting for next session to start
                stop_session()
                
                # Sending stop signal wirelessly to stop update function
                try:
                    poke_socket.send_string("stop")
                except Exception as e:
                    print("Error stopping session", e)

                print("Stop command received. Stopping sequence.")
                continue

            # Communicating with start button to start the next session
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
                
                # Assigning the integer part to a variable
                value = int(msg_parts[2])  
                
                # Turn off the previously active LED if any
                if current_led_pin is not None:
                    pig.write(current_led_pin, 0)
                
                # Manipulate pin values based on the integer value
                if value == int(params['nosepokeL_id']):
                    # Starting sound the sound queue
                    sound_chooser.running = True
                    
                    # Setting the left LED to start blinking
                    led_pin = led_green_l  
                    
                    # Writing to the LED pin such that it blinks acc to the parameters 
                    pig.set_mode(led_pin, pigpio.OUTPUT)
                    pig.set_PWM_frequency(led_pin, pwm_frequency)
                    pig.set_PWM_dutycycle(led_pin, pwm_duty_cycle)
                    
                    # Playing sound from the left speaker
                    sound_chooser.empty_queue()
                    sound_chooser.set_channel('left')
                    sound_chooser.set_sound_cycle()
                    sound_chooser.play()
                    
                    # Debug message
                    print(f"Turning port {value} green")

                    # Keep track of which port is rewarded and which pin
                    # is rewarded
                    prev_port = value
                    current_led_pin = led_pin # for LED only 

                elif value == int(params['nosepokeR_id']):
                    # Starting sound
                    sound_chooser.running = True
                    
                    # Setting right LED pin to start blinking
                    led_pin = led_green_r
                    
                    # Writing to the LED pin such that it blinks acc to the parameters 
                    pig.set_mode(led_pin, pigpio.OUTPUT)
                    pig.set_PWM_frequency(led_pin, pwm_frequency)
                    pig.set_PWM_dutycycle(led_pin, pwm_duty_cycle)
                    
                    # Playing sound from the right speaker
                    sound_chooser.empty_queue()
                    sound_chooser.set_channel('right')
                    sound_chooser.set_sound_cycle()
                    sound_chooser.play()

                    # Debug message
                    print(f"Turning port {value} green")
                    
                    # Keep track of which port is rewarded and which pin
                    # is rewarded
                    prev_port = value
                    current_led_pin = led_pin
                
                else:
                    # TODO: document why this happens
                    # Current Reward Port
                    prev_port = value
                    print(f"Current Reward Port: {value}")
                
            elif msg.startswith("Reward Poke Completed"):
                # This seems to occur when the GUI detects that the poked
                # port was rewarded. This will be too slow. The reward port
                # should be opened if it knows it is the rewarded pin. 
                
                """
                Tried to implement this logic within the Pi itself. Can work on it more if needed
                """
                
                # Emptying the queue completely
                sound_chooser.running = False
                sound_chooser.set_channel('none')
                sound_chooser.empty_queue()

                # Flashing all lights and opening Solenoid Valve
                flash()
                open_valve(prev_port)
                
                # Updating all the parameters that will influence the next trialy
                sound_chooser.update_parameters(
                    rate_min, rate_max, irregularity_min, irregularity_max, 
                    amplitude_min, amplitude_max, center_freq_min, center_freq_max, bandwidth)
                poke_socket.send_string(sound_chooser.update_parameters.parameter_message)
                
                
                # Turn off the currently active LED
                if current_led_pin is not None:
                    pig.write(current_led_pin, 0)
                    print("Turning off currently active LED.")
                    current_led_pin = None  # Reset the current LED
                else:
                    print("No LED is currently active.")
           
            else:
                print("Unknown message received:", msg)

except KeyboardInterrupt:
    # Stops the pigpio connection
    pig.stop()

## QUITTING ALL NETWORK AND HARDWARE PROCESSES

finally:
    # Close all sockets and contexts
    poke_socket.close()
    poke_context.term()
    json_socket.close()
    json_context.term()


















        
    
