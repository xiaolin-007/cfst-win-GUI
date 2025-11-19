# cfst_gui.py
# 依赖: PySide6
# pip install PySide6
# 运行: python cfst_gui.py

import sys
import os
import csv
import subprocess
import threading
import time
from collections import defaultdict

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QMessageBox, QListWidgetItem,
    QStatusBar, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QSpinBox
)
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtCore import Qt, QTimer

# ---------- PyInstaller 资源路径 ----------
def resource_path(relative_path):
    """
    保证打包后能正确找到资源文件（ico 等）
    """
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return relative_path

# ---------- 常量 ----------
DEFAULT_CFST_NAME = "cfst.exe"
DEFAULT_IP_FILENAME = "ip.txt"
WORK_DIR = os.getcwd()
REGION_CSV = os.path.join(WORK_DIR, "region.csv")
REGION_OK = os.path.join(WORK_DIR, "region_ok.txt")
RESULT_CSV = os.path.join(WORK_DIR, "result.csv")

CODE_TO_COUNTRY = {
    "SJC": "美国 (圣何塞)", "SFO": "美国 (旧金山)", "LAX": "美国 (洛杉矶)",
    "ORD": "美国 (芝加哥)", "JFK": "美国 (纽约)", "DEN": "美国 (丹佛)",
    "SEA": "美国 (西雅图)", "EWR": "美国 (纽瓦克/Newark)", "IAD": "美国 (华盛顿 Dulles)",
    "BOS": "美国 (波士顿)", "MIA": "美国 (迈阿密)", "DFW": "美国 (达拉斯/Fort Worth)",
    "ATL": "美国 (亚特兰大)", "PHX": "美国 (菲尼克斯)", "CLT": "美国 (夏洛特)",
    "MSP": "美国 (明尼阿波利斯)", "SLC": "美国 (盐湖城)", "TPA": "美国 (坦帕)",
    "NRT": "日本 (成田)", "HND": "日本 (羽田)", "KIX": "日本 (关西)", "FUK": "日本 (福冈)",
    "HKG": "中国 (香港)",
    "LHR": "英国 (伦敦希思罗)", "LGW": "英国 (伦敦盖特威克)",
    "CDG": "法国 (巴黎戴高乐)", "ORY": "法国 (巴黎奥利)",
    "FRA": "德国 (法兰克福)", "MUC": "德国 (慕尼黑)",
    "AMS": "荷兰 (阿姆斯特丹)",
    "SYD": "澳大利亚 (悉尼)", "MEL": "澳大利亚 (墨尔本)", "BNE": "澳大利亚 (布里斯班)",
    "EZE": "阿根廷 (布宜诺斯艾利斯)",
    "GRU": "巴西 (圣保罗)",
    "DXB": "阿联酋 (迪拜)", "AUH": "阿联酋 (阿布扎比)",
    "SIN": "新加坡", "ICN": "韩国 (仁川)",
    "IST": "土耳其 (伊斯坦布尔)",
    "MAD": "西班牙 (马德里）",
    "YYZ": "加拿大 (多伦多）",
}

# ---------- 工具函数 ----------
def looks_like_ip(s: str) -> bool:
    s = (s or "").strip()
    parts = s.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return True
    if ":" in s and all(len(p) <= 4 for p in s.split(":") if p):
        return True
    return False

