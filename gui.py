## TODO: 
# Document what each class in this script does.
# Separate the classes that are for running the GUI from the classes
# that interact with the Pi and run the task 
# Put the ones that run the GUI in another script and import them here


# Importing necessary libraries
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

# Set up argument parsing to select box
parser = argparse.ArgumentParser(description="Load parameters for a specific box.")
parser.add_argument('json_filename', type=str, help="The name of the JSON file (without 'configs/' and '.json')")

# Parse arguments
args = parser.parse_args()

# Constructing the full path to the config file
param_directory = f"gui/configs/{args.json_filename}.json"

# Load the parameters from the specified JSON file
with open(param_directory, "r") as p:
    params = json.load(p)

# Fetching all the ports to use for the trials    
active_nosepokes = [int(i) for i in params['active_nosepokes']]

# Variable to keep track of the current task
current_task = None
current_time = None

# Function to print to terminal and store log files as txt
def print_out(*args, **kwargs):
    global current_task, current_time
    
    output_filename = params['save_directory'] + f"/terminal_logs/{current_task}_{current_time}.txt"
    
    # Join the arguments into a single string
    statement = " ".join(map(str, args))
    
    # Print the statement to the console
    print(statement, **kwargs)
    
    # Write the statement to the file
    with open(output_filename, 'a') as outputFile:
            outputFile.write(statement + "\n")

# Creating a class for the individual Raspberry Pi signals
class PiSignal(QGraphicsEllipseItem):
    def __init__(self, index, total_ports):
        super(PiSignal, self).__init__(0, 0, 38, 38)
        self.index = index
        self.total_ports = total_ports # Creating a variable for the total number of Pis
        
        # Ensure index is within range of ports
        if 0 <= self.index < len(params['ports']):
            port_data = params['ports'][self.index]
            label_text = port_data['label']
        
        self.label = QGraphicsTextItem(f"Port-{port_data['label']}", self) # Label for each Pi
        font = QFont()
        font.setPointSize(8)  # Set the font size here (10 in this example)
        self.label.setFont(font)
        self.label.setPos(19 - self.label.boundingRect().width() / 2, 19 - self.label.boundingRect().height() / 2) # Positioning the labels
        self.setPos(self.calculate_position()) # Positioning the individual Pi elements
        self.setBrush(QColor("gray")) # Setting the initial color of the Pi signals to red

    # Function to calculate the position of the ports
    def calculate_position(self):  
        angle = 2 * math.pi * self.index / self.total_ports # Arranging the Pi signals in a circle
        radius = 62
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        return QPointF(200 + x, 200 + y)

    # Function to set the color for each individual port
    def set_color(self, color):
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

