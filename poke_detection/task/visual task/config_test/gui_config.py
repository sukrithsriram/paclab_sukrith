# Importing necessary libraries
import sys
import zmq
import numpy as np
import time
import math
import pyqtgraph as pg
import random
import json
import csv
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QGraphicsEllipseItem, QListWidget, QListWidgetItem, QGraphicsTextItem, QGraphicsScene, QGraphicsView, QWidget, QVBoxLayout, QPushButton, QApplication, QHBoxLayout, QLineEdit, QListWidget, QFileDialog, QDialog, QLabel, QDialogButtonBox
from PyQt5.QtCore import QPointF, QTimer, pyqtSignal, QObject, QThread, pyqtSlot,  QMetaObject, Qt
from PyQt5.QtGui import QColor

# Creating a class for the individual Raspberry Pi signals
class PiSignal(QGraphicsEllipseItem):
    def __init__(self, index, total_Pis):
        super(PiSignal, self).__init__(0, 0, 50, 50)
        self.index = index
        self.total_Pis = total_Pis # Creating a variable for the total number of Pis
        self.label = QGraphicsTextItem(f"Pi-{index + 1}", self) # Label for each Pi
        self.label.setPos(25 - self.label.boundingRect().width() / 2, 25 - self.label.boundingRect().height() / 2) # Positioning the labels
        self.setPos(self.calculate_position()) # Positioning the individual Pi elements
        self.setBrush(QColor("gray")) # Setting the initial color of the Pi signals to red

    # Function to calculate the position of the Pi signals
    def calculate_position(self):  
        angle = 2 * math.pi * self.index / self.total_Pis # Arranging the Pi signals in a circle
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

class Worker(QObject):
    greenPiNumberSignal = pyqtSignal(int, str)

    def __init__(self, pi_widget):
        super().__init__()
        self.initial_time = None
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.bind("tcp://*:5555")

        self.last_pi_received = None
        self.timer = None
        self.pi_widget = pi_widget
        self.total_Pis = self.pi_widget.total_Pis 
        self.Pi_signals = self.pi_widget.Pi_signals 
        self.green_Pi_numbers = self.pi_widget.green_Pi_numbers 
        self.identities = set()
        
        # Initialize reward_port and related variables
        self.reward_port = None
        self.previous_port = None
        self.trials = 0

        # Placeholder for timestamps and ports visited
        self.timestamps = []
        self.reward_ports = []

    @pyqtSlot()
    def start_sequence(self):
        # Reset data when starting a new sequence
        self.initial_time = time.time()
        self.timestamps = []
        self.reward_ports = []

        # Randomly choose either 3 or 4 as the initial reward port
        self.reward_port = random.choice([1, 3, 5, 7])
        message = f"Reward Port: {self.reward_port}"
        print(message)
        
        # Send the message to all connected Pis
        for identity in self.identities:
            self.socket.send_multipart([identity, bytes(message, 'utf-8')])

        # Start the timer loop
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_Pi)
        self.timer.start(500)

    @pyqtSlot()
    def stop_sequence(self):
        if self.timer is not None: 
            self.timer.stop()
            self.timer.timeout.disconnect(self.update_Pi)

    @pyqtSlot()
    def update_Pi(self):
        current_time = time.time()
        elapsed_time = current_time - self.initial_time
        # Update the color of PiSignal objects based on the current Reward Port number
        for index, Pi in enumerate(self.Pi_signals):
            if index + 1 == self.reward_port:
                Pi.set_color("green")
            else:
                Pi.set_color("gray")

        # Receive message from the socket
        identity, message = self.socket.recv_multipart()
        self.identities.add(identity)
        self.socket.send_multipart([identity, bytes(f"Reward Port: {self.reward_port}", 'utf-8')])

        try:
            green_Pi = int(message)
            
            if 1 <= green_Pi <= self.total_Pis: 
                green_Pi_signal = self.Pi_signals[green_Pi - 1] 
                
                # Check if the received Pi number matches the current Reward Port
                if green_Pi == self.reward_port:
                    color = "green" if self.trials == 0 else "blue"
                    if self.trials > 0:
                        self.trials = 0  # Reset attempts since change
                else:
                    color = "red"
                    self.trials += 1
                
                # Set the color of the PiSignal object
                green_Pi_signal.set_color(color) 
                
                self.green_Pi_numbers.append(green_Pi) 
                print("Sequence:", self.green_Pi_numbers) 
                self.last_pi_received = identity
                
                # Emit the signal with the appropriate color
                self.greenPiNumberSignal.emit(green_Pi, color)
                
                # Record timestamp and port visited
                self.timestamps.append(elapsed_time)
                self.reward_ports.append(self.reward_port)
                
                if color == "green" or color == "blue":
                    for identity in self.identities:
                        self.socket.send_multipart([identity, b"Reward Poke Completed"])
                    self.reward_port = random.choice([1, 3, 5, 7])
                    self.trials = 0
                    print(f"Reward Port: {self.reward_port}")  # Print the updated Reward Port

                    # Send the message to all connected Pis
                    for identity in self.identities:
                        self.socket.send_multipart([identity, bytes(f"Reward Port: {self.reward_port}", 'utf-8')])

            else:
                print("Invalid Pi number received:", green_Pi)
        except ValueError:
            print("Connected to Raspberry Pi:", message)

    def save_results_to_csv(self):
        # Save results to a CSV file
        filename, _ = QFileDialog.getSaveFileName(None, "Save Results", "", "CSV Files (*.csv)")
        if filename:
            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Poke Timestamp (seconds)", "Port Visited", "Current Reward Port"])
                for timestamp, green_Pi, reward_port in zip(self.timestamps, self.green_Pi_numbers, self.reward_ports):
                    writer.writerow([timestamp, green_Pi, reward_port])

