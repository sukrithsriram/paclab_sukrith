class ConfigurationDetailsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Details")
        self.config = config

        # Create QLineEdit to allow editing of the name
        self.name_label = QLabel("Name:")
        self.name_edit = QLineEdit(config['name'])
        
        self.task_label = QLabel(f"Task: {config['task']}")
        self.amplitude_label = QLabel(f"Amplitude: {config['amplitude_min']} - {config['amplitude_max']}")
        self.chunk_label = QLabel(f"Chunk Duration: {config['chunk_min']} - {config['chunk_max']}")
        self.pause_label = QLabel(f"Pause Duration: {config['pause_min']} - {config['pause_max']}")

        # Create button box with OK and Cancel buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # Arrange widgets in a vertical layout
        layout = QVBoxLayout()
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_edit)
        layout.addWidget(self.task_label)
        layout.addWidget(self.amplitude_label)
        layout.addWidget(self.chunk_label)
        layout.addWidget(self.pause_label)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

    def get_updated_config(self):
        self.config['name'] = self.name_edit.text()
        return self.config

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

        # Enable custom context menu
        self.config_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.config_tree.customContextMenuRequested.connect(self.show_context_menu)

    def load_default_parameters(self):
        with open('/home/mouse/dev/paclab_sukrith/pi/configs/defaults.json', 'r') as file:
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
                file_path = os.path.join("/home/mouse/dev/paclab_sukrith/pi/configs/task", f"{config_name}.json")
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
        default_directory = os.path.abspath("/home/mouse/dev/paclab_sukrith/pi/configs/task")
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

    def show_context_menu(self, pos):
        item = self.config_tree.itemAt(pos)
        if item and item.parent():  # Ensure it's a config item, not a category
            menu = QMenu(self)
            edit_action = QAction("Edit Configuration", self)
            view_action = QAction("View Details", self)
            edit_action.triggered.connect(lambda: self.edit_configuration(item))
            view_action.triggered.connect(lambda: self.view_configuration_details(item))
            menu.addAction(edit_action)
            menu.addAction(view_action)
            menu.exec_(self.config_tree.mapToGlobal(pos))

    def edit_configuration(self, item):
        selected_config = item.data(0, Qt.UserRole)
        dialog = ConfigurationDialog(self, selected_config["name"], selected_config["task"], selected_config)
        if dialog.exec_() == QDialog.Accepted:
            updated_config = dialog.get_configuration()
            if updated_config:
                # Update the configuration in the list
                index = self.configurations.index(selected_config)
                self.configurations[index] = updated_config
                self.update_config_list()

                # Automatically save the updated configuration
                config_name = updated_config["name"]
                file_path = os.path.join("/home/mouse/dev/paclab_sukrith/pi/configs/task", f"{config_name}.json")
                with open(file_path, 'w') as file:
                    json.dump(updated_config, file, indent=4)

    def view_configuration_details(self, item):
        selected_config = item.data(0, Qt.UserRole)
        dialog = ConfigurationDetailsDialog(selected_config, self)
        if dialog.exec_() == QDialog.Accepted:
            updated_config = dialog.get_updated_config()
            if updated_config:
                # Update the configuration in the list
                index = self.configurations.index(selected_config)
                self.configurations[index] = updated_config
                self.update_config_list()

                # Automatically save the updated configuration
                config_name = updated_config["name"]
                file_path = os.path.join("/home/mouse/dev/paclab_sukrith/pi/configs/task", f"{config_name}.json")
                with open(file_path, 'w') as file:
                    json.dump(updated_config, file, indent=4)
            
            
---------------------------------------------------
            
class ConfigurationList(QWidget):
    # Existing code...

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
                file_path = os.path.join("/home/mouse/dev/paclab_sukrith/pi/configs/task", f"{config_name}.json")
                with open(file_path, 'w') as file:
                    json.dump(new_config, file, indent=4)
------------------------------------------------------------------
            
from PyQt5.QtWidgets import QMessageBox

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

        # Add the config list (assuming it's a QListWidget)
        self.config_list = QListWidget(self)  # Add your config list widget here
        self.config_list.addItems(["Config1", "Config2", "Config3"])  # Example items, replace with your configs

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
        layout.addWidget(self.config_list)  # Add the config list to the layout
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
        # Check if a config is selected
        if not self.config_list.currentItem():
            QMessageBox.warning(self, "Warning", "Please select a config before starting the experiment.")
            return

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

