import sys
import json
import os
from datetime import datetime, timedelta
from PySide6.QtWidgets import (QApplication, QMainWindow, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QHBoxLayout,
                               QWidget, QPushButton, QDialog, QFormLayout,
                               QComboBox, QDateEdit, QTimeEdit, QLineEdit,
                               QHeaderView, QMenu, QAbstractItemView, QStyledItemDelegate)
from PySide6.QtCore import Qt, QDate, QTime
from PySide6.QtGui import QColor, QBrush, QPainter, QIcon, QPixmap

# 数据持久化文件路径
DATA_FILE = "events_data.json"


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

        # 绘制半透明右侧网格分割线
        painter.setPen(QColor(255, 255, 255, 20))
        painter.drawLine(option.rect.topRight(), option.rect.bottomRight())
        painter.restore()


class MinimalTable(QTableWidget):
    """拦截原生拖拽释放事件，手动触发全局数据同步与重绘以修复合并单元格撕裂问题"""

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
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.clicked.connect(self.open_add_dialog)
        header_layout.addStretch()
        header_layout.addWidget(self.add_btn)
        layout.addLayout(header_layout)

        # 初始化网格：36行(6:00-24:00)，21列(21天)
        self.table = MinimalTable(36, 21)
        layout.addWidget(self.table)

        self.setup_table()
        self.populate_table()

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
        # 禁用默认网格线与边框
        self.table.setShowGrid(False)
        self.table.setFrameShape(QTableWidget.Shape.NoFrame)
        # 锁定列宽自适应
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        # 开启行高弹性拉伸，移除最小高度限制
        self.table.verticalHeader().setMinimumSectionSize(1)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # 禁用垂直滚动条
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 初始化日期表头
        for i in range(21):
            date_obj = self.start_date + timedelta(days=i)
            text = f"{date_obj.strftime('%m-%d')}\n周{'一二三四五六日'[date_obj.weekday()]}"
            item = QTableWidgetItem(text)
            # 高亮当天
            if i == 10: item.setBackground(QColor("#222222"))
            self.table.setHorizontalHeaderItem(i, item)

        # 初始化时间表头（6:00起始，偶数整点显示）
        times = []
        for h in range(6, 24):
            times.append(f"{h:02d}:00" if h % 2 == 0 else "")
            times.append("")
        self.table.setVerticalHeaderLabels(times)

        # 配置拖放引擎
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

        # 挂载自定义渲染器
        self.table.setItemDelegate(MinimalDelegate())

        # 注入全局深色 QSS 样式
        self.setStyleSheet(""" 
            QMainWindow, QDialog { background-color: #000000; color: #FFFFFF; }
            QTableWidget { background-color: #000000; color: #FFFFFF; border: none; }
            QHeaderView::section:horizontal { background-color: #111111; color: #FFFFFF; border: 1px solid #222222; }
            QHeaderView::section:vertical { background-color: #000000; color: #FFFFFF; border: none; padding-right: 5px; }
            QPushButton, QLineEdit, QComboBox, QDateEdit, QTimeEdit { background-color: #222222; color: #FFFFFF; border: 1px solid #444444; }
            QMenu { background-color: #222; color: white; border: 1px solid #444; }
            QMenu::item:selected { background-color: #555; }
        """)

        # 挂载右键菜单与内容变更监听
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.cellChanged.connect(self.on_cell_changed)

    def populate_table(self):
        """解析 JSON 数据映射并重绘网格"""
        # 阻断信号以防循环触发
        self.table.blockSignals(True)
        # 清除现有数据与合并状态
        self.table.clearContents()
        self.table.clearSpans()

        for date_str, times in self.events_data.items():
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            col = (date_obj - self.start_date).days

            # 过滤超界列数据
            if 0 <= col < 21:
                for time_str, event in times.items():
                    h, m = map(int, time_str.split(':'))
                    # 过滤 6:00 以前的历史异常数据
                    if h < 6: continue

                    # 坐标系转换：计算网格行索引
                    row = (h - 6) * 2 + (1 if m >= 30 else 0)

                    item = QTableWidgetItem(event["text"])
                    color_pref = event.get("color", "auto")
                    # 取出时长配置，最低强制限制为 2 格
                    duration = max(2, event.get("duration", 2))

                    # 应用颜色策略
                    if color_pref == "auto":
                        bg_hex, fg_hex = self.analyzer.get_style(date_obj, self.today)
                    else:
                        bg_hex, fg_hex = color_pref, "#000000"

                    item.setBackground(QBrush(QColor(bg_hex)))
                    item.setForeground(QBrush(QColor(fg_hex)))

                    # 将属性注入底层隐藏数据位
                    item.setData(Qt.ItemDataRole.UserRole + 1, color_pref)
                    item.setData(Qt.ItemDataRole.UserRole + 2, duration)
                    item.setData(Qt.ItemDataRole.UserRole + 3, event.get("repeat", "无"))

                    self.table.setItem(row, col, item)

                    # 处理跨越多行的合并单元格
                    if duration > 1:
                        # 计算剩余安全行数，防止越界报错
                        safe_dur = min(duration, 36 - row)
                        self.table.setSpan(row, col, safe_dur, 1)

        # 恢复信号监听
        self.table.blockSignals(False)

    def sync_data_from_table(self):
        """遍历网格层状态，逆向同步至本地 JSON 数据集"""
        new_data = {}
        for col in range(21):
            date_str = (self.start_date + timedelta(days=col)).strftime("%Y-%m-%d")
            for row in range(36):
                item = self.table.item(row, col)
                # 仅处理有效文本单元格
                if item and item.text().strip():
                    # 坐标系还原计算：基于行索引算出真实时分
                    h = (row // 2) + 6
                    m = "30" if row % 2 != 0 else "00"
                    time_str = f"{h:02d}:{m}"

                    if date_str not in new_data: new_data[date_str] = {}

                    # 读取隐藏属性组装数据，时长收集应用下限限制
                    new_data[date_str][time_str] = {
                        "text": item.text().strip(),
                        "color": item.data(Qt.ItemDataRole.UserRole + 1) or "auto",
                        "duration": max(2, item.data(Qt.ItemDataRole.UserRole + 2) or 2),
                        "repeat": item.data(Qt.ItemDataRole.UserRole + 3) or "无"
                    }
        # 更新内存实例并触发落盘
        self.events_data = new_data
        self.save_data()

    def on_cell_changed(self, row, col):
        """捕获网格编辑信号触发同步管线"""
        self.sync_data_from_table()
        self.populate_table()

    def show_context_menu(self, pos):
        """解析单击坐标，展示右键菜单并处理业务逻辑"""
        item = self.table.itemAt(pos)
        # 空白网格跳过处理
        if not item or not item.text().strip(): return

        menu = QMenu(self)
        edit_action = menu.addAction("修改属性")
        menu.addSeparator()
        del_action = menu.addAction("删除事件")

        # 映射坐标并阻塞式弹出菜单
        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == del_action:
            # 阻断修改信号，清空文本由后续重绘流程销毁数据
            self.table.blockSignals(True)
            item.setText("")
            self.table.blockSignals(False)
            self.on_cell_changed(item.row(), item.column())

        elif action == edit_action:
            # 提取现存底层属性
            cur_color = item.data(Qt.ItemDataRole.UserRole + 1) or "auto"
            cur_duration = item.data(Qt.ItemDataRole.UserRole + 2) or 2
            cur_repeat = item.data(Qt.ItemDataRole.UserRole + 3) or "无"

            dialog = EventPropertyDialog(cur_color, cur_duration, cur_repeat, self)
            # 若对话框正常确认返回
            if dialog.exec():
                color, duration, repeat = dialog.get_data()

                # 阻断信号，将新属性写回单元格隐藏位
                self.table.blockSignals(True)
                item.setData(Qt.ItemDataRole.UserRole + 1, color)
                item.setData(Qt.ItemDataRole.UserRole + 2, duration)
                item.setData(Qt.ItemDataRole.UserRole + 3, repeat)
                self.table.blockSignals(False)

                # 提交同步操作
                self.sync_data_from_table()
                self.populate_table()

    def open_add_dialog(self):
        """弹出新建事件模态窗，接收输入并注入数据集"""
        dialog = AddEventDialog(self.today, self)
        if dialog.exec():
            data = dialog.get_data()
            date_str = data["date"].strftime("%Y-%m-%d")
            time_str = data["time"].toString("HH:mm")

            if date_str not in self.events_data:
                self.events_data[date_str] = {}

                # 组装数据结构并插入
            self.events_data[date_str][time_str] = {
                "text": data["text"],
                "color": "auto",
                "duration": data["duration"],
                "repeat": "无"
            }
            # 执行持久化与重绘
            self.save_data()
            self.populate_table()

    def resizeEvent(self, event):
        """重写缩放事件，固定分配七等分视图宽度"""
        super().resizeEvent(event)
        col_width = self.table.viewport().width() // 7
        for i in range(21): self.table.setColumnWidth(i, col_width)

    def showEvent(self, event):
        """重写显现事件，调整水平滚动条将当天日期居中"""
        super().showEvent(event)
        self.table.horizontalScrollBar().setValue(7 * self.table.columnWidth(0))


# ==========================================
# 组件层：下拉弹窗与表单配置
# ==========================================
def create_color_icon(hex_code):
    """生成下拉选框用的预设颜色块图标"""
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("#000000" if hex_code == "auto" else hex_code))
    return QIcon(pixmap)


