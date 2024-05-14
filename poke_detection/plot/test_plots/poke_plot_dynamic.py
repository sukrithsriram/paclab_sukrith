# Importing necessary libraries
import sys
import zmq
import numpy as np
import time
import math
import pyqtgraph as pg
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
        self.setBrush(QColor("red")) # Setting the initial color of the Pi signals to red

    # Function to calculate the position of the Pi signals
    def calculate_position(self):  
        angle = 2 * math.pi * self.index / self.total_Pis # Arranging the Pi signals in a circle
        radius = 150
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        return QPointF(200 + x, 200 + y)

    # Function to set the Pi signals to green
    def set_green(self):  
        self.setBrush(QColor("green"))

    # Function to set the Pi signals to red
    def set_red(self):  
        self.setBrush(QColor("red"))

#  Worker Class to handle the communication with the Raspberry Pi
class Worker(QObject):
    greenPiNumberSignal = pyqtSignal(int) # Signal to emit the number of the active Pi

    def __init__(self, pi_widget):
        super().__init__()
        
        # Creating a ZeroMQ context and socket for communication with the Raspberry Pi
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER) # Using the ROUTER socket
        self.socket.bind("tcp://*:5555") # Binding to all sockets on the port on the local IP address
        
        self.last_pi_received = None
        self.timer = None  # Initialize timer as None
        self.pi_widget = pi_widget
        self.total_Pis = self.pi_widget.total_Pis 
        self.Pi_signals = self.pi_widget.Pi_signals 
        self.green_Pi_numbers = self.pi_widget.green_Pi_numbers 
        self.identities = set()  # Store unique identities for all incoming communications

    # Function to start the sequence of communication with the Raspberry Pi
    @pyqtSlot() # Decorator to indicate that the following function is a slot (used for connecting signals from other threads to slots in other classes)
    def start_sequence(self):
        self.timer = QTimer()  # Create QTimer object in worker thread
        self.timer.timeout.connect(self.update_Pi) 
        self.timer.start(500)

    # Function to stop the sequence of communication with the Raspberry Pi
    @pyqtSlot()
    def stop_sequence(self):
        if self.timer is not None: 
            self.timer.stop()
            self.timer.timeout.disconnect(self.update_Pi)  # Disconnect the timeout signal from the update_Pi slot

    # Function to update the Pi signals
    @pyqtSlot()
    def update_Pi(self):
        # Setting all Pis to red
        for Pi in self.Pi_signals:
            Pi.set_red()

        # Receiving messages from the Raspberry Pi with it's identity
        identity, message = self.socket.recv_multipart()
        self.identities.add(identity) # Add the identity to the set of identities (used to close the program on the pis when the GUI is closed)

        # Extracting the Pi number from the received message
        try:
            green_Pi = int(message) # Convert the message to an integer
            if 1 <= green_Pi <= self.total_Pis: 
                green_Pi_signal = self.Pi_signals[green_Pi - 1] 
                green_Pi_signal.set_green() # Set the active Pi to green
                
                # Recording and Printing the sequence of active Pis
                self.green_Pi_numbers.append(green_Pi) 
                print("Sequence:", self.green_Pi_numbers) 
                
                # Sending an acknowledgment to the Raspberry Pi that sent an incoming signal
                self.socket.send_multipart([identity, b"ACK"])
                self.last_pi_received = identity

                # Emit a signal with the new updated green_Pi to another class
                self.greenPiNumberSignal.emit(green_Pi)
            else:
                print("Invalid Pi number received:", green_Pi)
        except ValueError:
            print("Invalid message received from the Raspberry Pi:", message)
    
    # Function to stop the Pis from sending messages when the GUI is closed
    def close(self):
        for identity in self.identities:
            self.socket.send_multipart([identity, b"CLOSE"])  # Send acknowledgement to each identity

# Creating a class for the Window that manages and displays the sequence of Pi signals
class PiWidget(QWidget):
    updateSignal = pyqtSignal(int) # Signal to emit the number of the active Pi

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
    def emit_update_signal(self, green_Pi_number):
        # Emit the updateSignal with the received green_Pi_number
        self.updateSignal.emit(green_Pi_number)

    def update(self):
        pass
    
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

        # Entering the plot parameters and titles
        self.plot_graph = pg.PlotWidget()
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.plot_graph)
        self.plot_graph.setBackground("w")
        self.plot_graph.setTitle("Active Pi vs Time", color="red", size="12pt")
        styles = {"color": "red", "font-size": "15px"}
        self.plot_graph.setLabel("left", "Active Pi Number", **styles)
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
            symbolBrush="g",
        )

        # Connecting to signals from PiWidget
        pi_widget.updateSignal.connect(self.handle_update_signal)

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

        # Setting the central widget as a container widget for all components
        container_widget = QWidget(self)
        container_layout = QHBoxLayout(container_widget)
        container_layout.addWidget(self.subject_list)
        container_layout.addWidget(self.Pi_widget)
        container_layout.addWidget(self.plot_window)
        self.setCentralWidget(container_widget)

        # Setting the dimensions of the main window
        self.resize(1400, 600)
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
        