--------------------------------------------
class PiWidget(QWidget):
    # Define a signal to be emitted when the start button is clicked
    startButtonClicked = pyqtSignal()

    def __init__(self, main_window, *args, **kwargs):
        super(PiWidget, self).__init__(*args, **kwargs)

        # Initialize the start button
        self.start_button = QPushButton("Start Experiment")
        self.start_button.clicked.connect(self.on_start_button_clicked)
        
        # Other initializations...
        
    def on_start_button_clicked(self):
        # Emit the signal when the start button is clicked
        self.startButtonClicked.emit()
        
        # Other code related to starting the sequence...

class ConfigurationList(QWidget):
    configselectSignal = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        # Other initializations...
        
    def on_start_button_clicked(self):
        if self.current_config is None:
            QMessageBox.warning(self, "Warning", "Please select a mouse before starting the experiment.")
        else:
            # Proceed with the experiment start sequence using self.current_config
            print("Starting experiment with configuration:", self.current_config)
            self.configselectSignal.emit()  # Emit the signal to notify the configuration is selected

class MainApplication(QMainWindow):
    def __init__(self):
        super(MainApplication, self).__init__()
        
        self.config_list = ConfigurationList()
        self.pi_widget = PiWidget(self)
        
        # Connect the startButtonClicked signal to the on_start_button_clicked slot
        self.pi_widget.startButtonClicked.connect(self.config_list.on_start_button_clicked)
        
        # Layout and other initializations...

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    main_window = MainApplication()
    main_window.show()
    sys.exit(app.exec_())

--------------------------------------------------

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QMessageBox, QGraphicsScene, QGraphicsView, QTreeWidget, QTreeWidgetItem, QDialog, QMenu, QAction, QFileDialog
from PyQt5.QtCore import pyqtSignal, Qt, QTime, QTimer
import zmq
import json
import os
import sys

class PiWidget(QWidget):
    startButtonClicked = pyqtSignal()

    def __init__(self, main_window, *args, **kwargs):
        super(PiWidget, self).__init__(*args, **kwargs)

        self.main_window = main_window
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.total_ports = 8
        self.Pi_signals = [PiSignal(i, self.total_ports) for i in range(self.total_ports)]
        [self.scene.addItem(Pi) for Pi in self.Pi_signals]

        self.config_list = QListWidget(self)
        self.config_list.addItems(["Config1", "Config2", "Config3"])

        self.start_button = QPushButton("Start Experiment")
        self.stop_button = QPushButton("Stop Experiment")
        self.stop_button.clicked.connect(self.save_results_to_csv)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time_elapsed)

        self.start_time = QTime(0, 0)
        self.poke_time = QTime(0, 0)

        self.red_count = 0
        self.blue_count = 0
        self.green_count = 0

        self.details_layout = QVBoxLayout()
        self.time_label = QLabel("Time Elapsed: 00:00", self)
        self.poke_time_label = QLabel("Time since last poke: 00:00", self)
        self.red_label = QLabel("Number of Pokes: 0", self)
        self.blue_label = QLabel("Number of Trials: 0", self)
        self.green_label = QLabel("Number of Correct Trials: 0", self)
        self.fraction_correct_label = QLabel("Fraction Correct (FC): 0.000", self)
        self.rcp_label = QLabel("Rank of Correct Port (RCP): 0")

        self.details_layout.addWidget(self.time_label)
        self.details_layout.addWidget(self.poke_time_label)
        self.details_layout.addWidget(self.red_label)
        self.details_layout.addWidget(self.blue_label)
        self.details_layout.addWidget(self.green_label)
        self.details_layout.addWidget(self.fraction_correct_label)
        self.details_layout.addWidget(self.rcp_label)

        self.last_poke_timer = QTimer()
        self.last_poke_timer.timeout.connect(self.update_last_poke_time)

        start_stop_layout = QHBoxLayout()
        start_stop_layout.addWidget(self.start_button)
        start_stop_layout.addWidget(self.stop_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.view)
        layout.addWidget(self.config_list)
        layout.addLayout(start_stop_layout)
        layout.addLayout(self.details_layout)

        self.setLayout(layout)

        self.start_button.clicked.connect(self.on_start_button_clicked)
        self.stop_button.clicked.connect(self.stop_sequence)

    def on_start_button_clicked(self):
        self.startButtonClicked.emit()

    def stop_sequence(self):
        print("Experiment Stopped!")
        self.timer.stop()

    def update_time_elapsed(self):
        elapsed_time = self.start_time.elapsed() / 1000.0
        minutes, seconds = divmod(elapsed_time, 60)
        self.time_label.setText(f"Time elapsed: {str(int(minutes)).zfill(2)}:{str(int(seconds)).zfill(2)}")

    def update_last_poke_time(self):
        current_time = time.time()
        elapsed_time = current_time - self.last_poke_timestamp
        minutes, seconds = divmod(elapsed_time, 60)
        self.poke_time_label.setText(f"Time since last poke: {str(int(minutes)).zfill(2)}:{str(int(seconds)).zfill(2)}")

    def save_results_to_csv(self):
        pass

