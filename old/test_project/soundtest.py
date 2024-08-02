## Blocks of code to use for the process function from autopilot and new wheel task

# SoundPlayer object from wheel task 
class SoundPlayer(object):
    """Object to play sounds"""
    def __init__(self, name='jack_client', audio_cycle=None):
        """Initialize a new JackClient

        This object contains a jack.Client object that actually plays audio.
        It provides methods to send sound to its jack.Client, notably a 
        `process` function which is called every 5 ms or so.
        
        name : str
            Required by jack.Client
        
        audio_cycle : iter
            Should produce a frame of audio on request
        
        This object should focus only on playing sound as precisely as
        possible.
        """
        ## Store provided parameters
        self.name = name
        
        self.audio_cycle = audio_cycle
        
        ## Acoustic parameters of the sound
        # TODO: define these elsewhere -- these should not be properties of
        # this object, because this object should be able to play many sounds
        
        # Lock for thread-safe set_channel() updates
        self.lock = threading.Lock()  
        
        
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
        # Making process() thread-safe (so that multiple calls don't try to
        # write to the outports at the same time)
        # with self.lock: 
        # This seems to noticeably increase xrun errors (possibly because
        # the lock is working?)
        
        # Get data from cycle
        data = next(self.audio_cycle)
        data_std = np.std(data)
        
        if data_std > 1e-5:
            # This is only an approximate hash because it excludes the
            # middle of the data
            data_hash = hash(str(data))
            
            # Get the current time
            # lft is the only precise one, and it's at the start of the process
            # block
            # fscs is approx number of frames since then until now
            # dt is about now
            # later, using lft, fscs, and dt, we can reconstruct the approx
            # relationship between frame times and clock time
            # this will get screwed up on every xrun
            lft = self.client.last_frame_time

            dt = datetime.datetime.now().isoformat()
            fscs = self.client.frames_since_cycle_start
            
            # Use this to estimate the delay in getting these values
            #dt2 = datetime.datetime.now().isoformat()
            #fscs2 = self.client.frames_since_cycle_start
            
            
            # Subtract fscs from the delay
            # The delay should be three periods (16 ms) minus the fixed latency
            # of this code, which empirically is about 0.5 ms
            delay = .016 - .0005 - fscs / 192000
            
            # Pulse
            threading.Timer(delay, pulse_on).start()
            threading.Timer(delay + .001, pulse_off).start()

            
            
            #~ print('data std is {} with hash {} at {} + {} ie {}'.format(
                #~ data_std, 
                #~ data_hash,
                #~ lft,
                #~ fscs,
                #~ dt
                #~ ))

        # Error check
        assert data.shape[1] == 2

        # Write one column to each channel
        for n_outport, outport in enumerate(self.client.outports):
            buff = outport.get_array()
            buff[:] = data[:, n_outport]




# Queue from wheel task 
## Define audio to play
click = np.zeros((1024, 2))
click[0] = 1
click[1] = -1
audio_cycle = itertools.cycle([
    0.001 * (np.random.uniform(-1, 1, (1024, 2))),
    click,
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    00 * (np.random.uniform(-1, 1, (1024, 2))),
    ])



