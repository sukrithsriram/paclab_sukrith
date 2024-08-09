## TODO: 
# Document what each class in this script does.
# Separate the classes that are for running the GUI from the classes
# that interact with the Pi and run the task 
# Put the ones that run the GUI in another script and import them here


## IMPORTING LIBRARIES

import sys
import zmq
import numpy as np
import time
import os
import math
import pyqtgraph as pg
import random
import csv
import json
import argparse
from datetime import datetime
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QMenu, QAction, QComboBox, QGroupBox, QMessageBox, QLabel, QGraphicsEllipseItem, QListWidget, QListWidgetItem, QGraphicsTextItem, QGraphicsScene, QGraphicsView, QWidget, QVBoxLayout, QPushButton, QApplication, QHBoxLayout, QLineEdit, QListWidget, QFileDialog, QDialog, QLabel, QDialogButtonBox, QTreeWidget, QTreeWidgetItem
from PyQt5.QtCore import QPointF, QTimer, QTime, pyqtSignal, QObject, QThread, pyqtSlot,  QMetaObject, Qt
from PyQt5.QtGui import QFont, QColor
from pyqttoast import Toast, ToastPreset

## SELECTING BOX 
"""
Multiple GUI windows can be opened at once by using by inputting the name of the box in the command line (eg: python3 gui.py box1)
box1 - Testing on seaturtle computer 
box2-5 - Behavior Boxes 
"""
# Set up argument parsing to select box
parser = argparse.ArgumentParser(description="Load parameters for a specific box.")
parser.add_argument('json_filename', type=str, help="The name of the JSON file (without 'configs/' and '.json')")
args = parser.parse_args()

# Constructing the full path to the config file
param_directory = f"gui/configs/{args.json_filename}.json"

# Load the parameters from the specified JSON file
with open(param_directory, "r") as p:
    params = json.load(p)

# Fetching all the ports to use for the trials (This was implemented becuase I had to test on less than 8 nosepokes)    
active_nosepokes = [int(i) for i in params['active_nosepokes']]

# Variable to store the name of the current task and the timestamp at which the session was started (mainly used for saving)
current_task = None
current_time = None

## SAVING TERMINAL INFO
"""
This function was implemented to save logs for test sessions or sessions that weren't saved due to crashes. 
It logs all the terminal information being printed on the GUI side of the code and saves it to a txt file. 
This implementation hasn't been done for the terminal information on the pi side. (currently does not use the logging library - maybe can be included later)
"""
# Function to print to terminal and store log files as txt
def print_out(*args, **kwargs):
    global current_task, current_time
    
    # Naming the txt file according to the current task and time and saving it to a log folder 
    output_filename = params['save_directory'] + f"/terminal_logs/{current_task}_{current_time}.txt"
    
    # Joining the arguments into a single string
    statement = " ".join(map(str, args))
    
    # Print the statement to the console
    print(statement, **kwargs)
    
    # Write the statement to the file
    with open(output_filename, 'a') as outputFile:
            outputFile.write(statement + "\n")

## VISUAL REPRESENTATION OF PORTS

"""
Creating a class for the individual ports on the Raspberry Pi 
"""
class PiSignal(QGraphicsEllipseItem):
    def __init__(self, index, total_ports):
        super(PiSignal, self).__init__(0, 0, 38, 38) # Setting the diameters of the ellipse while initializing the class
        self.index = index # The location at which the different ports will be arranged (range from 0-7)
        self.total_ports = total_ports # Creating a variable for the total number of ports
        
        # Defining list and order of the ports
        if 0 <= self.index < len(params['ports']): # Ensure index is within specified number of ports listed in params 
            port_data = params['ports'][self.index]
            label_text = port_data['label'] # Assigning a label to each port index in params 
        
        self.label = QGraphicsTextItem(f"Port-{port_data['label']}", self) # Setting the label for each port on the GUI
        font = QFont()
        font.setPointSize(8)  # Set the font size here (10 in this example)
        self.label.setFont(font)
        self.label.setPos(19 - self.label.boundingRect().width() / 2, 19 - self.label.boundingRect().height() / 2) # Positioning the labels within the ellipse
        self.setPos(self.calculate_position()) # Positioning the individual ports
        self.setBrush(QColor("gray")) # Setting the initial color of the ports to gray

    def calculate_position(self):  
        """
        Function to calculate the position of the ports and arrange them in a circle
        """
        angle = 2 * math.pi * self.index / self.total_ports 
        radius = 62
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        return QPointF(200 + x, 200 + y) # Arranging the Pi signals in a circle based on x and y coordinates calculated using the radius

    def set_color(self, color):
        """
        Function used to change the color from the individual ports during a a trial according to the pokes. 
        The logic for when to change to color of the individual ports is mostly present in the worker class.
        QColors currently used for ports: gray (default), green(reward port), red(incorrect port), blue(used previously but not currently)
        """
        if color == "green":
            self.setBrush(QColor("green"))
        elif color == "blue":
            self.setBrush(QColor("blue"))
        elif color == "red":
            self.setBrush(QColor("red"))
        elif color == "gray":
            self.setBrush(QColor("gray"))
        else:
            print_out("Invalid color:", color)

## HANDLING LOGIC FOR OTHER GUI CLASSES (TO LOWER LOAD)