class EventPropertyDialog(QDialog):
    """独立事件属性配置子页面"""

    def __init__(self, cur_color, cur_duration, cur_repeat, parent=None):
        super().__init__(parent)
        self.setWindowTitle("属性")
        layout = QFormLayout(self)

        # 颜色属性初始化
        self.color_cb = QComboBox()
        colors = [("动态自动 (基于日期)", "auto"), ("浅灰", "#D3D3D3"), ("浅粉", "#FFB3BA"), ("浅绿", "#BAFFC9"),
                  ("浅蓝", "#BAE1FF")]
        for name, hx in colors: self.color_cb.addItem(create_color_icon(hx), name, hx)
        idx = self.color_cb.findData(cur_color)
        self.color_cb.setCurrentIndex(idx if idx >= 0 else 0)

        # 时长属性初始化
        self.dur_cb = QComboBox()
        durations = [("1小时 (2格)", 2), ("1.5小时 (3格)", 3), ("2小时 (4格)", 4), ("3小时 (6格)", 6)]
        for name, val in durations: self.dur_cb.addItem(name, val)
        idx2 = self.dur_cb.findData(cur_duration)
        self.dur_cb.setCurrentIndex(idx2 if idx2 >= 0 else 0)

        # 重复属性初始化
        self.repeat_cb = QComboBox()
        self.repeat_cb.addItems(["无", "每天", "每周"])
        self.repeat_cb.setCurrentText(cur_repeat)

        save_btn = QPushButton("确认")
        save_btn.clicked.connect(self.accept)

        layout.addRow("底色:", self.color_cb)
        layout.addRow("时长:", self.dur_cb)
        layout.addRow("重复:", self.repeat_cb)
        layout.addWidget(save_btn)

    def get_data(self):
        """返回对话框提取的数据"""
        return self.color_cb.currentData(), self.dur_cb.currentData(), self.repeat_cb.currentText()