# Queue from paft_child
    def initalize_sounds(self,             
        target_highpass, target_amplitude, target_lowpass,
        distracter_highpass, distracter_amplitude, distracter_lowpass,
        ):
        """Defines sounds that will be played during the task"""
        ## Define sounds
        # Left and right target noise bursts
        self.left_target_stim = autopilot.stim.sound.sounds.Noise(
            duration=10, amplitude=target_amplitude, channel=0, 
            lowpass=target_lowpass, highpass=target_highpass,
            attenuation_file='/home/pi/attenuation.csv',
            )       

        self.right_target_stim = autopilot.stim.sound.sounds.Noise(
            duration=10, amplitude=target_amplitude, channel=1, 
            lowpass=target_lowpass, highpass=target_highpass,
            attenuation_file='/home/pi/attenuation.csv',
            )

        # Left and right distracter noise bursts
        self.left_distracter_stim = autopilot.stim.sound.sounds.Noise(
            duration=10, amplitude=distracter_amplitude, channel=0, 
            lowpass=distracter_lowpass, highpass=distracter_highpass,
            attenuation_file='/home/pi/attenuation.csv',
            )       

        self.right_distracter_stim = autopilot.stim.sound.sounds.Noise(
            duration=10, amplitude=distracter_amplitude, channel=1, 
            lowpass=distracter_lowpass, highpass=distracter_highpass,
            attenuation_file='/home/pi/atchunktenuation.csv',
            )  
            
        # Left and right tritone error noises
        self.left_error_sound = autopilot.stim.sound.sounds.Tritone(
            frequency=8000, duration=250, amplitude=.003, channel=0)

        self.right_error_sound = autopilot.stim.sound.sounds.Tritone(
            frequency=8000, duration=250, amplitude=.003, channel=1)
        
        # Chunk the sounds into frames
        if not self.left_target_stim.chunks:
            self.left_target_stim.chunk()
        if not self.right_target_stim.chunks:
            self.right_target_stim.chunk()
        if not self.left_distracter_stim.chunks:
            self.left_distracter_stim.chunk()
        if not self.right_distracter_stim.chunks:
            self.right_distracter_stim.chunk()
        if not self.left_error_sound.chunks:
            self.left_error_sound.chunk()
        if not self.right_error_sound.chunks:
            self.right_error_sound.chunk()
    
    def set_sound_cycle(self, params):
        """Define self.sound_cycle, to go through sounds
        
        params : dict
            This comes from a message on the net node.
            Possible keys:
                left_on
                right_on
                left_mean_interval
                right_mean_interval
        """
        # Log
        self.logger.debug('set_sound_cycle: received params: {}'.format(params))
        
        # This is just a left sound, gap, then right sound, then gap
        # And use a cycle to repeat forever
        # But this could be made more complex
        self.sound_block = []

        # Helper function
        def append_gap(gap_chunk_size=30):
            """Append `gap_chunk_size` silent chunks to sound_block"""
            for n_blank_chunks in range(gap_chunk_size):
                self.sound_block.append(
                    np.zeros(autopilot.stim.sound.jackclient.BLOCKSIZE, 
                    dtype='float32'))

        # Extract params or use defaults
        left_on = params.get('left_on', False)
        right_on = params.get('right_on', False)
        left_target_rate = params.get('left_target_rate', 0)
        right_target_rate = params.get('right_target_rate', 0)
        left_distracter_rate = params.get('left_distracter_rate', 0)
        right_distracter_rate = params.get('right_distracter_rate', 0)
        
        # Global params
        target_temporal_std = 10 ** params.get(
            'stim_target_temporal_log_std', -2)
        distracter_temporal_std = 10 ** params.get(
            'stim_distracter_temporal_log_std', -2)
       
        
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

        # left distracter
        if left_on and left_distracter_rate > 1e-3:
            # Change of basis
            mean_interval = 1 / left_distracter_rate
            var_interval = distracter_temporal_std ** 2

            # Change of basis
            gamma_shape = (mean_interval ** 2) / var_interval
            gamma_scale = var_interval / mean_interval

            # Draw
            left_distracter_intervals = np.random.gamma(
                gamma_shape, gamma_scale, 100)
        else:
            left_distracter_intervals = np.array([])

        # right distracter
        if right_on and right_distracter_rate > 1e-3:
            # Change of basis
            mean_interval = 1 / right_distracter_rate
            var_interval = distracter_temporal_std ** 2

            # Change of basis
            gamma_shape = (mean_interval ** 2) / var_interval
            gamma_scale = var_interval / mean_interval

            # Draw
            right_distracter_intervals = np.random.gamma(
                gamma_shape, gamma_scale, 100)
        else:
            right_distracter_intervals = np.array([])               
        
        
        ## Sort all the drawn intervals together
        # Turn into series
        left_target_df = pandas.DataFrame.from_dict({
            'time': np.cumsum(left_target_intervals),
            'side': ['left'] * len(left_target_intervals),
            'sound': ['target'] * len(left_target_intervals),
            })
        right_target_df = pandas.DataFrame.from_dict({
            'time': np.cumsum(right_target_intervals),
            'side': ['right'] * len(right_target_intervals),
            'sound': ['target'] * len(right_target_intervals),
            })
        left_distracter_df = pandas.DataFrame.from_dict({
            'time': np.cumsum(left_distracter_intervals),
            'side': ['left'] * len(left_distracter_intervals),
            'sound': ['distracter'] * len(left_distracter_intervals),
            })
        right_distracter_df = pandas.DataFrame.from_dict({
            'time': np.cumsum(right_distracter_intervals),
            'side': ['right'] * len(right_distracter_intervals),
            'sound': ['distracter'] * len(right_distracter_intervals),
            })
        
        # Concatenate them all together and resort by time
        both_df = pandas.concat([
            left_target_df, right_target_df, 
            left_distracter_df, right_distracter_df,
            ], axis=0).sort_values('time')

        # Calculate the gap between sounds
        both_df['gap'] = both_df['time'].diff().shift(-1)
        
        # Drop the last row which has a null gap
        both_df = both_df.loc[~both_df['gap'].isnull()].copy()

        # Keep only those below the sound cycle length
        both_df = both_df.loc[both_df['time'] < 10].copy()
        
        # Nothing should be null
        assert not both_df.isnull().any().any() 

        # Calculate gap size in chunks
        both_df['gap_chunks'] = (both_df['gap'] *
            autopilot.stim.sound.jackclient.FS / 
            autopilot.stim.sound.jackclient.BLOCKSIZE)
        both_df['gap_chunks'] = both_df['gap_chunks'].round().astype(np.int)
        
        # Floor gap_chunks at 1 chunk, the minimal gap size
        # This is to avoid distortion
        both_df.loc[both_df['gap_chunks'] < 1, 'gap_chunks'] = 1
        
        # Log
        self.logger.debug("generated both_df: {}".format(both_df))
        
        # Save
        self.current_audio_times_df = both_df.copy()
        self.current_audio_times_df = self.current_audio_times_df.rename(
            columns={'time': 'relative_time'})

        
        ## Depends on how long both_df is
        # If both_df has a nonzero but short length, results will be weird,
        # because it might just be one noise burst repeating every ten seconds
        # This only happens with low rates ~0.1Hz
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
                elif bdrow.side == 'left' and bdrow.sound == 'distracter':
                    for frame in self.left_distracter_stim.chunks:
                        self.sound_block.append(frame)                         
                elif bdrow.side == 'right' and bdrow.sound == 'target':
                    for frame in self.right_target_stim.chunks:
                        self.sound_block.append(frame) 
                elif bdrow.side == 'right' and bdrow.sound == 'distracter':
                    for frame in self.right_distracter_stim.chunks:
                        self.sound_block.append(frame)       
                else:
                    raise ValueError(
                        "unrecognized side and sound: {} {}".format(
                        bdrow.side, bdrow.sound))
                
                # Append the gap
                append_gap(bdrow.gap_chunks)
        
        
        ## Cycle so it can repeat forever
        self.sound_cycle = itertools.cycle(self.sound_block)  