# Modify PiWidget Class
class PiWidget(QWidget):
    updateSignal = pyqtSignal(int, str) # Signal to emit the number and color of the active Pi
    resetSignal = pyqtSignal()

    def __init__(self, main_window):
        super(PiWidget, self).__init__()

        # Creating the GUI to display the Pi signals
        self.main_window = main_window
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.total_Pis = 8
        self.Pi_signals = [PiSignal(i, self.total_Pis) for i in range(self.total_Pis)]
        [self.scene.addItem(Pi) for Pi in self.Pi_signals]

        # Creating buttons to start and stop the sequence of communication with the Raspberry Pi
        self.green_Pi_numbers = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)

        self.start_button = QPushButton("Start Experiment")
        self.stop_button = QPushButton("Stop Experiment")
        self.save_results_button = QPushButton("Save Results")
        self.save_results_button.clicked.connect(self.save_results_to_csv)  # Connect save button to save method
        self.reset_button = QPushButton("Reset Experiment")
        self.reset_button.clicked.connect(self.reset_experiment)

        # Create an HBoxLayout for start and stop buttons
        start_stop_layout = QHBoxLayout()
        start_stop_layout.addWidget(self.start_button)
        start_stop_layout.addWidget(self.stop_button)

        # Create a QVBoxLayout
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)  # Assuming self.view exists
        layout.addLayout(start_stop_layout)  # Add the QHBoxLayout to the QVBoxLayout
        layout.addWidget(self.reset_button)
        layout.addWidget(self.save_results_button)  # Add save button to layout

        # Creating an instance of the Worker Class and a Thread to handle the communication with the Raspberry Pi
        self.worker = Worker(self)
        self.thread = QThread()
        self.worker.moveToThread(self.thread) # Move the worker object to the thread
        self.start_button.clicked.connect(self.start_sequence) # Connect the start button to the start_sequence function
        self.stop_button.clicked.connect(self.stop_sequence) # Connect the stop button to the stop_sequence function

        # Connect the greenPiNumberSignal from the Worker to a new slot
        self.worker.greenPiNumberSignal.connect(self.emit_update_signal) # Connect the greenPiNumberSignal to the emit_update_signal function

    # Function to emit the update signal
    def emit_update_signal(self, green_Pi_number, color):
        # Emit the updateSignal with the received green_Pi_number and color
        self.updateSignal.emit(green_Pi_number, color)

    def start_sequence(self):
        # Start the worker thread when the start button is pressed
        self.thread.start()
        print("Experiment Started!")
        QMetaObject.invokeMethod(self.worker, "start_sequence", Qt.QueuedConnection)

    def stop_sequence(self):
        # Stop the worker thread when the stop button is pressed
        QMetaObject.invokeMethod(self.worker, "stop_sequence", Qt.QueuedConnection)
        print("Experiment Stopped!")
        self.thread.quit()

    def save_results_to_csv(self):
        self.worker.save_results_to_csv()  # Call worker method to save results
    
    def reset_experiment(self):
        # Emit the reset signal
        self.stop_sequence()
        self.worker.reward_port = None
        self.worker.previous_port = None
        self.worker.trials = 0
        self.worker.timestamps = []
        self.worker.reward_ports = []
        self.worker.green_Pi_numbers = []
        self.resetSignal.emit()

