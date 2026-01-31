import sys
import json
import math
import time
import ctypes
import os

# 단일 인스턴스 강제 (중복 실행 방지)
try:
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "NireumHeatmapMutex")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(0, "Nireum Heatmap이 이미 실행 중입니다.", "알림", 0x40)
        sys.exit(0)
except:
    pass

# Windows 작업표시줄 아이콘 설정
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Menglda.NireumHeatmap.1.0")
except:
    pass


from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python 3.8 이하 호환
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import yfinance as yf
import pandas as pd

from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout, 
                              QHBoxLayout, QPushButton, QFrame, QGraphicsDropShadowEffect, QToolTip, QDialog)
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal, QThread

from PyQt5.QtGui import QColor, QFont, QCursor, QIcon


try:
    from treemap_layout import calculate_treemap
except ImportError:
    def calculate_treemap(data, x, y, w, h, value_key): return []

import stocks_data

# EXE 실행 시 실행 파일 위치, 소스 실행 시 스크립트 위치
if getattr(sys, 'frozen', False):
    CONFIG_FILE = Path(sys.executable).parent / "config.json"
else:
    CONFIG_FILE = Path(__file__).parent / "config.json"

# 기본 스톡 데이터가 없을 경우 stocks_data에서 가져옴
DEFAULT_STOCKS = stocks_data.STOCKS

def get_color(change):
    """[그라데이션 개선] 등락율에 비례하는 부드러운 색상 변화"""
    if change == 0: return "#2c2c34"  # 0%: 검회색
    
    # 기준 색상 정의 (더 밝고 선명한 색상)
    base_gray = (44, 44, 52)  # #2c2c34
    green_max = (46, 125, 50)   # #2e7d32 (밝은 진한 녹색)
    red_max = (211, 47, 47)     # #d32f2f (밝은 진한 빨강)
    
    # 등락율을 0~1 범위로 정규화 (+-4% 기준으로 더 빠르게 진해지게)
    intensity = min(abs(change) / 4.0, 1.0)
    
    # 비선형 스케일링 + 최소값 보장 (0.25 ~ 1.0 범위)
    intensity = 0.25 + (intensity ** 0.6) * 0.75  # 최소 25%부터 시작
    
    if change > 0:
        # 녹색 그라데이션
        r = int(base_gray[0] + (green_max[0] - base_gray[0]) * intensity)
        g = int(base_gray[1] + (green_max[1] - base_gray[1]) * intensity)
        b = int(base_gray[2] + (green_max[2] - base_gray[2]) * intensity)
    else:
        # 빨강 그라데이션
        r = int(base_gray[0] + (red_max[0] - base_gray[0]) * intensity)
        g = int(base_gray[1] + (red_max[1] - base_gray[1]) * intensity)
        b = int(base_gray[2] + (red_max[2] - base_gray[2]) * intensity)
    
    return f"#{r:02x}{g:02x}{b:02x}"