class ConfigurationList(QWidget):
    configselectSignal = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.configurations = []
        self.current_config = None
        self.default_parameters = self.load_default_parameters()
        self.init_ui()
        self.load_default()

        self.context = zmq.Context()
        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.bind("tcp://*:5556")

    def init_ui(self):
        self.config_tree = QTreeWidget()
        self.config_tree.setHeaderLabels(["Tasks"])
        
        self.add_button = QPushButton('Add Mouse')
        self.remove_button = QPushButton('Remove Mouse')
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

        self.config_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.config_tree.customContextMenuRequested.connect(self.show_context_menu)

    def load_default_parameters(self):
        with open('/home/mouse/dev/paclab_sukrith/pi/configs/defaults.json', 'r') as file:
            return json.load(file)

    def add_configuration(self):
        pass

    def remove_configuration(self):
        pass

    def load_configurations(self):
        pass

    def load_default(self):
        default_directory = os.path.abspath("/home/mouse/dev/paclab_sukrith/pi/configs/task")
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

        self.config_tree.itemDoubleClicked.connect(self.config_item_clicked)

    def config_item_clicked(self, item, column):
        if item.parent():
            selected_config = item.data(0, Qt.UserRole)
            self.current_config = selected_config
            self.selected_config_label.setText(f"Selected Config: {selected_config['name']}")

            confirm_dialog = QMessageBox()
            confirm_dialog.setIcon(QMessageBox.Question)
            confirm_dialog.setText(f"Do you want to use '{selected_config['name']}'?")
            confirm_dialog.setWindowTitle("Confirm Configuration")
            confirm_dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            confirm_dialog.setDefaultButton(QMessageBox.Yes)
            
            if confirm_dialog.exec_() == QMessageBox.Yes:
                json_data = json.dumps(selected_config)
                self.publisher.send_json(json_data)
            else:
                self.selected_config_label.setText(f"Selected Config: None")

    def show_context_menu(self, pos):
        pass

    def on_start_button_clicked(self):
        if self.current_config is None:
            QMessageBox.warning(self, "Warning", "Please select a config before starting the experiment.")
        else:
            print("Starting experiment with configuration:", self.current_config)
            self.configselectSignal.emit()

class MainApplication(QMainWindow):
    def __init__(self):
        super(MainApplication, self).__init__()
        
        self.config_list = ConfigurationList()
        self.pi_widget = PiWidget(self)
        
        self.pi_widget.startButtonClicked.connect(self.config_list.on_start_button_clicked)
        
        layout = QVBoxLayout()
        layout.addWidget(self.pi_widget)
        layout.addWidget(self.config_list)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.setWindowTitle('Main Application')

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = MainApplication()
    main_window.show()
    sys.exit(app.exec_())
-----------------------------------------------------------------------------------------------------------

class PiWidget(QWidget):
    startButtonClicked = pyqtSignal()

    def __init__(self, main_window, *args, **kwargs):
        super(PiWidget, self).__init__(*args, **kwargs)
        self.main_window = main_window
        self.thread = QThread()
        self.worker = Worker()
        self.worker.moveToThread(self.thread)

        # Connect the start button to the start sequence method
        self.start_button.clicked.connect(self.start_sequence)

        # Ensure the ConfigurationList slot is connected
        self.startButtonClicked.connect(self.main_window.config_list.on_start_button_clicked)

    def start_sequence(self):
        self.startButtonClicked.emit()
        
        if self.main_window.config_list.current_config is None:
            QMessageBox.warning(self, "Warning", "Please select a config before starting the experiment.")
            return
        
        # Start the worker thread when the start button is pressed
        self.thread.start()
        print("Experiment Started!")
        QMetaObject.invokeMethod(self.worker, "start_sequence", Qt.QueuedConnection)

        # Start the plot
        self.main_window.plot_window.start_plot()

        # Start the timer
        self.start_time.start()
        self.timer.start(10)  # Update every second

