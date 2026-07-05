import sys
import json
import os
import requests
from datetime import datetime, timedelta
from PySide6.QtWidgets import (QApplication, QMainWindow, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QHBoxLayout,
                               QWidget, QPushButton, QDialog, QFormLayout,
                               QComboBox, QDateEdit, QTimeEdit, QLineEdit,
                               QHeaderView, QMenu, QAbstractItemView, QStyledItemDelegate,
                               QLabel, QTextEdit, QMessageBox, QGroupBox)
from PySide6.QtCore import Qt, QDate, QTime, QTimer
from PySide6.QtGui import QColor, QBrush, QPainter, QIcon, QPixmap, QPen

# 数据持久化文件路径 - 使用程序所在目录
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "events_data.json")
QWEN_API_KEY = "sk-6e454cef3da84febb530247cb277e27a"


# ==========================================
# 逻辑层：颜色计算模块
# ==========================================
class UrgencyAnalyzer:
    """计算目标日期与当前的差值，返回对应状态的背景色和文本色"""

    def __init__(self):
        # 预设基于时间跨度的颜色字典
        self.colors = {
            "past": "#333333",
            0: "#C64B4B",
            1: "#BA7070",
            2: "#AD8585",
            3: "#A39494",
            "normal": "#999999"
        }

    def get_style(self, target_date_obj, current_date_obj):
        # 计算天数差
        delta = (target_date_obj - current_date_obj).days

        # 匹配对应颜色
        if delta < 0:
            bg = self.colors["past"]
        elif delta > 3:
            bg = self.colors["normal"]
        else:
            bg = self.colors[delta]

        # 动态反转文本颜色以确保可读性
        text_color = "#000000" if bg in ["#999999", "#A39494"] else "#FFFFFF"
        return bg, text_color


# ==========================================
# 视图层：自定义单元格渲染器
# ==========================================
class MinimalDelegate(QStyledItemDelegate):
    """重写 paint 函数，取消系统裁剪，允许色块溢出单元格边界"""

    def paint(self, painter: QPainter, option, index):
        painter.save()
        # 解除系统画布边界裁剪限制
        painter.setClipping(False)

        bg_brush = index.data(Qt.ItemDataRole.BackgroundRole)
        text = index.data(Qt.ItemDataRole.DisplayRole)

        # 绘制单元格背景（网格底色）
        painter.fillRect(option.rect, QColor("#111111"))

        # 绘制网格线（边界）
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        painter.drawRect(option.rect)

        # 绘制时间分隔线（每小时一条较粗的线）
        row = index.row()
        if row % 2 == 0:  # 整点时刻
            painter.setPen(QPen(QColor(80, 80, 80), 2))
            painter.drawLine(option.rect.topLeft(), option.rect.topRight())

        if bg_brush:
            # 缩减 2px 生成色块内边距
            draw_rect = option.rect.adjusted(2, 2, -2, -2)

            # 强制色块最小高度为 24px，高度不足时将向下溢出
            if draw_rect.height() < 24:
                draw_rect.setHeight(24)

            # 填充背景
            painter.fillRect(draw_rect, bg_brush)

            if text:
                fg_brush = index.data(Qt.ItemDataRole.ForegroundRole)
                painter.setPen(fg_brush.color() if fg_brush else QColor("#FFFFFF"))

                # 设置文本包围盒并绘制文本
                text_rect = draw_rect.adjusted(4, 2, -4, -2)
                painter.drawText(text_rect,
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                                 text)

        painter.restore()


class MinimalTable(QTableWidget):
    """拦截原生拖拽释放事件，手动触发全局数据同步与重绘以修复合并单元格撕裂问题"""

    def __init__(self, rows, cols):
        super().__init__(rows, cols)
        self.current_time = datetime.now()

    def update_current_time(self):
        self.current_time = datetime.now()
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        self.draw_time_line()

    def draw_time_line(self):
        """在今天的列上绘制一条时间线"""
        now = self.current_time

        # 获取表格尺寸
        if self.rowCount() == 0 or self.columnCount() == 0:
            return

        # 计算当前时间对应的行位置（6:00-24:00）
        if now.hour < 6 or now.hour >= 24:
            return

        # 计算Y坐标（基于行索引和行高）
        minutes_since_6am = (now.hour - 6) * 60 + now.minute
        row_index = int(minutes_since_6am / 30)  # 每30分钟一行

        if row_index < 0 or row_index >= self.rowCount():
            return

        # 获取行的Y位置
        row_rect = self.visualRect(self.model().index(row_index, 0))
        row_height = row_rect.height()

        # 计算分钟在30分钟槽内的偏移
        minute_in_slot = minutes_since_6am % 30
        line_y = row_rect.top() + (minute_in_slot / 30) * row_height

        # 获取今天列的位置（第11列，索引为10）
        if 10 >= self.columnCount():
            return

        # 获取列的X位置
        col_left = self.columnViewportPosition(10)
        col_width = self.columnWidth(10)
        col_right = col_left + col_width

        # 确保位置有效
        if col_left < 0 or line_y < 0:
            return

        # 创建painter并绘制
        painter = QPainter(self.viewport())
        painter.save()

        # 绘制红色时间线
        painter.setPen(QPen(QColor("#FF0000"), 2))
        painter.drawLine(int(col_left), int(line_y), int(col_right), int(line_y))

        # 绘制标记点
        painter.setBrush(QColor("#FF0000"))
        painter.drawEllipse(int(col_left + 5), int(line_y - 4), 8, 8)

        painter.restore()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.window().sync_data_from_table()
        self.window().populate_table()


