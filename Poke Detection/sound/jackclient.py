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
