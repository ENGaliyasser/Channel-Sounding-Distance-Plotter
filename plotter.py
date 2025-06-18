
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


class TerminalTextEdit(QtWidgets.QTextEdit):
    def __init__(self, parent=None):
        super(TerminalTextEdit, self).__init__(parent)
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setUndoRedoEnabled(False)
        self.moveCursor(QtGui.QTextCursor.End)

    def append_text(self, text):
        self.moveCursor(QtGui.QTextCursor.End)
        self.insertPlainText(text)
        self.moveCursor(QtGui.QTextCursor.End)

    def write_data(self, data):
        self.append_text(data)


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
        self.plotWidget.addLegend()

        # Dictionary to store data by (anchor_id, type_str)
        self.plot_data = {}

        # Anchor colors keyed by anchor_id
        self.anchor_colors = {
            1: 'r',
            2: 'g',
            3: 'b',
            4: 'm',
            5: 'y',
            6: 'k'
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

    def init_anchor_data(self, anchor_id, type_str):
        """
        Initialize plot data structures for a new (anchor_id, type_str).
        """
        key = (anchor_id, type_str)
        self.plot_data[key] = {
            "x": [],
            "y": [],
            "count": 0,
            "curve": None
        }

        # Pick color for this anchor (default black)
        color = self.anchor_colors.get(anchor_id, 'k')
        legend_name = f"Anchor_{anchor_id}_{type_str}"

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

            # Check OEM command lines
            if "Received OEM App Command:" in line:
                self.show_oem_notification(line)

            # Attempt to parse anchor lines
            match = re.search(r"Anchor\s+(\d+)\s+Distance\s+(\S+):\s+([\d\.]+)", line)
            if match:
                anchor_id = int(match.group(1))
                type_str = match.group(2)
                distance_value = float(match.group(3))

                # Make sure we have a plot for this anchor/type
                key = (anchor_id, type_str)
                if key not in self.plot_data:
                    self.init_anchor_data(anchor_id, type_str)

                # Append data
                self.plot_data[key]["count"] += 1
                count_val = self.plot_data[key]["count"]
                self.plot_data[key]["x"].append(count_val)
                self.plot_data[key]["y"].append(distance_value)

                # Trim based on slider
                window_size = self.windowSizeSlider.value()
                if len(self.plot_data[key]["x"]) > window_size:
                    self.plot_data[key]["x"] = self.plot_data[key]["x"][-window_size:]
                    self.plot_data[key]["y"] = self.plot_data[key]["y"][-window_size:]

                # Update plot
                curve = self.plot_data[key]["curve"]
                curve.setData(self.plot_data[key]["x"], self.plot_data[key]["y"])

                # If logging is active, write to log
                if self.is_logging and self.log_file:
                    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    log_line = f"{timestamp},Anchor {anchor_id} {type_str},{distance_value}\n"
                    with QMutexLocker(self.log_mutex):
                        self.log_file.write(log_line)
                        self.log_file.flush()
            else:
                print(f"(Debug) No anchor match: {line}")

    def show_oem_notification(self, line):
        """
        Extract the OEM command from the line and show a system tray notification.
        Example line: "Received OEM App Command: <cmd>"
        """
        try:
            # Split and grab everything after the colon
            tokens = line.split("Received OEM App Command:", 1)
            if len(tokens) > 1:
                command = tokens[1].strip()
                if command:
                    # Ensure tray icon is visible
                    self.tray_icon.show()

                    # Show a balloon message for 5 seconds
                    self.tray_icon.showMessage(
                        "OEM Command",
                        command,
                        QtWidgets.QSystemTrayIcon.Information,
                        2000
                    )
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


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