class StockCell(QFrame):
    def __init__(self, stock, mini=False, parent=None):
        super().__init__(parent)
        self.stock = stock
        self.mini = mini
        self.setObjectName("StockCell")
        self.setMouseTracking(True)
        self.tooltip_timer = QTimer(self)
        self.tooltip_timer.setSingleShot(True)
        self.tooltip_timer.timeout.connect(self.show_custom_tooltip)
        self.setup_ui()
        
    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0)
        self.layout.setSpacing(0)
        self.layout.setAlignment(Qt.AlignCenter)
        
        # [FIX] 미니 모드에서도 ticker_label 생성 (디버그용 표시 위해)
        self.ticker_label = QLabel(self.stock["ticker"])
        self.ticker_label.setAlignment(Qt.AlignCenter)
        self.change_label = QLabel("0.00%")
        self.change_label.setAlignment(Qt.AlignCenter)
        
        if not self.mini:
            self.layout.addWidget(self.ticker_label)
            self.layout.addWidget(self.change_label)
            self.add_shadow(self.ticker_label)
            self.add_shadow(self.change_label)
        else:
            # 미니 모드: 레이아웃에 추가하지 않고 수동 위치 지정
            self.ticker_label.setParent(self)
            self.change_label.setParent(self)
            self.ticker_label.hide()
            self.change_label.hide()
            
        self.update_content() 

    def add_shadow(self, label):
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(2); shadow.setColor(QColor(0,0,0,120)); shadow.setOffset(1,1)
        label.setGraphicsEffect(shadow)

    def update_color(self):
        self.current_color = get_color(self.stock.get("change", 0))
        # [RESTORE] 미니 위젯에서도 기업 간 구분을 위해 1px 테두리 유지
        border_style = "1px solid rgba(0,0,0,0.25)"
        if self.mini: border_style = "1px solid rgba(10, 10, 15, 0.8)"
        
        hover_style = ""
        if not self.mini: 
            hover_style = f"QFrame#StockCell:hover {{ border: 1.5px solid white; }}"
            
        self.setStyleSheet(f"QFrame#StockCell {{ background-color: {self.current_color}; border: {border_style}; border-radius: {1 if self.mini else 2}px; }} {hover_style}")
        
    def update_tooltip(self):
        # 표준 툴팁은 끄고 커스텀 로직 사용
        pass

    def enterEvent(self, event):
        if not self.mini:
            self.tooltip_timer.start(300) # 0.3초 딜레이

    def leaveEvent(self, event):
        self.tooltip_timer.stop()
        QToolTip.hideText()

    def show_custom_tooltip(self):
        change = self.stock.get("change", 0)
        text = f"<b>{self.stock['name']}</b> ({self.stock['ticker']})<br>Change: <span style='color:{'#4caf50' if change >= 0 else '#ef5350'};'>{change:+.2f}%</span>"
        QToolTip.showText(QCursor.pos(), text, self)

    def update_content(self):
        self.update_color()
        if not self.mini:
            change = self.stock.get("change", 0)
            txt = f"{change:+.2f}%" if change != 0 else "-"
            self.change_label.setText(txt)
            self.update_tooltip()
            self.resizeEvent(None)

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        
        if self.mini:
            # [MINI-TICKER] 미니 위젯에서 큰 셀에 티커 표시 (직관성 향상)
            if w >= 12 and h >= 8:
                self.ticker_label.setText(self.stock['ticker'])
                # Qt는 CSS text-shadow를 지원하지 않음 - 제거
                self.ticker_label.setStyleSheet("color: white; font-size: 6px; font-weight: bold; background: transparent; border: none;")
                self.ticker_label.setGeometry(1, 0, w-2, h)
                self.ticker_label.show()
            else:
                self.ticker_label.hide()
            self.change_label.hide()
            return
            
        w, h = self.width(), self.height()
        if w <= 8 or h <= 8: self.ticker_label.hide(); self.change_label.hide(); return
        
        # 폰트 크기 가변화 - 최대 크기 추가 30% 증가 (28 → 36)
        area = w * h
        base_size = math.sqrt(area) / 4.7
        font_size = max(2, min(base_size, 36)) 
        
        # [REFINED] 글자가 너무 작으면 깔끔하게 숨김
        if font_size < 2.8:
            self.ticker_label.hide()
            self.change_label.hide()
        else:
            self.ticker_label.show()
            self.ticker_label.setStyleSheet(f"color: white; font-weight: 800; font-size: {int(font_size)}px; background: transparent; border: none;")
            
            # 세로 공간이 충분하고 가로도 어느 정도 확보될 때만 등락률 표시
            if h > font_size * 2.3 and w > font_size * 2.0:
                self.change_label.show()
                # 등락률 폰트도 30% 증가 (0.75 → 0.8 비율)
                self.change_label.setStyleSheet(f"color: rgba(255,255,255,0.85); font-weight: 500; font-size: {max(2, int(font_size*0.8))}px; background: transparent; border: none;")

            else:
                self.change_label.hide()


