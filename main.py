import sys
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
import random
import time
from collections import deque
import threading
from questions import questions

# Knightboard Class from documentation
class KnightBoard:
    def __init__(self, serial_port: str, num_channels: int):
        self.params = BrainFlowInputParams()
        self.params.serial_port = serial_port
        self.params.other_info = '{"gain": 6}'
        self.num_channels = num_channels

        self.board_shim = BoardShim(BoardIds.NEUROPAWN_KNIGHT_BOARD.value, self.params)
        self.board_id = self.board_shim.get_board_id()
        self.eeg_channels = self.board_shim.get_exg_channels(self.board_id)
        self.sampling_rate = self.board_shim.get_sampling_rate(self.board_id)

    def start_stream(self, buffer_size: int = 450000):
        self.board_shim.prepare_session()

        # Configure channels BEFORE streaming
        for x in range(1, self.num_channels + 1):
            cmd = f"chon_{x}_12"
            self.board_shim.config_board(cmd)
            print(f"Activating channel {x}: {cmd}")

            rld = f"rldadd_{x}"
            self.board_shim.config_board(rld)

        self.board_shim.start_stream(buffer_size)
        print("Stream started accurately.")

    def stop_stream(self):
        if self.board_shim.is_prepared():
            self.board_shim.stop_stream()
            self.board_shim.release_session()
            print("Stream stopped and session released.")

# Main class for visualizer 
class MainWindow(QMainWindow):
    def __init__(self, board):
        super().__init__()
        
        # Initialization
        self.setWindowTitle("My App")
        self.setFixedSize(QSize(600, 600))
        
        # Getting board channels
        self.board = board
        self.ch3_index = board.eeg_channels[2] 
        self.ch7_index = board.eeg_channels[6]

        self.plot_graph = pg.PlotWidget()
        self.setCentralWidget(self.plot_graph)

        self.start_time = time.time()

        self.max_points = 1000 
        
        # This just clears the points when it gets too large
        self.points = deque(maxlen=self.max_points)

        self.curve = self.plot_graph.plot(pen=pg.mkPen("g", width=1))
        
        #This starts a timer to continously update the graph after 40 miliseconds
        self.timer = QTimer()
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.update_plot)
        self.timer.start()
    
    # Method to detect spikes in the graph
    def detect_spike(self):
        if len(self.points) < 30:  # If there is insufficient data, it returns as no spike
            return
        

        current_time = self.points[-1][0] # points data is set up as (([time], [values])...), so it goes to the latest point and its time value
        
        # Makes sure the y values is in a range of a second 
        y_values = [y for x, y in self.points if current_time - x <= 0.4]
        if not y_values:
            return
        if sum(y_values) / len(y_values) >= 20000:
            return False

        data_array = np.array(y_values)
        mean = np.mean(data_array) # mean function gets the average of the data
        std = np.std(data_array) # this is the standard deviation, it still confuses me cuz its statistics and stuff, but basically its how far apart data is spread from the average, this is used to detect spikes
        threshold = mean + 2.5 * std # minimum value for a spike, depends on standard deviation and average
        
        latest_value = self.points[-1][1] # gets the latest y value

        max_of_y = max(y_values)
        min_of_y = min(y_values)
        average_of_y = sum(y_values) / len(y_values)

        if latest_value > threshold and std > 5.0 and ((latest_value > average_of_y + (latest_value* 0.1)) or (latest_value< -average_of_y + (-latest_value * 1.1))): # if the value is greater than the threshold, and the data has variation, it will detect a spike
            return True
        return False

    # Method to update plot
    def update_plot(self):
        data = self.board.board_shim.get_board_data() # get board data
        
        if data.size > 0:
            samples_ch3 = data[self.ch3_index, :]
            samples_ch7 = data[self.ch7_index, :]
            

            y_array = (samples_ch3 + samples_ch7) / 2.0 # get the average data between channel 3 and 7
            num_new_samples = len(y_array)
            

            current_timestamp = time.time() - self.start_time
            
            time_step = 1.0 / self.board.sampling_rate  # calculates the time when each data point was read. sampling rate is how fast it takes for the board to collect a piece of data
            
            for i, val in enumerate(y_array): # packs the data together and puts it in the points list

                sample_time = current_timestamp - (num_new_samples - 1 - i) * time_step
                self.points.append((sample_time, val))
            

            xs, ys = zip(*self.points) # gets all the time values and the brain values
            self.curve.setData(xs, ys)
            
    # stops the knightboard when the app is closed
    def closeEvent(self, event):
        self.board.stop_stream()
        event.accept()


# spike detector function, it just runs in the background when a question is asked and listens for spikes
global spike_detected
def spike_watcher(window, stop_event):
    global spike_detected
    while not stop_event.is_set():
        if window.detect_spike():
            spike_detected = True
            return
        time.sleep(0.001)
    spike_detected = False
    
# asks questions
def question_loop(window):
    while True:
        window.can_close = False
        window.points = []

        stop_event = threading.Event()

        watcher = threading.Thread(target=spike_watcher, args=(window, stop_event))
        watcher.start()
        print("Answer the next question, if you want to stop the lie detector, say: stop")

        answer = input(random.choice(questions))

        stop_event.set()
        watcher.join()

        window.can_close = True

        if spike_detected:
            print("You lied!")
            time.sleep(5)
            window.points = []
        elif answer.lower() != "stop":
            print("You didn't lie!")
            time.sleep(5)
            window.points = []

        if answer.lower() == "stop":
            QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)
            break
        
app = QApplication(sys.argv)

Knight_board = KnightBoard("COM3", 8)
Knight_board.start_stream()

window = MainWindow(Knight_board)
window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
window.show()
window.raise_()
window.activateWindow()

t = threading.Thread(target=question_loop, args=(window,), daemon=True)
t.start()

sys.exit(app.exec())


