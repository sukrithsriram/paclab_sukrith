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