class PlotWindow(QWidget):
    def __init__(self, pi_widget):
        super().__init__()

        self.is_active = False  # Flag to check if the Start Button is pressed
        self.timer = QTimer(self)  # Create a QTimer object

        # Entering the plot parameters and titles
        self.plot_graph = pg.PlotWidget()
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.plot_graph)
        self.plot_graph.setBackground("w")
        self.plot_graph.setTitle("Active Nosepoke vs Time", color="red", size="12pt")
        styles = {"color": "red", "font-size": "15px"}
        self.plot_graph.setLabel("left", "Nosepoke ID", **styles)
        self.plot_graph.setLabel("bottom", "Time", **styles)
        self.plot_graph.addLegend()
        self.plot_graph.showGrid(x=True, y=True)
        self.plot_graph.setYRange(1, 8)
        self.timestamps = []  # List to store timestamps
        self.signal = []  # List to store active Pi signals

        # Plotting the initial graph
        self.line = self.plot_graph.plot(
            self.timestamps,
            self.signal,
            name="Active Pi",
            pen=None,
            symbol="o",
            symbolSize=10,
            symbolBrush="r",
        )

        # Connecting to signals from PiWidget
        pi_widget.updateSignal.connect(self.handle_update_signal)
        # Connect the signal from Worker to a slot
        pi_widget.worker.greenPiNumberSignal.connect(self.plot_green_pi)
        # Connect the reset signal to the clear_plot slot
        pi_widget.resetSignal.connect(self.clear_plot)

    def start_plot(self):
        # Activating the plot window
        self.is_active = True
        self.timer.start()

    def stop_plot(self):
        # Deactivating the plot window
        self.is_active = False
        self.timer.stop()
    
    def clear_plot(self):
        # Clear the plot by clearing data lists
        self.timestamps.clear()
        self.signal.clear()
        # Update the plot with cleared data
        self.update_plot()

    def handle_update_signal(self, update_value):
        # Append current timestamp and update value to the lists
        self.timestamps.append(time.time())
        self.signal.append(update_value)
        self.update_plot()

    def plot_green_pi(self, green_pi_value, color):
        brush_color = "g" if color == "green" else "r" if color == "red" else "b"
        self.plot_graph.plot(
            [time.time()],
            [green_pi_value],
            pen=None,
            symbol="o",
            symbolSize=10,
            symbolBrush=brush_color,
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
        self.value_label = QLabel(f"Value: {config['value']}")
        self.frequency_label = QLabel(f"PWM Frequency: {config['pwm_frequency']}")
        self.duty_cycle_label = QLabel(f"PWM Duty Cycle: {config['pwm_duty_cycle']}")

        # Create button box with OK button
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.button_box.accepted.connect(self.accept)

        # Arrange widgets in a vertical layout
        layout = QVBoxLayout()
        layout.addWidget(self.name_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.frequency_label)
        layout.addWidget(self.duty_cycle_label)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

class ConfigurationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Configuration")

        # Create labels and line edits for configuration parameters
        self.name_label = QLabel("Name:")
        self.name_edit = QLineEdit()
        self.frequency_label = QLabel("PWM Frequency:")
        self.frequency_edit = QLineEdit()
        self.duty_cycle_label = QLabel("PWM Duty Cycle:")
        self.duty_cycle_edit = QLineEdit()

        # Create button box with OK and Cancel buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # Arrange widgets in a vertical layout
        layout = QVBoxLayout()
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_edit)
        layout.addWidget(self.frequency_label)
        layout.addWidget(self.frequency_edit)
        layout.addWidget(self.duty_cycle_label)
        layout.addWidget(self.duty_cycle_edit)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

    def get_configuration(self):
        name = self.name_edit.text()
        frequency = int(self.frequency_edit.text())
        duty_cycle = int(self.duty_cycle_edit.text())
        return {"name": name, "pwm_frequency": frequency, "pwm_duty_cycle": duty_cycle}

