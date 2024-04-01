# Importing necessary libraries
import sys
import zmq
import numpy as np
import time
import math
import pyqtgraph as pg
import random
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QGraphicsEllipseItem, QGraphicsTextItem, QGraphicsScene, QGraphicsView, QWidget, QVBoxLayout, QPushButton, QApplication, QHBoxLayout, QLineEdit, QListWidget
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

    @pyqtSlot()
    def start_sequence(self):
        # Randomly choose either 3 or 4
        self.reward_port = random.choice([1,3 ,5,7])
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
                
                if color == "green" or color == "blue":
                    for identity in self.identities:
                        self.socket.send_multipart([identity, b"Reward Poke Completed"])
                    self.reward_port = random.choice([1,3, 5, 7])
                    self.trials = 0
                    print(f"Reward Port: {self.reward_port}")  # Print the updated Reward Port

                    # Send the message to all connected Pis
                    for identity in self.identities:
                        self.socket.send_multipart([identity, bytes(f"Reward Port: {self.reward_port}", 'utf-8')])

            else:
                print("Invalid Pi number received:", green_Pi)
        except ValueError:
            print("Connected to Raspberry Pi:", message)

# Creating a class for the Window that manages and displays the sequence of Pi signals
class PiWidget(QWidget):
    updateSignal = pyqtSignal(int, str) # Signal to emit the number and color of the active Pi

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

        # Arranging the GUI in a vertical layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)

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

    def start_plot(self):
        # Activating the plot window
        self.is_active = True
        self.timer.start()

    def stop_plot(self):
        # Deactivating the plot window
        self.is_active = False
        self.timer.stop()

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


# Creating a class to enter a list of subjects
class SubjectList(QWidget):
    def __init__(self):
        super().__init__()

        self.subjects = []
        self.init_ui()

    # Creating the GUI for the Subject List 
    def init_ui(self):
        self.subject_list = QListWidget()
        self.subject_entry = QLineEdit()

        # Creating buttons to add and remove subjects
        self.add_button = QPushButton('Add Subject')
        self.remove_button = QPushButton('Remove Subject')

        # Arranging the buttons in a horizontal layout
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)

        # Arranging the GUI in a vertical layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.subject_entry)
        main_layout.addWidget(self.subject_list)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)
        self.add_button.clicked.connect(self.add_subject)
        self.remove_button.clicked.connect(self.remove_subject)

        self.setWindowTitle('Subject List')
        self.show()

    # Function to add subjects to the list
    def add_subject(self):
        subject_text = self.subject_entry.text()
        if subject_text:
            self.subjects.append(subject_text)
            self.update_subject_list()
            self.subject_entry.clear()

    # Function to remove subjects from the list
    def remove_subject(self):
        selected_item = self.subject_list.currentItem()
        if selected_item:
            selected_subject = selected_item.text()
            self.subjects.remove(selected_subject)
            self.update_subject_list()

    # Function to update the subject list
    def update_subject_list(self):
        self.subject_list.clear()
        self.subject_list.addItems(self.subjects)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        # Main Window Title
        self.setWindowTitle("Experiment GUI")

        # Creating instances of PiWidget and SubjectList
        self.Pi_widget = PiWidget(self)
        self.subject_list = SubjectList()

        # Initializing PlotWindow after PiWidget
        self.plot_window = PlotWindow(self.Pi_widget)

        # Creating container widgets for each component
        subject_list_container = QWidget()
        subject_list_container.setFixedWidth(300)  # Limiting the width of the subject list container
        subject_list_container.setLayout(QVBoxLayout())
        subject_list_container.layout().addWidget(self.subject_list)

        pi_widget_container = QWidget()
        pi_widget_container.setFixedWidth(450)  # Limiting the width of the PiWidget container
        pi_widget_container.setLayout(QVBoxLayout())
        pi_widget_container.layout().addWidget(self.Pi_widget)

        # Setting the central widget as a container widget for all components
        container_widget = QWidget(self)
        container_layout = QHBoxLayout(container_widget)
        container_layout.addWidget(subject_list_container)
        container_layout.addWidget(pi_widget_container)
        container_layout.addWidget(self.plot_window)
        self.setCentralWidget(container_widget)

        # Setting the dimensions of the main window
        self.resize(2000, 600)
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
        