class Worker(QObject):
    """
    The Worker class primarily communicates with the PiSignal and PiWidget classes. 
    It handles the logic of starting sessions, stopping sessions, choosing reward ports
    sending messages to the pis (about reward ports), sending acknowledgements for completed trials (needs to be changed).
    The Worker class also handles tracking information regarding each poke / trial and saving them to a csv file.
    """
    # Signal emitted when a poke occurs (This is used to communicate with other classes that strictly handle defining GUI elements)
    pokedportsignal = pyqtSignal(int, str)

    def __init__(self, pi_widget):
        super().__init__()
        self.initial_time = None
        
        """
        Setting up a ZMQ socket to send and receive information about poked ports 
        (the DEALER socket on the Pi initiates the connection and then the ROUTER manages the message queue from different dealers and sends acknowledgements)
        """
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.bind("tcp://*" + params['worker_port'])  # Making it bind to the port used for sending poke related information 
        
        """
        Making lists to store the trial parameters for each poke.
        We append the parameters at each poke to these lists so that we can write them to a CSV
        """
        self.amplitudes = []
        self.target_rates = []
        self.target_temporal_log_stds = []
        self.center_freqs = []

        # Tracking the parameters that need to be saved at every poke
        self.current_amplitude = 0.0
        self.current_target_rate = 0.0
        self.current_target_temporal_log_std = 0.0
        self.current_center_freq = 0.0
        self.current_bandwidth = 0.0
        self.current_poke = 0
        self.current_completed_trials = 0
        self.current_correct_trials = 0
        self.current_fraction_correct = 0
        
        # Initialize variables to track information used to control the logic of the task 
        self.last_pi_received = None # Stores the identity of the pi that sent the most recent message
        self.prev_choice = None # Used while randomly selecting ports to make sure that the same port is not rewarded twice
        self.timer = None # Used to create a QTimer when the sequence is started 
        self.current_task = None # Used to keep track of the current task (used in naming the CSV file)
        self.ports = None

        
        # Connecting the Worker Class to PiWidget elements 
        self.pi_widget = pi_widget
        self.total_ports = self.pi_widget.total_ports 
        self.Pi_signals = self.pi_widget.Pi_signals
        self.poked_port_numbers = self.pi_widget.poked_port_numbers 

        """
        Variables used to store the functions to map the labels of ports present in the params file of a particular to indicies and vice versa
        It is essentially to make sure that the labels of the ports are at the right positions on the GUI widget
        """
        self.label_to_index = None # Used to relate a label of a port to the index of that particular port in the GUI
        self.index_to_label = None # Used this to properly update the port according to its label
        self.index = None
        
        # Variables to keep track of reward related messages 
        self.identities = set() # Set of identities of all pis connected to that instance of ther GUI 
        self.last_poke_timestamp = None  # Variable to store the timestamp of the last poke 
        self.reward_port = None # Keeping track of the current reward port
        self.last_rewarded_port = None # Keeping track of last rewarded port

        # Initializing variables and lists to store trial information 
        self.trials = 0 # Number of pokes per trial (needs to be renamed) 
        self.timestamps = []
        self.pokes = []
        self.completed_trials = []
        self.correct_trials = []
        self.fc = []
        self.reward_ports = []
        
        """
        These variables were used in my calculation for RCP, I don't think I've implemented it correctly so these might need to be removed or changed
        """
        self.unique_ports_visited = []  # List to store unique ports visited in each trial
        self.unique_ports_colors = {}  # Dictionary to store the outcome for each unique port
        self.average_unique_ports = 0  # Variable to store the average number of unique ports visited
    
    # Method that contains logic to be executed when a new session is started
    @pyqtSlot()
    def start_sequence(self):
        """
        First we store the initial timestamp where the session was started in a variable.
        This used with the poketimes sent by the pi to calculate the time at which the pokes occured
        """
        self.initial_time = datetime.now() 
        print(self.initial_time)
        
        # Resetting sequences when a new session is started 
        self.timestamps = []
        self.reward_ports = []
        
        # Randomly choosing the initial reward port
        self.reward_port = self.choose()
        reward_message = f"Reward Port: {self.reward_port}"
        print_out(reward_message)
        
        # Sending the current reward port to all connected pis
        for identity in self.identities:
            self.socket.send_multipart([identity, bytes(reward_message, 'utf-8')])
        
        # Creating a dictionary that takes the label of each port and matches it to the index on the GUI (used for reordering)
        self.ports = params['ports']
        self.label_to_index = {port['label']: port['index'] for port in self.ports} # Refer to when variables were initialized above
        self.index_to_label = {port['index']: port['label'] for port in self.ports}
        self.index = self.label_to_index.get(str(self.reward_port)) # Setting an index of remapped ports (so that colors can be changed accordign to label)
        
        # Set the color of the initial reward port to green
        self.Pi_signals[self.index].set_color("green")

        # Start the timer loop
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_Pi)
        self.timer.start(10)

    # Method that contains logic to be executed when a session is completed
    @pyqtSlot()
    def stop_sequence(self):
        if self.timer is not None:
            self.timer.stop() # Stops the timer for the session 
            self.timer.timeout.disconnect(self.update_Pi) # Blocking out communication with the Pis till a new session is started 
        
        # Clearing recorded data for the completed session and resetting necessary variables
        self.initial_time = None
        self.timestamps.clear()
        self.reward_ports.clear()
        self.poked_port_numbers.clear()
        self.amplitudes.clear()
        self.target_rates.clear()
        self.target_temporal_log_stds.clear()
        self.center_freqs.clear()
        self.unique_ports_visited.clear()
        self.identities.clear()
        self.last_poke_timestamp = None
        self.reward_port = None
        self.trials = 0
        self.average_unique_ports = 0
    
    # Method to update unique ports visited (used to calculate RCP on GUI)
    def update_unique_ports(self):
        # Calculate unique ports visited in the current trial
        unique_ports = set(self.poked_port_numbers)
        self.unique_ports_visited.append(len(unique_ports))
 
    # Method to calculate the average number of unique ports visited (used to calculate RCP on GUI)
    def calculate_average_unique_ports(self):
        # Calculate the average number of unique ports visited per trial
        if self.unique_ports_visited:
            self.average_unique_ports = sum(self.unique_ports_visited) / len(self.unique_ports_visited)
            
    # Method to randomly choose next port to reward
    def choose(self):
        ports = active_nosepokes # Getting the list of choices to choose from  
        poss_choices = [choice for choice in ports if choice != self.prev_choice] # Setting up a new set of possible choices after omitting the previously rewarded port
        new_choice =  random.choice(poss_choices) # Randomly choosing within the new set of possible choices
        self.prev_choice = new_choice # Updating the previous choice that was made so the next choice can omit it 
        return new_choice
    
    """
    ** This is the main method of this class that controls most of the logic for the GUI **
    Method to handle the updating Pis (sending and receiving poke related information and executing logic)
    """
    @pyqtSlot()
    def update_Pi(self):
        
        # Updating time related information 
        current_time = datetime.now() # Used to name the file 
        elapsed_time = current_time - self.initial_time # Used to display elapsed time in the Pi Widget class
        self.last_poke_timestamp = current_time # Update the last poke timestamp whenever a poke  occurs
        
        """
        This is the logic on what to do when the GUI receives messages that aren't pokes
        'rpi': Initial connection to all the pis trying to connect to the GUI (Debug message to see if all Pis are connected)
        'stop': Pauses all updates from the Pi when the session is stopped
        'start': Setting a new reward port whenever a new session is started after the previous one is stopped (might be redundant but works for now)
        'Current Parameters': Sends all the sound parameters for every trial; the values are extracted from a string and then appended to lists to be saved in a csv 
        """
        try:
            # Waiting to receive messages from the pis
            identity, message = self.socket.recv_multipart()
            self.identities.add(identity)
            
            # Converting all messages from bytes to strings
            message_str = message.decode('utf-8')
            
            # Message from pi side that initiates the connection 
            if "rpi" in message_str:
                print_out("Connected to Raspberry Pi:", message_str)
            
            # Message to stop updates if the session is stopped
            if message_str.strip().lower() == "stop":
                print_out("Received 'stop' message, aborting update.")
                return
            
            # Sending the initial message to start the loop
            self.socket.send_multipart([identity, bytes(f"Reward Port: {self.reward_port}", 'utf-8')])

            # Starting next session
            if message_str.strip().lower() == "start":
                self.socket.send_multipart([identity, bytes(f"Reward Port: {self.reward_port}", 'utf-8')])
    
            # Keeping track of current parameters for every trial 
            if "Current Parameters" in message_str:
                sound_parameters = message_str
                print_out("Updated:", message_str) 
                
                # Remove the "Current Parameters - " part and strip any whitespace
                param_string = sound_parameters.split("-", 1)[1].strip()
                
                # Extracting parameters from message strings
                params = {}
                for param in param_string.split(','):
                    key, value = param.split(':')
                    params[key.strip()] = value.strip()
                
                # Extract and convert the strings to numeric values
                self.current_amplitude = float(params.get("Amplitude", 0))
                self.current_target_rate = float(params.get("Rate", "0").split()[0])
                self.current_target_temporal_log_std = float(params.get("Irregularity", "0").split()[0])
                self.current_center_freq = float(params.get("Center Frequency", "0").split()[0])
                self.current_bandwidth = float(params.get("Bandwidth", "0"))
                
            else:
                """
                Logic for what to do when a poke is received
                """
                poked_port = int(message_str) # Converting message string to int 
                
                # Check if the poked port is the same as the last rewarded port
                if poked_port == self.last_rewarded_port:
                     # If it is, do nothing and return
                        return

                # For any label in the list of port labels, correlate it to the index of the port in the visual arrangement in the widget  
                if 1 <= poked_port <= self.total_ports:
                    poked_port_index = self.label_to_index.get(message_str)
                    poked_port_icon = self.Pi_signals[poked_port_index]

                    """
                    Choosing colors to represent the outcome of each poke in the context of the trial
                    green: correct trial
                    blue: completed trial
                    red: pokes at all ports that aren't the reward port
                    """                    
                    if poked_port == self.reward_port:
                        color = "green" if self.trials == 0 else "blue"
                        if self.trials > 0:
                            self.trials = 0
                    else:
                        color = "red" 
                        self.trials += 1
                        self.current_poke += 1

                    # Setting the color of the port on the Pi Widget
                    poked_port_icon.set_color(color)
                    
                    # Appending the poked port to a sequence that contains all pokes during a session
                    self.poked_port_numbers.append(poked_port)
                    print_out("Sequence:", self.poked_port_numbers) # Can be commented out to declutter terminal
                    self.last_pi_received = identity

                    # Sending information regarding poke and outcome of poke to Pi Widget
                    self.pokedportsignal.emit(poked_port, color)
                    
                    # Appending the current reward port to save to csv 
                    self.reward_ports.append(self.reward_port)
                    
                    # Used to update RCP calculation
                    self.update_unique_ports()
                    
                    # Updating poke / trial related information depending on the outcome of the poke
                    if color == "green" or color == "blue":
                        self.current_poke += 1 # Updating number of pokes in the session 
                        self.current_completed_trials += 1 # Updating the number of trials in the session 
                        
                        # Sending an acknowledgement to the Pis when the reward port is poked
                        for identity in self.identities:
                            self.socket.send_multipart([identity, bytes(f"Reward Poke Completed: {self.reward_port}", 'utf-8]')])
                        
                        # Storing the completed reward port to make sure the next choice is not at the same port
                        self.last_rewarded_port = self.reward_port 
                        self.reward_port = self.choose() 
                        self.trials = 0 # Resetting the number of pokes that have happened in the trial
                        print_out(f"Reward Port: {self.reward_port}")
                        
                        # Logic for if a correct trial is completed
                        if color == "green":
                            self.current_correct_trials += 1 # Updating count for correct trials
                            self.current_fraction_correct = self.current_correct_trials / self.current_completed_trials

                        # Finding the index in the visual representation depending on the 
                        index = self.index_to_label.get(poked_port_index)
                        
                        # When a new trial is started reset color of all non-reward ports to gray and set new reward port to green
                        for index, Pi in enumerate(self.Pi_signals):
                            if index + 1 == self.reward_port: # This might be a hack that doesnt work for some boxes (needs to be changed)
                                Pi.set_color("green")
                            else:
                                Pi.set_color("gray")

                        # Sending the reward port to all connected Pis after a trial is completed
                        for identity in self.identities:
                            self.socket.send_multipart([identity, bytes(f"Reward Port: {self.reward_port}", 'utf-8')])
                            
                    
                    # Appending all the information at the time of a particular poke to their respective lists
                    self.pokes.append(self.current_poke)
                    self.timestamps.append(elapsed_time)
                    self.amplitudes.append(self.current_amplitude)
                    self.target_rates.append(self.current_target_rate)
                    self.target_temporal_log_stds.append(self.current_target_temporal_log_std)
                    self.center_freqs.append(self.current_center_freq)
                    self.completed_trials.append(self.current_completed_trials)
                    self.correct_trials.append(self.current_correct_trials)
                    self.fc.append(self.current_fraction_correct)
        
        except ValueError:
            pass
            #print_out("Unknown message:", message_str)
            
    
   # Method to save results to a CSV file
    def save_results_to_csv(self):
        global current_task, current_time
        
        # Specifying the directory where you want to save the CSV files
        save_directory = params['save_directory']
        
        # Generating filename based on current_task and current date/time
        filename = f"{current_task}_{current_time}_saved.csv"
        
        # Saving the results to a CSV file
        with open(f"{save_directory}/{filename}", 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            
            # Writing the header row for the CSV file with parameters to be saved as the columns
            writer.writerow(["No. of Pokes", "Poke Timestamp (seconds)", "Port Visited", "Current Reward Port", "No. of Trials", "No. of Correct Trials", "Fraction Correct", "Amplitude", "Rate", "Irregularity", "Center Frequency"])
           
           # Assigning the values at each individual poke to the columns in the CSV file
            for poke, timestamp, poked_port, reward_port, completed_trial, correct_trial, fc, amplitude, target_rate, target_temporal_log_std, center_freq in zip(
                self.pokes, self.timestamps, self.poked_port_numbers, self.reward_ports, self.completed_trials, self.correct_trials, self.fc, self.amplitudes, self.target_rates, self.target_temporal_log_stds, self.center_freqs):
                writer.writerow([poke, timestamp, poked_port, reward_port, completed_trial, correct_trial, fc, amplitude, target_rate, target_temporal_log_std, center_freq])

        print_out(f"Results saved to logs")
    
    # Method to send start message to the pi
    def start_message(self):
        for identity in self.identities:
            self.socket.send_multipart([identity, b"start"])
    
    # Method to send a stop message to the pi
    def stop_message(self):        
        for identity in self.identities:
            self.socket.send_multipart([identity, b"stop"])
        for index, Pi in enumerate(self.Pi_signals):
            Pi.set_color("gray")

## TRIAL INFORMATION DISPLAY / SESSION CONTROL    

# PiWidget Class that represents all ports
class PiWidget(QWidget):
    """
    This class is the main GUI class that displays the ports on the Raspberry Pi and the information related to the trials.
    The primary use of the widget is to keep track of the pokes in the trial (done through the port icons and details box).
    This information is then used to calclate performance metrics like fraction correct and RCP. 
    It also has additional logic to stop and start sessions. 
    """

    # Signals that communicate with the Worker class
    startButtonClicked = pyqtSignal() # Signal that is emitted whenever the start button is pressed (connects to the logic in Worker class)
    updateSignal = pyqtSignal(int, str) # Signal to emit the id and outcome of the current poke

    def __init__(self, main_window, *args, **kwargs):
        super(PiWidget, self).__init__(*args, **kwargs)

        # Creating the GUI widget to display the Pi signals
        self.main_window = main_window
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)

        # Adding individual ports to the widget 
        self.total_ports = 8
        self.Pi_signals = [PiSignal(i, self.total_ports) for i in range(self.total_ports)]
        [self.scene.addItem(Pi) for Pi in self.Pi_signals]
        
        # Setting for bold font
        font = QFont()
        font.setBold(True)
        
        # Creating buttons to control the session (connects to the stop and start logic present in the worker class )
        self.poked_port_numbers = []
        self.start_button = QPushButton("Start Session")
        self.start_button.setStyleSheet("background-color : green; color: white;") # Changing the color of the buttons
        #self.start_button.setFont(font)   
        self.stop_button = QPushButton("Stop Session")
        self.stop_button.setStyleSheet("background-color : red; color: white;") 
        #self.stop_button.setFont(font)   
        self.stop_button.clicked.connect(self.save_results_to_csv)  # Making it so that the results are saved to a csvv when the session is stopped

        # Making a timer to be displayed on the GUI 
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time_elapsed) # Method to calculate and update elapsed time (can be replaced with date time instead of current implementation if needed)
        
        # Setting initial time to zero for all labels
        self.start_time = QTime(0, 0)
        self.poke_time = QTime(0, 0)

        # Variables to keep track of poke outcomes (can be renamed if needed)
        self.red_count = 0
        self.blue_count = 0
        self.green_count = 0

        # Create QVBoxLayout for session details 
        self.details_layout = QVBoxLayout()
        
        # Setting title 
        self.title_label = QLabel("Session Details:", self)
        self.title_label.setFont(font)
        
        # Making labels that constantly update according to the session details
        self.time_label = QLabel("Time Elapsed: 00:00", self)
        self.poke_time_label = QLabel("Time since last poke: 00:00", self)
        self.red_label = QLabel("Number of Pokes: 0", self)
        self.blue_label = QLabel("Number of Trials: 0", self)
        self.green_label = QLabel("Number of Correct Trials: 0", self)
        self.fraction_correct_label = QLabel("Fraction Correct (FC): 0.000", self)
        self.rcp_label = QLabel("Rank of Correct Port (RCP): 0", self)
        
        # Adding these labels to the layout used to contain the session information 
        self.details_layout.addWidget(self.title_label)
        self.details_layout.addWidget(self.time_label)
        self.details_layout.addWidget(self.poke_time_label)
        self.details_layout.addWidget(self.red_label)
        self.details_layout.addWidget(self.blue_label)
        self.details_layout.addWidget(self.green_label)
        self.details_layout.addWidget(self.fraction_correct_label)
        self.details_layout.addWidget(self.rcp_label)

        # Initializing QTimer for tracking time since last poke (resets when poke is detected)
        self.last_poke_timer = QTimer()
        self.last_poke_timer.timeout.connect(self.update_last_poke_time)

        # Creating horizontal layout for start and stop buttons
        start_stop_layout = QHBoxLayout()
        start_stop_layout.addWidget(self.start_button)
        start_stop_layout.addWidget(self.stop_button)

        # Creating a layout where the port window and buttons are arranged vertically
        view_buttons_layout = QVBoxLayout()
        view_buttons_layout.addWidget(self.view)  
        view_buttons_layout.addLayout(start_stop_layout)  

        # Arranging the previous layout horizontally with the session details
        main_layout = QHBoxLayout(self)
        main_layout.addLayout(view_buttons_layout)  
        main_layout.addLayout(self.details_layout)  

        # Set main_layout as the layout for this widget
        self.setLayout(main_layout)

        # Creating an instance of the Worker Class and a QThread to handle the logic in a separate thread from the GUI elements
        self.worker = Worker(self)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)  # Move the worker object to the thread
        self.start_button.clicked.connect(self.start_sequence)  # Connect the start button to the start_sequence function (includes start logic from the worker class)
        self.stop_button.clicked.connect(self.stop_sequence)  # Connect the stop button to the stop_sequence function
        
        # Connect the pokedportsignal from the Worker to slots that call some methods in Pi Widget
        self.worker.pokedportsignal.connect(self.emit_update_signal)  # Connect the pokedportsignal to the emit_update_signal function
        self.worker.pokedportsignal.connect(self.reset_last_poke_time)
        self.worker.pokedportsignal.connect(self.calc_and_update_avg_unique_ports) # Used for RCP calculation (needs to be changed)

    # Function to emit the update signal
    def emit_update_signal(self, poked_port_number, color):
        """
        This method is to communicate with the plotting object to plot the different outcomes of each poke. 
        This is also used to update the labels present in Pi Widget based on the information received over the network by the Worker class
        Some of this logic is already present in the worker class for CSV saving but that was implemented after I implemented the initial version here
        """
        # Emit the updateSignal with the received poked_port_number and color (used for plotting)
        self.updateSignal.emit(poked_port_number, color)
        self.last_poke_timestamp = time.time() # This timer was present before I changed timing implementation. Did not try to change it 

        # Logic for non-reward pokes
        if color == "red":
            self.red_count += 1
            self.red_label.setText(f"Number of Pokes: {(self.red_count + self.green_count + self.blue_count)}") # Updating the number of pokes

        # Logic for completed trials
        if color == "blue":
            self.blue_count += 1
            self.red_label.setText(f"Number of Pokes: {(self.red_count + self.green_count + self.blue_count)}")
            self.blue_label.setText(f"Number of Trials: {(self.blue_count + self.green_count)}") # Updating number of completed trials
            if self.blue_count != 0:
                self.fraction_correct = self.green_count / (self.blue_count + self.green_count) # Updating fraction correct
                self.fraction_correct_label.setText(f"Fraction Correct (FC): {self.fraction_correct:.3f}")

        # Logic for correct trials
        elif color == "green":
            self.green_count += 1
            self.red_label.setText(f"Number of Pokes: {(self.red_count + self.green_count + self.blue_count)}")
            self.blue_label.setText(f"Number of Trials: {(self.blue_count + self.green_count)}")
            self.green_label.setText(f"Number of Correct Trials: {self.green_count}") # Updating number of correct trials 
            if self.blue_count == 0:
                self.fraction_correct_label.setText(f"Fraction Correct (FC): {(self.green_count/self.green_count):.3f}")    
            elif self.blue_count != 0:
                self.fraction_correct = self.green_count / (self.blue_count + self.green_count)
                self.fraction_correct_label.setText(f"Fraction Correct (FC): {self.fraction_correct:.3f}")

    # Method to start the session using the button on the GUI
    def start_sequence(self):
        self.startButtonClicked.emit() 
        self.worker.start_message() # Initiating start logic on the worker class
        
        # Starting the worker thread when the start button is pressed
        self.thread.start()
        print_out("Experiment Started!")
        QMetaObject.invokeMethod(self.worker, "start_sequence", Qt.QueuedConnection) 

        # Sending a message so that the plotting object can start plotting
        self.main_window.plot_window.start_plot()

        # Start the timer
        self.start_time.start()
        self.timer.start(10)  # Update every second               

    # Method of what to do when the session is stopped
    def stop_sequence(self):
        QMetaObject.invokeMethod(self.worker, "stop_sequence", Qt.QueuedConnection)
        print_out("Experiment Stopped!")
        
        # Stopping the plot
        self.main_window.plot_window.stop_plot()
        
        # Reset all labels to intial values (Currently an issue with time since last poke updating after session is stopped. This parameter is not saved on the CSV but is just for display)
        self.time_label.setText("Time Elapsed: 00:00")
        self.poke_time_label.setText("Time since last poke: 00:00")
        self.red_label.setText("Number of Pokes: 0")
        self.blue_label.setText("Number of Trials: 0")
        self.green_label.setText("Number of Correct Trials: 0")
        self.fraction_correct_label.setText("Fraction Correct (FC): 0.000")
        self.rcp_label.setText("Rank of Correct Port (RCP): 0")

        # Resetting poke and trial counts
        self.red_count = 0
        self.blue_count = 0
        self.green_count = 0

        # Stopping the timer for the session 
        self.timer.stop()
        
        # Quitting the thread so a new session can be started
        self.thread.quit()

    # Timer to display the elapsed time in a particular session 
    @pyqtSlot() # decorater function being used here because these methods are being used with slots
    def update_time_elapsed(self):
        elapsed_time = self.start_time.elapsed() / 1000.0  # Convert milliseconds to seconds
        minutes, seconds = divmod(elapsed_time, 60)  # Convert seconds to minutes and seconds
        # Update the QLabel text with the elapsed time in minutes and seconds
        self.time_label.setText(f"Time elapsed: {str(int(minutes)).zfill(2)}:{str(int(seconds)).zfill(2)}")
           
    # Method that stops and then starts the timer everytime a poke is detected 
    @pyqtSlot()
    def reset_last_poke_time(self):
        # Stopping the timer whenever a poke is detected 
        self.last_poke_timer.stop()

        # Start the timer again
        self.last_poke_timer.start(1000)  # Setting update interval to 1000 milliseconds (1 second)
        
    # RCP related function to calculate the number of unique ports visited in a trial and calculate average (currently incorrect)
    @pyqtSlot()
    def calc_and_update_avg_unique_ports(self):
        self.worker.calculate_average_unique_ports()
        average_unique_ports = self.worker.average_unique_ports
        self.rcp_label.setText(f"Rank of Correct Port: {average_unique_ports:.2f}")
    
    # Method to keep track of the time elapsed between pokes (not sure why I made this a separate method)
    @pyqtSlot()
    def update_last_poke_time(self):
        # Calculate the elapsed time since the last poke
        current_time = time.time()
        elapsed_time = current_time - self.last_poke_timestamp

        # Constantly update the QLabel text with the time since the last poke
        minutes, seconds = divmod(elapsed_time, 60)  # Convert seconds to minutes and seconds
        self.poke_time_label.setText(f"Time since last poke: {str(int(minutes)).zfill(2)}:{str(int(seconds)).zfill(2)}")

    # Method to save results by calling the worker method 
    def save_results_to_csv(self):
        self.worker.stop_message()
        self.worker.save_results_to_csv()  # Calling worker method to save results
        toast = Toast(self) # Initializing a toast message
        toast.setDuration(5000)  # Hide after 5 seconds
        toast.setTitle('Results Saved') # Printing acknowledgement in terminal
        toast.setText('Log saved to /home/mouse/dev/paclab_sukrith/logs') # Setting text for the toast message
        toast.applyPreset(ToastPreset.SUCCESS)  # Apply style preset
        toast.show()