class SectorContainer(QFrame):
    def __init__(self, sector_name, stocks, is_mini=False, parent=None):
        super().__init__(parent)
        self.sector_name = sector_name
        self.stocks = stocks
        self.is_mini = is_mini
        self.cells = []
        self.setup_ui()
        
    def setup_ui(self):
        # 섹터 베젤 (미니 위젯에서도 1px 테두리로 경계선 표시)
        if self.is_mini:
            # [MINI-BORDER] 미니 위젯에서 섹터 구분을 위한 검은 테두리
            self.setStyleSheet("QFrame { background: transparent; border: 1px solid rgba(0, 0, 0, 0.8); }")
        else:
            border = "1px solid rgba(255, 255, 255, 0.12);"
            bg = "rgba(255,255,255,0.01);"
            self.setStyleSheet(f"QFrame {{ background: {bg}; border: {border}; border-radius: 1px; }}")
        
        if not self.is_mini:
            # 헤더 높이 축소 및 디자인 정제
            self.header_bg = QFrame(self)
            self.header_bg.setStyleSheet("background: rgba(255,255,255,0.03); border: none; border-bottom: 1px solid rgba(255,255,255,0.03);")
            
            # [LAYERED HEADER] 제목이 위로 오도록 레이아웃 대신 절대 좌표 활용 준비
            self.header = QLabel(self.sector_name.upper(), self.header_bg)
            self.header.setStyleSheet("color: rgba(255, 255, 255, 0.8); font-size: 9px; font-weight: 800; letter-spacing: 0.4px; background: transparent; border: none;")
            self.header.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.header.raise_() # 제목을 최상단으로
            
            self.sector_perf = QLabel("", self.header_bg)
            # 등락률 글자를 더 투명하게 하여 겹쳐도 제목이 보이도록 처리
            self.sector_perf.setStyleSheet("font-size: 9px; font-weight: 700; background: transparent; border: none;")
            self.sector_perf.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sector_perf.lower() # 등락률을 뒤로 보냄
            
            self.header_bg.show()
            self.update_performance()
        else: 
            self.header = None
            self.header_bg = None
            
        # [CRITICAL FIX] 셀 생성 루프를 setup_ui로 복구 (update_performance에서 제외)
        for stock in self.stocks:
            cell = StockCell(stock, mini=self.is_mini, parent=self)
            self.cells.append(cell)
            cell.show()

    def update_performance(self):
        if self.is_mini or not hasattr(self, 'sector_perf'): return
        valid_stocks = [s for s in self.stocks if s.get("weight", 0) > 0]
        if not valid_stocks: return
        total_w = sum(s["weight"] for s in valid_stocks)
        avg_change = sum(s.get("change", 0) * s["weight"] for s in valid_stocks) / total_w
        # [가시성 개선] 등락률 투명도 0.55 → 0.85로 증가
        color_rgb = "76, 175, 80" if avg_change >= 0 else "239, 83, 80"
        self.sector_perf.setText(f"{avg_change:+.2f}%")
        self.sector_perf.setStyleSheet(f"color: rgba({color_rgb}, 0.85); font-size: 9px; font-weight: 700; background: transparent; border: none;")

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 4 or h <= 4: return # 안전 처리
        
        top_margin = 0
        header_h = 16
        
        if not self.is_mini and self.header_bg:
            self.header_bg.setGeometry(0, 0, w, header_h)
            self.header.setGeometry(6, 0, w-12, header_h)
            self.sector_perf.setGeometry(6, 0, w-12, header_h)
            
            if h < 35 or w < 60: self.header_bg.hide()
            else: self.header_bg.show()
            top_margin = header_h if h > 45 else 0
        
        margin = 1 if not self.is_mini else 0
        treemap_w = w - 2*margin
        treemap_h = h - margin - top_margin
        if treemap_w <= 0 or treemap_h <= 0: return
        
        layout_data = self.stocks
        
        # [LAYOUT-SYNC] 확장 위젯에서 레이아웃을 계산하고 캐시
        if not self.is_mini:
            rects = calculate_treemap(layout_data, margin, top_margin, treemap_w, treemap_h, value_key='weight')
            
            # 정규화된 좌표(0-1 비율)로 캐시
            if self.sector_name not in TreemapWidget._cached_stock_layouts:
                TreemapWidget._cached_stock_layouts[self.sector_name] = {}
            
            for rect in rects:
                ticker = rect['data']['ticker']
                TreemapWidget._cached_stock_layouts[self.sector_name][ticker] = {
                    'x': (rect['x'] - margin) / treemap_w if treemap_w > 0 else 0,
                    'y': (rect['y'] - top_margin) / treemap_h if treemap_h > 0 else 0,
                    'w': rect['w'] / treemap_w if treemap_w > 0 else 0,
                    'h': rect['h'] / treemap_h if treemap_h > 0 else 0,
                    'data': rect['data']
                }
        else:
            # 미니 위젯: 캐시된 레이아웃을 스케일링해서 사용
            cached = TreemapWidget._cached_stock_layouts.get(self.sector_name)
            if cached:
                rects = []
                for ticker, c in cached.items():
                    rects.append({
                        'x': c['x'] * treemap_w + margin,
                        'y': c['y'] * treemap_h + top_margin,
                        'w': c['w'] * treemap_w,
                        'h': c['h'] * treemap_h,
                        'data': c['data']
                    })
            else:
                # 캐시가 없으면 직접 계산 (펴백)
                rects = calculate_treemap(layout_data, margin, top_margin, treemap_w, treemap_h, value_key='weight')
        
        boundary_x = margin + treemap_w
        boundary_y = top_margin + treemap_h
        
        for rect in rects:
            stock_data = rect['data']
            target_cell = next((c for c in self.cells if c.stock['ticker'] == stock_data['ticker']), None)
            if target_cell:
                # [SMART-ROUNDING] w = round(x+w) - round(x)
                ix, iy = round(rect['x']), round(rect['y'])
                iw = round(rect['x'] + rect['w']) - ix
                ih = round(rect['y'] + rect['h']) - iy
                
                # [OVERLAP-FILL] 미니 위젯: 1px 오버랩으로 공백 방지
                if self.is_mini:
                    iw += 1
                    ih += 1

                # [HARD-SNAP] 경계 밀착
                if ix + iw >= boundary_x - 1: iw = max(iw, boundary_x - ix)
                if iy + ih >= boundary_y - 1: ih = max(ih, boundary_y - iy)
                
                # [DOT-GUARD] 최소 2px 보장
                iw, ih = max(iw, 2), max(ih, 2)
                
                target_cell.setGeometry(ix, iy, iw, ih)

    def update_cells(self):
        for cell in self.cells: cell.update_content()
        self.update_performance()


