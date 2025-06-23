import sys
import os
import datetime
from PyQt5 import QtWidgets, uic, QtGui, QtCore
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, QMutex, QMutexLocker
import pyqtgraph as pg
import serial
import serial.tools.list_ports
import re
from pyqtgraph.exporters import ImageExporter

from gui import Ui_MainWindow  # Replace with your UI class if necessary
from terminal_text_edit import TerminalTextEdit

# Serial Reader Thread
class SerialReaderThread(QThread):
    data_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = False

    def run(self):
        self.running = True
        while self.running and self.serial_port and self.serial_port.is_open:
            try:
                # Read up to 64 bytes (can adjust if needed)
                chunk = self.serial_port.read(64).decode(errors='ignore')
                if chunk:
                    # Emit chunk to MainWindow (this may be partial lines)
                    self.data_received.emit(chunk)
            except Exception as e:
                self.error_occurred.emit(str(e))
                break

    def stop(self):
        self.running = False





class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.setupUi(self)

        # Terminal widget (promoted in Qt Designer)
        self.terminal = self.TerminalTextEdit

        # This buffer will accumulate partial data until we find '\n'
        self.input_buffer = ""

        # Connect send mechanisms for commands
        self.SendButton.clicked.connect(self.send_cmd_text)
        self.CMDtextEdit.returnPressed.connect(self.send_cmd_text)

        # Setup plot
        self.plotWidget.setBackground('white')
        self.plotWidget.showGrid(x=True, y=True)
        self.plotWidget.setLabel('left', 'Distance (m)')
        self.plotWidget.setLabel('bottom', 'Measurement count')
        legend = self.plotWidget.addLegend()
        if legend is not None:
            for _, label in legend.items:
                label.setStyleSheet("color: #222222; font-size: 12pt; font-weight: bold;")

        # Dictionary to store data by (anchor_id, type_str)
        self.plot_data = {}

        # Anchor colors keyed by anchor_id
        self.anchor_colors = {
            1: 'r',    # Red
            2: 'g',    # Green
            3: 'b',    # Blue
            4: 'm',    # Magenta
            5: 'y',    # Yellow
            6: 'k',    # Black
            7: 'c',    # Cyan
            8: 'orange',
            9: 'purple',
            10: 'brown',
            11: 'pink',
            12: 'lime',
            13: 'navy',
            14: 'teal',
            15: 'olive',
            16: 'maroon',
        }

        # Setup Baud rate combo box
        self.baudRateComboBox.addItems(['9600', '115200', '921600'])

        # Connect action buttons
        self.TclearButton.clicked.connect(self.clear_terminal)
        self.ClearButton.clicked.connect(self.clear_plot)
        self.SaveButton.clicked.connect(self.save_plot)

        # Serial objects
        self.serial = None
        self.serial_thread = None

        # Logging
        self.is_logging = False
        self.log_file = None
        self.log_mutex = QMutex()

        # Start/Stop, Log
        self.StartButton.clicked.connect(self.toggle_serial)
        self.LogButton.clicked.connect(self.toggle_logging)

        # Additional command buttons
        self.command_buttons = {
            self.PairButton: "sd op",
            self.PassiveButton: "sd pe",
            self.BondlistButton: "listbd",
            self.FactoryResetButton: "factoryreset",
            self.ResetButton: "reset",
        }

        # Connect command buttons
        for button, command in self.command_buttons.items():
            button.clicked.connect(lambda _, cmd=command: self.send_command(cmd))

        # Window Size Slider
        self.windowSizeSlider.setMinimum(10)
        self.windowSizeSlider.setMaximum(1000)
        self.windowSizeSlider.setValue(100)
        self.windowSizeSlider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.windowSizeSlider.setTickInterval(100)
        self.windowSizeSlider.valueChanged.connect(self.update_window_size)

        # COM port refresh timer
        self.com_ports_refresh_timer = QTimer()
        self.com_ports_refresh_timer.timeout.connect(self.refresh_com_ports)
        self.com_ports_refresh_timer.start(1000)

        # Initialize COM ports
        self.refresh_com_ports()

        # Optional: create tray icon now (or lazily when needed)
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        # Use application icon for notifications (or set your own)
        self.tray_icon.setIcon(self.windowIcon())

    def init_anchor_data(self, anchor_id, device_id, type_str):
        """
        Initialize plot data structures for a new (anchor_id, device_id, type_str).
        """
        key = (anchor_id, device_id, type_str)
        self.plot_data[key] = {
            "x": [],
            "y": [],
            "count": 0,
            "curve": None
        }

        # Pick color for this anchor (default black), offset for device
        base_colors = list(self.anchor_colors.values())
        color_idx = (anchor_id - 1) % len(base_colors)
        color = base_colors[color_idx]
        # Slightly change color for each device (if needed, can use more advanced coloring)
        if device_id > 1:
            color = pg.intColor((color_idx * 5 + device_id) % 16)
        legend_name = f"Anchor_{anchor_id}_Device_{device_id}_{type_str}"

        plot_line = self.plotWidget.plot(
            pen=color,
            symbol='o',
            symbolPen=color,
            symbolBrush=color,
            name=legend_name
        )
        self.plot_data[key]["curve"] = plot_line


    def send_cmd_text(self):
        command = self.CMDtextEdit.text()
        if command.strip():  # Check if command is not empty
            self.CMDtextEdit.clear()
            self.send_command(command)

    def handle_serial_data(self, chunk):
        """Accumulate chunk into input_buffer. Split on newline to get full lines."""
        # Write raw chunk to terminal for debugging/visibility
        self.terminal.append_text(chunk)

        # Accumulate chunk into self.input_buffer
        self.input_buffer += chunk

        # Process complete lines if we have them
        while "\n" in self.input_buffer:
            line, self.input_buffer = self.input_buffer.split("\n", 1)
            line = line.strip("\r")  # remove trailing carriage return if present
            line = line.strip()      # remove extra whitespace

            if not line:
                continue  # skip empty lines

            # Parse location : (x,y) and update region GUI
            loc_match = re.search(r"location\s*:\s*\((-?\d*\.?\d+),\s*(-?\d*\.?\d+)\)", line, re.IGNORECASE)
            if loc_match:
                x = float(loc_match.group(1))
                y = float(loc_match.group(2))
                self.update_location_region(x, y)
                continue

            # Check OEM command lines
            if "Received OEM App Command:" in line:
                self.show_oem_notification(line)

            # Try to match with device id: Anchor 1 Device 2 Distance RAW: 3.45
            match = re.search(r"Anchor\s+(\d+)\s+Device\s+(\d+)\s+Distance\s+(\S+):\s+([\d\.]+)", line)
            if match:
                anchor_id = int(match.group(1))
                device_id = int(match.group(2))
                type_str = match.group(3)
                distance_value = float(match.group(4))
                key = (anchor_id, device_id, type_str)
                if key not in self.plot_data:
                    self.init_anchor_data(anchor_id, device_id, type_str)
                self.plot_data[key]["count"] += 1
                count_val = self.plot_data[key]["count"]
                self.plot_data[key]["x"].append(count_val)
                self.plot_data[key]["y"].append(distance_value)
                window_size = self.windowSizeSlider.value()
                if len(self.plot_data[key]["x"]) > window_size:
                    self.plot_data[key]["x"] = self.plot_data[key]["x"][-window_size:]
                    self.plot_data[key]["y"] = self.plot_data[key]["y"][-window_size:]
                curve = self.plot_data[key]["curve"]
                curve.setData(self.plot_data[key]["x"], self.plot_data[key]["y"])
                if self.is_logging and self.log_file:
                    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    log_line = f"{timestamp},Anchor {anchor_id} Device {device_id} {type_str},{distance_value}\n"
                    with QMutexLocker(self.log_mutex):
                        self.log_file.write(log_line)
                        self.log_file.flush()
                continue
            # Fallback: old format (no device id)
            match = re.search(r"Anchor\s+(\d+)\s+Distance\s+(\S+):\s+([\d\.]+)", line)
            if match:
                anchor_id = int(match.group(1))
                device_id = 1  # Default device id if not present
                type_str = match.group(2)
                distance_value = float(match.group(3))
                key = (anchor_id, device_id, type_str)
                if key not in self.plot_data:
                    self.init_anchor_data(anchor_id, device_id, type_str)
                self.plot_data[key]["count"] += 1
                count_val = self.plot_data[key]["count"]
                self.plot_data[key]["x"].append(count_val)
                self.plot_data[key]["y"].append(distance_value)
                window_size = self.windowSizeSlider.value()
                if len(self.plot_data[key]["x"]) > window_size:
                    self.plot_data[key]["x"] = self.plot_data[key]["x"][-window_size:]
                    self.plot_data[key]["y"] = self.plot_data[key]["y"][-window_size:]
                curve = self.plot_data[key]["curve"]
                curve.setData(self.plot_data[key]["x"], self.plot_data[key]["y"])
                if self.is_logging and self.log_file:
                    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    log_line = f"{timestamp},Anchor {anchor_id} Device {device_id} {type_str},{distance_value}\n"
                    with QMutexLocker(self.log_mutex):
                        self.log_file.write(log_line)
                        self.log_file.flush()
            else:
                print(f"(Debug) No anchor match: {line}")

    def show_oem_notification(self, line):
        """
        Show a styled notification in the center of the app for 1 second.
        """
        try:
            tokens = line.split("Received OEM App Command:", 1)
            if len(tokens) > 1:
                command = tokens[1].strip()
                if command:
                    # Create notification label if not exists
                    if not hasattr(self, '_oem_notification_label'):
                        self._oem_notification_label = QtWidgets.QLabel(self)
                        self._oem_notification_label.setAlignment(QtCore.Qt.AlignCenter)
                        self._oem_notification_label.setStyleSheet('''
                            QLabel {
                                background-color: #222;
                                color: #fff;
                                border-radius: 12px;
                                padding: 24px 48px;
                                font-size: 20px;
                                font-weight: bold;
                                border: 2px solid #4CAF50;
                                box-shadow: 0px 4px 16px rgba(0,0,0,0.3);
                            }
                        ''')
                        self._oem_notification_label.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.ToolTip)
                        self._oem_notification_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
                    self._oem_notification_label.setText(command)
                    # Center the label in the main window
                    self._oem_notification_label.adjustSize()
                    w = self._oem_notification_label.width()
                    h = self._oem_notification_label.height()
                    x = (self.width() - w) // 2
                    y = (self.height() - h) // 2
                    self._oem_notification_label.setGeometry(x, y, w, h)
                    self._oem_notification_label.show()
                    # Hide after 1 second
                    QtCore.QTimer.singleShot(2000, self._oem_notification_label.hide)
        except Exception as e:
            print(f"Error parsing OEM command: {e}")

    def handle_serial_error(self, error_message):
        QtWidgets.QMessageBox.critical(self, "Error", f"Serial Error: {error_message}")
        self.stop_serial()

    def toggle_serial(self):
        if self.serial is None or not self.serial.is_open:
            port = self.comPortComboBox.currentText()
            if port != 'None':
                try:
                    baud = int(self.baudRateComboBox.currentText())
                    self.serial = serial.Serial(port, baud, timeout=0.1)

                    self.serial_thread = SerialReaderThread(self.serial)
                    self.serial_thread.data_received.connect(self.handle_serial_data)
                    self.serial_thread.error_occurred.connect(self.handle_serial_error)
                    self.serial_thread.start()

                    self.StartButton.setText("Stop")
                    self.comPortComboBox.setEnabled(False)
                    self.baudRateComboBox.setEnabled(False)
                except Exception as e:
                    QtWidgets.QMessageBox.critical(
                        self, "Error", f"Could not open port {port}: {str(e)}"
                    )
                    self.serial = None
            else:
                QtWidgets.QMessageBox.warning(self, "Warning", "No valid serial port selected.")
        else:
            self.stop_serial()

    def stop_serial(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None
        if self.serial:
            self.serial.close()
            self.serial = None
        self.StartButton.setText("Start")
        self.comPortComboBox.setEnabled(True)
        self.baudRateComboBox.setEnabled(True)

        # Clear out any leftover data in buffer
        self.input_buffer = ""


    def clear_terminal(self):
        self.terminal.clear()
    def clear_plot(self):
        self.plot_data.clear()
        self.plotWidget.clear()
        self.plotWidget.addLegend()
        # Make legend font darker and bold
        legend = self.plotWidget.legend
        if legend is not None:
            for _, label in legend.items:
                label.setStyleSheet("color: #222222; font-size: 12pt; font-weight: bold;")

    def save_plot(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Plot", "", "PNG Files (*.png);;All Files (*)"
        )
        if filename:
            try:
                exporter = ImageExporter(self.plotWidget.plotItem)
                exporter.export(filename)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Could not save plot: {str(e)}")

    def toggle_logging(self):
        if not self.is_logging:
            options = QtWidgets.QFileDialog.Options()
            options |= QtWidgets.QFileDialog.DontUseNativeDialog
            log_filename, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Select Log File",
                "",
                "Log Files (*.log);;Text Files (*.txt);;All Files (*)",
                options=options
            )
            if log_filename:
                # Determine extension from filter
                if selected_filter.startswith("Log Files"):
                    default_ext = ".log"
                elif selected_filter.startswith("Text Files"):
                    default_ext = ".txt"
                else:
                    default_ext = ""

                if not os.path.splitext(log_filename)[1]:
                    log_filename += default_ext

                try:
                    self.log_file = open(log_filename, 'a')
                    self.log_file.write("Timestamp,Anchor_Type,Distance\n")
                    self.is_logging = True
                    self.LogButton.setText("Stop Logging")
                except Exception as e:
                    QtWidgets.QMessageBox.critical(
                        self, "Error", f"Could not open log file: {str(e)}"
                    )
                    self.log_file = None
            else:
                self.is_logging = False
        else:
            self.is_logging = False
            self.LogButton.setText("Start Logging")
            if self.log_file:
                self.log_file.close()
                self.log_file = None

    def refresh_com_ports(self):
        current_ports = [port.device for port in serial.tools.list_ports.comports()]
        current_ports.insert(0, 'None')
        if self.comPortComboBox.isEnabled():
            prev_sel = self.comPortComboBox.currentText()
            self.comPortComboBox.clear()
            self.comPortComboBox.addItems(current_ports)
            if prev_sel in current_ports:
                idx = self.comPortComboBox.findText(prev_sel)
                self.comPortComboBox.setCurrentIndex(idx)
            else:
                self.comPortComboBox.setCurrentIndex(0)

    def update_window_size(self, value):
        """
        Trim anchor data sets to 'value' points and redraw.
        """
        for key, anchor_dict in self.plot_data.items():
            if len(anchor_dict["x"]) > value:
                anchor_dict["x"] = anchor_dict["x"][-value:]
                anchor_dict["y"] = anchor_dict["y"][-value:]
            anchor_dict["curve"].setData(anchor_dict["x"], anchor_dict["y"])

    def send_command(self, command):
        if self.serial and self.serial.is_open:
            try:
                # Send the command over serial
                self.serial.write((command + '\n').encode())
                # Optionally, display the sent command in the terminal
                self.terminal.append_text(f"> {command}\n")
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Error", f"Failed to send command: {str(e)}")
        else:
            QtWidgets.QMessageBox.warning(self, "Warning", "Serial port is not open.")
    def closeEvent(self, event):
        self.stop_serial()
        if self.log_file:
            self.log_file.close()
        event.accept()

    def update_location_region(self, x, y):
        # Car dimensions: width=2, height=1.5, center at (0,0)
        # Boundaries
        half_width = 0.5
        half_height = 0.25
        region = None
        # Check inside
        if -half_width <= x <= half_width and -half_height <= y <= half_height:
            region = 'inside'
        elif y > half_height:
            region = 'front'
        elif y < -half_height:
            region = 'behind'
        elif x < -half_width:
            region = 'left'
        elif x > half_width:
            region = 'right'
        else:
            region = 'unknown'

        # Set all to red, then set the active one to green
        default_styles = {
            'front': "background-color: #e53935; color: white; border-radius: 8px;",
            'behind': "background-color: #e53935; color: white; border-radius: 8px;",
            'left': "background-color: #e53935; color: white; border-radius: 8px;",
            'right': "background-color: #e53935; color: white; border-radius: 8px;",
            'inside': "background-color: #d32f2f; color: white; border-radius: 8px; font-weight: bold;"
        }
        green_style = "background-color: #43a047; color: white; border-radius: 8px; font-weight: bold;"
        # Reset all
        self.regionFront.setStyleSheet(default_styles['front'])
        self.regionBehind.setStyleSheet(default_styles['behind'])
        self.regionLeft.setStyleSheet(default_styles['left'])
        self.regionRight.setStyleSheet(default_styles['right'])
        self.regionInside.setStyleSheet(default_styles['inside'])
        # Set green for the detected region
        if region == 'front':
            self.regionFront.setStyleSheet(green_style)
        elif region == 'behind':
            self.regionBehind.setStyleSheet(green_style)
        elif region == 'left':
            self.regionLeft.setStyleSheet(green_style)
        elif region == 'right':
            self.regionRight.setStyleSheet(green_style)
        elif region == 'inside':
            self.regionInside.setStyleSheet(green_style)
        # Update the Location label
        self.Location.setText(f"({x:.2f}, {y:.2f})  [{region.capitalize()}]")


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