## PLOTTING 

# Widget that contains a plot that is continuously depending on the ports that are poked
class PlotWindow(QWidget):
    """
    This class defines a pyqtgraph plot that updates in real-time based on the pokes received by Pi Widget
    It is connected to PiWidget but updates in accordance to updates received by worker since PiWidget uses its methods
    It communicates using the signals updateSignal and startbuttonClicked 
    """
    def __init__(self, pi_widget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_active = False  # Flag to check if the Start Button is pressed
        self.start_time = None # Initializing the start time 
        self.timer = QTimer(self)  # Create a QTimer object
        self.timer.timeout.connect(self.update_plot)  # Connecting the timer to a method used to continuously update the plot
        
        # Creating a QTimer for updating the moving time bar
        self.time_bar_timer = QTimer(self)
        self.time_bar_timer.timeout.connect(self.update_time_bar) # Connecting it to the method used to update the time bar

        # Entering the plot parameters and titles
        self.plot_graph = pg.PlotWidget() # Initializing the pyqtgraph widget
        self.start_time = None  # Initializing the varaible that defines the start time 
        self.plot_graph.setXRange(0, 1600)  # Set x-axis range to [0, 1600] which is more or less the duration of the task in seconds (can be changed) (might be better to display in minutes also)
        
        # Setting the layout of the plotting widget 
        self.layout = QVBoxLayout(self) 
        self.layout.addWidget(self.plot_graph)
        self.plot_graph.setBackground("k") # Setting the background of the plot to be black. Use 'w' for white
        self.plot_graph.setTitle("Pokes vs Time", color="white", size="12px") # Setting the title of the plot 
        styles = {"color": "white", "font-size": "11px"} # Setting the font/style for the rest of the text used in the plot
        self.plot_graph.setLabel("left", "Port", **styles) # Setting label for y axis
        self.plot_graph.setLabel("bottom", "Time (s)", **styles) # Setting label for x axis 
        self.plot_graph.addLegend()
        self.plot_graph.showGrid(x=True, y=True) # Adding a grid background to make it easier to see where pokes are in time
        self.plot_graph.setYRange(1, 9) # Setting the range for the Y axis
        self.timestamps = []  # List to store timestamps
        self.signal = []  # List to store pokes 
        
        # Defining the parameters for the sliding timebar 
        self.line_of_current_time_color = 0.5
        self.line_of_current_time = self.plot_graph.plot(x=[0, 0], y=[-1, 8], pen=pg.mkPen(self.line_of_current_time_color))

        # Setting up the plot to be able to start plotting
        self.line = self.plot_graph.plot(
            self.timestamps,
            self.signal,
            pen=None,
            symbol="o", # Included a separate symbol here that shows as a tiny dot under the raster to make it easier to distinguish multiple pokes in sequence
            symbolSize=1,
            symbolBrush="r",
        )

        # List to keep track of all plotted items to make it easier to clear the plot
        self.plotted_items = []

        # Connecting to signals from PiWidget and Worker 
        pi_widget.updateSignal.connect(self.handle_update_signal)
        pi_widget.worker.pokedportsignal.connect(self.plot_poked_port)

    def start_plot(self):
        # Activating the plot window and starting the plot timer
        self.is_active = True # Flag to initiate plotting 
        self.start_time = datetime.now()  # Setting the initial time at which plotting starts 
        self.timer.start(10)  # Start the timer to update every 10 ms 

        # Start the timer for updating the time bar when the plot starts
        self.time_bar_timer.start(50)  # Update every 50 ms

    def stop_plot(self):
        # Deactivating the plot window and stopping the timer
        self.is_active = False # Stopping the plot
        self.timer.stop()
        
        # Stop the timer for updating the time bar when the plot stops
        self.time_bar_timer.stop()
        self.clear_plot() # Using a method to reset the plot to its initial state 

    # Method to reset plot
    def clear_plot(self):
        # Clear the plot information by clearing lists
        self.timestamps.clear()
        self.signal.clear()
        # Resetting the initial plot location to zero
        self.line.setData(x=[], y=[])

        # Clear all items on the plot
        for item in self.plotted_items:
            self.plot_graph.removeItem(item)
        self.plotted_items.clear()

        # Resetting thje timebar to zero 
        self.line_of_current_time.setData(x=[], y=[])

    # Method that controls how the timebar moves according to the timer 
    def update_time_bar(self):
        # Using current time to approximately update timebar based on total seconds 
        if self.start_time is not None:
            current_time = datetime.now()
            approx_time_in_session = (
                current_time - self.start_time).total_seconds()

            # Updating the position of the timebar
            self.line_of_current_time_color = np.mod(
                self.line_of_current_time_color + 0.1, 2)
            self.line_of_current_time.setData(
                x=[approx_time_in_session, approx_time_in_session], y=[-1, 9],
                pen=pg.mkPen(np.abs(self.line_of_current_time_color - 1)),
            )
    
    # Getting information from the other classes and appending it to the lists in this class 
    def handle_update_signal(self, update_value):
        if self.is_active:
            # Append current timestamp and update value to the lists
            self.timestamps.append((datetime.now() - self.start_time).total_seconds())
            self.signal.append(update_value)
            self.update_plot()

    """
    This is the main function used to draw the poke items as rasters on the plot. It is similar to the previous implementation in autopilot
    It appends the items to a list based on the position of the relative time from the start of the session
    Currently it does not used the timestamps sent from the pi to plot these pokes but this could be changed in the future 
    """
    def plot_poked_port(self, poked_port_value, color):
        if self.is_active:
            brush_color = "g" if color == "green" else "r" if color == "red" else "b" # Setting item colors to match the logic present in the worker class
            relative_time = (datetime.now() - self.start_time).total_seconds()  # Convert to seconds to plot according to start time
            
            # Setting the parameters for the individual items being plotted
            item = self.plot_graph.plot(
                [relative_time],
                [poked_port_value],
                pen=None, # No connecting line between these points 
                symbol="arrow_down",  # "o" for dots # Previous implementation used this to display rasters 
                symbolSize=20,  # use 8 or lower if using dots
                symbolBrush=brush_color, # Setting brush color to change dynamically 
                symbolPen=None,
            )
            self.plotted_items.append(item) # Appending items to a list of plotted items

    def update_plot(self):
        # Update plot with timestamps and signals
        self.line.setData(x=self.timestamps, y=self.signal)

## LIST / CONFIG RELATED CLASSES
"""
These are classes that are primarily used to display different tasks in a list that can be edited on the GUI.
There are a lot of different menus and elements involved that's why there are a lot of  individual classes in this section (could have named them better)
Their functions are as follows:
- ConfigurationDetailsDialog: Dialog Box that shows up to display all the parameters for a specific task when right clicking a task (can't be edited)
- PresetTaskDialog: This is a menu that appears when adding a new mouse. It gives you the option to just choose a task from a list and the 
    default parameters will be applied according to the values set in the defaults file (pi/configs/defaults.json)
- ConfigurationDialog: This is an editable window that shows up when right clicking a task and selecting 'Edit Configuration'. The values of the different task parameters can be changed and saved here
- ConfigurationList: The list of saved tasks for the mice. New mice can be added or removed here and can be searched for. It is also responsible for sending task parameters to the pi side using another network socket.
    (Initially wanted Worker class to handle all network related but was not able to implement it properly. Can be changed if needed)
"""

# Displays a Dialog box with all the details of the task when you click View Details after right-clicking
class ConfigurationDetailsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        
        # Setting the title for the window
        self.setWindowTitle("Configuration Details") 

        # Creating labels to display saved configuration parameters in the window
        self.name_label = QLabel(f"Name: {config['name']}")
        self.task_label = QLabel(f"Task: {config['task']}")
        self.amplitude_label = QLabel(f"Amplitude: {config['amplitude_min']} - {config['amplitude_max']}")
        self.rate_label = QLabel(f"Rate: {config['rate_min']} - {config['rate_max']}")
        self.irregularity_label = QLabel(f"Irregularity: {config['irregularity_min']} - {config['irregularity_max']}")
        self.reward_label = QLabel(f"Reward Value: {config['reward_value']}")
        self.freq_label = QLabel(f"Center Frequency: {config['center_freq_min']} - {config['center_freq_max']}")
        self.band_label = QLabel(f"Bandwidth: {config['bandwidth']}")

        # Creating a button used to exit the window 
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.button_box.accepted.connect(self.accept)

        # Arranging all the labels in a vertical layout
        layout = QVBoxLayout()
        layout.addWidget(self.name_label)
        layout.addWidget(self.task_label)
        layout.addWidget(self.amplitude_label)
        layout.addWidget(self.freq_label)
        layout.addWidget(self.band_label)
        layout.addWidget(self.rate_label)
        layout.addWidget(self.irregularity_label)
        layout.addWidget(self.reward_label)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

# Displays the prompt to make a new task based on default parameters (with the option to edit if needed)
class PresetTaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Setting the title for the window
        self.setWindowTitle("Enter Name and Select Task")

        # Setting a vertical layout for all the elements in this window
        self.layout = QVBoxLayout(self)

        # Making an editable section to save the name
        self.name_label = QLabel("Name:")
        self.name_edit = QLineEdit(self)

        # Making a drop-down list of existing task presets to choose from 
        self.task_label = QLabel("Select Task:")
        self.task_combo = QComboBox(self)
        self.task_combo.addItems(["Fixed", "Sweep", "Poketrain", "Distracter", "Audio"])  
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)

        # Adding all the elements in this window to a vertical layout 
        self.layout.addWidget(self.name_label)
        self.layout.addWidget(self.name_edit)
        self.layout.addWidget(self.task_label)
        self.layout.addWidget(self.task_combo)
        self.layout.addWidget(self.ok_button)

    # Method to get the saved name and the selected task type of the mouse
    def get_name_and_task(self):
        return self.name_edit.text(), self.task_combo.currentText()

