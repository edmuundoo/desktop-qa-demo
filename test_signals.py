"""Проверка двух обновлений: кнопки → TCP → таблица."""

import json
import subprocess
import sys
from pathlib import Path

import allure
import pytest
from PySide6.QtCore import Qt

from app import Window


@pytest.fixture
def snapshots():
    # Уникальные значения позволяют обнаружить перепутанные ID.
    # Есть отрицательные, нулевые и дробные значения.
    first = [
        {"id": i, "name": f"Датчик {i}", "value": (i - 5) * 1.125,
         "quality": "GOOD", "time": "2026-01-01T10:00:00Z"}
        for i in range(1, 11)
    ]
    # Меняем значения, время, часть quality и порядок строк.
    second = [
        {**signal, "value": signal["value"] + 100.25,
         "quality": "BAD" if signal["id"] % 2 == 0 else "GOOD",
         "time": "2026-01-01T10:00:01Z"}
        for signal in reversed(first)
    ]
    return [first, second]


@pytest.fixture
@allure.title("Запуск отдельного TCP-симулятора")
def service(tmp_path, snapshots, qtbot):
    data_file, ready_file = tmp_path / "snapshots.json", tmp_path / "ready"
    log_file = tmp_path / "service.log"
    data_file.write_text(json.dumps(snapshots, ensure_ascii=False), encoding="utf-8")
    command = [sys.executable, "-u", str(Path(__file__).with_name("simulator.py")),
               "--port", "2001", "--snapshots", str(data_file),
               "--ready-file", str(ready_file)]
    with log_file.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            # Готовность именно нашего процесса, а не чужого сервиса на порту.
            def is_ready():
                if process.poll() is not None:
                    pytest.fail("Симулятор завершился при запуске:\n"
                                + log_file.read_text(encoding="utf-8"))
                return ready_file.exists()
            try:
                qtbot.waitUntil(is_ready, timeout=5000)
            except Exception as error:
                pytest.fail(f"Не удалось запустить симулятор: {error}\n"
                            + log_file.read_text(encoding="utf-8"))
            yield
        finally:
            # Уборка выполняется и после упавшего assert.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            allure.attach.file(str(log_file), name="Журнал TCP-симулятора",
                               attachment_type=allure.attachment_type.TEXT)


def read_table(table):
    """Читаем текст ячеек интерфейса, а не внутреннюю модель ответа."""
    rows = []
    for row in range(table.rowCount()):
        cells = []
        for column in range(table.columnCount()):
            item = table.item(row, column)
            assert item is not None, f"Пустая ячейка: строка {row}, колонка {column}"
            cells.append(item.text())
        rows.append(cells)
    return rows


def assert_snapshot(table, expected):
    allure.attach(json.dumps(expected, ensure_ascii=False, indent=2),
                  name="Ожидаемый снимок", attachment_type=allure.attachment_type.JSON)
    assert table.columnCount() == 5
    assert table.rowCount() == 10, "Должно отображаться ровно 10 сигналов"
    rows = read_table(table)
    allure.attach(json.dumps(rows, ensure_ascii=False, indent=2),
                  name="Фактический текст таблицы", attachment_type=allure.attachment_type.JSON)
    actual_ids = [row[0] for row in rows]
    # Проверяем дубли до dict: словарь мог бы скрыть повторяющиеся ID.
    assert len(set(actual_ids)) == 10, f"Повторяющиеся ID: {actual_ids}"
    actual = {row[0]: row[1:] for row in rows}
    expected_by_id = {
        str(signal["id"]): [signal["name"], f'{signal["value"]:.3f}',
                            signal["quality"], signal["time"]]
        for signal in expected
    }
    # Все пять колонок, сопоставление по ID. Порядок строк не задан условием.
    assert actual == expected_by_id


@allure.title("Два обновления корректно отображают все 10 сигналов")
@allure.feature("Отображение сигналов по TCP")
@allure.severity(allure.severity_level.CRITICAL)
def test_two_updates_show_correct_signals(qtbot, service, snapshots):
    window = Window(port=2001)
    qtbot.addWidget(window)
    window.show()
    try:
        with allure.step("Проверить начальное состояние окна"):
            assert window.table.rowCount() == 0
            assert not window.refresh_button.isEnabled()
        with allure.step("Подключиться к сервису на 127.0.0.1:2001"):
            # Посылаем события мыши через Qt; не вызываем сетевые обработчики.
            qtbot.mouseClick(window.connect_button, Qt.MouseButton.LeftButton)
            qtbot.waitUntil(lambda: window.refresh_button.isEnabled()
                            or window.connect_button.isEnabled(), timeout=5000)
            assert window.status.text() == "Подключено", window.status.text()
        for index, expected in enumerate(snapshots, start=1):
            with allure.step(f"Обновление {index}: проверить 10 сигналов и все поля по ID"):
                qtbot.mouseClick(window.refresh_button, Qt.MouseButton.LeftButton)
                # Ожидаем состояние, а не фиксированное число секунд.
                qtbot.waitUntil(lambda: window.refresh_button.isEnabled()
                                or window.connect_button.isEnabled(), timeout=5000)
                assert window.status.text() == "Обновлено", window.status.text()
                assert_snapshot(window.table, expected)
                artifacts = Path("artifacts")
                artifacts.mkdir(exist_ok=True)
                screenshot = artifacts / f"snapshot-{index}.png"
                if window.grab().save(str(screenshot)):
                    allure.attach.file(str(screenshot), name=f"Окно после обновления {index}",
                                       attachment_type=allure.attachment_type.PNG)
    except Exception:
        artifacts = Path("artifacts")
        artifacts.mkdir(exist_ok=True)
        screenshot = artifacts / "failure.png"
        if window.grab().save(str(screenshot)):
            allure.attach.file(str(screenshot), name="Окно при падении",
                               attachment_type=allure.attachment_type.PNG)
        raise
    finally:
        window.close()