class TreemapWidget(QFrame):
    # [LAYOUT-CACHE] 확장 위젯의 레이아웃을 캐시하여 미니 위젯에서 재사용
    _cached_sector_layout = None  # {sector_name: {'x': 0-1, 'y': 0-1, 'w': 0-1, 'h': 0-1}}
    _cached_stock_layouts = {}    # {sector_name: {ticker: {'x': 0-1, 'y': 0-1, 'w': 0-1, 'h': 0-1}}}
    
    def __init__(self, stocks, is_mini=False, parent=None):
        super().__init__(parent)
        self.stocks = stocks
        self.is_mini = is_mini
        self.sector_containers = []
        self.setup_base()
        
    def setup_base(self):
        sectors = {}
        for stock in self.stocks:
            s = stock.get("sector", "Unknown")
            if s not in sectors: sectors[s] = []
            sectors[s].append(stock)
        sector_data = []
        for name, s_stocks in sectors.items():
            total_w = sum(s.get("weight", 0) for s in s_stocks)
            sector_data.append({'sector': name, 'weight': total_w, 'stocks': s_stocks})
        # [DETERMINISTIC] 섹터 데이터를 가중치 내림차순으로 미리 정렬하여 일관된 순서 보장
        sector_data.sort(key=lambda x: (x['weight'], x['sector']), reverse=True)
        self.sector_data = sector_data
        
        # [LAYOUT-INIT] is_mini여도 캐시가 없으면 확장 위젯 크기로 레이아웃 미리 계산
        if TreemapWidget._cached_sector_layout is None:
            self._init_layout_cache()
        
        for s_data in sector_data:
            container = SectorContainer(s_data['sector'], s_data['stocks'], is_mini=self.is_mini, parent=self)
            self.sector_containers.append(container)
            container.show()
    
    def _init_layout_cache(self):
        """[캐시 초기화] 확장 위젯 크기(1200x800)로 레이아웃을 계산하여 캐시 생성"""
        w, h = 1200, 800
        rects = calculate_treemap(self.sector_data, 0, 0, w, h, value_key='weight')
        
        TreemapWidget._cached_sector_layout = {}
        for rect in rects:
            sector_name = rect['data']['sector']
            TreemapWidget._cached_sector_layout[sector_name] = {
                'x': rect['x'] / w,
                'y': rect['y'] / h,
                'w': rect['w'] / w,
                'h': rect['h'] / h,
                'data': rect['data']
            }
            
            # 종목 레이아웃도 미리 계산
            s_stocks = rect['data']['stocks']
            s_w, s_h = rect['w'], rect['h']
            if s_w > 0 and s_h > 0:
                stock_rects = calculate_treemap(s_stocks, 0, 0, s_w, s_h, value_key='weight')
                TreemapWidget._cached_stock_layouts[sector_name] = {}
                for sr in stock_rects:
                    ticker = sr['data']['ticker']
                    TreemapWidget._cached_stock_layouts[sector_name][ticker] = {
                        'x': sr['x'] / s_w,
                        'y': sr['y'] / s_h,
                        'w': sr['w'] / s_w,
                        'h': sr['h'] / s_h,
                        'data': sr['data']
                    }
            
    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0: return
        
        # [LAYOUT-SYNC] 확장 위젯(is_mini=False)에서 레이아웃을 계산하고 캐시
        if not self.is_mini:
            rects = calculate_treemap(self.sector_data, 0, 0, w, h, value_key='weight')
            
            # 정규화된 좌표(0-1 비율)로 캐시
            TreemapWidget._cached_sector_layout = {}
            for rect in rects:
                sector_name = rect['data']['sector']
                TreemapWidget._cached_sector_layout[sector_name] = {
                    'x': rect['x'] / w,
                    'y': rect['y'] / h,
                    'w': rect['w'] / w,
                    'h': rect['h'] / h,
                    'data': rect['data']
                }
        else:
            # 미니 위젯: 캐시된 레이아웃을 스케일링해서 사용
            if TreemapWidget._cached_sector_layout:
                rects = []
                for sector_name, cached in TreemapWidget._cached_sector_layout.items():
                    rects.append({
                        'x': cached['x'] * w,
                        'y': cached['y'] * h,
                        'w': cached['w'] * w,
                        'h': cached['h'] * h,
                        'data': cached['data']
                    })
            else:
                # 캐시가 없으면 직접 계산 (펴백)
                rects = calculate_treemap(self.sector_data, 0, 0, w, h, value_key='weight')

        for rect in rects:
            s_data = rect['data']
            container = next((c for c in self.sector_containers if c.sector_name == s_data['sector']), None)
            if container:
                # [SMART-ROUNDING]
                ix, iy = round(rect['x']), round(rect['y'])
                iw = round(rect['x'] + rect['w']) - ix
                ih = round(rect['y'] + rect['h']) - iy
                
                # [HARD-SNAP] 전체 위젯 경계 밀착
                if ix + iw >= w - 1: iw = max(iw, w - ix)
                if iy + ih >= h - 1: ih = max(ih, h - iy)
                    
                container.setGeometry(ix, iy, iw, ih)

    def update_all_cells(self):
        for container in self.sector_containers: container.update_cells()

    def clear_containers(self):
        for c in self.sector_containers:
            for cell in c.cells: cell.setParent(None); cell.deleteLater()
            c.setParent(None); c.deleteLater()
        self.sector_containers = []

    def refresh_data(self, stocks):
        self.stocks = stocks
        self.clear_containers()
        self.setup_base()
        self.resizeEvent(None)


