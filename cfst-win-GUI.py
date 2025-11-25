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
    QSpinBox, QComboBox
)
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtCore import Qt, QTimer

# ---------- 兼容 PyInstaller 路径 ----------
def resource_path(relative_path):
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
    "TPE": "中国 (台湾台北)", "KHH": "中国 (台湾高雄)",
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

# ---------- 辅助 ----------
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

# ---------- 主 GUI ----------
class CFSTGui(QWidget):
    MAX_DISPLAY_ROWS = 10  # 只显示前 10 行

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CFST GUI - 小琳解说 V2.1")
        self.setWindowIcon(QIcon(resource_path("xl.ico")))
        self.resize(390, 600)
        self.setFont(QFont("Microsoft YaHei", 10))
        self._current_process = None
        self._ui_timer = None
        self._build_ui()
        self._bind_events()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 原来 row2 布局替换为：左右弹性间隔 + 居中按钮组
        row2 = QHBoxLayout()
        btn_style = "background:#2ecc71;color:white;border-radius:4px;font-size:11pt;"
        stat_style = "background:#f39c12;color:white;border-radius:4px;font-size:11pt;"
        btn_width = 160; btn_height = 36

        # 创建按钮
        self.btn_scan = QPushButton("一键扫描")
        self.btn_scan.setStyleSheet(btn_style)
        self.btn_scan.setFixedSize(btn_width, btn_height)

        self.btn_stat = QPushButton("统计地区")
        self.btn_stat.setStyleSheet(stat_style)
        self.btn_stat.setFixedSize(btn_width, btn_height)

        btn_group = QHBoxLayout()
        btn_group.setSpacing(8)
        btn_group.addWidget(self.btn_scan)
        btn_group.addWidget(self.btn_stat)

        row2.addStretch(1)
        row2.addLayout(btn_group)
        row2.addStretch(1)
        root.addLayout(row2)

        # 新增：并发线程与扫描端口 同行左右排列（位于一键扫描按钮下面）
        row_controls = QHBoxLayout()
        row_controls.addStretch(1)

        # 并发线程控件
        lbl = QLabel("并发线程")
        lbl.setFixedHeight(24)
        self.spin_concurrency = QSpinBox()
        self.spin_concurrency.setRange(1, 200)
        self.spin_concurrency.setValue(50)
        self.spin_concurrency.setFixedWidth(70)
        row_controls.addWidget(lbl)
        row_controls.addWidget(self.spin_concurrency)

        row_controls.addSpacing(12)

        # 端口下拉控件
        lblp = QLabel("扫描端口")
        lblp.setFixedHeight(24)
        self.cmb_port = QComboBox()
        ports = ["443", "2053", "2083", "2087", "2096", "8443"]
        self.cmb_port.addItems(ports)
        self.cmb_port.setCurrentText("443")
        self.cmb_port.setFixedWidth(70)
        row_controls.addWidget(lblp)
        row_controls.addWidget(self.cmb_port)

        row_controls.addStretch(1)
        root.addLayout(row_controls)

        splitter = QSplitter(Qt.Vertical)
        root.addWidget(splitter, 1)

        top_widget = QWidget(); top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(6,6,6,6); top_layout.setSpacing(6)
        top_layout.addWidget(QLabel("地区统计列表"))
        self.lst_regions = QListWidget(); self.lst_regions.setSelectionMode(QListWidget.SingleSelection)
        top_layout.addWidget(self.lst_regions, 1)
        top_layout.addWidget(QLabel("双击地区载入，点击测速。"))
        splitter.addWidget(top_widget)

        bottom_widget = QWidget(); bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(6,6,6,6); bottom_layout.setSpacing(6)
        bottom_layout.addWidget(QLabel("测速结果（双击单元格复制）"))

        self.tbl_result = QTableWidget(0, 4)
        self.tbl_result.setHorizontalHeaderLabels(["IP 地址", "平均延迟", "下载速度", "地区码"])
        header = self.tbl_result.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.tbl_result.setColumnWidth(0, 118)
        self.tbl_result.setColumnWidth(1, 62)
        self.tbl_result.setColumnWidth(2, 72)
        self.tbl_result.setColumnWidth(3, 62)
        self.tbl_result.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_result.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_result.setSortingEnabled(False)
        self.tbl_result.cellDoubleClicked.connect(self._on_cell_double_clicked)
        bottom_layout.addWidget(self.tbl_result, 1)

        row_speed = QHBoxLayout()
        row_speed.addStretch(1)
        self.btn_speed = QPushButton("测 速")
        speed_style = "background:#e74c3c;color:white;border-radius:4px;font-size:11pt;"
        self.btn_speed.setStyleSheet(speed_style)
        self.btn_speed.setFixedSize(120, 36)
        row_speed.addWidget(self.btn_speed); row_speed.addStretch(1)
        bottom_layout.addLayout(row_speed)

        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 1); splitter.setStretchFactor(1, 1)

        self.status = QStatusBar(); self.status.showMessage("就绪")
        root.addWidget(self.status)

    def _bind_events(self):
        self.btn_scan.clicked.connect(self.on_scan)
        self.btn_stat.clicked.connect(self.on_stat)
        self.lst_regions.itemDoubleClicked.connect(self.on_region_double)
        self.btn_speed.clicked.connect(self.on_speed)

    # ---------- 双击复制单元格 ----------
    def _on_cell_double_clicked(self, row: int, column: int):
        item = self.tbl_result.item(row, column)
        if item is None:
            return
        text = item.text()
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)
        self.status.showMessage(f"已复制: {text}")
        QTimer.singleShot(1500, lambda: self.status.showMessage("就绪"))

    # ---------- 读取 result.csv ----------
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
            reader = csv.reader(lines, delimiter=",")
            rows = [r for r in reader]
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
                for v in variants:
                    vv = v.lower()
                    if vv == hs or vv in hs:
                        indices[key] = i
                        break
                if key in indices:
                    break

        probable_header = any(k in indices for k in ("ip", "avg_rtt", "down_mb", "region"))
        start_row = 1 if probable_header else 0

        sample_rows = rows[start_row:start_row+10]
        if "ip" not in indices:
            for c in range(max(len(r) for r in sample_rows) if sample_rows else len(header)):
                for r in sample_rows:
                    if c < len(r) and looks_like_ip(r[c]):
                        indices["ip"] = c
                        break
                if "ip" in indices:
                    break

        num_cols = max(len(r) for r in rows)
        if "ip" not in indices:
            indices["ip"] = 0
        if "avg_rtt" not in indices:
            indices["avg_rtt"] = min(4, num_cols - 1)
        if "down_mb" not in indices:
            indices["down_mb"] = min(5, num_cols - 1)
        if "region" not in indices:
            indices["region"] = min(6, num_cols - 1)

        self.tbl_result.setRowCount(0)
        added = 0
        for r in rows[start_row:]:
            if not any(cell.strip() for cell in r):
                continue
            if added >= self.MAX_DISPLAY_ROWS:
                break

            def safe_get(idx):
                return r[idx].strip() if idx < len(r) else ""

            ip = safe_get(indices["ip"])
            if not ip:
                for cell in r:
                    if looks_like_ip(cell):
                        ip = cell.strip(); break
            avg_raw = safe_get(indices["avg_rtt"])
            down_raw = safe_get(indices["down_mb"])
            region = safe_get(indices["region"])

            avg = self._normalize_avg(avg_raw)
            down = self._normalize_down(down_raw)

            row_idx = self.tbl_result.rowCount()
            self.tbl_result.insertRow(row_idx)

            item_ip = QTableWidgetItem(ip); item_ip.setTextAlignment(Qt.AlignCenter)
            item_avg = QTableWidgetItem(avg); item_avg.setTextAlignment(Qt.AlignCenter)
            item_down = QTableWidgetItem(down); item_down.setTextAlignment(Qt.AlignCenter)
            item_region = QTableWidgetItem(region); item_region.setTextAlignment(Qt.AlignCenter)

            self.tbl_result.setItem(row_idx, 0, item_ip)
            self.tbl_result.setItem(row_idx, 1, item_avg)
            self.tbl_result.setItem(row_idx, 2, item_down)
            self.tbl_result.setItem(row_idx, 3, item_region)

            added += 1

        self.status.showMessage(f"已加载 {added} 条结果（最多显示 {self.MAX_DISPLAY_ROWS} 行）")

    def _normalize_down(self, s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        low = s.lower().replace(",", "").strip()
        try:
            if "mb" in low:
                num = ''.join(ch for ch in low if (ch.isdigit() or ch=='.'))
                if num:
                    return f"{float(num):.2f}"
            if "kb" in low:
                num = ''.join(ch for ch in low if (ch.isdigit() or ch=='.'))
                if num:
                    return f"{float(num)/1024:.2f}"
            if "b/s" in low or "bps" in low or "byte" in low:
                num = ''.join(ch for ch in low if (ch.isdigit() or ch=='.'))
                if num:
                    return f"{float(num)/1024/1024:.2f}"
            num = ''.join(ch for ch in low if (ch.isdigit() or ch=='.'))
            if num:
                return f"{float(num):.2f}"
        except Exception:
            pass
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
            if num:
                return f"{float(num):.1f}"
        except Exception:
            pass
        return s if len(s) <= 12 else s[:12] + "..."

    # ---------- 扫描 ----------
    def on_scan(self):
        cfst_path = os.path.join(WORK_DIR, DEFAULT_CFST_NAME)
        ip_path = os.path.join(WORK_DIR, DEFAULT_IP_FILENAME)

        missing = []
        if not os.path.isfile(cfst_path):
            missing.append(DEFAULT_CFST_NAME)
        if not os.path.isfile(ip_path):
            missing.append(DEFAULT_IP_FILENAME)

        if missing:
            QMessageBox.warning(self, "缺少文件", f"当前目录缺少必须的文件：{', '.join(missing)}\n请把这两个文件放到同一目录后再试。")
            self.status.showMessage("缺少必须文件，扫描被取消")
            return

        # 从输入框读取并发线程数与端口
        n_threads = str(self.spin_concurrency.value())
        tp_port = str(self.cmb_port.currentText())

        cmd = [
            cfst_path,
            "-n", n_threads,
            "-tp", tp_port,
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
                self.status.showMessage("扫描完成: region.csv 已生成")
            else:
                if rc is None:
                    self.status.showMessage("就绪")
                else:
                    self.status.showMessage(f"就绪（扫描结束，退出码 {rc}）")

        monitor_process_and_restore(p, on_done)

        if self._ui_timer is None:
            self._ui_timer = QTimer(self)
            def ui_check():
                if self._current_process is None:
                    if self._ui_timer:
                        self._ui_timer.stop()
                    self._ui_timer = None
                    return
                try:
                    rc = self._current_process.poll()
                    if rc is not None:
                        on_done(rc)
                        if self._ui_timer:
                            self._ui_timer.stop()
                        self._ui_timer = None
                except Exception:
                    on_done(None)
                    if self._ui_timer:
                        self._ui_timer.stop()
                    self._ui_timer = None
            self._ui_timer.timeout.connect(ui_check)
            self._ui_timer.start(300)

    # ---------- 统计 ----------
    def on_stat(self):
        if not os.path.isfile(REGION_CSV):
            QMessageBox.warning(self, "错误", "找不到 region.csv，请先运行扫描生成该文件。")
            return
        try:
            with open(REGION_CSV, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取 region.csv 时失败: {e}")
            return

        if not rows:
            QMessageBox.information(self, "提示", "region.csv 内容为空。")
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
        if ip_idx == -1:
            if rows and len(rows) > start_row:
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
            region = (r[region_idx].strip() if (region_idx != -1 and region_idx < len(r)) else "").strip()
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

    # ---------- 双击地区 ----------
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
            self.status.showMessage(f"{country}地区IP已导入，点击测速。")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存 region_ok.txt 时失败: {e}")

    # ---------- 测速 ----------
    def on_speed(self):
        cfst_path = os.path.join(WORK_DIR, DEFAULT_CFST_NAME)
        if not os.path.isfile(cfst_path):
            QMessageBox.warning(self, "缺少文件", f"当前目录缺少 {DEFAULT_CFST_NAME}，请把它放在同一目录后再试。")
            return
        if not os.path.isfile(REGION_OK):
            QMessageBox.information(self, "提示", "找不到 region_ok.txt，请先双击某个地区以自动提取并保存 IP。")
            return

        try:
            if os.path.isfile(RESULT_CSV):
                os.remove(RESULT_CSV)
        except Exception:
            pass

        # 使用并发输入框的值作为测速的 -n，同时使用端口下拉的值作为 -tp
        n_threads = str(self.spin_concurrency.value())
        tp_port = str(self.cmb_port.currentText())

        cmd = [
            cfst_path,
            "-n", n_threads,
            "-tp", tp_port,
            "-f", REGION_OK,
            "-o", RESULT_CSV
        ]
        self.status.showMessage("测速正在进行中...")
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
                self.status.showMessage("测速完成: result.csv 已生成")
                try:
                    self._load_result_into_table()
                except Exception as e:
                    self.status.showMessage(f"就绪（加载结果失败: {e}）")
            else:
                if rc is None:
                    self.status.showMessage("就绪")
                else:
                    self.status.showMessage(f"就绪（测速结束，退出码 {rc}）")

        monitor_process_and_restore(p, on_done)

        if self._ui_timer is None:
            self._ui_timer = QTimer(self)
            def ui_check():
                if self._current_process is None:
                    if self._ui_timer:
                        self._ui_timer.stop()
                    self._ui_timer = None
                    if os.path.isfile(RESULT_CSV):
                        try:
                            self._load_result_into_table()
                        except Exception:
                            pass
                    return
                try:
                    rc = self._current_process.poll()
                    if rc is not None:
                        on_done(rc)
                        if self._ui_timer:
                            self._ui_timer.stop()
                        self._ui_timer = None
                except Exception:
                    on_done(None)
                    if self._ui_timer:
                        self._ui_timer.stop()
                    self._ui_timer = None
            self._ui_timer.timeout.connect(ui_check)
            self._ui_timer.start(300)

# ---------- 启动 ----------
def main():
    app = QApplication(sys.argv)
    gui = CFSTGui()
    gui.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