# Displays an editable dialog box on clicking 'Edit Configuration' to change the parameters for the tasks if needed (after right clicking task) 
class ConfigurationDialog(QDialog):
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        
        # Setting window title 
        self.setWindowTitle("Edit Configuration Details")
        
        # Initializing the format for edited configs to be saved in (if more parameters need to be added later this needs to be changed)
        self.config = config if config else {
            "name": "",
            "task": "",
            "amplitude_min": 0.0,
            "amplitude_max": 0.0,
            "rate_min": 0.0,
            "rate_max": 0.0,
            "irregularity_min": 0.0,
            "irregularity_max": 0.0,
            "center_freq_min": 0.0,
            "center_freq_max": 0.0,
            "bandwidth": 0.0,
            "reward_value": 0.0
        }
        
        self.init_ui()

    def init_ui(self):
        
        # Setting a vertical layout for all elements in this menu
        layout = QVBoxLayout(self)

        # Section to edit name 
        self.name_label = QLabel("Name:")
        self.name_edit = QLineEdit(self.config.get("name", ""))
        
        """
        Currently the main format tasks are saved in are for the sweep task. The hack to making the logic work for fixed is to make both the min and max values the same
        For poketrain, these values are set to a very small number so there is no sound playing at all
        """

        # Task remains fixed (cannot be edited currently)
        self.task_label = QLabel(f"Task: {self.config.get('task', '')}")

        # Section to edit the range of amplitudes 
        self.amplitude_label = QLabel("Amplitude:")
        amplitude_layout = QHBoxLayout()
        self.amplitude_min_label = QLabel("Min:")
        self.amplitude_min_edit = QLineEdit(str(self.config.get("amplitude_min", "")))
        self.amplitude_max_label = QLabel("Max:")
        self.amplitude_max_edit = QLineEdit(str(self.config.get("amplitude_max", "")))
        amplitude_layout.addWidget(self.amplitude_min_label)
        amplitude_layout.addWidget(self.amplitude_min_edit)
        amplitude_layout.addWidget(self.amplitude_max_label)
        amplitude_layout.addWidget(self.amplitude_max_edit)

        # Section to edit the range of playing rate 
        self.rate_label = QLabel("Rate:")
        rate_layout = QHBoxLayout()
        self.rate_min_label = QLabel("Min:")
        self.rate_min_edit = QLineEdit(str(self.config.get("rate_min", "")))
        self.rate_max_label = QLabel("Max:")
        self.rate_max_edit = QLineEdit(str(self.config.get("rate_max", "")))
        rate_layout.addWidget(self.rate_min_label)
        rate_layout.addWidget(self.rate_min_edit)
        rate_layout.addWidget(self.rate_max_label)
        rate_layout.addWidget(self.rate_max_edit)

        # Section to edit irregularity
        self.irregularity_label = QLabel("Irregularity:")
        irregularity_layout = QHBoxLayout()
        self.irregularity_min_label = QLabel("Min:")
        self.irregularity_min_edit = QLineEdit(str(self.config.get("irregularity_min", "")))
        self.irregularity_max_label = QLabel("Max:")
        self.irregularity_max_edit = QLineEdit(str(self.config.get("irregularity_max", "")))
        irregularity_layout.addWidget(self.irregularity_min_label)
        irregularity_layout.addWidget(self.irregularity_min_edit)
        irregularity_layout.addWidget(self.irregularity_max_label)
        irregularity_layout.addWidget(self.irregularity_max_edit)
        
        # Section to edit center frequency of the filtered white noise
        self.freq_label = QLabel("Center Frequency:")
        freq_layout = QHBoxLayout()
        self.freq_min_label = QLabel("Min:")
        self.freq_min_edit = QLineEdit(str(self.config.get("center_freq_min", "")))
        self.freq_max_label = QLabel("Max:")
        self.freq_max_edit = QLineEdit(str(self.config.get("center_freq_max", "")))
        freq_layout.addWidget(self.freq_min_label)
        freq_layout.addWidget(self.freq_min_edit)
        freq_layout.addWidget(self.freq_max_label)
        freq_layout.addWidget(self.freq_max_edit)
        
        # Section to edit bandwidth
        self.band_label = QLabel("Bandwidth:")
        self.band_edit = QLineEdit(str(self.config.get("bandwidth", "")))
        
        # Section to edit reward duration 
        self.reward_label = QLabel("Reward Value:")
        self.reward_edit = QLineEdit(str(self.config.get("reward_value", "")))

        # Create button box with OK and Cancel buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # Arrange widgets in a vertical layout
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_edit)
        layout.addWidget(self.task_label)
        layout.addWidget(self.amplitude_label)
        layout.addLayout(amplitude_layout)
        layout.addWidget(self.rate_label)
        layout.addLayout(rate_layout)
        layout.addWidget(self.irregularity_label)
        layout.addLayout(irregularity_layout)
        layout.addWidget(self.freq_label)
        layout.addLayout(freq_layout)
        layout.addWidget(self.band_label)
        layout.addWidget(self.band_edit)
        layout.addWidget(self.reward_label)
        layout.addWidget(self.reward_edit)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

        # Show/hide widgets based on the task type 
        self.update_widgets_based_on_task()

    def update_widgets_based_on_task(self):
        """
        This method makes it so that the range is hidden for when the task is Fixed. 
        Since Fixed doesnt need a min or max range, we remove extra editable boxes and ranges.
        This method also sets the min and max values to be the same 
        (This can be done for poketrain too)
        """
        task = self.config.get("task", "")

        if task.lower() == "fixed":
            # For "Fixed" task, hide max edit fields and labels
            self.amplitude_min_label.hide()
            self.amplitude_max_label.hide()
            self.amplitude_max_edit.hide()
            self.rate_min_label.hide()
            self.rate_max_label.hide()
            self.rate_max_edit.hide()
            self.irregularity_min_label.hide()
            self.irregularity_max_label.hide()
            self.irregularity_max_edit.hide()
            self.freq_min_label.hide()
            self.freq_max_label.hide()
            self.freq_max_edit.hide()

            # Connect min edit fields to update max fields such that their value is the same
            self.amplitude_min_edit.textChanged.connect(self.update_amplitude_max)
            self.rate_min_edit.textChanged.connect(self.update_rate_max)
            self.irregularity_min_edit.textChanged.connect(self.update_irregularity_max)
            self.freq_min_edit.textChanged.connect(self.update_freq_max)


        else:
            # For other tasks, show all min and max edit fields
            pass

    # Methods used to match the min and max parameter value
    def update_amplitude_max(self):
        value = self.amplitude_min_edit.text()
        self.amplitude_max_edit.setText(value)

    def update_rate_max(self):
        value = self.rate_min_edit.text()
        self.rate_max_edit.setText(value)

    def update_irregularity_max(self):
        value = self.irregularity_min_edit.text()
        self.irregularity_max_edit.setText(value)

    def update_freq_max(self):
        value = self.freq_min_edit.text()
        self.freq_max_edit.setText(value)
    
    def get_configuration(self):
        """
        Method to save all the updated values of the task / mouse. 
        It grabs the text entered in the boxes and formats it according to the format we sent earlier.
        It overwrites the current json file used for the task 
        """
        
        # Updating the name of the mouse and grabbing the task associated with it 
        updated_name = self.name_edit.text()
        task = self.config.get("task", "")

        # Grabbing all the values from the text boxes and overwriting the existing values
        try:
            amplitude_min = float(self.amplitude_min_edit.text())
            amplitude_max = float(self.amplitude_max_edit.text())
            rate_min = float(self.rate_min_edit.text())
            rate_max = float(self.rate_max_edit.text())
            irregularity_min = float(self.irregularity_min_edit.text())
            irregularity_max = float(self.irregularity_max_edit.text())
            center_freq_min = float(self.freq_min_edit.text())
            center_freq_max = float(self.freq_max_edit.text())
            bandwidth = float(self.band_edit.text())
            reward_value = float(self.reward_edit.text())
            
        except ValueError:
            # Handle invalid input
            return None

        # Updating the format to be used while saving these values to the json file
        updated_config = {
            "name": updated_name,
            "task": task,
            "amplitude_min": amplitude_min,
            "amplitude_max": amplitude_max,
            "rate_min": rate_min,
            "rate_max": rate_max,
            "irregularity_min": irregularity_min,
            "irregularity_max": irregularity_max,
            "center_freq_min": center_freq_min,
            "center_freq_max": center_freq_max,
            "bandwidth": bandwidth,
            "reward_value": reward_value
        }

        return updated_config