class ExpandedWidget(QWidget):
    closed = pyqtSignal(); position_changed = pyqtSignal(int, int)
    def __init__(self, stocks, parent=None):
        super().__init__(parent)
        self.stocks = stocks
        self.dragging = False; self.drag_position = QPoint()
        self.setup_ui()
        
    def setup_ui(self):
        self.setFixedSize(1200, 850)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        # 회색 모서리 잔상 제거를 위해 TranslucentBackground 복구
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 윈도우 아이콘 설정
        icon_path = Path(__file__).parent / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        
        self.main_frame = QFrame(self)
        self.main_frame.setStyleSheet("QFrame#main { background-color: rgba(15, 15, 20, 0.98); border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); }")
        self.main_frame.setObjectName("main")
        self.main_frame.setGeometry(0, 0, 1200, 850)
        
        # [FIX] UpdateLayeredWindowIndirect failed 에러 해결을 위해 그림자 제거
        # 투명 윈도우(TranslucentBackground) 위에서의 그림자 효과는 Windows API 호출 에러를 유발할 수 있음
        # shadow = QGraphicsDropShadowEffect(self); shadow.setBlurRadius(20); shadow.setOffset(0, 5); shadow.setColor(QColor(0,0,0,180))
        # self.main_frame.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.main_frame)
        # 외부 베젤을 1/10 수준(1~2px)으로 최소화
        layout.setContentsMargins(1, 1, 1, 1); layout.setSpacing(2)

        # --- Header ---
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        
        # 중앙 정렬을 위한 왼쪽 더미 스페이서 (오른쪽 닫기 버튼 폭 고려)
        header.addSpacing(32) 
        header.addStretch()
        
        # 타이틀 및 수익률 컨테이너
        title_container = QHBoxLayout()
        self.title_label = QLabel("S&P 500")
        self.title_label.setStyleSheet("color: white; font-size: 24px; font-weight: 800; border: none;")
        self.change_label = QLabel("")
        self.change_label.setStyleSheet("color: #aaa; font-size: 16px; border: none; margin-left: 10px;")
        title_container.addWidget(self.title_label)
        title_container.addWidget(self.change_label)
        header.addLayout(title_container)
        
        header.addStretch()
        
        # [갱신 시간] 마지막 업데이트 시간 표시
        self.update_time_label = QLabel("")
        self.update_time_label.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px; border: none;")
        header.addWidget(self.update_time_label)
        
        header.addSpacing(10)
        
        # [About 버튼] 정보 창 열기
        about_btn = QPushButton("ⓘ")
        about_btn.setFixedSize(24, 24)
        about_btn.setStyleSheet("""
            QPushButton { 
                background: transparent; 
                border: none; 
                color: rgba(255,255,255,0.4); 
                font-size: 14px; 
            } 
            QPushButton:hover { 
                color: white; 
            }
        """)
        about_btn.clicked.connect(self.show_about)
        header.addWidget(about_btn)
        
        header.addSpacing(5)
        
        # [닫기 버튼] 테두리 없이 깔끔한 X
        close_btn = QPushButton("X")
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet("""
            QPushButton { 
                background: transparent; 
                border: none; 
                color: rgba(255,255,255,0.5); 
                font-size: 20px; 
                font-weight: 400;
            } 
            QPushButton:hover { 
                color: #ef5350; 
            }
        """)
        close_btn.clicked.connect(self.close_widget)
        header.addWidget(close_btn)

        layout.addLayout(header)
        
        # --- Heatmap ---
        self.treemap = TreemapWidget(self.stocks, is_mini=False)
        layout.addWidget(self.treemap)

    def contextMenuEvent(self, event):
        pass

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.pos().y() < 40: self.dragging = True; self.drag_position = e.globalPos() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self.dragging: self.move(e.globalPos() - self.drag_position)
    def mouseReleaseEvent(self, e):
        self.dragging = False; self.position_changed.emit(self.pos().x(), self.pos().y())
    def close_widget(self):
        self.position_changed.emit(self.pos().x(), self.pos().y()); self.closed.emit(); self.hide()
    def showEvent(self, event):
        super().showEvent(event)
        self.update_view()

    def update_view(self): 
        try:
            self.treemap.update_all_cells()
            
            # [FIX] 모든 종목의 변화율 평균 계산 (0.00%도 표시되도록)
            changes = [s.get("change", 0) for s in self.stocks]
            avg_change = sum(changes) / len(changes) if changes else 0
            
            # [STYLE-FIX] 등락율: 더 굵고 선명하게
            c_color = "#4caf50" if avg_change >= 0 else "#ef5350"  # 더 선명한 초록/빨강
            self.change_label.setText(f"{avg_change:+.2f}%")
            self.change_label.setStyleSheet(f"color: {c_color}; font-size: 20px; border: none; margin-left: 12px; font-weight: 800;")
            
            # [갱신 시간] 마지막 업데이트 시간 표시
            from datetime import datetime
            self.update_time_label.setText(f"Last: {datetime.now().strftime('%H:%M')}")

        except Exception: pass
    
    def show_about(self):
        """About 다이얼로그 표시 - 프레임리스 현대적 디자인"""
        import webbrowser
        
        dialog = QDialog(self)
        dialog.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        dialog.setAttribute(Qt.WA_TranslucentBackground)
        dialog.setFixedSize(380, 260)
        
        # 메인 컨테이너 (둥근 모서리, 그라데이션 배경)
        container = QFrame(dialog)
        container.setGeometry(0, 0, 380, 260)
        container.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2a2a38, stop:1 #1a1a22);
                border-radius: 12px;
                border: 1px solid #3a3a45;
            }
        """)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 14, 20, 18)
        layout.setSpacing(0)
        
        # 헤더: 타이틀 + 버전 (중앙) + 닫기 버튼 (오른쪽 끝)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        
        # 왼쪽 더미 (닫기 버튼 너비만큼)
        header.addSpacing(28)
        header.addStretch()
        
        title = QLabel("Nireum Heatmap")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: white; border: none; background: transparent;")

        header.addWidget(title)
        
        version = QLabel("v0.3.1")
        version.setStyleSheet("font-size: 11px; color: #555; border: none; background: transparent; margin-left: 6px; margin-top: 3px;")
        header.addWidget(version)
        
        header.addStretch()
        
        close_btn = QPushButton("×")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton { 
                background: transparent; 
                border: none; 
                color: #888; 
                font-size: 22px;
                font-weight: 400;
                padding-bottom: 2px;
            }
            QPushButton:hover { color: #ef5350; }
        """)
        close_btn.clicked.connect(dialog.close)
        header.addWidget(close_btn)
        
        layout.addLayout(header)
        layout.addSpacing(16)
        
        # 설명 영역 (영어, 폰트 키움, 정중앙)
        desc = QLabel(
            "This widget is designed to provide\nan intuitive overview of market trends,\nnot for trading purposes.\n\n"
            "Data may be delayed by 15-20 minutes\nand should not be used as investment advice."
        )
        desc.setStyleSheet("font-size: 13px; color: #777; border: none; background: transparent;")
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        layout.addStretch()
        
        # GitHub 버튼
        github_btn = QPushButton("GitHub")
        github_btn.setStyleSheet("""
            QPushButton { 
                background: #2d5a27; 
                color: white; 
                border: none; 
                border-radius: 6px; 
                padding: 10px 20px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover { background: #3d7a37; }
        """)
        github_btn.clicked.connect(lambda: webbrowser.open("https://github.com/Menglda/Nireum-heatmap"))

        layout.addWidget(github_btn)
        

        # 드래그 기능
        dialog._drag_pos = None
        def mousePressEvent(e):
            if e.button() == Qt.LeftButton:
                dialog._drag_pos = e.globalPos() - dialog.frameGeometry().topLeft()
        def mouseMoveEvent(e):
            if dialog._drag_pos:
                dialog.move(e.globalPos() - dialog._drag_pos)
        def mouseReleaseEvent(e):
            dialog._drag_pos = None
        dialog.mousePressEvent = mousePressEvent
        dialog.mouseMoveEvent = mouseMoveEvent
        dialog.mouseReleaseEvent = mouseReleaseEvent
        
        dialog.exec_()



