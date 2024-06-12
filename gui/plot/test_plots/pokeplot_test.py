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
from datetime import datetime
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QMenu, QAction, QComboBox, QGroupBox, QLabel, QGraphicsEllipseItem, QListWidget, QListWidgetItem, QGraphicsTextItem, QGraphicsScene, QGraphicsView, QWidget, QVBoxLayout, QPushButton, QApplication, QHBoxLayout, QLineEdit, QListWidget, QFileDialog, QDialog, QLabel, QDialogButtonBox, QTreeWidget, QTreeWidgetItem
from PyQt5.QtCore import QPointF, QTimer, QTime, pyqtSignal, QObject, QThread, pyqtSlot,  QMetaObject, Qt
from PyQt5.QtGui import QColor

# Creating a class for the individual Raspberry Pi signals
class PiSignal(QGraphicsEllipseItem):
    def __init__(self, index, total_ports):
        super(PiSignal, self).__init__(0, 0, 50, 50)
        self.index = index
        self.total_ports = total_ports # Creating a variable for the total number of Pis
        self.label = QGraphicsTextItem(f"Port-{index + 1}", self) # Label for each Pi
        self.label.setPos(25 - self.label.boundingRect().width() / 2, 25 - self.label.boundingRect().height() / 2) # Positioning the labels
        self.setPos(self.calculate_position()) # Positioning the individual Pi elements
        self.setBrush(QColor("gray")) # Setting the initial color of the Pi signals to red

    # Function to calculate the position of the Pi signals
    def calculate_position(self):  
        angle = 2 * math.pi * self.index / self.total_ports # Arranging the Pi signals in a circle
        radius = 150
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        return QPointF(200 + x, 200 + y)

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
            print("Invalid color:", color)

# Worker class to lower the load on the GUI
class Worker(QObject):
    # Signal emitted when a poke event occurs
    pokedportsignal = pyqtSignal(int, str)

    def __init__(self, pi_widget):
        super().__init__()
        self.initial_time = None
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.bind("tcp://*:5555")  # Change Port number if you want to run multiple instances

        self.last_pi_received = None
        self.timer = None
        self.pi_widget = pi_widget
        self.total_ports = self.pi_widget.total_ports 
        self.Pi_signals = self.pi_widget.Pi_signals 
        self.poked_port_numbers = self.pi_widget.poked_port_numbers 
        self.identities = set()
        self.last_poke_timestamp = None  # Attribute to store the timestamp of the last poke event

        # Initialize reward_port and related variables
        self.reward_port = None
        self.previous_port = None

        # Initializing lists for timestamps and ports visited
        self.trials = 0
        self.timestamps = []
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

        # Sending initialization message to Pi
        for identity in self.identities:
            self.socket.send_multipart([identity, b"start"])
        #time.sleep(1)
        
        # Randomly choose either 3 or 4 as the initial reward port
        self.reward_port = random.choice([5, 7])
        reward_message = f"Reward Port: {self.reward_port}"
        print(reward_message)
        
        # Send the message to all connected Pis
        for identity in self.identities:
            self.socket.send_multipart([identity, bytes(reward_message, 'utf-8')])
            
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
            
    # Method to handle the update of Pis
    @pyqtSlot()
    def update_Pi(self):
        current_time = time.time()
        elapsed_time = current_time - self.initial_time

        # Update the last poke timestamp whenever a poke event occurs
        self.last_poke_timestamp = current_time

        # Receive message from the socket
        identity, message = self.socket.recv_multipart()
        self.identities.add(identity)
        self.socket.send_multipart([identity, bytes(f"Reward Port: {self.reward_port}", 'utf-8')])

        try:
            message_str = message.decode('utf-8')
            if "Current Parameters" in message_str:
                print("Updated:", message_str)
            else:
                poked_port = int(message_str)
                if 1 <= poked_port <= self.total_ports:
                    poked_port_signal = self.Pi_signals[poked_port - 1]

                    if poked_port == self.reward_port:
                        color = "green" if self.trials == 0 else "blue"
                        if self.trials > 0:
                            self.trials = 0
                    else:
                        color = "red"
                        self.trials += 1

                    poked_port_signal.set_color(color)
                    self.poked_port_numbers.append(poked_port)
                    print("Sequence:", self.poked_port_numbers)
                    self.last_pi_received = identity

                    self.pokedportsignal.emit(poked_port, color)
                    self.timestamps.append(elapsed_time)
                    self.reward_ports.append(self.reward_port)
                    self.update_unique_ports()

                    if color == "green" or color == "blue":
                        for identity in self.identities:
                            self.socket.send_multipart([identity, b"Reward Poke Completed"])
                        self.reward_port = random.choice([5, 7])
                        self.trials = 0
                        print(f"Reward Port: {self.reward_port}")

                        # Reset color of all non-reward ports to gray and reward port to green
                        for index, Pi in enumerate(self.Pi_signals):
                            if index + 1 == self.reward_port:
                                Pi.set_color("green")
                            else:
                                Pi.set_color("gray")

                        for identity in self.identities:
                            self.socket.send_multipart([identity, bytes(f"Reward Port: {self.reward_port}", 'utf-8')])

        except ValueError:
            print("Connected to Raspberry Pi:", message_str)

    # Method to save results to a CSV file
    def save_results_to_csv(self):
        # Save results to a CSV file
        filename, _ = QFileDialog.getSaveFileName(None, "Save Results", "", "CSV Files (*.csv)")
        if filename:
            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Poke Timestamp (seconds)", "Port Visited", "Current Reward Port"])
                for timestamp, poked_port, reward_port in zip(self.timestamps, self.poked_port_numbers, self.reward_ports):
                    writer.writerow([timestamp, poked_port, reward_port])