class AddEventDialog(QDialog):
    """新建事件录入子页面"""

    def __init__(self, default_date, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加")
        layout = QFormLayout(self)

        self.text_input = QLineEdit()
        self.date_input = QDateEdit()
        # 转化传入参数为基础日期结构并启用日历控件
        self.date_input.setDate(QDate(default_date.year, default_date.month, default_date.day))
        self.date_input.setCalendarPopup(True)

        self.time_input = QTimeEdit()
        self.time_input.setDisplayFormat("HH:mm")
        # 限制时间选取下限为 6:00
        self.time_input.setMinimumTime(QTime(6, 0))

        self.dur_cb = QComboBox()
        durations = [("1小时 (2格)", 2), ("1.5小时 (3格)", 3), ("2小时 (4格)", 4), ("3小时 (6格)", 6)]
        for name, val in durations: self.dur_cb.addItem(name, val)

        save_btn = QPushButton("确认")
        save_btn.clicked.connect(self.accept)

        layout.addRow("内容:", self.text_input)
        layout.addRow("日期:", self.date_input)
        layout.addRow("时间:", self.time_input)
        layout.addRow("时长:", self.dur_cb)
        layout.addWidget(save_btn)

    def get_data(self):
        """返回表单打包数据"""
        return {
            "text": self.text_input.text(),
            "date": self.date_input.date().toPython(),
            "time": self.time_input.time(),
            "duration": self.dur_cb.currentData()
        }


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CalendarApp()
    window.show()
    sys.exit(app.exec())