class MiniWidget(QWidget):
    clicked = pyqtSignal(); position_changed = pyqtSignal(int, int)
    def __init__(self, stocks, parent=None):
        super().__init__(parent)
        self.stocks = stocks
        self.dragging = False; self.drag_position = QPoint(); self.click_pos = None
        self.setup_ui()
        
    def setup_ui(self):
        W, H = 140, 90; BTN_SIZE = 16
        self.setFixedSize(W + 10, H + 10)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)  # 위젯 전체에 검지손가락 커서


        self.main_frame = QFrame(self)
        self.main_frame.setStyleSheet("background-color: rgba(20, 20, 28, 0.95); border-radius: 4px; border: 1px solid rgba(255, 255, 255, 0.15);")
        # [BEZEL-FIX] 베젤이 왼쪽/위만 보이던 문제 해결: main_frame을 전체 범위에서 2px 안쪽으로 배치
        self.main_frame.setGeometry(2, 2, W - 4, H - 4)
        layout = QVBoxLayout(self.main_frame); layout.setContentsMargins(1, 1, 1, 1)
        self.treemap = TreemapWidget(self.stocks, is_mini=True)
        layout.addWidget(self.treemap)
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
        self.close_btn.setStyleSheet("""QPushButton { background: #111; color: #ddd; border-radius: 0px; font-size: 10px; border: 1px solid #555; } QPushButton:hover { background: #b71c1c; border-color: #b71c1c; }""")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        # [닫기 버튼 위치] 오른쪽 끝에 정확히 배치 (W+10 = 전체 폭, BTN_SIZE=16, 여백 2px)
        self.close_btn.move(W + 10 - BTN_SIZE - 2, 0)
        self.close_btn.clicked.connect(self.app_quit)
        shadow = QGraphicsDropShadowEffect(self.main_frame); shadow.setBlurRadius(8); shadow.setColor(QColor(0,0,0,120))
        self.main_frame.setGraphicsEffect(shadow)
        
    def app_quit(self): QApplication.instance().quit() 
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.dragging = True; self.drag_position = e.globalPos() - self.frameGeometry().topLeft(); self.click_pos = e.globalPos()
    def mouseMoveEvent(self, e):
        if self.dragging: self.move(e.globalPos() - self.drag_position)
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = False
            if self.click_pos and (e.globalPos() - self.click_pos).manhattanLength() < 5:
                if not self.close_btn.geometry().contains(e.pos()): self.clicked.emit()
            self.position_changed.emit(self.pos().x(), self.pos().y())
    def update_view(self):
        self.treemap.update_all_cells()
        self.treemap.resizeEvent(None)