class ConfigurationList(QWidget):
    configselectSignal = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.configurations = []
        self.current_config = None
        self.default_parameters = self.load_default_parameters()
        self.init_ui()
        self.load_default()

        self.context = zmq.Context()
        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.bind("tcp://*:5556")

    def init_ui(self):
        self.config_tree = QTreeWidget()
        self.config_tree.setHeaderLabels(["Tasks"])
        
        self.add_button = QPushButton('Add Mouse')
        self.remove_button = QPushButton('Remove Mouse')
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

        self.config_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.config_tree.customContextMenuRequested.connect(self.show_context_menu)

    def load_default_parameters(self):
        with open('/home/mouse/dev/paclab_sukrith/pi/configs/defaults.json', 'r') as file:
            return json.load(file)

    def add_configuration(self):
        # Your implementation here
        pass

    def remove_configuration(self):
        # Your implementation here
        pass

    def load_configurations(self):
        # Your implementation here
        pass

    def load_default(self):
        default_directory = os.path.abspath("/home/mouse/dev/paclab_sukrith/pi/configs/task")
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

        self.config_tree.itemDoubleClicked.connect(self.config_item_clicked)

    def config_item_clicked(self, item, column):
        if item.parent():
            selected_config = item.data(0, Qt.UserRole)
            self.current_config = selected_config
            self.selected_config_label.setText(f"Selected Config: {selected_config['name']}")

            confirm_dialog = QMessageBox()
            confirm_dialog.setIcon(QMessageBox.Question)
            confirm_dialog.setText(f"Do you want to use '{selected_config['name']}'?")
            confirm_dialog.setWindowTitle("Confirm Configuration")
            confirm_dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            confirm_dialog.setDefaultButton(QMessageBox.Yes)
            
            if confirm_dialog.exec_() == QMessageBox.Yes:
                json_data = json.dumps(selected_config)
                self.publisher.send_json(json_data)
            else:
                self.selected_config_label.setText(f"Selected Config: None")

    def show_context_menu(self, pos):
        # Your implementation here
        pass

    def on_start_button_clicked(self):
        if self.current_config is None:
            QMessageBox.warning(self, "Warning", "Please select a config before starting the experiment.")
        else:
            print("Starting experiment with configuration:", self.current_config)
            self.configselectSignal.emit()


class MainApplication(QMainWindow):
    def __init__(self):
        super(MainApplication, self).__init__()
        
        self.config_list = ConfigurationList()
        self.pi_widget = PiWidget(self)
        
        self.pi_widget.startButtonClicked.connect(self.config_list.on_start_button_clicked)
        
        layout = QVBoxLayout()
        layout.addWidget(self.pi_widget)
        layout.addWidget(self.config_list)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.setWindowTitle('Main Application')

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = MainApplication()
    main_window.show()
    sys.exit(app.exec_())

-------------------------------------------------------------------------