# Worker class to lower the load on the GUI
class Worker(QObject):
    # Signal emitted when a poke event occurs
    pokedportsignal = pyqtSignal(int, str)

    def __init__(self, pi_widget):
        super().__init__()
        self.initial_time = None
        
        # Setting up ZMQ context to send and receive information about poked ports
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.bind("tcp://*" + params['worker_port'])  # Change Port number if you want to run multiple instances
        
        # Initializing values for sound parameters
        self.amplitudes = []
        self.target_rates = []
        self.target_temporal_log_stds = []
        self.center_freqs = []

        self.current_amplitude = 0.0
        self.current_target_rate = 0.0
        self.current_target_temporal_log_std = 0.0
        self.current_center_freq = 0.0
        self.current_bandwidth = 0.0
        self.current_poke = 0
        self.current_completed_trials = 0
        self.current_correct_trials = 0
        
        # Initialize reward_port and related variables that need to be continually updated
        self.last_pi_received = None
        self.prev_choice = None
        self.timer = None
        self.current_task = None
        self.pi_widget = pi_widget
        self.total_ports = self.pi_widget.total_ports 
        self.Pi_signals = self.pi_widget.Pi_signals 
        self.poked_port_numbers = self.pi_widget.poked_port_numbers 
        self.identities = set()
        self.last_poke_timestamp = None  # Attribute to store the timestamp of the last poke event
        self.reward_port = None
        self.last_rewarded_port = None
        self.previous_port = None

        # Initializing lists for timestamps and ports visited
        self.trials = 0
        self.timestamps = []
        self.pokes = []
        self.completed_trials = []
        self.correct_trials = []
        self.reward_ports = []
        self.unique_ports_visited = []  # List to store unique ports visited in each trial
        self.unique_ports_colors = {}  # Dictionary to store color for each unique port
        self.average_unique_ports = 0  # Variable to store the average number of unique ports visited
    
    # Method to start the sequence
    @pyqtSlot()
    def start_sequence(self):
        # Reset data when starting a new sequence
        self.initial_time = time.time()
        self.timestamps = []
        self.reward_ports = []
        
        # Randomly choose the initial reward port
        self.reward_port = self.choose()
        reward_message = f"Reward Port: {self.reward_port}"
        print_out(reward_message)
        
        # Send the message to all connected Pis
        for identity in self.identities:
            self.socket.send_multipart([identity, bytes(reward_message, 'utf-8')])
        
        port_data = params['ports'][int(self.reward_port)]
        label_text = port_data['label']
        
        # Set the color of the initial reward port to green
        self.Pi_signals[self.reward_port - 1].set_color("green")

        # Start the timer loop
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_Pi)
        self.timer.start(10)

    # Method to stop the sequence
    @pyqtSlot()
    def stop_sequence(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer.timeout.disconnect(self.update_Pi)
        
        # Clear the recorded data and reset necessary attributes
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
        self.previous_port = None
        self.trials = 0
        self.average_unique_ports = 0
    
    # Method to update unique ports visited
    def update_unique_ports(self):
        # Calculate unique ports visited in the current trial
        unique_ports = set(self.poked_port_numbers)
        self.unique_ports_visited.append(len(unique_ports))

    # Method to calculate the average number of unique ports visited
    def calculate_average_unique_ports(self):
        # Calculate the average number of unique ports visited per trial
        if self.unique_ports_visited:
            self.average_unique_ports = sum(self.unique_ports_visited) / len(self.unique_ports_visited)
            
    # Method to randomly choose next port to reward
    def choose(self):
        ports = active_nosepokes
        poss_choices = [choice for choice in ports if choice != self.prev_choice]
        new_choice =  random.choice(poss_choices)
        self.prev_choice = new_choice
        return new_choice
    
    # Method to handle the update of Pis
    @pyqtSlot()
    def update_Pi(self):
        current_time = time.time()
        elapsed_time = current_time - self.initial_time

        # Update the last poke timestamp whenever a poke event occurs
        self.last_poke_timestamp = current_time

        try:
            # Receive message from the socket
            identity, message = self.socket.recv_multipart()
            self.identities.add(identity)
            message_str = message.decode('utf-8')
            
            # Message to signal if pis are connected
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
    
            # Statement to keep track of the current parameters 
            if "Current Parameters" in message_str:
                sound_parameters = message_str
                print_out("Updated:", message_str)
                
                # Remove the "Current Parameters - " part and strip any leading/trailing whitespace
                param_string = sound_parameters.split("-", 1)[1].strip()
                
                # Extract parameters
                params = {}
                for param in param_string.split(','):
                    key, value = param.split(':')
                    params[key.strip()] = value.strip()
                
                # Extract and convert the values
                self.current_amplitude = float(params.get("Amplitude", 0))
                self.current_target_rate = float(params.get("Rate", "0").split()[0])
                self.current_target_temporal_log_std = float(params.get("Irregularity", "0").split()[0])
                self.current_center_freq = float(params.get("Center Frequency", "0").split()[0])
                self.current_bandwidth = float(params.get("Bandwidth", "0"))

            else:
                poked_port = int(message_str)
                # Check if the poked port is the same as the last rewarded port
                if poked_port == self.last_rewarded_port:
                     # If it is, do nothing and return
                        return

                if 1 <= poked_port <= self.total_ports:
                    poked_port_signal = self.Pi_signals[poked_port - 1]

                    if poked_port == self.reward_port:
                        color = "green" if self.trials == 0 else "blue"
                        if self.trials > 0:
                            self.trials = 0
                    else:
                        color = "red"
                        self.trials += 1
                        self.current_poke += 1

                    poked_port_signal.set_color(color)
                    self.poked_port_numbers.append(poked_port)
                    print_out("Sequence:", self.poked_port_numbers)
                    self.last_pi_received = identity

                    self.pokedportsignal.emit(poked_port, color)
                    self.timestamps.append(elapsed_time)
                    self.reward_ports.append(self.reward_port)
                    self.amplitudes.append(self.current_amplitude)
                    self.target_rates.append(self.current_target_rate)
                    self.target_temporal_log_stds.append(self.current_target_temporal_log_std)
                    self.center_freqs.append(self.current_center_freq)
                    self.pokes.append(self.current_poke)
                    self.completed_trials.append(self.current_completed_trials)
                    self.correct_trials.append(self.current_correct_trials)
                    
                    self.update_unique_ports()

                    if color == "green" or color == "blue":
                        self.current_poke += 1
                        self.current_completed_trials += 1
                        for identity in self.identities:
                            self.socket.send_multipart([identity, bytes(f"Reward Poke Completed: {self.reward_port}", 'utf-8]')])
                        self.last_rewarded_port = self.reward_port   
                        self.reward_port = self.choose()
                        self.trials = 0
                        print_out(f"Reward Port: {self.reward_port}")
                        if color == "green":
                            self.current_correct_trials += 1 

                        # Reset color of all non-reward ports to gray and reward port to green
                        for index, Pi in enumerate(self.Pi_signals):
                            if index + 1 == self.reward_port:
                                Pi.set_color("green")
                            else:
                                Pi.set_color("gray")

                        for identity in self.identities:
                            self.socket.send_multipart([identity, bytes(f"Reward Port: {self.reward_port}", 'utf-8')])

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
        
        # Save results to a CSV file
        with open(f"{save_directory}/{filename}", 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["No. of Pokes","Poke Timestamp (seconds)", "Port Visited", "Current Reward Port", "No. of Trials", "No. of Correct Trials", "Amplitude", "Rate", "Irregularity", "Center Frequency"])
            for poke, timestamp, poked_port, reward_port, completed_trial, correct_trial,  amplitude, target_rate, target_temporal_log_std, center_freq in zip(self.timestamps, self.poked_port_numbers, self.reward_ports, self.pokes, self.completed_trials, self.correct_trials, self.amplitudes, self.target_rates, self.target_temporal_log_stds, self.center_freqs):
                writer.writerow([ poke, timestamp, poked_port, reward_port, completed_trial, correct_trial, amplitude, target_rate, target_temporal_log_std,center_freq])
        
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

# PiWidget Class that represents all PiSignals
class PiWidget(QWidget):
    startButtonClicked = pyqtSignal()
    updateSignal = pyqtSignal(int, str) # Signal to emit the number and color of the active Pi

    def __init__(self, main_window, *args, **kwargs):
        super(PiWidget, self).__init__(*args, **kwargs)

        # Creating the GUI to display the Pi signals
        self.main_window = main_window
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.total_ports = 8
        self.Pi_signals = [PiSignal(i, self.total_ports) for i in range(self.total_ports)]
        [self.scene.addItem(Pi) for Pi in self.Pi_signals]
        
        # Setting for bold font
        font = QFont()
        font.setBold(True)
        
        # Creating buttons to start and stop the sequence of communication with the Raspberry Pi
        self.poked_port_numbers = []
        self.start_button = QPushButton("Start Session")
        self.start_button.setStyleSheet("background-color : green; color: white;") 
        #self.start_button.setFont(font)   
        self.stop_button = QPushButton("Stop Session")
        self.stop_button.setStyleSheet("background-color : red; color: white;") 
        #self.stop_button.setFont(font)   
        self.stop_button.clicked.connect(self.save_results_to_csv)  # Connect save button to save method

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time_elapsed)
        
        self.start_time = QTime(0, 0)
        self.poke_time = QTime(0, 0)

        self.red_count = 0
        self.blue_count = 0
        self.green_count = 0

        # Create QVBoxLayout for details
        self.details_layout = QVBoxLayout()
        
        # Details Title
        self.title_label = QLabel("Session Details:", self)
        self.title_label.setFont(font)
        
        # Session Details
        self.time_label = QLabel("Time Elapsed: 00:00", self)
        self.poke_time_label = QLabel("Time since last poke: 00:00", self)
        self.red_label = QLabel("Number of Pokes: 0", self)
        self.blue_label = QLabel("Number of Trials: 0", self)
        self.green_label = QLabel("Number of Correct Trials: 0", self)
        self.fraction_correct_label = QLabel("Fraction Correct (FC): 0.000", self)
        self.rcp_label = QLabel("Rank of Correct Port (RCP): 0", self)
        
        # Adding labels to details_layout
        self.details_layout.addWidget(self.title_label)
        self.details_layout.addWidget(self.time_label)
        self.details_layout.addWidget(self.poke_time_label)
        self.details_layout.addWidget(self.red_label)
        self.details_layout.addWidget(self.blue_label)
        self.details_layout.addWidget(self.green_label)
        self.details_layout.addWidget(self.fraction_correct_label)
        self.details_layout.addWidget(self.rcp_label)

        # Initialize QTimer for resetting last poke time
        self.last_poke_timer = QTimer()
        self.last_poke_timer.timeout.connect(self.update_last_poke_time)

        # Create HBoxLayout for start and stop buttons
        start_stop_layout = QHBoxLayout()
        start_stop_layout.addWidget(self.start_button)
        start_stop_layout.addWidget(self.stop_button)

        # Create QHBoxLayout for self.view and start_stop_layout
        view_buttons_layout = QVBoxLayout()
        view_buttons_layout.addWidget(self.view)  # Add self.view to the layout
        view_buttons_layout.addLayout(start_stop_layout)  # Add start_stop_layout to the layout

        # Create QVBoxLayout for the main layout
        main_layout = QHBoxLayout(self)
        main_layout.addLayout(view_buttons_layout)  # Add view_buttons_layout to the main layout
        main_layout.addLayout(self.details_layout)  # Add details_layout below view_buttons_layout

        # Set main_layout as the layout for this widget
        self.setLayout(main_layout)

        # Creating an instance of the Worker Class and a Thread to handle the communication with the Raspberry Pi
        self.worker = Worker(self)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)  # Move the worker object to the thread
        self.start_button.clicked.connect(self.start_sequence)  # Connect the start button to the start_sequence function
        self.stop_button.clicked.connect(self.stop_sequence)  # Connect the stop button to the stop_sequence function
        
        # Connect the pokedportsignal from the Worker to a new slot
        self.worker.pokedportsignal.connect(self.emit_update_signal)  # Connect the pokedportsignal to the emit_update_signal function
        self.worker.pokedportsignal.connect(self.reset_last_poke_time)
        self.worker.pokedportsignal.connect(self.calc_and_update_avg_unique_ports)

    # Function to emit the update signal
    def emit_update_signal(self, poked_port_number, color):
        # Emit the updateSignal with the received poked_port_number and color
        self.updateSignal.emit(poked_port_number, color)
        self.last_poke_timestamp = time.time()

        if color == "red":
            self.red_count += 1
            self.red_label.setText(f"Number of Pokes: {(self.red_count + self.green_count + self.blue_count)}")

        if color == "blue":
            self.blue_count += 1
            self.red_label.setText(f"Number of Pokes: {(self.red_count + self.green_count + self.blue_count)}")
            self.blue_label.setText(f"Number of Trials: {(self.blue_count + self.green_count)}")
            if self.blue_count != 0:
                self.fraction_correct = self.green_count / (self.blue_count + self.green_count)
                self.fraction_correct_label.setText(f"Fraction Correct (FC): {self.fraction_correct:.3f}")

        elif color == "green":
            self.green_count += 1
            self.red_label.setText(f"Number of Pokes: {(self.red_count + self.green_count + self.blue_count)}")
            self.blue_label.setText(f"Number of Trials: {(self.blue_count + self.green_count)}")
            self.green_label.setText(f"Number of Correct Trials: {self.green_count}")
            if self.blue_count == 0:
                self.fraction_correct_label.setText(f"Fraction Correct (FC): {(self.green_count/self.green_count):.3f}")    
            elif self.blue_count != 0:
                self.fraction_correct = self.green_count / (self.blue_count + self.green_count)
                self.fraction_correct_label.setText(f"Fraction Correct (FC): {self.fraction_correct:.3f}")

    def start_sequence(self):
        self.startButtonClicked.emit()
        self.worker.start_message()
        
        # Start the worker thread when the start button is pressed
        self.thread.start()
        print_out("Experiment Started!")
        QMetaObject.invokeMethod(self.worker, "start_sequence", Qt.QueuedConnection)

        # Start the plot
        self.main_window.plot_window.start_plot()

        # Start the timer
        self.start_time.start()
        self.timer.start(10)  # Update every second               

    def stop_sequence(self):
        QMetaObject.invokeMethod(self.worker, "stop_sequence", Qt.QueuedConnection)
        print_out("Experiment Stopped!")
        
        # Stop the plot
        self.main_window.plot_window.stop_plot()
        
        # Reset all labels
        self.time_label.setText("Time Elapsed: 00:00")
        self.poke_time_label.setText("Time since last poke: 00:00")
        self.red_label.setText("Number of Pokes: 0")
        self.blue_label.setText("Number of Trials: 0")
        self.green_label.setText("Number of Correct Trials: 0")
        self.fraction_correct_label.setText("Fraction Correct (FC): 0.000")
        self.rcp_label.setText("Rank of Correct Port (RCP): 0")

        # Reset poke and trial counts
        self.red_count = 0
        self.blue_count = 0
        self.green_count = 0

        # Stop the timer
        self.timer.stop()
        
        # Allow starting a new experiment
        self.thread.quit()

    @pyqtSlot()
    def update_time_elapsed(self):
        elapsed_time = self.start_time.elapsed() / 1000.0  # Convert milliseconds to seconds
        minutes, seconds = divmod(elapsed_time, 60)  # Convert seconds to minutes and seconds
        # Update the QLabel text with the elapsed time in minutes and seconds
        self.time_label.setText(f"Time elapsed: {str(int(minutes)).zfill(2)}:{str(int(seconds)).zfill(2)}")
           
    @pyqtSlot()
    def reset_last_poke_time(self):
        # Stop the timer if it's active
        self.last_poke_timer.stop()

        # Start the timer again
        self.last_poke_timer.start(1000)  # Set interval to 1000 milliseconds (1 second)
        
    @pyqtSlot()
    def calc_and_update_avg_unique_ports(self):
        self.worker.calculate_average_unique_ports()
        average_unique_ports = self.worker.average_unique_ports
        self.rcp_label.setText(f"Rank of Correct Port: {average_unique_ports:.2f}")
    
    @pyqtSlot()
    def update_last_poke_time(self):
        # Calculate the elapsed time since the last poke
        current_time = time.time()
        elapsed_time = current_time - self.last_poke_timestamp

        # Update the QLabel text with the time since the last poke
        minutes, seconds = divmod(elapsed_time, 60)  # Convert seconds to minutes and seconds
        self.poke_time_label.setText(f"Time since last poke: {str(int(minutes)).zfill(2)}:{str(int(seconds)).zfill(2)}")

    def save_results_to_csv(self):
        self.worker.stop_message()
        self.worker.save_results_to_csv()  # Call worker method to save results
        toast = Toast(self)
        toast.setDuration(5000)  # Hide after 5 seconds
        toast.setTitle('Results Saved')
        toast.setText('Log saved to /home/mouse/dev/paclab_sukrith/logs')
        toast.applyPreset(ToastPreset.SUCCESS)  # Apply style preset
        toast.show()