# List of mice that have been saved under certain tasks. It is used to send task parameters to the Pi
class ConfigurationList(QWidget):
    send_config_signal = pyqtSignal(dict) # Currently unused. I think I put this here while trying to make the Worker send the configs instead but that didnt work
    
    def __init__(self):
        super().__init__()
        
        # Initializing variables to store current task
        self.configurations = []
        self.current_config = None
        self.current_task = None

        # Loading default parameters for tasks and also the list of tasks from the default directory
        self.default_parameters = self.load_default_parameters()
        self.load_default()  # Call the method to load configurations from a default directory during initialization

        self.init_ui()

        # Making a ZMQ socket strictly to send task params to pi
        self.context = zmq.Context()
        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.bind("tcp://*" + params['config_port'])  # Binding to the port assigned for publishing params 

    def init_ui(self):
        # Making a cascasing list of tasks that mice are categorized under
        self.config_tree = QTreeWidget()
        self.config_tree.setHeaderLabels(["Tasks"])
        
        # Making a search box used to search for mice
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search for a mouse...")
        
        # Buttons to add / remove mice
        self.add_button = QPushButton('Add Mouse')
        self.remove_button = QPushButton('Remove Mouse')
        
        # Label to display the currently selected mouse 
        self.selected_config_label = QLabel()

        # Making horizontal layout for the buttons 
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)

        # Making a vertical layout for the entire widget
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.selected_config_label)
        main_layout.addWidget(self.search_box)
        main_layout.addWidget(self.config_tree)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

        # Assigning methods to be executed when the relevant buttons are clicked 
        self.add_button.clicked.connect(self.add_configuration)
        self.remove_button.clicked.connect(self.remove_configuration)
        
        # Setting title for the window
        self.setWindowTitle('Configuration List')
        
        # Displaying the widget
        self.show()

        # Enable custom context menu (that appears when right clicking)
        self.config_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.config_tree.customContextMenuRequested.connect(self.show_context_menu)
        
        # Executing a method to filter configs when the text in the search box is changed 
        self.search_box.textChanged.connect(self.filter_configurations)
        
    # Executes a method to display only the configs that contain the same string as it and update the whole list dynamically
    def filter_configurations(self, text):
        # Logic to remove mice that do not match the string 
        if not text:
            self.update_config_list()
            return
        
        # Displaying the list of configs that contain the same characters as the text in the search box
        filtered_configs = [] # Empty list to add matching configs to
        for config in self.configurations:
            if text.lower() in config["name"].lower():
                filtered_configs.append(config) # Appending matching configs to a list 

        # Updating the entire list of configs
        self.update_config_list(filtered_configs)

    # Warning to notify user that no config is selected when starting session
    def on_start_button_clicked(self):
        if self.current_config is None:
            QMessageBox.warning(self, "Warning", "Please select a mouse before starting the experiment.")
    
    # Loading default task parameters from json file when needed
    def load_default_parameters(self):
        with open(params['pi_defaults'], 'r') as file:
            return json.load(file)

    # Method to add a new mouse
    def add_configuration(self):
        
        # Displaying the preset menu to name the mouse
        preset_task_dialog = PresetTaskDialog(self)
        if preset_task_dialog.exec_() == QDialog.Accepted:
            name, task = preset_task_dialog.get_name_and_task()
            
            # Get the default parameters for the selected task
            if task in self.default_parameters:
                default_params = self.default_parameters[task]
            else:
                default_params = {
                    "amplitude_min": 0.0,
                    "amplitude_max": 0.0,
                    "rate_min": 0.0,
                    "rate_max": 0.0,
                    "irregularity_min": 0.0,
                    "irregularity_max": 0.0,
                    "center_freq_min": 0.0,
                    "center_freq_max": 0.0,
                    "bandwidth": 0.0,
                    "reward_value": 0.0
                }

            # Instantiate ConfigurationDialog properly (for editing it later)
            dialog = ConfigurationDialog(self, {
                "name": name,
                "task": task,
                **default_params
            })
            
            # Once the mouse is saved, update the config list with the new mouse
            if dialog.exec_() == QDialog.Accepted:
                new_config = dialog.get_configuration()
                self.configurations.append(new_config)
                self.update_config_list()

                # Automatically save a json file of the configuration according the mouse's name 
                config_name = new_config["name"]
                file_path = os.path.join(params['task_configs'], f"{config_name}.json")
                with open(file_path, 'w') as file:
                    json.dump(new_config, file, indent=4)

    # Method to remove mice 
    def remove_configuration(self):
        # Selecting which mouse to remove 
        selected_item = self.config_tree.currentItem()

        # Removing the mouse from the list of configs to display
        if selected_item and selected_item.parent():
            selected_config = selected_item.data(0, Qt.UserRole)
            self.configurations.remove(selected_config)
            self.update_config_list()

            # Get the filename of the selected mouse
            config_name = selected_config["name"] # Make sure filename is the same as name in the json
            
            # Constructing the full file path with the name
            file_path = os.path.join(params['task_configs'], f"{config_name}.json")

            # Checking if the file exists and deleting it
            if os.path.exists(file_path):
                os.remove(file_path)

    # This function is an extra functionality to load configs from a folder apart from the default location in directory if needed
    def load_configurations(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Configuration Folder")
        if folder:
            self.configurations = self.import_configs_from_folder(folder)
            self.update_config_list()

    # This is a function that loads all the saved task from the default directory where mice are saved
    def load_default(self):
        default_directory = os.path.abspath(params['task_configs'])
        if os.path.isdir(default_directory):
            self.configurations = self.import_configs_from_folder(default_directory)
            self.update_config_list()

    # Method used to load all the configs from a specific folder 
    def import_configs_from_folder(self, folder):
        configurations = [] # list of configs
        for filename in os.listdir(folder): 
            if filename.endswith(".json"): # Looking at all json files in specified folder
                file_path = os.path.join(folder, filename) 
                with open(file_path, 'r') as file:
                    config = json.load(file) # Loading all json files 
                    configurations.append(config) # Appending to list of configuration s
        return configurations

    # Method used to update cascading lists whenever a change is made (adding/removing/update)
    def update_config_list(self, configs=None):
        self.config_tree.clear() # Clearing old list of mice
        categories = {}

        # Adding all configs
        if configs is None:
            configs = self.configurations

        # Categorizing mice based on their different tasks (name of task is extracted from json)
        for config in configs:
            category = config.get("task", "Uncategorized") # Making a category for config files without task (unused now)
            if category not in categories:
                category_item = QTreeWidgetItem([category])
                self.config_tree.addTopLevelItem(category_item)
                categories[category] = category_item
            else:
                category_item = categories[category]

            # Listing the names of different configs under categories 
            config_item = QTreeWidgetItem([config["name"]])
            config_item.setData(0, Qt.UserRole, config)
            category_item.addChild(config_item)

        # Executing the method for sending a config file to the pi when a mouse on the list is double clicked 
        self.config_tree.itemDoubleClicked.connect(self.config_item_clicked)
        
    # Method for logic on what to do when a mouse is double clicked (mainly used to send data to pi)
    def config_item_clicked(self, item, column):
        global current_task, current_time 
        
        if item.parent():  # Ensure it's a config item, not a category
            selected_config = item.data(0, Qt.UserRole)
            self.current_config = selected_config
            self.selected_config_label.setText(f"Selected Config: {selected_config['name']}") # Changing the label text to indicate the currently selected config. Otherwise None
            
            # Prompt to confirm selected configuration (to prevent accidentally using parameters for wrong mouse)
            confirm_dialog = QMessageBox()
            confirm_dialog.setIcon(QMessageBox.Question)
            confirm_dialog.setText(f"Do you want to use '{selected_config['name']}'?")
            confirm_dialog.setWindowTitle("Confirm Configuration")
            confirm_dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            confirm_dialog.setDefaultButton(QMessageBox.Yes)
            
            # Logic for what to do when the selection is confirmed 
            if confirm_dialog.exec_() == QMessageBox.Yes:
                # Serialize JSON data and send it over ZMQ to all the IPs connected to the specified port
                json_data = json.dumps(selected_config)
                self.publisher.send_json(json_data)

                # Updating the global variables for the selected task and updating the time to indicate when it was sent 
                self.current_task = selected_config['name'] + "_" + selected_config['task']
                self.current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                current_time = self.current_time
                current_task = self.current_task

                # Creating a toast message to indicate that the message has been sent to all IPs connected to the config port
                toast = Toast(self)
                toast.setDuration(5000)  # Hide after 5 seconds
                toast.setTitle('Task Parameters Sent') # Setting title
                toast.setText(f'Parameters for task {current_task} have been sent to {args.json_filename}') # Setting test
                toast.applyPreset(ToastPreset.SUCCESS)  # Apply style preset
                toast.show()
            else:
                self.selected_config_label.setText(f"Selected Config: None")

    # Displaying a context menu with options to view and edit when a config is right clicked
    def show_context_menu(self, pos):
        item = self.config_tree.itemAt(pos)
        if item and item.parent():  # Ensure it's a config item, not a category
            menu = QMenu(self)
            
            # Listing possible actions
            view_action = QAction("View Details", self)
            edit_action = QAction("Edit Configuration", self)
            
            # Connecting these actions to methods
            view_action.triggered.connect(lambda: self.view_configuration_details(item))
            edit_action.triggered.connect(lambda: self.edit_configuration(item))
            
            # Listing these actions on the context menu 
            menu.addAction(view_action)
            menu.addAction(edit_action)
            menu.exec_(self.config_tree.mapToGlobal(pos))

    # Method for what to do when 'Edit Configuration' is clicked
    def edit_configuration(self, item):
        selected_config = item.data(0, Qt.UserRole)
        dialog = ConfigurationDialog(self, selected_config) # Displays the menu to edit configurations
        if dialog.exec_() == QDialog.Accepted: 
            updated_config = dialog.get_configuration() # Updating details based on saved information 
            if updated_config:
                self.configurations = [config if config['name'] != selected_config['name'] else updated_config for config in self.configurations] # overwriting 
                self.update_config_list() # Updating list of configs based on edits made 

                # Saving the updated configuration as a json file/ Updating existing json
                config_name = updated_config["name"]
                file_path = os.path.join(params['task_configs'], f"{config_name}.json")
                with open(file_path, 'w') as file:
                    json.dump(updated_config, file, indent=4)

    # Method for what to do when 'View Details' is clicked 
    def view_configuration_details(self, item):
        selected_config = item.data(0, Qt.UserRole)
        dialog = ConfigurationDetailsDialog(selected_config, self) # Display the menu
        dialog.exec_()

## MAIN GUI WINDOW
"""
Here we make objects of all the different elements of the GUI and arrange the widgets
We also connect the signals defined earlier to slots defined in other classes to make them be able to share information
"""
# Main window of the GUI that launches when the program is run and arranges all the widgets 
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Main Window Title
        self.setWindowTitle(f"GUI - {args.json_filename}")

        # Creating instances of PiWidget and ConfigurationList
        self.Pi_widget = PiWidget(self)
        self.config_list = ConfigurationList()

        # Initializing PlotWindow after PiWidget since it inherits information from it
        self.plot_window = PlotWindow(self.Pi_widget)

        # Creating a menu bar with some actions
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')

        # Creating an action to change directory to load mice from 
        load_action = QAction('Load Config Directory', self)
        load_action.triggered.connect(self.config_list.load_configurations)

        # Adding actions to file menu
        file_menu.addAction(load_action)

        # Creating container widgets for each component (these determine their size and layout with respect to each other )
        # Config List
        config_list_container = QWidget()
        config_list_container.setFixedWidth(250)  # Limiting the width of the configuration list container
        config_list_container.setLayout(QVBoxLayout())
        config_list_container.layout().addWidget(self.config_list)

        # Pi Widget
        pi_widget_container = QWidget()
        pi_widget_container.setFixedWidth(500)  # Limiting the width of the PiWidget container
        pi_widget_container.setLayout(QVBoxLayout())
        pi_widget_container.layout().addWidget(self.Pi_widget)

        # Setting the central widget as a container widget for all components
        container_widget = QWidget(self)
        container_layout = QtWidgets.QHBoxLayout(container_widget)
        container_layout.addWidget(config_list_container)
        container_layout.addWidget(pi_widget_container)
        container_layout.addWidget(self.plot_window)
        self.setCentralWidget(container_widget)

        # Setting the dimensions of the main window (in pixels)
        self.resize(2000, 270)
        self.show()

        # Connecting signals to the respective slots/methods after the MainWindow is fully initialized
        self.Pi_widget.worker.pokedportsignal.connect(self.plot_window.handle_update_signal)
        self.Pi_widget.updateSignal.connect(self.plot_window.handle_update_signal)
        self.Pi_widget.startButtonClicked.connect(self.config_list.on_start_button_clicked)

    # Function to plot the Pi signals using the PlotWindow class
    def plot_poked_port(self, poked_port_value):
        self.plot_window.handle_update_signal(poked_port_value)

    # Executes when the window is closed to send 'exit' signal to all IP addresses bound to the GUI
    def closeEvent(self, event):
        # Iterate through identities and send 'exit' message
        for identity in self.Pi_widget.worker.identities:
            self.Pi_widget.worker.socket.send_multipart([identity, b"exit"])
        event.accept()

# Running the GUI
if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = MainWindow()
    sys.exit(app.exec())