# PiWidget Class that represents all PiSignals
class PiWidget(QWidget):
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
        
        # Creating buttons to start and stop the sequence of communication with the Raspberry Pi
        self.poked_port_numbers = []

        self.start_button = QPushButton("Start Experiment")
        self.stop_button = QPushButton("Stop Experiment")
        self.stop_button.clicked.connect(self.save_results_to_csv)  # Connect save button to save method

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time_elapsed)
        
        self.start_time = QTime(0, 0)
        self.poke_time = QTime(0, 0)

        self.red_count = 0
        self.blue_count = 0
        self.green_count = 0

        #self.details_box = QGroupBox("Details")
        self.details_layout = QVBoxLayout()
        self.time_label = QLabel("Time Elapsed: 00:00",self)
        self.poke_time_label = QLabel("Time since last poke: 00:00", self)
        self.red_label = QLabel("Number of Pokes: 0", self)
        self.blue_label = QLabel("Number of Trials: 0", self)
        self.green_label = QLabel("Number of Correct Trials: 0", self)
        self.fraction_correct_label = QLabel("Fraction Correct (FC): 0.000", self)
        self.rcp_label = QLabel("Rank of Correct Port (RCP): 0", self) # Check if correct 

        # Making Widgets for the labels
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

        # Create an HBoxLayout for start and stop buttons
        start_stop_layout = QHBoxLayout()
        start_stop_layout.addWidget(self.start_button)
        start_stop_layout.addWidget(self.stop_button)

        # Create a QVBoxLayout
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)  # Assuming self.view exists
        layout.addLayout(start_stop_layout)  # Add the QHBoxLayout to the QVBoxLayout
        layout.addLayout(self.details_layout)

        # Set the layout for the widget
        self.setLayout(layout)

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
        # Start the worker thread when the start button is pressed
        self.thread.start()
        print("Experiment Started!")
        QMetaObject.invokeMethod(self.worker, "start_sequence", Qt.QueuedConnection)

        # Start the plot
        self.main_window.plot_window.start_plot()

        # Start the timer
        self.start_time.start()
        self.timer.start(10)  # Update every second        

    def stop_sequence(self):
        # Stop the worker thread when the stop button is pressed
        QMetaObject.invokeMethod(self.worker, "stop_sequence", Qt.QueuedConnection)
        print("Experiment Stopped!")
        #self.thread.quit()

        # Stop the plot
        self.main_window.plot_window.stop_plot()

        # Stop the timer
        self.timer.stop()

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
        self.worker.save_results_to_csv()  # Call worker method to save results

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
        self.plot_graph.setTitle("Active Nosepoke vs Time", color="white", size="12pt")
        styles = {"color": "white", "font-size": "15px"}
        self.plot_graph.setLabel("left", "Nosepoke ID", **styles)
        self.plot_graph.setLabel("bottom", "Time", **styles)
        self.plot_graph.addLegend()
        self.plot_graph.showGrid(x=True, y=True)
        self.plot_graph.setYRange(1, 8)
        self.timestamps = []  # List to store timestamps
        self.signal = []  # List to store active Pi signals
        
        # Setting Initial Time Bar
        self.line_of_current_time_color = 0.5
        self.line_of_current_time = self.plot_graph.plot(x=[0, 0], y=[-1, 8], pen=pg.mkPen(self.line_of_current_time_color))

        # Plotting the initial graph
        self.line = self.plot_graph.plot(
            self.timestamps,
            self.signal,
            name="Active Pi",
            pen=None,
            symbol="o",
            symbolSize=1,
            symbolBrush="r",
        )

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
        self.time_bar_timer.start(100)  # Update every 100 milliseconds

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
            self.plot_graph.plot(
                [relative_time],
                [poked_port_value],
                pen=None,
                symbol="arrow_down",  # "o" for dots
                symbolSize=22,  # use 8 or lower if using dots
                symbolBrush=brush_color,
                symbolPen=None,
            )

    def update_plot(self):
        # Update plot with timestamps and signals
        self.line.setData(x=self.timestamps, y=self.signal)

class ConfigurationDetailsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Details")

        # Create labels to display configuration parameters
        self.name_label = QLabel(f"Name: {config['name']}")
        self.amplitude_label = QLabel(f"Amplitude: {config['amplitude_min']} - {config['amplitude_max']}")
        self.chunk_label = QLabel(f"Chunk Duration: {config['chunk_min']} - {config['chunk_max']}")
        self.pause_label = QLabel(f"Pause Duration: {config['pause_min']} - {config['pause_max']}")

        # Create button box with OK button
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.button_box.accepted.connect(self.accept)

        # Arrange widgets in a vertical layout
        layout = QVBoxLayout()
        layout.addWidget(self.name_label)
        layout.addWidget(self.amplitude_label)
        layout.addWidget(self.chunk_label)
        layout.addWidget(self.pause_label)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

class PresetTaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Name and Select Task")

        self.layout = QVBoxLayout(self)

        self.name_label = QLabel("Name:")
        self.name_edit = QLineEdit(self)

        self.task_label = QLabel("Select Task:")
        self.task_combo = QComboBox(self)
        self.task_combo.addItems(["Fixed", "Sweep", "Distractor", "Poketrain", "Audio"])  # Add your preset tasks here

        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)

        self.layout.addWidget(self.name_label)
        self.layout.addWidget(self.name_edit)
        self.layout.addWidget(self.task_label)
        self.layout.addWidget(self.task_combo)
        self.layout.addWidget(self.ok_button)

    def get_name_and_task(self):
        return self.name_edit.text(), self.task_combo.currentText()