def start_process_new_console(cmd_args, cwd=WORK_DIR):
    try:
        if os.name == "nt":
            p = subprocess.Popen(cmd_args, cwd=cwd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            p = subprocess.Popen(cmd_args, cwd=cwd)
    except FileNotFoundError as e:
        QMessageBox.critical(None, "启动失败", f"找不到可执行文件: {e}")
        return None
    except Exception as e:
        QMessageBox.critical(None, "启动失败", f"启动进程失败: {e}")
        return None
    return p

def monitor_process_and_restore(p, on_done_callback, check_interval=0.2):
    def runner():
        try:
            while True:
                rc = p.poll()
                if rc is not None:
                    QTimer.singleShot(0, lambda rc=rc: on_done_callback(rc))
                    break
                time.sleep(check_interval)
        except Exception:
            QTimer.singleShot(0, lambda: on_done_callback(None))
    threading.Thread(target=runner, daemon=True).start()

# ---------- 主界面 ----------
class CFSTGui(QWidget):
    MAX_DISPLAY_ROWS = 10

    def __init__(self):
        super().__init__()

        # 设置窗口标题
        self.setWindowTitle("CFST GUI - 小琳解说")

        # ---------- ★ 程序图标（标题栏 + 任务栏）----------
        self.setWindowIcon(QIcon(resource_path("xl.ico")))

        self.resize(400, 600)
        self.setFont(QFont("Microsoft YaHei", 10))
        self._current_process = None
        self._ui_timer = None

        self._build_ui()
        self._bind_events()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 按钮行
        row2 = QHBoxLayout()
        row2.setAlignment(Qt.AlignHCenter)
        btn_style = "background:#2ecc71;color:white;border-radius:4px;font-size:11pt;"
        stat_style = "background:#f39c12;color:white;border-radius:4px;font-size:11pt;"
        btn_width = 160; btn_height = 36

        self.btn_scan = QPushButton("一键扫描")
        self.btn_scan.setStyleSheet(btn_style)
        self.btn_scan.setFixedSize(btn_width, btn_height)

        self.btn_stat = QPushButton("统计地区")
        self.btn_stat.setStyleSheet(stat_style)
        self.btn_stat.setFixedSize(btn_width, btn_height)

        row2.addWidget(self.btn_scan)
        row2.addSpacing(8)
        row2.addWidget(self.btn_stat)
        root.addLayout(row2)

        # 并发线程设置
        thread_row = QHBoxLayout()
        thread_row.setAlignment(Qt.AlignHCenter)
        lbl_threads = QLabel("并发线程数")
        lbl_threads.setFixedHeight(28)
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 1000)
        self.spin_threads.setValue(50)
        self.spin_threads.setFixedWidth(50)

        thread_row.addWidget(lbl_threads)
        thread_row.addSpacing(6)
        thread_row.addWidget(self.spin_threads)
        root.addLayout(thread_row)

        # 上下分栏
        splitter = QSplitter(Qt.Vertical)
        root.addWidget(splitter, 1)

        # 上部：地区统计
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(6, 6, 6, 6)
        top_layout.setSpacing(6)
        top_layout.addWidget(QLabel("地区统计列表"))

        self.lst_regions = QListWidget()
        self.lst_regions.setSelectionMode(QListWidget.SingleSelection)
        top_layout.addWidget(self.lst_regions, 1)
        top_layout.addWidget(QLabel("双击地区载入，点击测速。"))

        splitter.addWidget(top_widget)

        # 下部：测速结果
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(6, 6, 6, 6)
        bottom_layout.setSpacing(6)
        bottom_widget.setMinimumHeight(240)
        bottom_layout.addWidget(QLabel("测速结果（双击单元格复制）"))

        self.tbl_result = QTableWidget(0, 4)
        self.tbl_result.setHorizontalHeaderLabels(["IP 地址", "平均延迟", "下载速度", "地区码"])
        header = self.tbl_result.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)

        self.tbl_result.setColumnWidth(0, 118)
        self.tbl_result.setColumnWidth(1, 68)
        self.tbl_result.setColumnWidth(2, 80)
        self.tbl_result.setColumnWidth(3, 66)
        self.tbl_result.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_result.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_result.setSortingEnabled(False)
        self.tbl_result.cellDoubleClicked.connect(self._on_cell_double_clicked)

        bottom_layout.addWidget(self.tbl_result, 1)

        # 测速按钮
        row_speed = QHBoxLayout()
        row_speed.addStretch(1)
        self.btn_speed = QPushButton("测 速")
        speed_style = "background:#e74c3c;color:white;border-radius:4px;font-size:11pt;"
        self.btn_speed.setStyleSheet(speed_style)
        self.btn_speed.setFixedSize(120, 36)
        row_speed.addWidget(self.btn_speed)
        row_speed.addStretch(1)
        bottom_layout.addLayout(row_speed)

        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        # 状态栏
        self.status = QStatusBar()
        self.status.showMessage("就绪")
        root.addWidget(self.status)

    # ---------------- 事件绑定 ----------------
    def _bind_events(self):
        self.btn_scan.clicked.connect(self.on_scan)
        self.btn_stat.clicked.connect(self.on_stat)
        self.lst_regions.itemDoubleClicked.connect(self.on_region_double)
        self.btn_speed.clicked.connect(self.on_speed)

    # ---------------- 双击复制 ----------------
    def _on_cell_double_clicked(self, row: int, column: int):
        item = self.tbl_result.item(row, column)
        if item:
            text = item.text()
            QGuiApplication.clipboard().setText(text)
            self.status.showMessage(f"已复制: {text}")
            QTimer.singleShot(1500, lambda: self.status.showMessage("就绪"))

    # ---------------- 加载测速结果 ----------------
    def _load_result_into_table(self):
        if not os.path.isfile(RESULT_CSV):
            self.status.showMessage(f"未找到 {RESULT_CSV}")
            self.tbl_result.setRowCount(0)
            return

        try:
            with open(RESULT_CSV, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip("\n\r") for ln in f.readlines()]
        except Exception as e:
            self.status.showMessage(f"读取 {RESULT_CSV} 失败: {e}")
            self.tbl_result.setRowCount(0)
            return

        lines = [ln for ln in lines if ln.strip()]
        if not lines:
            self.tbl_result.setRowCount(0)
            self.status.showMessage("result.csv 内容为空")
            return

        try:
            rows = [r for r in csv.reader(lines, delimiter=",")]
        except Exception:
            rows = [ln.split(",") for ln in lines]

        rows = [r for r in rows if any(cell.strip() for cell in r)]
        if not rows:
            self.tbl_result.setRowCount(0)
            self.status.showMessage("没有有效数据行")
            return

        header = [h.strip() for h in rows[0]]
        col_map = {
            "ip": ["ip 地址", "ip地址", "ip", "address", "host"],
            "avg_rtt": ["平均延迟", "平均延时", "avg", "avg_rtt", "latency", "rtt", "平均延迟(ms)"],
            "down_mb": ["下载速度(mb/s)", "下载速度", "download", "download speed", "download_mb", "下载速度(MB/s)"],
            "region": ["地区码", "地区", "region", "colo", "cfcolo", "place", "country"]
        }

        indices = {}
        for key, variants in col_map.items():
            for i, h in enumerate(header):
                hs = h.strip().lower()
                if any(v.lower() == hs or v.lower() in hs for v in variants):
                    indices[key] = i
                    break

        probable_header = any(k in indices for k in ("ip", "avg_rtt", "down_mb", "region"))
        start_row = 1 if probable_header else 0

        sample_rows = rows[start_row:start_row+10]
        if "ip" not in indices:
            for c in range(max(len(r) for r in sample_rows) if sample_rows else len(header)):
                if any(c < len(r) and looks_like_ip(r[c]) for r in sample_rows):
                    indices["ip"] = c
                    break

        num_cols = max(len(r) for r in rows)
        indices.setdefault("ip", 0)
        indices.setdefault("avg_rtt", min(4, num_cols - 1))
        indices.setdefault("down_mb", min(5, num_cols - 1))
        indices.setdefault("region", min(6, num_cols - 1))

        self.tbl_result.setRowCount(0)
        added = 0
        for r in rows[start_row:]:
            if added >= self.MAX_DISPLAY_ROWS:
                break
            if not any(cell.strip() for cell in r):
                continue

            def safe_get(idx):
                return r[idx].strip() if idx < len(r) else ""

            ip = safe_get(indices["ip"])
            if not ip:
                for cell in r:
                    if looks_like_ip(cell):
                        ip = cell.strip()
                        break

            avg_raw = safe_get(indices["avg_rtt"])
            down_raw = safe_get(indices["down_mb"])
            region = safe_get(indices["region"])

            avg = self._normalize_avg(avg_raw)
            down = self._normalize_down(down_raw)

            row_idx = self.tbl_result.rowCount()
            self.tbl_result.insertRow(row_idx)

            def mk_item(text):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignCenter)
                return it

            self.tbl_result.setItem(row_idx, 0, mk_item(ip))
            self.tbl_result.setItem(row_idx, 1, mk_item(avg))
            self.tbl_result.setItem(row_idx, 2, mk_item(down))
            self.tbl_result.setItem(row_idx, 3, mk_item(region))
            added += 1

        self.status.showMessage(f"已加载 {added} 条结果（最多显示 {self.MAX_DISPLAY_ROWS} 行）")

    # ---------------- 单位转换 ----------------
    def _normalize_down(self, s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        low = s.lower().replace(",", "").strip()
        try:
            if "mb" in low:
                num = ''.join(ch for ch in low if (ch.isdigit() or ch == '.'))
                return f"{float(num):.2f}" if num else s
            if "kb" in low:
                num = ''.join(ch for ch in low if (ch.isdigit() or ch == '.'))
                return f"{float(num)/1024:.2f}" if num else s
            if "b/s" in low or "bps" in low or "byte" in low:
                num = ''.join(ch for ch in low if (ch.isdigit() or ch == '.'))
                return f"{float(num)/1024/1024:.2f}" if num else s
            num = ''.join(ch for ch in low if (ch.isdigit() or ch == '.'))
            return f"{float(num):.2f}" if num else s
        except:
            return s

    def _normalize_avg(self, s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        low = s.lower().replace("ms", " ").replace(",", " ").strip()
        num = ""
        for ch in low:
            if ch.isdigit() or ch == '.':
                num += ch
            elif num:
                break
        try:
            return f"{float(num):.1f}" if num else s
        except:
            return s

    # ---------------- 扫描 ----------------
    def on_scan(self):
        cfst_path = os.path.join(WORK_DIR, DEFAULT_CFST_NAME)
        ip_path = os.path.join(WORK_DIR, DEFAULT_IP_FILENAME)

        missing = []
        if not os.path.isfile(cfst_path):
            missing.append(DEFAULT_CFST_NAME)
        if not os.path.isfile(ip_path):
            missing.append(DEFAULT_IP_FILENAME)

        if missing:
            QMessageBox.warning(self, "缺少文件", f"当前目录缺少：{', '.join(missing)}")
            self.status.showMessage("缺少文件，扫描取消")
            return

        threads = int(self.spin_threads.value())

        cmd = [
            cfst_path,
            "-n", str(threads),
            "-tp", "443",
            "-url", "https://cf.xiu2.xyz/url",
            "-httping",
            "-dd",
            "-o", REGION_CSV
        ]

        self.status.showMessage("扫描在新窗口运行...")
        self.btn_scan.setEnabled(False)

        p = start_process_new_console(cmd)
        if p is None:
            self.btn_scan.setEnabled(True)
            self.status.showMessage("启动失败")
            return

        self._current_process = p

        def on_done(rc):
            self.btn_scan.setEnabled(True)
            self._current_process = None
            if os.path.isfile(REGION_CSV):
                self.status.showMessage("扫描完成，请统计地区")
            else:
                self.status.showMessage("扫描结束")

        monitor_process_and_restore(p, on_done)

    # ---------------- 地区统计 ----------------
    def on_stat(self):
        if not os.path.isfile(REGION_CSV):
            QMessageBox.warning(self, "错误", "找不到 region.csv，请先扫描")
            return

        try:
            with open(REGION_CSV, newline='', encoding='utf-8') as f:
                rows = list(csv.reader(f))
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取 region.csv 失败: {e}")
            return

        if not rows:
            QMessageBox.information(self, "提示", "region.csv 内容为空")
            return

        header = rows[0]
        lower = [h.strip().lower() for h in header]
        region_idx = -1
        ip_idx = -1

        for i, h in enumerate(lower):
            if any(k in h for k in ("colo", "cfcolo", "region", "place", "country")):
                region_idx = i
            if "ip" in h or "address" in h:
                ip_idx = i

        start_row = 1 if region_idx != -1 or ip_idx != -1 else 0
        if ip_idx == -1 and len(rows) > start_row:
            for i in range(len(rows[start_row])):
                if looks_like_ip(rows[start_row][i]):
                    ip_idx = i
                    break
        if ip_idx == -1:
            ip_idx = 0

        counter = defaultdict(list)
        for r in rows[start_row:]:
            if not r:
                continue
            ip = r[ip_idx].strip() if ip_idx < len(r) else ""
            region = r[region_idx].strip() if region_idx != -1 and region_idx < len(r) else ""
            if not region:
                token = None
                for col in r:
                    s = col.strip()
                    if 2 <= len(s) <= 4 and all(c.isalnum() for c in s):
                        token = s
                        break
                region = token or "UNKNOWN"
            if ip:
                counter[region].append(ip)

        items = []
        for code, ips in counter.items():
            count = len(ips)
            country = CODE_TO_COUNTRY.get(code.upper(), code)
            items.append((code, country, count, ips))

        items.sort(key=lambda x: x[2], reverse=True)
        self.lst_regions.clear()
        idx = 1
        for code, country, count, ips in items:
            text = f"{idx}. {country} {count}个可用IP [{code}]"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, {"code": code, "country": country, "ips": ips})
            self.lst_regions.addItem(item)
            idx += 1

        self.status.showMessage(f"统计完成，共 {len(items)} 个地区")

    # ---------------- 选择地区 ----------------
    def on_region_double(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if not data:
            return

        ips = data.get("ips", [])
        country = data.get("country", "未知")
        uniq = sorted({ip.strip() for ip in ips if ip.strip()})

        try:
            with open(REGION_OK, "w", encoding="utf-8") as f:
                for ip in uniq:
                    f.write(ip + "\n")
            self.status.showMessage(f"{country}地区 IP 已导入，点击测速")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"写入 region_ok.txt 出错: {e}")

    # ---------------- 测速 ----------------
    def on_speed(self):
        cfst_path = os.path.join(WORK_DIR, DEFAULT_CFST_NAME)
        if not os.path.isfile(cfst_path):
            QMessageBox.warning(self, "缺少文件", "找不到 cfst.exe")
            return
        if not os.path.isfile(REGION_OK):
            QMessageBox.warning(self, "缺少文件", "找不到 region_ok.txt，请先双击地区")
            return

        try:
            if os.path.isfile(RESULT_CSV):
                os.remove(RESULT_CSV)
        except:
            pass

        cmd = [
            cfst_path,
            "-n", "100",
            "-tp", "443",
            "-f", REGION_OK,
            "-o", RESULT_CSV
        ]

        self.status.showMessage("测速中...")
        self.btn_speed.setEnabled(False)

        p = start_process_new_console(cmd)
        if p is None:
            self.btn_speed.setEnabled(True)
            self.status.showMessage("启动测速失败")
            return

        self._current_process = p

        def on_done(rc):
            self.btn_speed.setEnabled(True)
            self._current_process = None

            if os.path.isfile(RESULT_CSV):
                self.status.showMessage("测速完成，加载结果...")
                try:
                    self._load_result_into_table()
                except Exception as e:
                    self.status.showMessage(f"加载失败: {e}")
            else:
                self.status.showMessage("测速结束")

        monitor_process_and_restore(p, on_done)

# ---------- 启动 ----------
def main():
    app = QApplication(sys.argv)
    gui = CFSTGui()
    gui.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