class ConfigurationList(QWidget):
    def __init__(self):
        super().__init__()
        self.configurations = []
        self.init_ui()
    
        # Create a ZMQ context and socket
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind("tcp://*:5556")  # Bind to a specific port

    # Creating the GUI for the Configuration List
    def init_ui(self):
        self.config_list = QListWidget()
        self.add_button = QPushButton('Add Config')
        self.remove_button = QPushButton('Remove Config')
        self.selected_config_label = QLabel()
        self.start_button = QPushButton('Send Config')

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.selected_config_label)
        main_layout.addWidget(self.config_list)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.start_button)

        self.setLayout(main_layout)
        self.add_button.clicked.connect(self.add_configuration)
        self.remove_button.clicked.connect(self.remove_configuration)
        self.start_button.clicked.connect(self.send_selected_config)
        self.setWindowTitle('Configuration List')
        self.show()

    # Function to add configurations to the list
    def add_configuration(self):
        dialog = ConfigurationDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            new_config = dialog.get_configuration()
            new_config["value"] = 0  # Placeholder value
            self.configurations.append(new_config)
            self.update_config_list()

    # Function to remove configurations from the list
    def remove_configuration(self):
        selected_item = self.config_list.currentItem()
        if selected_item:
            selected_config = selected_item.data(Qt.UserRole)
            self.configurations.remove(selected_config)
            self.update_config_list()

    # Function to update the configuration list
    def update_config_list(self):
        self.config_list.clear()
        for config in self.configurations:
            item = QListWidgetItem(config["name"])
            item.setData(Qt.UserRole, config)
            self.config_list.addItem(item)
        self.config_list.itemClicked.connect(self.config_item_clicked)

    def config_item_clicked(self, item):
        selected_config = item.data(Qt.UserRole)
        self.current_config = selected_config
        self.selected_config_label.setText(f"Selected Config: {selected_config['name']}")

    def send_selected_config(self):
        if self.current_config:
            # Send the configuration details over ZMQ
            topic = b"configuration"
            config_data = json.dumps(self.current_config).encode('utf-8')
            self.socket.send_multipart([topic, config_data])

    def update_config_list(self):
        self.config_list.clear()
        for config in self.configurations:
            item = QListWidgetItem(config["name"])
            item.setData(Qt.UserRole, config)
            self.config_list.addItem(item)
        # Connect the config_item_clicked method to the itemClicked signal
        self.config_list.itemClicked.connect(self.config_item_clicked)

    def config_item_clicked(self, item):
        selected_config = item.data(Qt.UserRole)
        self.current_config = selected_config
        self.selected_config_label.setText(f"Selected Config: {selected_config['name']}")
        dialog = ConfigurationDetailsDialog(selected_config, self)
        dialog.exec_()
    
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        # Main Window Title
        self.setWindowTitle("Experiment GUI")

        # Creating instances of PiWidget and ConfigurationList
        self.Pi_widget = PiWidget(self)
        self.config_list = ConfigurationList()

        # Initializing PlotWindow after PiWidget
        self.plot_window = PlotWindow(self.Pi_widget)

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
        self.resize(2000, 700)
        self.show()

        # Connecting signals after the MainWindow is fully initialized
        self.Pi_widget.worker.greenPiNumberSignal.connect(self.plot_window.handle_update_signal)
        self.Pi_widget.updateSignal.connect(self.plot_window.handle_update_signal)

    # Function to plot the Pi signals using the PlotWindow class
    def plot_green_pi(self, green_pi_value):
        self.plot_window.handle_update_signal(green_pi_value)

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
        