# Noise Class from PAFT_child
class Noise(BASE_CLASS):
    """Generates a white noise burst with specified parameters
    
    The `type` attribute is always "Noise".
    """
    # These are the parameters of the sound
    # These can be set in the GUI when generating a Nafc step in a Protocol
    PARAMS = ['duration', 'amplitude', 'highpass', 'lowpass', 'channel']
    
    # The type of the sound
    type='Noise'
    
    def __init__(self, duration, amplitude=0.01, channel=None, 
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
                Path to where a pandas.Series can be loaded containing attenuation
            **kwargs: extraneous parameters that might come along with instantiating us
        """
        # This calls the base class, which sets server-specific parameters
        # like sampling rate
        super(Noise, self).__init__(**kwargs)
        
        # Set the parameters specific to Noise
        self.duration = float(duration)
        self.amplitude = float(amplitude)
        if highpass is None:
            self.highpass = None
        else:
            self.highpass = float(highpass)
        if lowpass is None:
            self.lowpass = None
        else:
            self.lowpass = float(lowpass)
        try:
            self.channel = int(channel)
        except TypeError:
            self.channel = channel
        
        # Save attenuation
        if attenuation_file is not None:
            self.attenuation = pandas.read_table(
                attenuation_file, sep=',').set_index('freq')['atten']
        else:
            self.attenuation = None        
        
        # Currently only mono or stereo sound is supported
        if self.channel not in [None, 0, 1]:
            raise ValueError(
                "audio channel must be 0, 1, or None, not {}".format(
                self.channel))

        # Initialize the sound itself
        self.init_sound()

    def init_sound(self):
        """Defines `self.table`, the waveform that is played. 
        
        The way this is generated depends on `self.server_type`, because
        parameters like the sampling rate cannot be known otherwise.
        
        The sound is generated and then it is "chunked" (zero-padded and
        divided into chunks). Finally `self.initialized` is set True.
        """
        # Depends on the server_type
        if self.server_type == 'pyo':
            noiser = pyo.Noise(mul=self.amplitude)
            self.table = self.table_wrap(noiser)
        
        elif self.server_type in ('jack', 'dummy'):
            # This calculates the number of samples, using the specified 
            # duration and the sampling rate from the server, and stores it
            # as `self.nsamples`.
            self.get_nsamples()
            
            # Generate the table by sampling from a uniform distribution
            # The shape of the table depends on `self.channel`
            if self.channel is None:
                # The table will be 1-dimensional for mono sound
                self.table = np.random.uniform(-1, 1, self.nsamples)
                
                if self.highpass is not None:
                    bhi, ahi = scipy.signal.butter(
                        2, self.highpass / (self.fs / 2), 'high')
                    self.table = scipy.signal.filtfilt(bhi, ahi, self.table)
                
                if self.lowpass is not None:
                    blo, alo = scipy.signal.butter(
                        2, self.lowpass / (self.fs / 2), 'low')
                    self.table = scipy.signal.filtfilt(blo, alo, self.table)

            else:
                # The table will be 2-dimensional for stereo sound
                # Each channel is a column
                # Only the specified channel contains data and the other is zero
                data = np.random.uniform(-1, 1, self.nsamples)
                
                if self.highpass is not None:
                    bhi, ahi = scipy.signal.butter(
                        2, self.highpass / (self.fs / 2), 'high')
                    data = scipy.signal.filtfilt(bhi, ahi, data)
                
                if self.lowpass is not None:
                    blo, alo = scipy.signal.butter(
                        2, self.lowpass / (self.fs / 2), 'low')
                    data = scipy.signal.filtfilt(blo, alo, data)
                
                self.table = np.zeros((self.nsamples, 2))
                assert self.channel in [0, 1]
                self.table[:, self.channel] = data
            
            # Scale by the amplitude
            self.table = self.table * self.amplitude
            
            # Convert to float32
            self.table = self.table.astype(np.float32)
            
            # Apply attenuation
            if self.attenuation is not None:
                # Temporary hack
                # To make the attenuated sounds roughly match the original
                # sounds in loudness, multiply table by np.sqrt(10) (10 dB)
                # Better solution is to encode this into attenuation profile,
                # or a separate "gain" parameter
                self.table = self.table * np.sqrt(10)
                
                if self.table.ndim == 1:
                    self.table = apply_attenuation(
                        self.table, self.attenuation, self.fs)
                elif self.table.ndim == 2:
                    for n_column in range(self.table.shape[1]):
                        self.table[:, n_column] = apply_attenuation(
                            self.table[:, n_column], self.attenuation, self.fs)
                else:
                    raise ValueError("self.table must be 1d or 2d")
            
            # Chunk the sound
            if self.server_type == 'jack':
                self.chunk()

        # Flag as initialized
        self.initialized = True

    def iter_continuous(self) -> typing.Generator:
        """
        Continuously yield frames of audio. If this method is not overridden,
        just wraps :attr:`.table` in a :class:`itertools.cycle` object and
        returns from it.

        Returns:
            np.ndarray: A single frame of audio
        """
        # preallocate
        if self.channel is None:
            table = np.empty(self.blocksize, dtype=np.float32)
        else:
            table = np.empty((self.blocksize, 2), dtype=np.float32)

        rng = np.random.default_rng()


        while True:
            if self.channel is None:
                table[:] = rng.uniform(-self.amplitude, self.amplitude, self.blocksize)
            else:
                table[:,self.channel] = rng.uniform(-self.amplitude, self.amplitude, self.blocksize)

            yield table