# ==========================================
# 控制层：主窗口
# ==========================================
class CalendarApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Calendar")
        self.resize(1000, 800)

        # 初始化日期指针，设定期初为10天前
        self.today = datetime.today().date()
        self.start_date = self.today - timedelta(days=10)

        # 加载逻辑组件与本地数据
        self.analyzer = UrgencyAnalyzer()
        self.events_data = self.load_data()

        # 构建基础 Widget 容器与零边距布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 构建头部工具栏布局
        header_layout = QHBoxLayout()

        # 时间显示标签
        self.time_label = QLabel()
        self.time_label.setStyleSheet("color: #FFFFFF; font-size: 14px;")
        header_layout.addWidget(self.time_label)

        header_layout.addStretch()

        # 智能插入按钮
        self.smart_btn = QPushButton("🧠 智能插入")
        self.smart_btn.setFixedSize(90, 30)
        self.smart_btn.clicked.connect(self.open_smart_insert_dialog)
        self.smart_btn.setStyleSheet("background-color: #2E7D32; font-weight: bold;")
        header_layout.addWidget(self.smart_btn)

        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.clicked.connect(self.open_add_dialog)
        header_layout.addWidget(self.add_btn)

        # AI按钮
        self.ai_btn = QPushButton("🤖 AI")
        self.ai_btn.setFixedSize(50, 30)
        self.ai_btn.clicked.connect(self.open_ai_dialog)
        header_layout.addWidget(self.ai_btn)

        layout.addLayout(header_layout)

        # 初始化网格：36行(6:00-24:00)，21列(21天)
        self.table = MinimalTable(36, 21)
        layout.addWidget(self.table)

        self.setup_table()
        self.populate_table()

        # 更新时间显示
        self.update_time_display()

        # 设置定时器更新时间和时间线
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(1000)

    def on_timer(self):
        self.update_time_display()
        self.table.update_current_time()

    def update_time_display(self):
        now = datetime.now()
        self.time_label.setText(f"北京时间: {now.strftime('%Y年%m月%d日 %H:%M:%S')}")

    def load_data(self):
        """读取本地 JSON 存档"""
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        return {}

    def save_data(self):
        """序列化内存字典至本地 JSON 文件"""
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.events_data, f, ensure_ascii=False, indent=2)

    def setup_table(self):
        """配置网格属性、尺寸策略及 QSS 样式表"""
        self.table.setShowGrid(False)
        self.table.setFrameShape(QTableWidget.Shape.NoFrame)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        self.table.verticalHeader().setMinimumSectionSize(1)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        for i in range(21):
            date_obj = self.start_date + timedelta(days=i)
            text = f"{date_obj.strftime('%m-%d')}\n周{'一二三四五六日'[date_obj.weekday()]}"
            item = QTableWidgetItem(text)
            if i == 10: item.setBackground(QColor("#222222"))
            self.table.setHorizontalHeaderItem(i, item)

        times = []
        for h in range(6, 24):
            times.append(f"{h:02d}:00" if h % 2 == 0 else "")
            times.append("")
        self.table.setVerticalHeaderLabels(times)

        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

        self.table.setItemDelegate(MinimalDelegate())

        self.setStyleSheet(""" 
            QMainWindow, QDialog { background-color: #000000; color: #FFFFFF; }
            QTableWidget { background-color: #000000; color: #FFFFFF; border: none; }
            QHeaderView::section:horizontal { background-color: #111111; color: #FFFFFF; border: 1px solid #222222; }
            QHeaderView::section:vertical { background-color: #000000; color: #FFFFFF; border: none; padding-right: 5px; }
            QPushButton, QLineEdit, QComboBox, QDateEdit, QTimeEdit { background-color: #222222; color: #FFFFFF; border: 1px solid #444444; }
            QMenu { background-color: #222; color: white; border: 1px solid #444; }
            QMenu::item:selected { background-color: #555; }
        """)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.cellChanged.connect(self.on_cell_changed)

    def populate_table(self):
        """解析 JSON 数据映射并重绘网格"""
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.clearSpans()

        for date_str, times in self.events_data.items():
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            col = (date_obj - self.start_date).days

            if 0 <= col < 21:
                for time_str, event in times.items():
                    h, m = map(int, time_str.split(':'))
                    if h < 6: continue

                    row = (h - 6) * 2 + (1 if m >= 30 else 0)

                    item = QTableWidgetItem(event["text"])
                    color_pref = event.get("color", "auto")
                    duration = max(2, event.get("duration", 2))
                    repeat_type = event.get("repeat", "不重复")

                    if color_pref == "auto":
                        bg_hex, fg_hex = self.analyzer.get_style(date_obj, self.today)
                    else:
                        bg_hex, fg_hex = color_pref, "#000000"

                    item.setBackground(QBrush(QColor(bg_hex)))
                    item.setForeground(QBrush(QColor(fg_hex)))

                    item.setData(Qt.ItemDataRole.UserRole + 1, color_pref)
                    item.setData(Qt.ItemDataRole.UserRole + 2, duration)
                    item.setData(Qt.ItemDataRole.UserRole + 3, repeat_type)
                    item.setData(Qt.ItemDataRole.UserRole + 4, event.get("notes", ""))

                    self.table.setItem(row, col, item)

                    if duration > 1:
                        safe_dur = min(duration, 36 - row)
                        self.table.setSpan(row, col, safe_dur, 1)

                # 处理重复事件
                for time_str, event in times.items():
                    h, m = map(int, time_str.split(':'))
                    if h < 6: continue

                    row = (h - 6) * 2 + (1 if m >= 30 else 0)
                    duration = max(2, event.get("duration", 2))
                    repeat_type = event.get("repeat", "不重复")
                    color_pref = event.get("color", "auto")

                    if repeat_type == "每周":
                        weekday = date_obj.weekday()
                        for c in range(21):
                            if c != col:
                                current_date = self.start_date + timedelta(days=c)
                                if current_date.weekday() == weekday:
                                    existing_item = self.table.item(row, c)
                                    if not existing_item or not existing_item.text().strip():
                                        item = QTableWidgetItem(event["text"])
                                        if color_pref == "auto":
                                            bg_hex, fg_hex = self.analyzer.get_style(current_date, self.today)
                                        else:
                                            bg_hex, fg_hex = color_pref, "#000000"
                                        item.setBackground(QBrush(QColor(bg_hex)))
                                        item.setForeground(QBrush(QColor(fg_hex)))
                                        item.setData(Qt.ItemDataRole.UserRole + 1, color_pref)
                                        item.setData(Qt.ItemDataRole.UserRole + 2, duration)
                                        item.setData(Qt.ItemDataRole.UserRole + 3, repeat_type)
                                        item.setData(Qt.ItemDataRole.UserRole + 4, event.get("notes", ""))
                                        self.table.setItem(row, c, item)
                                        if duration > 1:
                                            safe_dur = min(duration, 36 - row)
                                            self.table.setSpan(row, c, safe_dur, 1)

                    elif repeat_type == "隔周":
                        weekday = date_obj.weekday()
                        base_week = date_obj.isocalendar()[1]
                        for c in range(21):
                            if c != col:
                                current_date = self.start_date + timedelta(days=c)
                                current_week = current_date.isocalendar()[1]
                                if current_date.weekday() == weekday and (current_week - base_week) % 2 == 0:
                                    existing_item = self.table.item(row, c)
                                    if not existing_item or not existing_item.text().strip():
                                        item = QTableWidgetItem(event["text"])
                                        if color_pref == "auto":
                                            bg_hex, fg_hex = self.analyzer.get_style(current_date, self.today)
                                        else:
                                            bg_hex, fg_hex = color_pref, "#000000"
                                        item.setBackground(QBrush(QColor(bg_hex)))
                                        item.setForeground(QBrush(QColor(fg_hex)))
                                        item.setData(Qt.ItemDataRole.UserRole + 1, color_pref)
                                        item.setData(Qt.ItemDataRole.UserRole + 2, duration)
                                        item.setData(Qt.ItemDataRole.UserRole + 3, repeat_type)
                                        item.setData(Qt.ItemDataRole.UserRole + 4, event.get("notes", ""))
                                        self.table.setItem(row, c, item)
                                        if duration > 1:
                                            safe_dur = min(duration, 36 - row)
                                            self.table.setSpan(row, c, safe_dur, 1)

        self.table.blockSignals(False)

    def sync_data_from_table(self):
        new_data = {}
        for col in range(21):
            date_str = (self.start_date + timedelta(days=col)).strftime("%Y-%m-%d")
            for row in range(36):
                item = self.table.item(row, col)
                if item and item.text().strip():
                    h = (row // 2) + 6
                    m = "30" if row % 2 != 0 else "00"
                    time_str = f"{h:02d}:{m}"

                    if date_str not in new_data: new_data[date_str] = {}

                    new_data[date_str][time_str] = {
                        "text": item.text().strip(),
                        "color": item.data(Qt.ItemDataRole.UserRole + 1) or "auto",
                        "duration": max(2, item.data(Qt.ItemDataRole.UserRole + 2) or 2),
                        "repeat": item.data(Qt.ItemDataRole.UserRole + 3) or "不重复",
                        "notes": item.data(Qt.ItemDataRole.UserRole + 4) or ""
                    }
        self.events_data = new_data
        self.save_data()

    def on_cell_changed(self, row, col):
        self.sync_data_from_table()
        self.populate_table()

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item or not item.text().strip(): return

        menu = QMenu(self)
        view_action = menu.addAction("查看详情")
        menu.addSeparator()
        edit_action = menu.addAction("修改属性")
        menu.addSeparator()
        del_action = menu.addAction("删除事件")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == del_action:
            self.table.blockSignals(True)
            item.setText("")
            self.table.blockSignals(False)
            self.on_cell_changed(item.row(), item.column())

        elif action == edit_action:
            cur_color = item.data(Qt.ItemDataRole.UserRole + 1) or "auto"
            cur_duration = item.data(Qt.ItemDataRole.UserRole + 2) or 2
            cur_repeat = item.data(Qt.ItemDataRole.UserRole + 3) or "无"
            cur_notes = item.data(Qt.ItemDataRole.UserRole + 4) or ""

            dialog = EventPropertyDialog(cur_color, cur_duration, cur_repeat, cur_notes, self)
            if dialog.exec():
                color, duration, repeat, notes = dialog.get_data()

                self.table.blockSignals(True)
                item.setData(Qt.ItemDataRole.UserRole + 1, color)
                item.setData(Qt.ItemDataRole.UserRole + 2, duration)
                item.setData(Qt.ItemDataRole.UserRole + 3, repeat)
                item.setData(Qt.ItemDataRole.UserRole + 4, notes)
                self.table.blockSignals(False)

                self.sync_data_from_table()
                self.populate_table()

        elif action == view_action:
            notes = item.data(Qt.ItemDataRole.UserRole + 4) or "无备注"
            QMessageBox.information(self, "事件详情", f"内容: {item.text()}\n\n备注: {notes}")

    def open_add_dialog(self):
        dialog = AddEventDialog(self.today, self)
        if dialog.exec():
            data = dialog.get_data()
            date_str = data["date"].strftime("%Y-%m-%d")
            time_str = data["time"].toString("HH:mm")

            if date_str not in self.events_data:
                self.events_data[date_str] = {}

            self.events_data[date_str][time_str] = {
                "text": data["text"],
                "color": "auto",
                "duration": data["duration"],
                "repeat": data["repeat"],
                "notes": data["notes"]
            }
            self.save_data()
            self.populate_table()

    def open_ai_dialog(self):
        dialog = AITextImportDialog(self)
        if dialog.exec():
            events = dialog.get_events()
            for event in events:
                date_str = event["date"]
                time_str = event["time"]

                if date_str not in self.events_data:
                    self.events_data[date_str] = {}

                self.events_data[date_str][time_str] = {
                    "text": event["text"],
                    "color": "auto",
                    "duration": event["duration"],
                    "repeat": "无",
                    "notes": event["notes"]
                }

            self.save_data()
            self.populate_table()

    # ==========================================================
    # 核心算法模块：艾宾浩斯非线性智能切分排程
    # ==========================================================
    def open_smart_insert_dialog(self):
        """弹出智能排程对话框并执行非线性填缝算法"""
        dialog = SmartInsertDialog(self.today, self)
        if dialog.exec():
            data = dialog.get_data()
            task_text = data["text"] if data["text"].strip() else "智能分配任务"
            duration_per_task = data["duration_per_task"]
            deadline_date = data["deadline"]
            task_count = data["task_count"]

            # 因为不再需要系统去切分，直接按照用户指定的每次时长生成任务块
            chunks = [duration_per_task] * task_count
            splits = task_count  # 保留 splits 变量名适配后续逻辑

            now = datetime.now()
            today_col = (self.today - self.start_date).days
            deadline_col = min(20, (deadline_date - self.start_date).days)

            if deadline_col < today_col:
                QMessageBox.warning(self, "排程失败", "您选定的截止日期早于今天，无法进行排程。")
                return

            # ---------------------------------------------------------
            # 步骤 1：基于现有数据建立可用时间二维矩阵 Occupied[21][36]
            # ---------------------------------------------------------
            occupied = [[False] * 36 for _ in range(21)]

            for c in range(today_col):
                if 0 <= c < 21:
                    for r in range(36): occupied[c][r] = True

            if 0 <= today_col < 21:
                current_row = (now.hour - 6) * 2 + (1 if now.minute >= 30 else 0)
                for r in range(min(36, current_row + 1)):
                    occupied[today_col][r] = True

            for date_str, times in self.events_data.items():
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                base_col = (date_obj - self.start_date).days

                for time_str, event in times.items():
                    h, m = map(int, time_str.split(':'))
                    if h < 6: continue
                    row = (h - 6) * 2 + (1 if m >= 30 else 0)
                    dur = max(2, event.get("duration", 2))
                    repeat_type = event.get("repeat", "不重复")

                    def mark_slots(c, r, d):
                        if 0 <= c < 21:
                            for i in range(d):
                                if r + i < 36: occupied[c][r + i] = True

                    if 0 <= base_col < 21: mark_slots(base_col, row, dur)

                    if repeat_type == "每周":
                        weekday = date_obj.weekday()
                        for c in range(21):
                            if c != base_col:
                                c_date = self.start_date + timedelta(days=c)
                                if c_date.weekday() == weekday: mark_slots(c, row, dur)
                    elif repeat_type == "隔周":
                        weekday = date_obj.weekday()
                        base_week = date_obj.isocalendar()[1]
                        for c in range(21):
                            if c != base_col:
                                c_date = self.start_date + timedelta(days=c)
                                if c_date.weekday() == weekday and (c_date.isocalendar()[1] - base_week) % 2 == 0:
                                    mark_slots(c, row, dur)

            # ---------------------------------------------------------
            # 步骤 2：生成艾宾浩斯（Ebbinghaus）目标分布列
            # ---------------------------------------------------------
            # 艾宾浩斯标准复习间隔天数，做了充分扩展以防止用户输入超大次数导致索引越界
            ideal_intervals = [0, 1, 3, 7, 15, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 400, 450, 500,
                               550]

            # 截取所需次数的间隔
            current_intervals = ideal_intervals[:splits]
            max_interval = current_intervals[-1] if splits > 0 else 1
            available_days = deadline_col - today_col

            target_cols = []
            for i in range(splits):
                if max_interval <= available_days:
                    # 时间极度充足，完全遵循标准的艾宾浩斯曲线
                    target_cols.append(today_col + current_intervals[i])
                else:
                    # 时间紧迫，将艾宾浩斯曲线按比例非线性压缩进可用时间
                    scaled_offset = int((current_intervals[i] / max_interval) * available_days)
                    target_cols.append(today_col + scaled_offset)

            # ---------------------------------------------------------
            # 步骤 3：执行带间隔目标的贪心寻隙算法 (带强制防堆叠)
            # ---------------------------------------------------------
            success_schedule = []
            last_placed_col = today_col - 1  # 记录上一次放置的列，用于防堆叠

            for i, chunk in enumerate(chunks):
                ideal_c = target_cols[i]

                # 强制防堆叠：如果理想日期等于或早于上一次分配的日期，尽量往后推一天
                if ideal_c <= last_placed_col and last_placed_col < deadline_col:
                    ideal_c = last_placed_col + 1

                placed = False

                # 优先策略：从理想日期向后寻找截止日期前的空隙
                for c in range(ideal_c, deadline_col + 1):
                    if c < 0 or c >= 21: continue

                    consecutive = 0
                    start_r = -1
                    for r in range(36):
                        if not occupied[c][r]:
                            if consecutive == 0: start_r = r
                            consecutive += 1
                            if consecutive == chunk:
                                # 成功找到符合条件的空隙
                                h = (start_r // 2) + 6
                                m = "30" if start_r % 2 != 0 else "00"
                                time_str = f"{h:02d}:{m}"
                                date_str = (self.start_date + timedelta(days=c)).strftime("%Y-%m-%d")

                                success_schedule.append({
                                    "date_str": date_str,
                                    "time_str": time_str,
                                    "duration": chunk
                                })
                                # 在虚拟矩阵中立即占领这块区域
                                for j in range(chunk): occupied[c][start_r + j] = True
                                placed = True
                                last_placed_col = c
                                break
                        else:
                            consecutive = 0
                            start_r = -1
                    if placed: break

                # 备用策略：如果往后找不到（快到deadline了太满），则妥协间隔，从理想日期往前找
                if not placed:
                    for c in range(ideal_c - 1, today_col - 1, -1):
                        if c < 0 or c >= 21: continue

                        consecutive = 0
                        start_r = -1
                        for r in range(36):
                            if not occupied[c][r]:
                                if consecutive == 0: start_r = r
                                consecutive += 1
                                if consecutive == chunk:
                                    h = (start_r // 2) + 6
                                    m = "30" if start_r % 2 != 0 else "00"
                                    time_str = f"{h:02d}:{m}"
                                    date_str = (self.start_date + timedelta(days=c)).strftime("%Y-%m-%d")

                                    success_schedule.append({
                                        "date_str": date_str,
                                        "time_str": time_str,
                                        "duration": chunk
                                    })
                                    for j in range(chunk): occupied[c][start_r + j] = True
                                    placed = True
                                    last_placed_col = c
                                    break
                            else:
                                consecutive = 0
                                start_r = -1
                        if placed: break

                if not placed:
                    # 如果任何一个碎片任务找不到容身之所，直接引发回滚失败
                    QMessageBox.warning(self, "排程失败",
                                        f"日历太满啦！算法无法在截止日期前找到足够的连续空隙以安放“{task_text}”。\n建议放宽截止日期、减少执行次数，或手动清理一下日程。")
                    return

            # ---------------------------------------------------------
            # 步骤 4：确立最终排程计划并映射至物理视图
            # ---------------------------------------------------------
            for item in success_schedule:
                d_str = item["date_str"]
                t_str = item["time_str"]
                if d_str not in self.events_data:
                    self.events_data[d_str] = {}
                self.events_data[d_str][t_str] = {
                    "text": f"*{task_text}",  # 前缀标注以示区分
                    "color": "auto",
                    "duration": item["duration"],
                    "repeat": "不重复",
                    "notes": "🧠 基于艾宾浩斯非线性间隔分布"
                }

            self.save_data()
            self.populate_table()
            QMessageBox.information(self, "排程成功", f"“{task_text}”已成功按艾宾浩斯遗忘曲线散布在您的日历中！")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        col_width = self.table.viewport().width() // 7
        for i in range(21): self.table.setColumnWidth(i, col_width)

    def showEvent(self, event):
        super().showEvent(event)
        self.table.horizontalScrollBar().setValue(7 * self.table.columnWidth(0))


# ==========================================
# 组件层：下拉弹窗与表单配置
# ==========================================
def create_color_icon(hex_code):
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("#000000" if hex_code == "auto" else hex_code))
    return QIcon(pixmap)


class EventPropertyDialog(QDialog):
    def __init__(self, cur_color, cur_duration, cur_repeat, cur_notes="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("属性")
        layout = QFormLayout(self)

        self.color_cb = QComboBox()
        colors = [("动态自动 (基于日期)", "auto"), ("浅灰", "#D3D3D3"), ("浅粉", "#FFB3BA"), ("浅绿", "#BAFFC9"),
                  ("浅蓝", "#BAE1FF")]
        for name, hx in colors: self.color_cb.addItem(create_color_icon(hx), name, hx)
        idx = self.color_cb.findData(cur_color)
        self.color_cb.setCurrentIndex(idx if idx >= 0 else 0)

        self.dur_cb = QComboBox()
        durations = [("1小时 (2格)", 2), ("1.5小时 (3格)", 3), ("2小时 (4格)", 4), ("3小时 (6格)", 6)]
        for name, val in durations: self.dur_cb.addItem(name, val)
        idx2 = self.dur_cb.findData(cur_duration)
        self.dur_cb.setCurrentIndex(idx2 if idx2 >= 0 else 0)

        self.repeat_cb = QComboBox()
        self.repeat_cb.addItems(["不重复", "每周", "隔周"])
        self.repeat_cb.setCurrentText(cur_repeat)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.notes_edit.setText(cur_notes)

        save_btn = QPushButton("确认")
        save_btn.clicked.connect(self.accept)

        layout.addRow("底色:", self.color_cb)
        layout.addRow("时长:", self.dur_cb)
        layout.addRow("重复:", self.repeat_cb)
        layout.addRow("备注:", self.notes_edit)
        layout.addWidget(save_btn)

    def get_data(self):
        return self.color_cb.currentData(), self.dur_cb.currentData(), self.repeat_cb.currentText(), self.notes_edit.toPlainText()


class AddEventDialog(QDialog):
    def __init__(self, default_date, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加")
        layout = QFormLayout(self)

        self.text_input = QLineEdit()
        self.date_input = QDateEdit()
        self.date_input.setDate(QDate(default_date.year, default_date.month, default_date.day))
        self.date_input.setCalendarPopup(True)

        self.time_input = QTimeEdit()
        self.time_input.setDisplayFormat("HH:mm")
        self.time_input.setMinimumTime(QTime(6, 0))

        self.dur_cb = QComboBox()
        durations = [("1小时 (2格)", 2), ("1.5小时 (3格)", 3), ("2小时 (4格)", 4), ("3小时 (6格)", 6)]
        for name, val in durations: self.dur_cb.addItem(name, val)

        self.repeat_cb = QComboBox()
        self.repeat_cb.addItems(["不重复", "每周", "隔周"])

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.notes_edit.setPlaceholderText("地点、注意事项等...")

        save_btn = QPushButton("确认")
        save_btn.clicked.connect(self.accept)

        layout.addRow("内容:", self.text_input)
        layout.addRow("日期:", self.date_input)
        layout.addRow("时间:", self.time_input)
        layout.addRow("时长:", self.dur_cb)
        layout.addRow("重复:", self.repeat_cb)
        layout.addRow("备注:", self.notes_edit)
        layout.addWidget(save_btn)

    def get_data(self):
        return {
            "text": self.text_input.text(),
            "date": self.date_input.date().toPython(),
            "time": self.time_input.time(),
            "duration": self.dur_cb.currentData(),
            "repeat": self.repeat_cb.currentText(),
            "notes": self.notes_edit.toPlainText()
        }


# ==========================================
# 新增：智能排程交互界面模块
# ==========================================
class SmartInsertDialog(QDialog):
    """用于设置运筹规划排程参数的弹窗"""

    def __init__(self, today_date, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧠 运筹级智能排程")
        self.resize(350, 200)
        layout = QFormLayout(self)

        # 任务名输入
        self.task_name = QLineEdit()
        self.task_name.setPlaceholderText("例如：复习线性代数 / 开发项目")

        # 修改为：每次任务预期时间
        self.duration_cb = QComboBox()
        for i in range(2, 17):  # 支持从 1小时(2格) 到 8小时(16格)
            hours = i * 0.5
            self.duration_cb.addItem(f"{hours} 小时 / 次", i)

            # 交付截止日期
        self.deadline_date = QDateEdit()
        self.deadline_date.setDate(QDate(today_date.year, today_date.month, today_date.day).addDays(10))
        self.deadline_date.setCalendarPopup(True)
        self.deadline_date.setMinimumDate(QDate(today_date.year, today_date.month, today_date.day))

        # 修改为：期望执行次数
        self.split_cb = QComboBox()
        for i in range(1, 21):  # 支持 1 到 20 次
            self.split_cb.addItem(f"共执行 {i} 次", i)

        save_btn = QPushButton("开始智能探测填隙")
        save_btn.setStyleSheet("background-color: #2E7D32; font-weight: bold; padding: 5px;")
        save_btn.clicked.connect(self.accept)

        layout.addRow("任务总称:", self.task_name)
        layout.addRow("单次时长:", self.duration_cb)
        layout.addRow("截止日期:", self.deadline_date)
        layout.addRow("执行次数:", self.split_cb)
        layout.addWidget(save_btn)

    def get_data(self):
        return {
            "text": self.task_name.text(),
            "duration_per_task": self.duration_cb.currentData(),
            "deadline": self.deadline_date.date().toPython(),
            "task_count": self.split_cb.currentData()
        }


class AITextImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🤖 AI智能录入")
        self.resize(600, 450)
        self.parsed_events = []

        layout = QVBoxLayout(self)

        info_label = QLabel("输入事件描述，AI将自动提取事件名称、时间和备注信息")
        info_label.setStyleSheet("color: #888;")
        layout.addWidget(info_label)

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("例如：明天上午9点在图书馆有数学考试，需要复习课本第三章")
        self.input_text.setMaximumHeight(100)
        layout.addWidget(self.input_text)

        self.ai_btn = QPushButton("🔍 AI分析")
        self.ai_btn.clicked.connect(self.analyze_text)
        layout.addWidget(self.ai_btn)

        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("color: #888; padding: 10px; background-color: #1a1a1a; border-radius: 5px;")
        layout.addWidget(self.result_label)

        self.events_group = QGroupBox("识别的事件")
        self.events_layout = QVBoxLayout()
        self.events_group.setLayout(self.events_layout)
        layout.addWidget(self.events_group)

        button_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("确认导入")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def analyze_text(self):
        text = self.input_text.toPlainText().strip()
        if not text:
            self.result_label.setText("请输入事件描述")
            return

        self.result_label.setText("正在分析...")
        QApplication.processEvents()

        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {QWEN_API_KEY}'
            }

            prompt = f"""分析以下事件描述，提取关键信息并以JSON格式返回。

输入文本：{text}

请提取以下信息：
1. event_name: 事件名称/标题
2. event_date: 日期（格式为YYYY-MM-DD，今天是{datetime.now().strftime('%Y-%m-%d')}）
3. event_time: 时间（格式为HH:MM，24小时制）
4. duration_hours: 时长（小时数，如1、1.5、2等）
5. notes: 备注信息（地点、注意事项等）

请以JSON格式返回：
{{"event_name": "...", "event_date": "YYYY-MM-DD", "event_time": "HH:MM", "duration_hours": 1, "notes": "..."}}

注意：
1. 只返回JSON，不要其他内容
2. 如果文本中没有明确时间，使用当前时间
3. 日期如果提到"今天"就是{datetime.now().strftime('%Y-%m-%d')}，"明天"就是{(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')}，"后天"就是{(datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')}
"""
            payload = {
                'model': 'qwen-max',
                'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': 1024
            }

            response = requests.post(
                'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
                headers=headers,
                json=payload,
                timeout=60
            )

            if response.status_code != 200:
                raise Exception(f"API请求失败: {response.text}")

            result = response.json()
            ai_response = result['choices'][0]['message']['content']

            import re
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                try:
                    event_data = json.loads(json_match.group())
                    self.parsed_events = [event_data]
                    self.result_label.setText(
                        f"✅ 识别成功！\n事件: {event_data.get('event_name', '')}\n时间: {event_data.get('event_date', '')} {event_data.get('event_time', '')}")
                    self.update_events_display()
                    self.confirm_btn.setEnabled(True)
                except json.JSONDecodeError as e:
                    self.result_label.setText(f"❌ JSON解析失败: {str(e)}\n响应内容: {ai_response}")
            else:
                self.result_label.setText(f"❌ 未找到JSON数据\n响应内容: {ai_response}")

        except requests.exceptions.RequestException as e:
            self.result_label.setText(f"❌ 网络请求失败: {str(e)}")
        except Exception as e:
            self.result_label.setText(f"❌ 分析失败: {str(e)}")

    def update_events_display(self):
        while self.events_layout.count() > 0:
            item = self.events_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, event in enumerate(self.parsed_events):
            event_widget = QWidget()
            event_layout = QVBoxLayout(event_widget)

            title_label = QLabel(f"📌 {event.get('event_name', '')}")
            title_label.setStyleSheet("font-weight: bold;")
            event_layout.addWidget(title_label)

            info_label = QLabel(f"⏰ {event.get('event_date', '')} {event.get('event_time', '')}")
            event_layout.addWidget(info_label)

            if event.get('notes'):
                notes_label = QLabel(f"📝 {event.get('notes')}")
                notes_label.setStyleSheet("color: #888; font-size: 12px;")
                notes_label.setWordWrap(True)
                event_layout.addWidget(notes_label)

            event_widget.setStyleSheet(
                "background-color: #1a1a1a; padding: 10px; margin-bottom: 5px; border-radius: 5px;")
            self.events_layout.addWidget(event_widget)

    def get_events(self):
        events = []
        for event in self.parsed_events:
            events.append({
                "text": event.get('event_name', ''),
                "date": event.get('event_date', datetime.now().strftime('%Y-%m-%d')),
                "time": event.get('event_time', datetime.now().strftime('%H:%M')),
                "duration": max(2, int(float(event.get('duration_hours', 1)) * 2)),
                "notes": event.get('notes', '')
            })
        return events


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CalendarApp()
    window.show()
    sys.exit(app.exec())