# Widget that contains a plot that is continuously depending on the ports that are poked
class PlotWindow(QWidget):
    def __init__(self, pi_widget, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.is_active = False  # Flag to check if the Start Button is pressed
        self.start_time = None
        self.timer = QTimer(self)  # Create a QTimer object
        self.timer.timeout.connect(self.update_plot)  # Connect the timer to update the plot
        
        # Create QTimer for updating time bar
        self.time_bar_timer = QTimer(self)
        self.time_bar_timer.timeout.connect(self.update_time_bar)

        # Entering the plot parameters and titles
        self.plot_graph = pg.PlotWidget()
        self.start_time = None  # Initialize start_time to None
        self.plot_graph.setXRange(0, 1600)  # Set x-axis range to [0, 1600]
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.plot_graph)
        self.plot_graph.setBackground("k")
        self.plot_graph.setTitle("Pokes vs Time", color="white", size="12px")
        styles = {"color": "white", "font-size": "11px"}
        self.plot_graph.setLabel("left", "Port", **styles)
        self.plot_graph.setLabel("bottom", "Time", **styles)
        self.plot_graph.addLegend()
        self.plot_graph.showGrid(x=True, y=True)
        self.plot_graph.setYRange(1, 9)
        self.timestamps = []  # List to store timestamps
        self.signal = []  # List to store active Pi signals
        
        # Setting Initial Time Bar
        self.line_of_current_time_color = 0.5
        self.line_of_current_time = self.plot_graph.plot(x=[0, 0], y=[-1, 8], pen=pg.mkPen(self.line_of_current_time_color))

        # Plotting the initial graph
        self.line = self.plot_graph.plot(
            self.timestamps,
            self.signal,
            pen=None,
            symbol="o",
            symbolSize=1,
            symbolBrush="r",
        )

        # List to keep track of all plotted items for easy clearing
        self.plotted_items = []

        # Connecting to signals from PiWidget
        pi_widget.updateSignal.connect(self.handle_update_signal)
        # Connect the signal from Worker to a slot
        pi_widget.worker.pokedportsignal.connect(self.plot_poked_port)

    def start_plot(self):
        # Activating the plot window and start the timer
        self.is_active = True
        self.start_time = datetime.now()  # Set the start time
        self.timer.start(10)  # Start the timer to update every second

        # Start the timer for updating the time bar when the plot starts
        self.time_bar_timer.start(50)  # Update every 100 milliseconds

    def stop_plot(self):
        # Deactivating the plot window and stop the timer
        self.is_active = False
        self.timer.stop()
        
        # Stop the timer for updating the time bar when the plot stops
        self.time_bar_timer.stop()
        self.clear_plot()

    def clear_plot(self):
        # Clear the plot by clearing data lists
        self.timestamps.clear()
        self.signal.clear()
        # Update the plot with cleared data
        self.line.setData(x=[], y=[])

        # Clear all plotted items
        for item in self.plotted_items:
            self.plot_graph.removeItem(item)
        self.plotted_items.clear()

        self.line_of_current_time.setData(x=[], y=[])

    def update_time_bar(self):
        # Using current time to approximately update timebar
        if self.start_time is not None:
            current_time = datetime.now()
            approx_time_in_session = (
                current_time - self.start_time).total_seconds()

            # Update the current time line
            self.line_of_current_time_color = np.mod(
                self.line_of_current_time_color + 0.1, 2)
            self.line_of_current_time.setData(
                x=[approx_time_in_session, approx_time_in_session], y=[-1, 9],
                pen=pg.mkPen(np.abs(self.line_of_current_time_color - 1)),
            )
    
    def handle_update_signal(self, update_value):
        if self.is_active:
            # Append current timestamp and update value to the lists
            self.timestamps.append((datetime.now() - self.start_time).total_seconds())
            self.signal.append(update_value)
            self.update_plot()

    def plot_poked_port(self, poked_port_value, color):
        if self.is_active:
            brush_color = "g" if color == "green" else "r" if color == "red" else "b"
            relative_time = (datetime.now() - self.start_time).total_seconds()  # Convert to seconds
            item = self.plot_graph.plot(
                [relative_time],
                [poked_port_value],
                pen=None,
                symbol="arrow_down",  # "o" for dots
                symbolSize=20,  # use 8 or lower if using dots
                symbolBrush=brush_color,
                symbolPen=None,
            )
            self.plotted_items.append(item)

    def update_plot(self):
        # Update plot with timestamps and signals
        self.line.setData(x=self.timestamps, y=self.signal)


