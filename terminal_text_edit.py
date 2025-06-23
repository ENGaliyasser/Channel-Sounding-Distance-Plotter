from PyQt5 import QtWidgets, QtGui

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