from PyQt5.QtWidgets import (
    QWidget, QTreeWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QMessageBox, QLineEdit, QAction, QMenu, QDialog,
    QTreeWidgetItem, QFileDialog, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal
import zmq
import json
import os

class ConfigurationList(QWidget):
    confingselectSignal = pyqtSignal()
    
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

        # Load configurations into the tree
        self.update_config_list()

    def filter_configurations(self, text):
        if not text:
            self.update_config_list()
            return
        
        filtered_configs = []
        for config in self.configurations:
            if text.lower() in config["name"].lower():
                filtered_configs.append(config)

        self.update_config_list(filtered_configs)

    def load_default_parameters(self):
        with open('/home/mouse/dev/paclab_sukrith/pi/configs/defaults.json', 'r') as file:
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
                file_path = os.path.join("/home/mouse/dev/paclab_sukrith/pi/configs/task", f"{config_name}.json")
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
            file_path = os.path.join("/home/mouse/dev/paclab_sukrith/pi/configs/task", f"{config_name}.json")

            # Check if the file exists and delete it
            if os.path.exists(file_path):
                os.remove(file_path)

    def load_configurations(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Configuration Folder")
        if folder:
            self.configurations = self.import_configs_from_folder(folder)
            self.update_config_list()

    def load_default(self):
        default_directory = os.path.abspath("/home/mouse/dev/paclab_sukrith/pi/configs/task")
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
            else:
                # Setting selected config to none
                self.selected_config_label.setText(f"Selected Config: None")

                pass

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
                file_path = os.path.join("/home/mouse/dev/paclab_sukrith/pi/configs/task", f"{config_name}.json")
                with open(file_path, 'w') as file:
                    json.dump(updated_config, file, indent=4)


    def view_configuration_details(self, item):
        selected_config = item.data(0, Qt.UserRole)
        dialog = ConfigurationDetailsDialog(selected_config, self)
        dialog.exec_()

# Example usage
if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    window = ConfigurationList()
    sys.exit(app.exec_())

---------------------------------------------------

from datetime import datetime

def save_results_to_csv(self):
    # Generate filename based on selected configuration and current date-time
    if self.current_config:
        config_name = self.current_config["name"]
    else:
        config_name = "unnamed_mouse"  # Default name if no configuration is selected
    
    current_datetime = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{config_name}_{current_datetime}.csv"

    # Ask user for confirmation to save
    confirm_dialog = QMessageBox()
    confirm_dialog.setIcon(QMessageBox.Question)
    confirm_dialog.setText(f"Do you want to save the results to '{filename}'?")
    confirm_dialog.setWindowTitle("Confirm Save")
    confirm_dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    confirm_dialog.setDefaultButton(QMessageBox.Yes)

    if confirm_dialog.exec_() == QMessageBox.Yes:
        # Proceed with saving to the generated filename
        with open(filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Poke Timestamp (seconds)", "Port Visited", "Current Reward Port"])
            for timestamp, poked_port, reward_port in zip(self.timestamps, self.poked_port_numbers, self.reward_ports):
                writer.writerow([timestamp, poked_port, reward_port])
        QMessageBox.information(self, "Save Successful", f"Results saved to '{filename}'.")
    else:
        QMessageBox.information(self, "Save Cancelled", "Save operation cancelled by user.")
    
    
------------------------------------------------------------
    
from PyQt5.QtCore import pyqtSignal, QObject

class ConfigurationList(QWidget):
    # Define a signal to emit the selected configuration
    send_config_signal = pyqtSignal(dict)

    # Existing code...

    def config_item_clicked(self, item, column):
        if item.parent():  # Ensure it's a config item, not a category
            selected_config = item.data(0, Qt.UserRole)
            self.current_config = selected_config
            self.selected_config_label.setText(f"Selected Config: {selected_config['name']}")
            
            # Emit signal with selected configuration
            self.send_config_signal.emit(selected_config)

from PyQt5.QtCore import QObject, pyqtSignal

class Worker(QObject):
    def __init__(self, pi_widget):
        super().__init__()
        self.pi_widget = pi_widget
        self.current_config = None  # Initialize current_config attribute

        # Connect to the send_config_signal from ConfigurationList
        self.pi_widget.send_config_signal.connect(self.receive_config)

    def receive_config(self, config):
        # Method to receive the selected configuration from ConfigurationList
        self.current_config = config
        print("Received configuration:", self.current_config)
        # Use the received configuration as needed in your worker logic

    def save_results_to_csv(self):
        if self.current_config:
            # Generate filename based on selected configuration and current date-time
            config_name = self.current_config["name"]
            current_datetime = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{config_name}_{current_datetime}.csv"

            # Proceed with saving to the generated filename
            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Poke Timestamp (seconds)", "Port Visited", "Current Reward Port"])
                for timestamp, poked_port, reward_port in zip(self.timestamps, self.poked_port_numbers, self.reward_ports):
                    writer.writerow([timestamp, poked_port, reward_port])
            print(f"Results saved to '{filename}'.")
        else:
            print("No configuration selected to save results.")

    # Other methods and logic in Worker class...


# Example of setting up ConfigurationList and Worker

# Assuming pi_widget is passed correctly to both ConfigurationList and Worker
pi_widget = ...  # Instantiate pi_widget as needed

# Create ConfigurationList instance
config_list = ConfigurationList()
# Create Worker instance
worker = Worker(pi_widget)

# Connect ConfigurationList's send_config_signal to Worker's receive_config method
config_list.send_config_signal.connect(worker.receive_config)

# Example usage: when saving results to CSV from ConfigurationList
# This assumes you have a mechanism to trigger save_results_to_csv in Worker, adjust as per your application flow
worker.save_results_to_csv()



