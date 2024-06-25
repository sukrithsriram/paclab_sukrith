import threading
import time
import random
import numpy as np
import jack
import scipy.signal

class JackClient:
    """Object to play sounds"""
    
    def __init__(self, name='jack_client', highpass=None, lowpass=None):
        """Initialize a new JackClient

        This object contains a jack.Client object that actually plays audio.
        It provides methods to send sound to its jack.Client, notably a 
        `process` function which is called every 5 ms or so.

        Parameters:
        name (str): Required by jack.Client
        highpass (float or None): highpass the noise above this value
        lowpass (float or None): lowpass the noise below this value
        """
        self.name = name
        self.set_channel = 'none'  # 'left', 'right', or 'none'
        self.lock = threading.Lock()
        self.chunk_duration = 0.01
        self.pause_duration = random.uniform(0.05, 0.2)
        self.amplitude = random.uniform(0.005, 0.02)
        self.last_chunk_time = time.time()
        
        self.highpass = highpass
        self.lowpass = lowpass
        
        # Create the jack.Client
        self.client = jack.Client(self.name)
        self.blocksize = self.client.blocksize
        self.fs = self.client.samplerate
        print("Received blocksize {} and fs {}".format(self.blocksize, self.fs))
        
        self.outchannels = [0, 1]  # Always stereo
        self.mono_output = False  # Always stereo

        # Register outports
        for n in range(len(self.outchannels)):
            self.client.outports.register('out_{}'.format(n))

        self.client.set_process_callback(self.process)
        self.client.activate()
        
        self._connect_outports()

    def _connect_outports(self):
        """Connect virtual outports to physical ports"""
        target_ports = self.client.get_ports(is_physical=True, is_input=True, is_audio=True)
        if len(self.outchannels) > len(target_ports):
            raise ValueError("Cannot connect {} ports, only {} available".format(
                len(self.outchannels), len(target_ports)))
        for n in range(len(self.outchannels)):
            physical_channel = target_ports[self.outchannels[n]]
            self.client.outports[n].connect(physical_channel)

    def update_parameters(self, chunk_min, chunk_max, pause_min, pause_max, amplitude_min, amplitude_max, highpass=None, lowpass=None):
        """Method to update sound parameters dynamically"""
        self.chunk_duration = random.uniform(chunk_min, chunk_max)
        self.pause_duration = random.uniform(pause_min, pause_max)
        self.amplitude = random.uniform(amplitude_min, amplitude_max)
        self.highpass = highpass
        self.lowpass = lowpass
        parameter_message = (f"Current Parameters - Amplitude: {self.amplitude}, "
                             f"Chunk Duration: {self.chunk_duration} s, "
                             f"Pause Duration: {self.pause_duration}, "
                             f"Highpass: {self.highpass}, Lowpass: {self.lowpass}")
        print(parameter_message)
        self.send_parameter_message(parameter_message)

    def send_parameter_message(self, message):
        """Send parameter message (placeholder for actual ZMQ or other message system)"""
        poke_socket.send_string(message)

    def process(self, frames):
        """Process callback function (used to play sound)"""
        with self.lock:
            current_time = time.time()
            data = np.zeros((self.blocksize, 2), dtype='float32')

            if current_time - self.last_chunk_time >= self.chunk_duration + self.pause_duration:
                self.last_chunk_time = current_time
            elif current_time - self.last_chunk_time >= self.chunk_duration:
                pass
            else:
                data = self.generate_filtered_noise()
            self.write_to_outports(data)

    def generate_filtered_noise(self):
        """Generate filtered noise"""
        noise = self.amplitude * np.random.uniform(-1, 1, (self.blocksize, 2))
        if self.highpass is not None:
            bhi, ahi = scipy.signal.butter(2, self.highpass / (self.fs / 2), 'high')
            noise[:, 0] = scipy.signal.filtfilt(bhi, ahi, noise[:, 0])
            noise[:, 1] = scipy.signal.filtfilt(bhi, ahi, noise[:, 1])
        if self.lowpass is not None:
            blo, alo = scipy.signal.butter(2, self.lowpass / (self.fs / 2), 'low')
            noise[:, 0] = scipy.signal.filtfilt(blo, alo, noise[:, 0])
            noise[:, 1] = scipy.signal.filtfilt(blo, alo, noise[:, 1])
        if self.set_channel == 'left':
            noise[:, 1] = 0
        elif self.set_channel == 'right':
            noise[:, 0] = 0
        return noise

    def write_to_outports(self, data):
        """Write data to outports"""
        for n_outport, outport in enumerate(self.client.outports):
            buff = outport.get_array()
            buff[:] = data[:, n_outport]

    def set_set_channel(self, mode):
        """Set which channel to play sound from"""
        with self.lock:
            self.set_channel = mode

# Example usage of zmq (if needed):
context = zmq.Context()
poke_socket = context.socket(zmq.PUB)
poke_socket.bind("tcp://*:5556")
------------------------
import threading
import time
import random
import numpy as np
import jack
import scipy.signal
import zmq

