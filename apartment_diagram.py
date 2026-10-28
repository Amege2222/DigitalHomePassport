import PyQt6
from PyQt6.QtWidgets import QApplication, QWidget, QMainWindow, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

def create_window(size):
    window = QWidget()
    window.setWindowTitle("Мое приложение 2")
    window.resize(size.width(),size.height())
    return window