# Displays a Dialog box with all the details of the task when you right-click an item on the list
class ConfigurationDetailsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Details")

        # Create labels to display configuration parameters
        self.name_label = QLabel(f"Name: {config['name']}")
        self.task_label = QLabel(f"Task: {config['task']}")
        self.amplitude_label = QLabel(f"Amplitude: {config['amplitude_min']} - {config['amplitude_max']}")
        self.rate_label = QLabel(f"Rate: {config['rate_min']} - {config['rate_max']}")
        self.irregularity_label = QLabel(f"Irregularity: {config['irregularity_min']} - {config['irregularity_max']}")
        self.reward_label = QLabel(f"Reward Value: {config['reward_value']}")
        self.freq_label = QLabel(f"Center Frequency: {config['center_freq_min']} - {config['center_freq_max']}")
        self.band_label = QLabel(f"Bandwidth: {config['bandwidth']}")

        # Create button box with OK button
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.button_box.accepted.connect(self.accept)

        # Arrange widgets in a vertical layout
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

# Displays the prompt to make a new task based on default parameters (with editable values if needed)
class PresetTaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Name and Select Task")

        self.layout = QVBoxLayout(self)

        self.name_label = QLabel("Name:")
        self.name_edit = QLineEdit(self)

        self.task_label = QLabel("Select Task:")
        self.task_combo = QComboBox(self)
        self.task_combo.addItems(["Fixed", "Sweep", "Distractor", "Poketrain", "Audio"])  
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)

        self.layout.addWidget(self.name_label)
        self.layout.addWidget(self.name_edit)
        self.layout.addWidget(self.task_label)
        self.layout.addWidget(self.task_combo)
        self.layout.addWidget(self.ok_button)

    def get_name_and_task(self):
        return self.name_edit.text(), self.task_combo.currentText()

