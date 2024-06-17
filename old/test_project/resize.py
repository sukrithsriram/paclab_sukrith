class PiWidget(QWidget):
    startButtonClicked = pyqtSignal()
    updateSignal = pyqtSignal(int, str)

    def __init__(self, main_window, *args, **kwargs):
        super(PiWidget, self).__init__(*args, **kwargs)

        self.main_window = main_window
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.total_ports = 8
        self.Pi_signals = [PiSignal(i, self.total_ports) for i in range(self.total_ports)]
        [self.scene.addItem(Pi) for Pi in self.Pi_signals]

        self.poked_port_numbers = []

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
        layout.addLayout(start_stop_layout)
        layout.addLayout(self.details_layout)

        self.setLayout(layout)

        self.worker = Worker(self)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.start_button.clicked.connect(self.start_sequence)
        self.stop_button.clicked.connect(self.stop_sequence)

        self.worker.pokedportsignal.connect(self.emit_update_signal)
        self.worker.pokedportsignal.connect(self.reset_last_poke_time)
        self.worker.pokedportsignal.connect(self.calc_and_update_avg_unique_ports)

    def emit_update_signal(self, poked_port_number, color):
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
        self.thread.start()
        print("Experiment Started!")
        QMetaObject.invokeMethod(self.worker, "start_sequence", Qt.QueuedConnection)

        self.main_window.plot_window.start_plot()

        self.start_time.start()
        self.timer.start(10)

    def stop_sequence(self):
        QMetaObject.invokeMethod(self.worker, "stop_sequence", Qt.QueuedConnection)
        print("Experiment Stopped!")
        self.main_window.plot_window.stop_plot()
        self.timer.stop()

    @pyqtSlot()
    def update_time_elapsed(self):
        elapsed_time = self.start_time.elapsed() / 1000.0
        minutes, seconds = divmod(elapsed_time, 60)
        self.time_label.setText(f"Time elapsed: {str(int(minutes)).zfill(2)}:{str(int(seconds)).zfill(2)}")

    @pyqtSlot()
    def reset_last_poke_time(self):
        self.last_poke_timer.stop()
        self.last_poke_timer.start(1000)

    @pyqtSlot()
    def calc_and_update_avg_unique_ports(self):
        self.worker.calculate_average_unique_ports()
        average_unique_ports = self.worker.average_unique_ports
        self.rcp_label.setText(f"Rank of Correct Port: {average_unique_ports:.2f}")

    @pyqtSlot()
    def update_last_poke_time(self):
        current_time = time.time()
        elapsed_time = current_time - self.last_poke_timestamp
        minutes, seconds = divmod(elapsed_time, 60)
        self.poke_time_label.setText(f"Time since last poke: {str(int(minutes)).zfill(2)}:{str(int(seconds)).zfill(2)}")

    def save_results_to_csv(self):
        self.worker.save_results_to_csv()

    def resizeEvent(self, event):
        rect = self.view.rect()
        self.scene.setSceneRect(rect)
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        super(PiWidget, self).resizeEvent(event)