class JackClient:
    """Object to play sounds"""
    
    def __init__(self, name='jack_client', center_frequency_min=500, center_frequency_max=1500, bandwidth=200):
        """Initialize a new JackClient

        This object contains a jack.Client object that actually plays audio.
        It provides methods to send sound to its jack.Client, notably a 
        `process` function which is called every 5 ms or so.

        Parameters:
        name (str): Required by jack.Client
        center_frequency_min (float): Minimum center frequency for bandpass filter
        center_frequency_max (float): Maximum center frequency for bandpass filter
        bandwidth (float): Bandwidth for the bandpass filter
        """
        self.name = name
        self.set_channel = 'none'  # 'left', 'right', or 'none'
        self.lock = threading.Lock()
        self.chunk_duration = 0.01
        self.pause_duration = random.uniform(0.05, 0.2)
        self.amplitude = random.uniform(0.005, 0.02)
        self.last_chunk_time = time.time()
        
        self.center_frequency_min = center_frequency_min
        self.center_frequency_max = center_frequency_max
        self.bandwidth = bandwidth
        self.center_frequency = random.uniform(self.center_frequency_min, self.center_frequency_max)
        self.highpass, self.lowpass = self.calculate_bandpass(self.center_frequency, self.bandwidth)
        
        # Create the jack.Client
        self.client = jack.Client(self.name)
        self.blocksize = self.client.blocksize
        self.fs = self.client.samplerate
        print("Received blocksize {} and fs {}".format(self.blocksize, self.fs))
        
        self.outchannels = [0, 1]  # Always stereo
        self.mono_output = False  # Always stereo

        # Register outports
        for n in range(len(self.outchannels)):
            self.client.outports.register('out_{}'.format(n))

        self.client.set_process_callback(self.process)
        self.client.activate()
        
        self._connect_outports()

    def _connect_outports(self):
        """Connect virtual outports to physical ports"""
        target_ports = self.client.get_ports(is_physical=True, is_input=True, is_audio=True)
        if len(self.outchannels) > len(target_ports):
            raise ValueError("Cannot connect {} ports, only {} available".format(
                len(self.outchannels), len(target_ports)))
        for n in range(len(self.outchannels)):
            physical_channel = target_ports[self.outchannels[n]]
            self.client.outports[n].connect(physical_channel)

    def update_parameters(self, chunk_min, chunk_max, pause_min, pause_max, amplitude_min, amplitude_max, center_frequency_min=None, center_frequency_max=None, bandwidth=None):
        """Method to update sound parameters dynamically"""
        self.chunk_duration = random.uniform(chunk_min, chunk_max)
        self.pause_duration = random.uniform(pause_min, pause_max)
        self.amplitude = random.uniform(amplitude_min, amplitude_max)
        if center_frequency_min is not None:
            self.center_frequency_min = center_frequency_min
        if center_frequency_max is not None:
            self.center_frequency_max = center_frequency_max
        if bandwidth is not None:
            self.bandwidth = bandwidth
        self.center_frequency = random.uniform(self.center_frequency_min, self.center_frequency_max)
        self.highpass, self.lowpass = self.calculate_bandpass(self.center_frequency, self.bandwidth)
        parameter_message = (f"Current Parameters - Amplitude: {self.amplitude}, "
                             f"Chunk Duration: {self.chunk_duration} s, "
                             f"Pause Duration: {self.pause_duration}, "
                             f"Center Frequency: {self.center_frequency}, "
                             f"Bandwidth: {self.bandwidth}, "
                             f"Highpass: {self.highpass}, Lowpass: {self.lowpass}")
        print(parameter_message)
        self.send_parameter_message(parameter_message)

    def send_parameter_message(self, message):
        """Send parameter message (placeholder for actual ZMQ or other message system)"""
        poke_socket.send_string(message)

    def calculate_bandpass(self, center_frequency, bandwidth):
        """Calculate highpass and lowpass frequencies based on center frequency and bandwidth"""
        highpass = center_frequency - (bandwidth / 2)
        lowpass = center_frequency + (bandwidth / 2)
        return highpass, lowpass

    def process(self, frames):
        """Process callback function (used to play sound)"""
        with self.lock:
            current_time = time.time()
            data = np.zeros((self.blocksize, 2), dtype='float32')

            if current_time - self.last_chunk_time >= self.chunk_duration + self.pause_duration:
                self.last_chunk_time = current_time
            elif current_time - self.last_chunk_time >= self.chunk_duration:
                pass
            else:
                data = self.generate_filtered_noise()
            self.write_to_outports(data)

    def generate_filtered_noise(self):
        """Generate filtered noise"""
        noise = self.amplitude * np.random.uniform(-1, 1, (self.blocksize, 2))
        if self.highpass is not None:
            bhi, ahi = scipy.signal.butter(2, self.highpass / (self.fs / 2), 'high')
            noise[:, 0] = scipy.signal.filtfilt(bhi, ahi, noise[:, 0])
            noise[:, 1] = scipy.signal.filtfilt(bhi, ahi, noise[:, 1])
        if self.lowpass is not None:
            blo, alo = scipy.signal.butter(2, self.lowpass / (self.fs / 2), 'low')
            noise[:, 0] = scipy.signal.filtfilt(blo, alo, noise[:, 0])
            noise[:, 1] = scipy.signal.filtfilt(blo, alo, noise[:, 1])
        if self.set_channel == 'left':
            noise[:, 1] = 0
        elif self.set_channel == 'right':
            noise[:, 0] = 0
        return noise

    def write_to_outports(self, data):
        """Write data to outports"""
        for n_outport, outport in enumerate(self.client.outports):
            buff = outport.get_array()
            buff[:] = data[:, n_outport]

    def set_set_channel(self, mode):
        """Set which channel to play sound from"""
        with self.lock:
            self.set_channel = mode

# Example usage of zmq (if needed):
context = zmq.Context()
poke_socket = context.socket(zmq.PUB)
poke_socket.bind("tcp://*:5556")



