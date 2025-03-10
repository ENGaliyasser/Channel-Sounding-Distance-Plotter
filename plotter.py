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
                line = self.serial_port.readline().decode(errors='ignore')
                if line:
                    # Emit the received line immediately
                    self.data_received.emit(line)
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

        # TerminalTextEdit is already in the UI and promoted to our custom class
        self.terminal = self.TerminalTextEdit

        # Connect SendButton to the method to send commands
        self.SendButton.clicked.connect(self.send_cmd_text)
        self.CMDtextEdit.returnPressed.connect(self.send_cmd_text)
        # Setup plot
        self.plotWidget.setBackground('white')
        self.plotWidget.showGrid(x=True, y=True)
        self.plotWidget.setLabel('left', 'Distance (m)')
        self.plotWidget.setLabel('bottom', 'Measurement count')

        # Initialize data arrays
        self.x_data = []
        self.y_data = []
        self.measurement_count = 0

        # Create plot line
        self.plot_line = self.plotWidget.plot(
            pen='r', symbol='o', symbolPen='r', symbolBrush='r', name='Distance')

        # Add legend
        self.plotWidget.addLegend()

        # Setup Baud rate combo box
        self.baudRateComboBox.addItems(['9600', '115200', '921600'])

        # Connect buttons
        self.ClearButton.clicked.connect(self.clear_plot)
        self.SaveButton.clicked.connect(self.save_plot)

        # Setup serial connection
        self.serial = None
        self.serial_thread = None

        # Logging variables
        self.is_logging = False
        self.log_file = None
        self.log_mutex = QMutex()  # Mutex to protect file access from multiple threads

        # Connect start/stop buttons
        self.StartButton.clicked.connect(self.toggle_serial)
        self.LogButton.clicked.connect(self.toggle_logging)

        # New buttons and their commands
        self.command_buttons = {
            self.PairButton: "sd op",
            self.PassiveButton: "sd pe",
            self.BondlistButton: "listbd",
            self.FactoryResetButton: "factoryreset",
            self.ResetButton: "reset",
            self.HelpButton: "help"
        }

        # Connect command buttons
        for button, command in self.command_buttons.items():
            button.clicked.connect(lambda _, cmd=command: self.send_command(cmd))

        # Setup window size slider
        self.windowSizeSlider.setMinimum(10)
        self.windowSizeSlider.setMaximum(1000)
        self.windowSizeSlider.setValue(100)
        self.windowSizeSlider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.windowSizeSlider.setTickInterval(100)

        # Connect slider value changed signal
        self.windowSizeSlider.valueChanged.connect(self.update_window_size)

        # Setup timer to refresh COM ports every second
        self.com_ports_refresh_timer = QTimer()
        self.com_ports_refresh_timer.timeout.connect(self.refresh_com_ports)
        self.com_ports_refresh_timer.start(1000)  # Refresh every 1 second

        # Initialize COM ports combo box
        self.refresh_com_ports()

    def send_cmd_text(self):
        command = self.CMDtextEdit.text()
        if command.strip():  # Check if command is not empty
            self.CMDtextEdit.clear()
            self.send_command(command)

    def update_window_size(self, value):
        self.trim_data_to_window_size()

    def trim_data_to_window_size(self):
        window_size = self.windowSizeSlider.value()
        if len(self.x_data) > window_size:
            self.x_data = self.x_data[-window_size:]
            self.y_data = self.y_data[-window_size:]

        self.update_plot()

    def update_plot(self):
        if self.y_data:
            self.plot_line.setData(self.x_data, self.y_data)
        else:
            self.plot_line.clear()

        # Update x-axis range
        window_size = self.windowSizeSlider.value()
        self.plotWidget.setXRange(
            max(0, self.measurement_count - window_size),
            self.measurement_count
        )

    def handle_serial_data(self, data):
        # Append data to terminal
        self.terminal.append_text(data)

        # Check if data contains distance information
        match = re.search(r"Distance [(]RADE[)]: ([\d\.]+)", data)
        if match:
            distance = float(match.group(1))
            self.y_data.append(distance)

            # For consistent x_data, increment measurement count
            self.measurement_count += 1
            self.x_data.append(self.measurement_count)

            # Limit data points based on window size
            window_size = self.windowSizeSlider.value()
            if len(self.x_data) > window_size:
                self.x_data = self.x_data[-window_size:]
                self.y_data = self.y_data[-window_size:]

            # Efficiently update the plot
            self.plot_line.setData(self.x_data, self.y_data, clear=True)

            # Log data if logging is enabled
            if self.is_logging and self.log_file:
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                log_line = f"{timestamp},{distance}\n"
                with QMutexLocker(self.log_mutex):
                    self.log_file.write(log_line)
                    self.log_file.flush()

    def handle_serial_error(self, error_message):
        QtWidgets.QMessageBox.critical(self, "Error", f"Serial Error: {error_message}")
        self.stop_serial()

    def toggle_serial(self):
        if self.serial is None or not self.serial.is_open:
            # Currently not connected, so attempt to start
            # Attempt to open the serial port
            port = self.comPortComboBox.currentText()
            if port != 'None':
                try:
                    baud = int(self.baudRateComboBox.currentText())
                    self.serial = serial.Serial(port, baud, timeout=0)

                    # Start the serial reader thread
                    self.serial_thread = SerialReaderThread(self.serial)
                    self.serial_thread.data_received.connect(self.handle_serial_data)
                    self.serial_thread.error_occurred.connect(self.handle_serial_error)
                    self.serial_thread.start()

                    self.StartButton.setText("Stop")

                    # Disable controls while running
                    self.comPortComboBox.setEnabled(False)
                    self.baudRateComboBox.setEnabled(False)
                except Exception as e:
                    QtWidgets.QMessageBox.critical(self, "Error", f"Could not open port {port}: {str(e)}")
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

        # Re-enable controls
        self.comPortComboBox.setEnabled(True)
        self.baudRateComboBox.setEnabled(True)

    def clear_plot(self):
        self.x_data = []
        self.y_data = []
        self.measurement_count = 0
        self.plot_line.clear()
        self.update_plot()

    def save_plot(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Plot", "", "PNG Files (*.png);;All Files (*)")
        if filename:
            try:
                exporter = ImageExporter(self.plotWidget.plotItem)
                exporter.export(filename)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Could not save plot: {str(e)}")

    def toggle_logging(self):
        if not self.is_logging:
            # Start logging
            # Ask the user for a log file location
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
                # Determine the default extension from the selected filter
                if selected_filter.startswith("Log Files"):
                    default_ext = ".log"
                elif selected_filter.startswith("Text Files"):
                    default_ext = ".txt"
                else:
                    default_ext = ""

                # Add the extension if it's missing
                if not os.path.splitext(log_filename)[1]:
                    log_filename += default_ext

                try:
                    # Open the log file
                    self.log_file = open(log_filename, 'a')
                    # Write header
                    self.log_file.write("Timestamp,Distance\n")
                    self.is_logging = True
                    self.LogButton.setText("Stop Logging")
                except Exception as e:
                    QtWidgets.QMessageBox.critical(
                        self, "Error", f"Could not open log file: {str(e)}")
                    self.log_file = None
            else:
                # User canceled the file dialog
                self.is_logging = False
        else:
            # Stop logging
            self.is_logging = False
            self.LogButton.setText("Start Logging")
            if self.log_file:
                self.log_file.close()
                self.log_file = None

    def refresh_com_ports(self):
        # Get the list of current COM ports
        current_ports = [port.device for port in serial.tools.list_ports.comports()]
        # Add 'None' option at the beginning
        current_ports.insert(0, 'None')
        # Update the combo box items if needed
        combo_box = self.comPortComboBox
        if combo_box.isEnabled():
            previous_selection = combo_box.currentText()
            combo_box.clear()
            combo_box.addItems(current_ports)
            # Re-select the previous selection if still available
            if previous_selection in current_ports:
                index = combo_box.findText(previous_selection)
                combo_box.setCurrentIndex(index)
            else:
                # If previous selection is not available, select 'None'
                combo_box.setCurrentIndex(0)

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
        # Close the log file if open
        if self.log_file:
            self.log_file.close()
        event.accept()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())