class DataFetcher(QThread):
    data_updated = pyqtSignal(list)
    def __init__(self, stocks): super().__init__(); self.stocks = stocks
    
    def run(self):
        batch_size = 50
        all_tickers = [s['ticker'] for s in self.stocks]
        
        try:
            print(f"[INFO] 데이터 페치 시작... ({len(all_tickers)}개 종목)")
            full_df = pd.DataFrame()
            failed_tickers = []  # 실패한 종목 추적
            
            for i in range(0, len(all_tickers), batch_size):
                batch = all_tickers[i:i+batch_size]
                if not batch: continue
                if i > 0: time.sleep(2.0) # Safety Delay
                try:
                    df = yf.download(batch, period="2d", group_by='ticker', progress=False, threads=True)
                    if not df.empty:
                        if full_df.empty: full_df = df
                        else: full_df = pd.concat([full_df, df], axis=1)
                except: continue
                    
            if not full_df.empty:
                for stock in self.stocks:
                    try:
                        t = stock['ticker']
                        if isinstance(full_df.columns, pd.MultiIndex):
                            if t in full_df.columns.levels[0]: 
                                data = full_df[t].ffill().dropna(subset=['Close'])
                            else: continue
                        else:
                            data = full_df.ffill().dropna(subset=['Close']) if len(all_tickers) == 1 else pd.DataFrame()

                        if not data.empty and len(data) >= 1:
                            last_row = data.iloc[-1]
                            price = last_row['Close']
                            
                            # nan 체크 강화
                            if pd.isna(price) and len(data) >= 2:
                                price = data.iloc[-2]['Close']
                                
                            prev_close = 0
                            if len(data) >= 2: prev_close = data.iloc[-2]['Close']
                            
                            # prev_close nan 체크 및 Open가 보완
                            if (pd.isna(prev_close) or prev_close <= 0) and 'Open' in last_row:
                                prev_close = last_row['Open']
                            
                            if pd.notna(price) and pd.notna(prev_close) and prev_close > 0:
                                change = ((price - prev_close) / prev_close) * 100
                                stock['change'] = round(change, 2)
                                # [DEBUG] Major stocks debug log
                                if t in ['AAPL', 'MSFT', 'FICO', 'KMI']:
                                    print(f"[CALC] {t}: price={price:.2f}, prev={prev_close:.2f}, change={change:.2f}%")
                            # [CACHE] New data failed, keep old value
                    except Exception as ex:
                        # [DEBUG] Exception log
                        print(f"[WARN] {t} processing error: {ex}")

                    
            # [SUCCESS/FAIL STATS]
            success_count = sum(1 for s in self.stocks if s.get('change', 0) != 0)
            failed_list = [s['ticker'] for s in self.stocks if s.get('change', 0) == 0]
            print(f"[INFO] Fetch complete: {success_count}/{len(self.stocks)} success")
            
            # [RETRY] Retry failed tickers individually
            if failed_list:
                print(f"[RETRY] Retrying {len(failed_list)} failed tickers: {failed_list}")
                time.sleep(1.0)
                for ticker in failed_list:
                    try:
                        df = yf.download(ticker, period="2d", progress=False)
                        if not df.empty:
                            # Fix: dropna without subset, check Close column exists
                            if 'Close' in df.columns:
                                df = df.ffill().dropna()
                            if len(df) >= 1:
                                price = df.iloc[-1]['Close'] if 'Close' in df.columns else None
                                prev_close = df.iloc[-2]['Close'] if len(df) >= 2 and 'Close' in df.columns else None
                                if prev_close is None and 'Open' in df.columns:
                                    prev_close = df.iloc[-1]['Open']

                                if pd.notna(price) and pd.notna(prev_close) and prev_close > 0:
                                    change = ((price - prev_close) / prev_close) * 100
                                    # Find and update the stock
                                    for s in self.stocks:
                                        if s['ticker'] == ticker:
                                            s['change'] = round(change, 2)
                                            print(f"[RETRY] {ticker}: success, change={change:.2f}%")
                                            break
                    except Exception as ex:
                        print(f"[RETRY] {ticker}: failed - {ex}")
            
            # Final stats
            final_success = sum(1 for s in self.stocks if s.get('change', 0) != 0)
            final_failed = [s['ticker'] for s in self.stocks if s.get('change', 0) == 0]
            print(f"[INFO] Final: {final_success}/{len(self.stocks)} success")
            if final_failed:
                print(f"[WARN] Still failed: {final_failed}")
            
            self.data_updated.emit(self.stocks)
        except Exception as e: 
            print(f"[ERROR] Fetch failed: {e}")
            self.data_updated.emit(self.stocks)