class ConfigurationDialog(QDialog):
    def __init__(self, parent=None, name="", task="", config=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Configuration Details")
        self.name = name
        self.task = task
        self.config = config
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Create labels and line edits for configuration parameters
        self.name_label = QLabel(f"Name:")
        self.name_edit = QLineEdit(self.config["name"] if self.config else self.name)
        self.task_label = QLabel(f"Task:")
        self.task_combo = QComboBox()
        self.task_combo.addItems(["Fixed", "Sweep", "Distractor", "Poketrain", "Audio"])  # Add your preset tasks here
        self.task_combo.setCurrentText(self.config["task"] if self.config else self.task)
        self.amplitude_label = QLabel("Amplitude:")
        self.amplitude_min_edit = QLineEdit(str(self.config.get("amplitude_min", "")) if self.config else "")
        self.amplitude_max_edit = QLineEdit(str(self.config.get("amplitude_max", "")) if self.config else "")
        self.chunksize_label = QLabel("Chunk Duration:")
        self.chunksize_min_edit = QLineEdit(str(self.config.get("chunk_min", "")) if self.config else "")
        self.chunksize_max_edit = QLineEdit(str(self.config.get("chunk_max", "")) if self.config else "")
        self.pausesize_label = QLabel("Gap Duration:")
        self.pausesize_min_edit = QLineEdit(str(self.config.get("pause_min", "")) if self.config else "")
        self.pausesize_max_edit = QLineEdit(str(self.config.get("pause_max", "")) if self.config else "")

        # Create button box with OK and Cancel buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # Arrange widgets in a vertical layout
        amplitude_layout = QHBoxLayout()
        amplitude_layout.addWidget(self.amplitude_min_edit)
        amplitude_layout.addWidget(self.amplitude_max_edit)

        chunk_layout = QHBoxLayout()
        chunk_layout.addWidget(self.chunksize_min_edit)
        chunk_layout.addWidget(self.chunksize_max_edit)

        pause_layout = QHBoxLayout()
        pause_layout.addWidget(self.pausesize_min_edit)
        pause_layout.addWidget(self.pausesize_max_edit)

        layout.addWidget(self.name_label)
        layout.addWidget(self.name_edit)
        layout.addWidget(self.task_label)
        layout.addWidget(self.task_combo)
        layout.addWidget(self.amplitude_label)
        layout.addLayout(amplitude_layout)
        layout.addWidget(self.chunksize_label)
        layout.addLayout(chunk_layout)
        layout.addWidget(self.pausesize_label)
        layout.addLayout(pause_layout)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

    def get_configuration(self):
        try:
            amplitude_min = float(self.amplitude_min_edit.text())
            amplitude_max = float(self.amplitude_max_edit.text())
            chunk_min = float(self.chunksize_min_edit.text())
            chunk_max = float(self.chunksize_max_edit.text())
            pause_min = float(self.pausesize_min_edit.text())
            pause_max = float(self.pausesize_max_edit.text())
        except ValueError:
            # Handle invalid input
            return None
        
        return {
            "name": self.name_edit.text(),
            "task": self.task_combo.currentText(),
            "amplitude_min": amplitude_min,
            "amplitude_max": amplitude_max,
            "chunk_min": chunk_min,
            "chunk_max": chunk_max,
            "pause_min": pause_min,
            "pause_max": pause_max
        }

class ConfigurationList(QWidget):
    def __init__(self):
        super().__init__()
        self.configurations = []
        self.current_config = None
        self.default_parameters = self.load_default_parameters()
        self.init_ui()
        self.load_default()  # Call the method to load configurations from a default directory during initialization

        # Initialize ZMQ context and socket for publishing
        self.context = zmq.Context()
        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.bind("tcp://*:5556")  # Binding to port 5556 for publishing

    def init_ui(self):
        self.config_tree = QTreeWidget()
        self.config_tree.setHeaderLabels(["Configurations"])
        
        self.add_button = QPushButton('Add Config')
        self.remove_button = QPushButton('Remove Config')
        self.selected_config_label = QLabel()

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.selected_config_label)
        main_layout.addWidget(self.config_tree)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)
        self.add_button.clicked.connect(self.add_configuration)
        self.remove_button.clicked.connect(self.remove_configuration)
        self.setWindowTitle('Configuration List')
        self.show()

        # Context menu setup
        self.config_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.config_tree.customContextMenuRequested.connect(self.show_context_menu)
    
    def show_context_menu(self, pos):
        item = self.config_tree.itemAt(pos)
        if item and item.parent():  # Ensure it's a config item, not a category
            menu = QMenu(self)
            edit_action = QAction("Edit Configuration", self)
            edit_action.triggered.connect(lambda: self.edit_configuration(item))
            menu.addAction(edit_action)
            menu.exec_(self.config_tree.mapToGlobal(pos))

    def edit_configuration(self, item):
        selected_config = item.data(0, Qt.UserRole)
        dialog = ConfigurationDialog(self, selected_config["name"], selected_config["task"], selected_config)
        if dialog.exec_() == QDialog.Accepted:
            updated_config = dialog.get_configuration()
            # Update the configuration in the list
            index = self.configurations.index(selected_config)
            self.configurations[index] = updated_config
            self.update_config_list()


    def load_default_parameters(self):
        with open('/home/mouse/dev/paclab_sukrith/task/configs/defaults.json', 'r') as file:
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
                    "chunk_min": 0.0,
                    "chunk_max": 0.0,
                    "pause_min": 0.0,
                    "pause_max": 0.0
                }

            dialog = ConfigurationDialog(self, name, task, default_params)
            if dialog.exec_() == QDialog.Accepted:
                new_config = dialog.get_configuration()
                self.configurations.append(new_config)
                self.update_config_list()

                # Automatically save the configuration with the name included in the dialog
                config_name = new_config["name"]
                file_path = os.path.join("/home/mouse/dev/paclab_sukrith/task/configs/task", f"{config_name}.json")
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
            file_path = os.path.join("/home/mouse/dev/paclab_sukrith/task/configs/task", f"{config_name}.json")

            # Check if the file exists and delete it
            if os.path.exists(file_path):
                os.remove(file_path)

    def load_configurations(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Configuration Folder")
        if folder:
            self.configurations = self.import_configs_from_folder(folder)
            self.update_config_list()

    def load_default(self):
        default_directory = os.path.abspath("/home/mouse/dev/paclab_sukrith/task/configs/task")
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

    def update_config_list(self):
        self.config_tree.clear()
        categories = {}

        for config in self.configurations:
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

        self.config_tree.itemClicked.connect(self.config_item_clicked)

    def config_item_clicked(self, item):
        if item.parent():  # Ensure it's a config item, not a category
            selected_config = item.data(0, Qt.UserRole)
            self.current_config = selected_config
            self.selected_config_label.setText(f"Selected Config: {selected_config['name']}")
            dialog = ConfigurationDetailsDialog(selected_config, self)
            dialog.exec_()
            
            # Serialize JSON data and send it over ZMQ to all IPs connected
            json_data = json.dumps(selected_config)
            self.publisher.send_json(json_data)
    
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        # Main Window Title
        self.setWindowTitle("GUI")

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
        config_list_container.setFixedWidth(350)  # Limiting the width of the configuration list container
        config_list_container.setLayout(QVBoxLayout())
        config_list_container.layout().addWidget(self.config_list)

        pi_widget_container = QWidget()
        pi_widget_container.setFixedWidth(450)  # Limiting the width of the PiWidget container
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
        self.resize(2000, 800)
        self.show()

        # Connecting signals after the MainWindow is fully initialized
        self.Pi_widget.worker.pokedportsignal.connect(self.plot_window.handle_update_signal)
        self.Pi_widget.updateSignal.connect(self.plot_window.handle_update_signal)

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



