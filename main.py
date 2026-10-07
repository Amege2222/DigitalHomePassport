import PyQt6
from PyQt6.QtWidgets import QApplication, QWidget, QMainWindow

app = QApplication([])

window = QMainWindow()
window.setWindowTitle("Мое приложение")
window.resize(1000, 600)

window.show()
app.exec()