"""Демонстрационное приложение. Сетевой ввод не блокирует GUI."""

import json
import math
import sys

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QTcpSocket
from PySide6.QtWidgets import (
    QApplication, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


class Window(QWidget):
    def __init__(self, port=2001):
        super().__init__()
        self.port = port
        self.buffer = bytearray()
        self.setWindowTitle("Монитор сигналов")
        self.resize(1000, 450)
        self.connect_button = QPushButton("Подключиться")
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setEnabled(False)
        self.status = QLabel("Нет соединения")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Имя", "Значение", "Качество", "Время"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout = QVBoxLayout(self)
        for widget in (self.connect_button, self.refresh_button, self.status, self.table):
            layout.addWidget(widget)
        self.socket = QTcpSocket(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(3000)
        self.connect_button.clicked.connect(self.connect_to_service)
        self.refresh_button.clicked.connect(self.refresh)
        self.socket.connected.connect(self.connected)
        self.socket.readyRead.connect(self.receive)
        self.socket.disconnected.connect(self.disconnected)
        self.socket.errorOccurred.connect(lambda _: self.fail(self.socket.errorString()))
        self.timer.timeout.connect(lambda: self.fail("Таймаут операции"))

    def connect_to_service(self):
        self.buffer.clear()
        self.connect_button.setEnabled(False)
        self.status.setText("Подключение…")
        self.timer.start()
        self.socket.connectToHost("127.0.0.1", self.port)

    def connected(self):
        self.timer.stop()
        self.status.setText("Подключено")
        self.refresh_button.setEnabled(True)

    def refresh(self):
        # Одновременно выполняется только один запрос.
        self.refresh_button.setEnabled(False)
        self.status.setText("Ожидание данных…")
        self.timer.start()
        self.socket.write(b"GET\n")

    def receive(self):
        self.buffer.extend(bytes(self.socket.readAll()))
        # TCP передаёт поток байтов. Граница сообщения — перевод строки.
        if len(self.buffer) > 1_000_000:
            self.fail("Превышен размер ответа")
            return
        while b"\n" in self.buffer:
            raw, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            try:
                rows = self.parse_snapshot(raw)
            except (ValueError, TypeError, KeyError) as error:
                self.fail(f"Некорректный ответ: {error}")
                return
            # Таблица меняется только после проверки всего снимка.
            self.table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column, text in enumerate(row):
                    self.table.setItem(row_index, column, QTableWidgetItem(text))
            self.table.resizeColumnsToContents()
            self.timer.stop()
            self.status.setText("Обновлено")
            self.refresh_button.setEnabled(True)

    @staticmethod
    def parse_snapshot(raw):
        signals = json.loads(raw)
        if not isinstance(signals, list) or len(signals) != 10:
            raise ValueError("Ожидается 10 сигналов")
        ids, rows = set(), []
        for signal in signals:
            if not isinstance(signal, dict):
                raise ValueError("Сигнал должен быть объектом")
            signal_id, value = signal["id"], signal["value"]
            if type(signal_id) is not int or signal_id in ids:
                raise ValueError("Некорректный или повторяющийся ID")
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Некорректное значение")
            if not all(isinstance(signal[key], str) for key in ("name", "quality", "time")):
                raise ValueError("Некорректные текстовые поля")
            ids.add(signal_id)
            rows.append([str(signal_id), signal["name"], f"{value:.3f}",
                         signal["quality"], signal["time"]])
        return rows

    def disconnected(self):
        self.timer.stop()
        self.refresh_button.setEnabled(False)
        self.connect_button.setEnabled(True)
        self.status.setText("Нет соединения; данные неактуальны")

    def fail(self, reason):
        self.timer.stop()
        self.socket.abort()
        self.buffer.clear()
        self.refresh_button.setEnabled(False)
        self.connect_button.setEnabled(True)
        self.status.setText(f"Ошибка: {reason}; данные неактуальны")

    def closeEvent(self, event):
        self.timer.stop()
        self.socket.abort()
        super().closeEvent(event)


if __name__ == "__main__":
    application = QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(application.exec())