class StockHeatmapApp:
    # [CACHE] Class-level cache to store successful change values
    _change_cache = {}  # {ticker: change_value}
    
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setFont(QFont("Segoe UI", 10))
        # 앱 전체 아이콘 설정 (작업표시줄 아이콘)
        icon_path = Path(__file__).parent / "icon.ico"
        if icon_path.exists():
            self.app.setWindowIcon(QIcon(str(icon_path)))

        
        self.config = self.load_config()
        self.stocks = self.config.get("tickers")
        if not self.stocks:
            self.stocks = [s.copy() for s in DEFAULT_STOCKS]
        
        self.first_run = True # Flag for first run

        
        # 데이터 수신 전 초기 상태 보장 (모두 0으로 설정하여 검회색 유지)
        for s in self.stocks: 
            s['change'] = 0
        
        self.mini = MiniWidget(self.stocks)
        pos = self.config.get("mini_position")
        if pos: self.mini.move(pos["x"], pos["y"])
        else: self.mini.move(self.app.primaryScreen().availableGeometry().width() - 170, 100)
        
        self.mini.clicked.connect(self.toggle_expanded)
        self.mini.position_changed.connect(self.save_pos_mini)
        
        self.expanded = None
        self.fetcher = None
        self.timer = QTimer(); self.timer.timeout.connect(self.update_data)
        
        self.timer.start(120000) # 2분마다 업데이트 (120,000ms)

        QTimer.singleShot(100, self.update_data) # Start immediately
        self.mini.show()
        
    def update_data(self):
        # Prevent Thread overlap
        if self.fetcher and self.fetcher.isRunning(): return
        
        # [TEST MODE] 임시 테스트: 랜덤 데이터로 갱신 확인 (개발 완료 후 제거)
        import random
        TEST_MODE = False  # True로 변경하면 테스트용 랜덤 데이터 사용

        
        if TEST_MODE:
            print("[TEST] 랜덤 데이터로 갱신")
            for s in self.stocks:
                s['change'] = round(random.uniform(-5, 5), 2)
            self.on_data_updated(self.stocks)
            return
        
        # [US MARKET HOURS] 미국 동부 시간(ET) 기준으로 정규장 체크
        try:
            eastern = ZoneInfo('America/New_York')
            now_et = datetime.now(eastern)
        except:
            # Fallback: UTC에서 5시간 빼기 (EST 근사값)
            now_et = datetime.now(timezone.utc).replace(tzinfo=None)
            now_et = now_et.replace(hour=(now_et.hour - 5) % 24)
        
        # 미국 정규장: 월~금 09:30~16:00 ET
        is_weekday = now_et.weekday() < 5  # 0=월, 4=금
        is_market_hours = is_weekday and (
            (now_et.hour == 9 and now_et.minute >= 30) or
            (10 <= now_et.hour < 16)
        )
        print(f"[INFO] update_data 호출 - 시간(ET): {now_et.strftime('%H:%M:%S')}, 장시간: {is_market_hours}, first_run: {self.first_run}")
        
        if self.first_run or is_market_hours:
            self.fetcher = DataFetcher(self.stocks)
            self.fetcher.data_updated.connect(self.on_data_updated)
            self.fetcher.start()
            self.first_run = False
        else:
            pass


    def on_data_updated(self, stocks):
        print(f"[INFO] on_data_updated - UI update start")
        
        # [CACHE] Update cache with successful values and restore failed ones
        for stock in stocks:
            ticker = stock.get('ticker', '')
            change = stock.get('change', 0)
            
            if change != 0:
                # Success: save to cache
                StockHeatmapApp._change_cache[ticker] = change
            elif ticker in StockHeatmapApp._change_cache:
                # Failed: restore from cache
                cached_value = StockHeatmapApp._change_cache[ticker]
                stock['change'] = cached_value
                print(f"[CACHE] {ticker}: restored {cached_value}% from cache")
            else:
                print(f"[CACHE] {ticker}: no cache available")
        
        self.stocks = stocks
        
        # Update cell references
        def update_cell(cell, matched):
            if matched:
                cell.stock = matched


        
        # MiniWidget와 내부 TreemapWidget 업데이트
        self.mini.stocks = stocks
        self.mini.treemap.stocks = stocks
        for container in self.mini.treemap.sector_containers:
            for cell in container.cells:
                matched = next((s for s in stocks if s['ticker'] == cell.stock['ticker']), None)
                update_cell(cell, matched)
        
        self.mini.update_view()
        
        if self.expanded and self.expanded.isVisible(): 
            self.expanded.stocks = stocks
            self.expanded.treemap.stocks = stocks
            for container in self.expanded.treemap.sector_containers:
                for cell in container.cells:
                    matched = next((s for s in stocks if s['ticker'] == cell.stock['ticker']), None)
                    update_cell(cell, matched)
            self.expanded.update_view()
        

        print(f"[INFO] UI 갱신 완료")

    def load_config(self):
        try: 
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except: return {}

    def save_config(self):
        try: 
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f)
        except: pass

    def save_pos_mini(self, x, y): self.config["mini_position"] = {"x": x, "y": y}; self.save_config()
    def save_pos_exp(self, x, y): self.config["expanded_position"] = {"x": x, "y": y}; self.save_config()
    def run(self): return self.app.exec_()

    def toggle_expanded(self):
        if self.expanded and self.expanded.isVisible():
            self.expanded.hide()
        else:
            if not self.expanded:
                self.expanded = ExpandedWidget(self.stocks)
                self.expanded.closed.connect(lambda: None)
                self.expanded.position_changed.connect(self.save_pos_exp)
                pos = self.config.get("expanded_position")
                if pos: self.expanded.move(pos["x"], pos["y"])
                else: self.expanded.move(100, 100)
            self.expanded.show()
            self.expanded.raise_()
            # [FIX] 창 표시 시점에 최신 데이터와 등락률을 확실하게 반영
            self.expanded.stocks = self.stocks 
            self.expanded.update_view()

if __name__ == "__main__":
    try: app = StockHeatmapApp(); sys.exit(app.run())
    except: pass
