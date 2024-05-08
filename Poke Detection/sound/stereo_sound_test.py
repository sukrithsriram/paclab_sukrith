import pigpio
import numpy as np
import os
import jack
import time

# Kill pigpiod and jackd if they are running
os.system('sudo killall pigpiod')
os.system('sudo killall jackd')
time.sleep(1)

# Restart them, and wait long enough that they have time to start
os.system('sudo pigpiod -t 0 -l -x 1111110000111111111111110000')
time.sleep(1)
os.system('jackd -P75 -p16 -t2000 -dalsa -dhw:sndrpihifiberry -P -r192000 -n3 -s &')
time.sleep(1)

class JackClient(object):
    def __init__(self, name='jack_client', outchannels=None):
        self.name = name

        # Create jack client
        self.client = jack.Client(self.name)

        # Pull these values from the initialized client
        # These comes from the jackd daemon
        self.blocksize = self.client.blocksize
        self.fs = self.client.samplerate
        print("received blocksize {} and fs {}".format(self.blocksize, self.fs))

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
            self.client.outports.register('out_0') #include this
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
                    "cannot connect {} ports, only {} available".format(
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

    def process(self, frames):
        # Generate some fake data
        # In the future this will be pulled from the queue
        data = np.random.uniform(-1, 1, self.blocksize) # Generating a random white noise signal
        self.table = np.zeros((self.blocksize, 2)) # Creating a table of zeros with 2 columns
        self.table[:, 0] = data # Assigning the random white noise signal to a channel in (0,1)
        amplitude = 0.001 
        self.table = self.table * amplitude # Scaling the signal by amplitude
        self.table = self.table.astype(np.float32) # Converting the table to float32
        #data = np.zeros(self.blocksize, dtype='float32')
        #print("data shape:", data.shape)

        # Write
        self.write_to_outports(self.table)

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

        else:
            raise ValueError("data must be 1D or 2D")


# Define a client to play sounds
jack_client = JackClient(name='jack_client')

# run forever
while True:
    print('running')
    time.sleep(1)
