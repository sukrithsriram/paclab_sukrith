# Importing necessary libraries
import sys
import zmq
import numpy as np
import math
import pyqtgraph as pg
import random
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QGraphicsEllipseItem, QGraphicsTextItem, QGraphicsScene, QGraphicsView, QWidget, QVBoxLayout, QPushButton, QApplication, QHBoxLayout, QLineEdit, QListWidget
from PyQt5.QtCore import QPointF, QTimer, pyqtSignal, QObject
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

class PiWidgetSignals(QObject):
    greenPiSignal = pyqtSignal(int)
    updateSignal = pyqtSignal(int)

# Creating a class for the Widget that controls the behavior of the individual Pi signals
class PiWidget(QWidget):
    def __init__(self, main_window):
        super(PiWidget, self).__init__()

        self.main_window = main_window # Creating a variable for the main window
        self.scene = QGraphicsScene(self) 
        self.view = QGraphicsView(self.scene)

        self.total_Pis = 8 # Setting the total number of Pis
        self.Pi_signals = [PiSignal(i, self.total_Pis) for i in range(self.total_Pis)]  # Creating a list of Pi signals
        [self.scene.addItem(Pi) for Pi in self.Pi_signals]

        self.green_Pi_numbers = []  # Creating an empty list to log which Pi signals turn green

        self.timer = QTimer(self)  # Creating a timer
        self.timer.timeout.connect(self.update_Pi) # Connecting the timer to the update_Pi function

        # Creating buttons to start and stop the experiment
        self.start_button = QPushButton("Start Experiment") 
        self.start_button.clicked.connect(self.start_sequence)

        self.stop_button = QPushButton("Stop Experiment")
        self.stop_button.clicked.connect(self.stop_sequence)

        # Arranging the buttons and the Widget in a vertical layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        
        # Creating a ZeroMQ context and socket for communication with the Raspberry Pi
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER) # Using the ROUTER socket
        self.socket.bind("tcp://*:5555")  # Binding to all IP addresses on port 5555
        self.last_pi_received = None  # Initialize attribute to record the last pi that sent a message
        self.signals = PiWidgetSignals()  # Creating an instance of the PiWidgetSignals class

    def start_sequence(self):
        self.timer.start(2000)
        self.main_window.plot_window.start_plot()

    def stop_sequence(self):
        self.timer.stop()
        self.main_window.plot_window.stop_plot()

    def update_Pi(self):
        # Setting all Pis to red
        for Pi in self.Pi_signals:
            Pi.set_red()

        # Receiving a message from the Raspberry Pi
        identity, message = self.socket.recv_multipart()

        # Extracting the Pi number from the received message
        try:
            green_Pi = int(message)
            if 1 <= green_Pi <= self.total_Pis:
                green_Pi_signal = self.Pi_signals[green_Pi - 1]
                green_Pi_signal.set_green()

                # Recording the sequence in which the Pis play audio
                self.green_Pi_numbers.append(green_Pi)
                self.main_window.plot_green_pi(green_Pi)

                # Emit signals to update the GUI in the main thread
                # self.signals.greenPiSignal.emit(green_Pi)
                # self.signals.updateSignal.emit(green_Pi)

                # Printing the sequence in which the Pis play audio
                print("Sequence:", self.green_Pi_numbers)

                # Sending an acknowledgement to the Raspberry Pi
                self.socket.send_multipart([identity, b"ACK"])
                self.last_pi_received = identity

            else:
                print("Invalid Pi number received:", green_Pi)
        except ValueError:
            print("Invalid message received from the Raspberry Pi:", message)

# Creating a class to dynamically plot the sequence in which the Pis play audio
class PlotWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.is_active = False  # Flag to check if the Start Button is pressed

        # Entering the plot parameters and titles
        self.plot_graph = pg.PlotWidget()
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.plot_graph)
        self.plot_graph.setBackground("w")
        self.plot_graph.setTitle("Active Pi vs Time", color="red", size="18pt")
        styles = {"color": "red", "font-size": "15px"}
        self.plot_graph.setLabel("left", "Active Pi Number", **styles)
        self.plot_graph.setLabel("bottom", "Time (s)", **styles)
        self.plot_graph.addLegend()
        self.plot_graph.showGrid(x=True, y=True)
        self.plot_graph.setYRange(1, 8)
        self.time = []
        self.signal = []

        # Plotting the initial graph
        self.line = self.plot_graph.plot(
            self.time,
            self.signal,
            name="Active Pi",
            pen=None,
            symbol="o",
            symbolSize=15,
            symbolBrush="g",
        )

        # Adding a timer to match when the Widget is active and changes color
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.update_plot)

    def start_plot(self):
        # Activating the plot window
        self.is_active = True
        self.timer.start()

    def stop_plot(self):
        # Deactivating the plot window
        self.is_active = False
        self.timer.stop()

    def update_signal(self, green_Pi_number):
        # This method is called by the PiWidget class to update the signal
        self.signal.append(green_Pi_number)
        # Setting the timer to start only if the button is pressed
        self.timer.start()

    # Function to update the plot in the PlotWindow class
    def update_plot(self):
        if not self.time:
            # Setting initial time to 0
            self.time.append(0)
        else:
            # Setting the increment time 
            self.time.append(self.time[-1] + 1)

        # Making the signal a 1D array
        signal_array = np.array(self.signal).flatten()

        # Creating new lists that plot points at the same intervals as PiWidget
        time_point = self.time[::2]
        signal_point = signal_array[::2]

        # Ensure time_point and signal_point have the same length
        min_length = min(len(time_point), len(signal_point))
        time_point = time_point[:min_length]
        signal_point = signal_point[:min_length]

        self.line.setData(x=time_point, y=signal_point)

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

# Creating the main window of the GUI
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        # Main Window Title
        self.setWindowTitle("Experiment GUI")

        # Creating instances of PlotWindow, PiWidget, and SubjectList
        self.Pi_widget = PiWidget(self)
        self.plot_window = PlotWindow()
        self.subject_list = SubjectList()

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

    # Function to plot the Pi signals using the PlotWindow class
    def plot_green_pi(self, green_pi_value):
        self.plot_window.update_signal(green_pi_value)
        self.plot_window.update_plot()

# Running the GUI
if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = MainWindow()
    sys.exit(app.exec())
