class Worker(QObject):
    # ... [other methods]

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
        self.chunk_durations.clear()
        self.pause_durations.clear()
        self.unique_ports_visited.clear()
        self.identities.clear()
        self.last_poke_timestamp = None
        self.reward_port = None
        self.previous_port = None
        self.trials = 0
        self.average_unique_ports = 0

class PiWidget(QWidget):
    # ... [other methods]

    def stop_sequence(self):
        QMetaObject.invokeMethod(self.worker, "stop_sequence", Qt.QueuedConnection)
        print("Experiment Stopped!")
        
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

class PlotWindow(QWidget):
    # ... [other methods]

    def stop_plot(self):
        self.is_active = False
        self.timer.stop()
        self.time_bar_timer.stop()
        self.clear_plot()

    def clear_plot(self):
        self.timestamps.clear()
        self.signal.clear()
        self.line.setData(x=[], y=[])
        self.line_of_current_time.setData(x=[], y=[])