# Editable dialog box with details to edit the parameters for the tasks
class ConfigurationDialog(QDialog):
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Configuration Details")
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
        layout = QVBoxLayout(self)

        # Create labels and line edits for configuration parameters
        self.name_label = QLabel("Name:")
        self.name_edit = QLineEdit(self.config.get("name", ""))
        self.task_label = QLabel(f"Task: {self.config.get('task', '')}")

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
        
        self.band_label = QLabel("Bandwidth:")
        self.band_edit = QLineEdit(str(self.config.get("bandwidth", "")))
        
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
        task = self.config.get("task", "")

        if task.lower() == "fixed":
            # For "Fixed" task, hide max edit fields and set values to be the same as min
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

            # Connect min edit fields to update max fields
            self.amplitude_min_edit.textChanged.connect(self.update_amplitude_max)
            self.rate_min_edit.textChanged.connect(self.update_rate_max)
            self.irregularity_min_edit.textChanged.connect(self.update_irregularity_max)
            self.freq_min_edit.textChanged.connect(self.update_freq_max)


        else:
            # For other tasks, show all min and max edit fields
            pass

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
        updated_name = self.name_edit.text()
        task = self.config.get("task", "")

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

# List of tasks that have been saved in the directory which also tells pis what parameters to use for each task
class ConfigurationList(QWidget):
    send_config_signal = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self.configurations = []
        self.current_config = None
        self.current_task = None
        self.default_parameters = self.load_default_parameters()
        self.init_ui()
        self.load_default()  # Call the method to load configurations from a default directory during initialization

        # Initialize ZMQ context and socket for publishing
        self.context = zmq.Context()
        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.bind("tcp://*" + params['config_port'])  # Binding to port 5556 for publishing

    def init_ui(self):
        self.config_tree = QTreeWidget()
        self.config_tree.setHeaderLabels(["Tasks"])
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search for a mouse...")
        
        self.add_button = QPushButton('Add Mouse')
        self.remove_button = QPushButton('Remove Mouse')
        self.selected_config_label = QLabel()

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.selected_config_label)
        main_layout.addWidget(self.search_box)
        main_layout.addWidget(self.config_tree)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)
        self.add_button.clicked.connect(self.add_configuration)
        self.remove_button.clicked.connect(self.remove_configuration)
        self.setWindowTitle('Configuration List')
        self.show()

        # Enable custom context menu
        self.config_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.config_tree.customContextMenuRequested.connect(self.show_context_menu)
        
        # Connect search box text changed signal to filter_configurations method
        self.search_box.textChanged.connect(self.filter_configurations)
        
    def filter_configurations(self, text):
        if not text:
            self.update_config_list()
            return
        
        filtered_configs = []
        for config in self.configurations:
            if text.lower() in config["name"].lower():
                filtered_configs.append(config)

        self.update_config_list(filtered_configs)

    def on_start_button_clicked(self):
        if self.current_config is None:
            QMessageBox.warning(self, "Warning", "Please select a mouse before starting the experiment.")
    
    def load_default_parameters(self):
        with open(params['pi_defaults'], 'r') as file:
            return json.load(file)

    def add_configuration(self):
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

            # Instantiate ConfigurationDialog properly
            dialog = ConfigurationDialog(self, {
                "name": name,
                "task": task,
                **default_params
            })
            
            if dialog.exec_() == QDialog.Accepted:
                new_config = dialog.get_configuration()
                self.configurations.append(new_config)
                self.update_config_list()

                # Automatically save the configuration with the name included in the dialog
                config_name = new_config["name"]
                file_path = os.path.join(params['task_configs'], f"{config_name}.json")
                with open(file_path, 'w') as file:
                    json.dump(new_config, file, indent=4)

    def remove_configuration(self):
        selected_item = self.config_tree.currentItem()
        if selected_item and selected_item.parent():
            selected_config = selected_item.data(0, Qt.UserRole)
            self.configurations.remove(selected_config)
            self.update_config_list()

            # Get the filename from the configuration data
            config_name = selected_config["name"] # Make sure filename is the same as name in the json
            
            # Construct the full file path
            file_path = os.path.join(params['task_configs'], f"{config_name}.json")

            # Check if the file exists and delete it
            if os.path.exists(file_path):
                os.remove(file_path)

    def load_configurations(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Configuration Folder")
        if folder:
            self.configurations = self.import_configs_from_folder(folder)
            self.update_config_list()

    def load_default(self):
        default_directory = os.path.abspath(params['task_configs'])
        if os.path.isdir(default_directory):
            self.configurations = self.import_configs_from_folder(default_directory)
            self.update_config_list()

    def import_configs_from_folder(self, folder):
        configurations = []
        for filename in os.listdir(folder):
            if filename.endswith(".json"):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r') as file:
                    config = json.load(file)
                    configurations.append(config)
        return configurations

    def update_config_list(self, configs=None):
        self.config_tree.clear()
        categories = {}

        if configs is None:
            configs = self.configurations

        for config in configs:
            category = config.get("task", "Uncategorized")
            if category not in categories:
                category_item = QTreeWidgetItem([category])
                self.config_tree.addTopLevelItem(category_item)
                categories[category] = category_item
            else:
                category_item = categories[category]

            config_item = QTreeWidgetItem([config["name"]])
            config_item.setData(0, Qt.UserRole, config)
            category_item.addChild(config_item)

        # Connect double-click signal to config_item_double_clicked slot
        self.config_tree.itemDoubleClicked.connect(self.config_item_clicked)
        
    # Define the slot for double-clicked items
    def config_item_clicked(self, item, column):
        global current_task, current_time 
        
        if item.parent():  # Ensure it's a config item, not a category
            selected_config = item.data(0, Qt.UserRole)
            self.current_config = selected_config
            self.selected_config_label.setText(f"Selected Config: {selected_config['name']}")
            
            # Prompt to confirm selected configuration
            confirm_dialog = QMessageBox()
            confirm_dialog.setIcon(QMessageBox.Question)
            confirm_dialog.setText(f"Do you want to use '{selected_config['name']}'?")
            confirm_dialog.setWindowTitle("Confirm Configuration")
            confirm_dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            confirm_dialog.setDefaultButton(QMessageBox.Yes)
            
            if confirm_dialog.exec_() == QMessageBox.Yes:
                # Serialize JSON data and send it over ZMQ to all IPs connected
                json_data = json.dumps(selected_config)
                self.publisher.send_json(json_data)
                self.current_task = selected_config['name'] + "_" + selected_config['task']
                self.current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                current_time = self.current_time
                current_task = self.current_task
                toast = Toast(self)
                toast.setDuration(5000)  # Hide after 5 seconds
                toast.setTitle('Task Parameters Sent')
                toast.setText(f'Parameters for task {current_task} have been sent to {args.json_filename}')
                toast.applyPreset(ToastPreset.SUCCESS)  # Apply style preset
                toast.show()
            else:
                self.selected_config_label.setText(f"Selected Config: None")

    def show_context_menu(self, pos):
        item = self.config_tree.itemAt(pos)
        if item and item.parent():  # Ensure it's a config item, not a category
            menu = QMenu(self)
            view_action = QAction("View Details", self)
            edit_action = QAction("Edit Configuration", self)
            view_action.triggered.connect(lambda: self.view_configuration_details(item))
            edit_action.triggered.connect(lambda: self.edit_configuration(item))
            menu.addAction(view_action)
            menu.addAction(edit_action)
            menu.exec_(self.config_tree.mapToGlobal(pos))

    def edit_configuration(self, item):
        selected_config = item.data(0, Qt.UserRole)
        dialog = ConfigurationDialog(self, selected_config)
        if dialog.exec_() == QDialog.Accepted:
            updated_config = dialog.get_configuration()
            if updated_config:
                self.configurations = [config if config['name'] != selected_config['name'] else updated_config for config in self.configurations]
                self.update_config_list()

                # Save the updated configuration
                config_name = updated_config["name"]
                file_path = os.path.join(params['task_configs'], f"{config_name}.json")
                with open(file_path, 'w') as file:
                    json.dump(updated_config, file, indent=4)


    def view_configuration_details(self, item):
        selected_config = item.data(0, Qt.UserRole)
        dialog = ConfigurationDetailsDialog(selected_config, self)
        dialog.exec_()

# Main window of the GUI that launches when the program is run and arranges all the widgets 
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        # Main Window Title
        self.setWindowTitle(f"GUI - {args.json_filename}")

        # Creating instances of PiWidget and ConfigurationList
        self.Pi_widget = PiWidget(self)
        self.config_list = ConfigurationList()

        # Initializing PlotWindow after PiWidget
        self.plot_window = PlotWindow(self.Pi_widget)
        
        # Creating actions
        load_action = QAction('Load Config Directory', self)
        load_action.triggered.connect(self.config_list.load_configurations)

        # Creating menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')
        file_menu.addAction(load_action)

        # Creating container widgets for each component
        config_list_container = QWidget()
        config_list_container.setFixedWidth(250)  # Limiting the width of the configuration list container
        config_list_container.setLayout(QVBoxLayout())
        config_list_container.layout().addWidget(self.config_list)

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

        # Setting the dimensions of the main window
        self.resize(2000, 270)
        self.show()

        # Connecting signals after the MainWindow is fully initialized
        self.Pi_widget.worker.pokedportsignal.connect(self.plot_window.handle_update_signal)
        self.Pi_widget.updateSignal.connect(self.plot_window.handle_update_signal)
        self.Pi_widget.startButtonClicked.connect(self.config_list.on_start_button_clicked)

    # Function to plot the Pi signals using the PlotWindow class
    def plot_poked_port(self, poked_port_value):
        self.plot_window.handle_update_signal(poked_port_value)

    # Override closeEvent to send 'exit' to all IP addresses bound to the GUI
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

