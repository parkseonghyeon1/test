"""EclipseSkip - 이클립스: 더 어웨이크닝 Skip 자동 넘김 (GUI)."""
import base64
import datetime
import os
import subprocess
import sys
import tkinter as tk
from dataclasses import replace
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import cv2

import engine as eng

try:
    from version import VERSION
except ImportError:
    VERSION = "dev"

# ---- 색상 (게임 UI 느낌의 어두운 테마 + 금색 포인트) ----
BG = "#141519"
PANEL = "#1c1e24"
PANEL_2 = "#23262e"
BORDER = "#2e323c"
TEXT = "#e9e6df"
MUTED = "#8f939e"
GOLD = "#d6a84e"
GOLD_DARK = "#a67f33"
GREEN = "#4fbf83"
RED = "#e2615a"
BLUE = "#5aa4e2"

PREVIEW_W, PREVIEW_H = 496, 279


def pick_font():
    fams = set(tkfont.families())
    for f in ("Malgun Gothic", "맑은 고딕", "NanumGothic", "Noto Sans CJK KR", "Segoe UI"):
        if f in fams:
            return f
    return "TkDefaultFont"


def to_photo(bgr, max_w, max_h):
    """OpenCV BGR 이미지를 Tk PhotoImage 로 (비율 유지 축소). (photo, scale) 반환."""
    h, w = bgr.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    if scale < 1.0:
        bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", bgr)
    return tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii")), scale


class App:
    def __init__(self, root, w32, selftest_out=None):
        self.root, self.w32 = root, w32
        self.settings = eng.Settings.load()
        self.hidden_pos = None  # 게임 창 숨기기 전 위치
        self.preview_img = None
        self.last_frame = None
        self.window_info = None
        self.selftest_out = selftest_out

        self.F = pick_font()
        self._style()
        self._build()
        self.apply_topmost()

        self.engine = eng.SkipEngine(w32, self.settings)
        self.engine.start()
        self.log(f"EclipseSkip {VERSION} 시작 - 관리자 권한: {'예' if w32.is_admin() else '아니오'}")
        if not w32.is_admin():
            self.show_banner("관리자 권한이 아닙니다. 게임이 관리자 권한으로 실행 중이면 캡처/입력이 막힐 수 있어요.",
                             "관리자 권한으로 다시 실행", self.relaunch_admin)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll)
        if selftest_out:
            self.root.after(3000, self.finish_selftest)

    # ------------------------------------------------------------ 스타일
    def _style(self):
        r = self.root
        r.title("EclipseSkip - 이클립스 Skip 자동 넘김")
        r.configure(bg=BG)
        r.geometry("960x720")
        r.minsize(900, 680)
        st = ttk.Style(r)
        st.theme_use("clam")
        F = self.F
        st.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL_2,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, font=(F, 10))
        st.configure("TFrame", background=BG)
        st.configure("Panel.TFrame", background=PANEL)
        st.configure("TLabel", background=BG, foreground=TEXT)
        st.configure("Panel.TLabel", background=PANEL)
        st.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=(F, 9))
        st.configure("Value.TLabel", background=PANEL, foreground=TEXT, font=(F, 10, "bold"))
        st.configure("Big.TLabel", background=PANEL, foreground=GOLD, font=(F, 26, "bold"))
        st.configure("Title.TLabel", font=(F, 17, "bold"), foreground=TEXT)
        st.configure("Sub.TLabel", foreground=MUTED, font=(F, 10))
        st.configure("TButton", background=PANEL_2, foreground=TEXT, padding=(12, 6), borderwidth=1,
                     focusthickness=0)
        st.map("TButton", background=[("active", BORDER), ("disabled", PANEL)],
               foreground=[("disabled", MUTED)])
        st.configure("Gold.TButton", background=GOLD, foreground="#1a1406", font=(F, 11, "bold"),
                     padding=(22, 9), bordercolor=GOLD_DARK)
        st.map("Gold.TButton", background=[("active", "#e3ba66")])
        st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0),
                     bordercolor=BG, lightcolor=BG, darkcolor=BG)
        st.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(18, 7), borderwidth=0,
                     font=(F, 10), bordercolor=BG, lightcolor=BG, darkcolor=BG)
        st.map("TNotebook.Tab", background=[("selected", PANEL), ("active", PANEL_2)],
               foreground=[("selected", GOLD)], lightcolor=[("selected", PANEL)],
               bordercolor=[("selected", PANEL)])
        st.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=PANEL, bordercolor=PANEL,
                     arrowcolor=MUTED, lightcolor=PANEL_2, darkcolor=PANEL_2, gripcount=0)
        st.map("Vertical.TScrollbar", background=[("active", BORDER)])
        st.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=(F, 10))
        st.configure("TCheckbutton", indicatorbackground=PANEL_2, indicatorforeground=GOLD,
                     indicatorcolor=PANEL_2, upperbordercolor=BORDER, lowerbordercolor=BORDER)
        st.map("TCheckbutton", background=[("active", PANEL)],
               indicatorbackground=[("selected", GOLD), ("!selected", PANEL_2)],
               indicatorforeground=[("selected", "#1a1406")])
        st.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=TEXT,
                     arrowcolor=TEXT, selectbackground=PANEL_2, selectforeground=TEXT)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL_2)], foreground=[("readonly", TEXT)])
        r.option_add("*TCombobox*Listbox.background", PANEL_2)
        r.option_add("*TCombobox*Listbox.foreground", TEXT)
        r.option_add("*TCombobox*Listbox.selectBackground", GOLD_DARK)
        st.configure("TSpinbox", fieldbackground=PANEL_2, foreground=TEXT, arrowcolor=TEXT)
        st.configure("TEntry", fieldbackground=PANEL_2, foreground=TEXT, insertcolor=TEXT)
        st.configure("Horizontal.TScale", background=PANEL, troughcolor=PANEL_2)
        st.configure("Treeview", background=PANEL_2, fieldbackground=PANEL_2, foreground=TEXT,
                     rowheight=26, borderwidth=0)
        st.configure("Treeview.Heading", background=PANEL, foreground=MUTED, relief="flat")
        st.map("Treeview", background=[("selected", GOLD_DARK)])

    def card(self, parent, **pack):
        f = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        f.pack(**pack)
        return f

    # ------------------------------------------------------------ 레이아웃
    def _build(self):
        F = self.F
        outer = ttk.Frame(self.root, padding=(18, 14, 18, 10))
        outer.pack(fill="both", expand=True)

        # 헤더
        head = ttk.Frame(outer)
        head.pack(fill="x")
        left = ttk.Frame(head)
        left.pack(side="left")
        ttk.Label(left, text="EclipseSkip", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="이클립스: 더 어웨이크닝 · Skip 자동 넘김", style="Sub.TLabel").pack(anchor="w")
        self.toggle_btn = ttk.Button(head, text="일시정지", style="Gold.TButton", command=self.toggle)
        self.toggle_btn.pack(side="right")
        self.state_pill = tk.Label(head, text="● 게임 찾는 중", bg=BG, fg=MUTED, font=(F, 11, "bold"))
        self.state_pill.pack(side="right", padx=16)

        # 알림 배너 (필요할 때만 표시)
        self.banner = tk.Frame(outer, bg="#3a2a12", highlightbackground=GOLD_DARK, highlightthickness=1)
        self.banner_text = tk.Label(self.banner, bg="#3a2a12", fg="#f3d99c", font=(F, 10),
                                    anchor="w", justify="left", wraplength=640)
        self.banner_text.pack(side="left", padx=12, pady=8, fill="x", expand=True)
        self.banner_btn = ttk.Button(self.banner, text="")
        self.banner_close = tk.Label(self.banner, text="✕", bg="#3a2a12", fg="#f3d99c", cursor="hand2",
                                     font=(F, 11))
        self.banner_close.bind("<Button-1>", lambda e: self.banner.pack_forget())
        self.banner_close.pack(side="right", padx=(0, 10))
        self.banner_btn.pack(side="right", padx=8, pady=6)

        self.body = ttk.Frame(outer)
        self.body.pack(fill="both", expand=True, pady=(12, 0))
        body = self.body

        # 왼쪽: 미리보기
        lcol = ttk.Frame(body)
        lcol.pack(side="left", fill="y")
        pv = self.card(lcol, fill="x")
        top = ttk.Frame(pv, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="게임 화면 미리보기", style="Value.TLabel").pack(side="left")
        self.preview_note = ttk.Label(top, text="", style="Muted.TLabel")
        self.preview_note.pack(side="right")
        self.canvas = tk.Canvas(pv, width=PREVIEW_W, height=PREVIEW_H, bg="#0c0d10",
                                highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack()
        self.canvas_text = self.canvas.create_text(PREVIEW_W // 2, PREVIEW_H // 2, fill=MUTED,
                                                   font=(F, 11), text="게임 창을 찾는 중...")
        btns = ttk.Frame(pv, style="Panel.TFrame")
        btns.pack(fill="x", pady=(10, 0))
        self.hide_btn = ttk.Button(btns, text="게임 창 화면 밖으로 숨기기", command=self.toggle_hide)
        self.hide_btn.pack(side="left")
        ttk.Button(btns, text="Skip 템플릿 추가", command=self.add_template).pack(side="left", padx=8)

        # 오른쪽: 상태
        rcol = ttk.Frame(body)
        rcol.pack(side="left", fill="both", expand=True, padx=(12, 0))
        stats = self.card(rcol, fill="x")
        row = ttk.Frame(stats, style="Panel.TFrame")
        row.pack(fill="x")
        c1 = ttk.Frame(row, style="Panel.TFrame")
        c1.pack(side="left", expand=True, fill="x")
        ttk.Label(c1, text="스킵 횟수", style="Muted.TLabel").pack(anchor="w")
        self.count_lbl = ttk.Label(c1, text="0", style="Big.TLabel")
        self.count_lbl.pack(anchor="w")
        c2 = ttk.Frame(row, style="Panel.TFrame")
        c2.pack(side="left", expand=True, fill="x")
        ttk.Label(c2, text="마지막 스킵", style="Muted.TLabel").pack(anchor="w")
        self.last_lbl = ttk.Label(c2, text="-", style="Value.TLabel", font=(F, 15, "bold"))
        self.last_lbl.pack(anchor="w", pady=(8, 0))

        ttk.Label(stats, text="Skip 일치도", style="Muted.TLabel").pack(anchor="w", pady=(14, 4))
        self.meter = tk.Canvas(stats, height=22, bg=PANEL, highlightthickness=0)
        self.meter.pack(fill="x")
        self.meter.bind("<Configure>", lambda e: self.draw_meter(self._score))
        self._score = 0.0

        info = self.card(rcol, fill="both", expand=True, pady=(12, 0))
        self.info = {}
        for key, label in (("window", "게임 창"), ("size", "화면 크기"), ("capture", "캡처 방식"),
                           ("method", "입력 방식"), ("admin", "권한")):
            r = ttk.Frame(info, style="Panel.TFrame")
            r.pack(fill="x", pady=3)
            ttk.Label(r, text=label, style="Muted.TLabel", width=9).pack(side="left")
            v = ttk.Label(r, text="-", style="Value.TLabel")
            v.pack(side="left")
            self.info[key] = v
        self.set_info("admin", ("관리자" if self.w32.is_admin() else "일반 사용자"),
                      GREEN if self.w32.is_admin() else GOLD)
        self.set_info("method", eng.METHODS[self.settings.method])

        # 하단 탭
        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=False, pady=(12, 0))
        self.nb = nb
        self._build_log_tab(nb)
        self._build_settings_tab(nb)
        self._build_templates_tab(nb)

        foot = ttk.Frame(outer)
        foot.pack(fill="x", pady=(8, 0))
        ttk.Label(foot, text="Ctrl+F10 일시정지/재개  ·  최소화하면 감지가 멈춰요 (다른 창 뒤에 두거나 '숨기기' 사용)",
                  style="Sub.TLabel", font=(F, 9)).pack(side="left")
        ttk.Label(foot, text=VERSION, style="Sub.TLabel", font=(F, 9)).pack(side="right")

    def _build_log_tab(self, nb):
        f = ttk.Frame(nb, style="Panel.TFrame", padding=8)
        nb.add(f, text="로그")
        self.log_text = tk.Text(f, height=6, bg=PANEL, fg=TEXT, relief="flat", font=(self.F, 9),
                                insertbackground=TEXT, wrap="word", state="disabled", highlightthickness=0)
        sb = ttk.Scrollbar(f, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("time", foreground=MUTED)
        self.log_text.tag_configure("skip", foreground=GOLD)
        self.log_text.tag_configure("warn", foreground=RED)

    def _build_settings_tab(self, nb):
        s = self.settings
        f = ttk.Frame(nb, style="Panel.TFrame", padding=(16, 12))
        nb.add(f, text="설정")
        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)

        def lab(text, r, c):
            ttk.Label(f, text=text, style="Panel.TLabel").grid(row=r, column=c, sticky="w", padx=(0, 10), pady=5)

        self.v_title = tk.StringVar(value=s.title)
        self.v_method = tk.StringVar(value=eng.METHODS[s.method])
        self.v_threshold = tk.DoubleVar(value=s.threshold)
        self.v_interval = tk.DoubleVar(value=s.interval)
        self.v_cooldown = tk.DoubleVar(value=s.cooldown)
        self.v_fg = tk.BooleanVar(value=s.allow_foreground)
        self.v_preview = tk.BooleanVar(value=s.preview)
        self.v_top = tk.BooleanVar(value=s.always_on_top)

        lab("입력 방식", 0, 0)
        cb = ttk.Combobox(f, textvariable=self.v_method, values=list(eng.METHODS.values()), state="readonly",
                          width=22)
        cb.grid(row=0, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_settings())

        lab("감지 기준", 1, 0)
        tf = ttk.Frame(f, style="Panel.TFrame")
        tf.grid(row=1, column=1, sticky="we")
        ttk.Scale(tf, from_=0.5, to=0.95, variable=self.v_threshold, length=170,
                  command=lambda v: self.on_settings()).pack(side="left")
        self.th_lbl = ttk.Label(tf, text="", style="Value.TLabel", width=5)
        self.th_lbl.pack(side="left", padx=8)

        lab("게임 창 제목", 2, 0)
        e = ttk.Entry(f, textvariable=self.v_title, width=24)
        e.grid(row=2, column=1, sticky="w")
        e.bind("<FocusOut>", lambda ev: self.on_settings())
        e.bind("<Return>", lambda ev: self.on_settings())

        lab("검사 주기(초)", 0, 2)
        ttk.Spinbox(f, from_=0.1, to=2.0, increment=0.1, textvariable=self.v_interval, width=6,
                    command=self.on_settings).grid(row=0, column=3, sticky="w")
        lab("입력 후 대기(초)", 1, 2)
        ttk.Spinbox(f, from_=0.3, to=5.0, increment=0.1, textvariable=self.v_cooldown, width=6,
                    command=self.on_settings).grid(row=1, column=3, sticky="w")

        checks = ttk.Frame(f, style="Panel.TFrame")
        checks.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))
        for text, var in (("미리보기 표시", self.v_preview), ("이 창을 항상 위에", self.v_top),
                          ("최후 수단: 게임 창을 잠깐 앞으로 가져와 입력 (포커스가 0.1초 이동)", self.v_fg)):
            ttk.Checkbutton(checks, text=text, variable=var, command=self.on_settings).pack(side="left",
                                                                                           padx=(0, 18))
        self.th_lbl.configure(text=f"{s.threshold:.2f}")

    def _build_templates_tab(self, nb):
        f = ttk.Frame(nb, style="Panel.TFrame", padding=8)
        nb.add(f, text="템플릿")
        self.tree = ttk.Treeview(f, columns=("kind", "width"), height=5)
        self.tree.heading("#0", text="이름", anchor="w")
        self.tree.heading("kind", text="종류", anchor="w")
        self.tree.heading("width", text="기준 화면 크기", anchor="w")
        self.tree.column("#0", width=320)
        self.tree.column("kind", width=90)
        self.tree.column("width", width=110)
        self.tree.pack(side="left", fill="both", expand=True)
        side = ttk.Frame(f, style="Panel.TFrame")
        side.pack(side="left", fill="y", padx=(10, 0))
        ttk.Button(side, text="지금 화면에서 추가", command=self.add_template).pack(fill="x")
        ttk.Button(side, text="선택 삭제", command=self.delete_template).pack(fill="x", pady=6)
        ttk.Button(side, text="폴더 열기", command=self.open_template_dir).pack(fill="x")
        self.refresh_templates()

    # ------------------------------------------------------------ 동작
    def log(self, msg, tag=None):
        t = self.log_text
        t.configure(state="normal")
        t.insert("end", f"{datetime.datetime.now():%H:%M:%S}  ", "time")
        t.insert("end", msg + "\n", tag)
        if int(t.index("end-1c").split(".")[0]) > 500:
            t.delete("1.0", "100.0")
        t.see("end")
        t.configure(state="disabled")

    def set_info(self, key, text, color=TEXT):
        self.info[key].configure(text=text, foreground=color)

    def set_state(self, state):
        styles = {
            "running": ("● 감시 중", GREEN, "일시정지"),
            "paused": ("❚❚ 일시정지", GOLD, "시작"),
            "searching": ("● 게임 찾는 중", MUTED, "일시정지"),
            "minimized": ("● 게임 최소화됨", RED, "일시정지"),
        }
        text, color, btn = styles[state]
        if state == "running" and not self.window_info:
            text, color = styles["searching"][:2]
        self.state_pill.configure(text=text, fg=color)
        self.toggle_btn.configure(text=btn)

    def show_banner(self, text, btn_text=None, cmd=None):
        self.banner_text.configure(text=text)
        if btn_text:
            self.banner_btn.configure(text=btn_text, command=cmd)
            self.banner_btn.pack(side="right", padx=8, pady=6)
        else:
            self.banner_btn.pack_forget()
        self.banner.pack(fill="x", pady=(12, 0), before=self.body)

    def draw_meter(self, score):
        self._score = score
        c = self.meter
        c.delete("all")
        w, h = max(c.winfo_width(), 50), 22
        c.create_rectangle(0, 6, w - 44, h - 6, fill=PANEL_2, outline="")
        bw = int((w - 44) * max(0.0, min(score, 1.0)))
        hit = score >= self.settings.threshold
        c.create_rectangle(0, 6, bw, h - 6, fill=GOLD if hit else BLUE, outline="")
        tx = int((w - 44) * self.settings.threshold)
        c.create_line(tx, 2, tx, h - 2, fill=TEXT, width=2)
        c.create_text(w - 2, h // 2, anchor="e", fill=GOLD if hit else MUTED, text=f"{score:.2f}",
                      font=(self.F, 10, "bold"))

    def toggle(self):
        self.engine.set_running(not self.engine.running.is_set())

    def on_settings(self):
        inv = {v: k for k, v in eng.METHODS.items()}
        try:
            interval = max(0.1, float(self.v_interval.get()))
            cooldown = max(0.3, float(self.v_cooldown.get()))
        except (tk.TclError, ValueError):
            return
        s = replace(self.settings,
                    title=self.v_title.get().strip() or "이클립스",
                    method=inv.get(self.v_method.get(), "auto"),
                    threshold=round(float(self.v_threshold.get()), 2),
                    interval=interval, cooldown=cooldown,
                    allow_foreground=self.v_fg.get(), preview=self.v_preview.get(),
                    always_on_top=self.v_top.get())
        if s == self.settings:
            return
        self.settings = s
        s.save()
        self.engine.apply_settings(s)
        self.th_lbl.configure(text=f"{s.threshold:.2f}")
        self.set_info("method", eng.METHODS[s.method])
        self.draw_meter(self._score)
        self.apply_topmost()
        if not s.preview:
            self.canvas.delete("frame")
            self.canvas.itemconfigure(self.canvas_text, text="미리보기 꺼짐", state="normal")

    def apply_topmost(self):
        self.root.attributes("-topmost", bool(self.settings.always_on_top))

    def toggle_hide(self):
        hwnd = self.engine.hwnd
        if self.hidden_pos is not None:
            if hwnd:
                self.w32.move_window(hwnd, *self.hidden_pos)
            self.hidden_pos = None
            self.hide_btn.configure(text="게임 창 화면 밖으로 숨기기")
            self.log("게임 창을 원래 위치로 되돌렸습니다.")
            return
        if not hwnd:
            self.log("게임 창을 아직 찾지 못했습니다.", "warn")
            return
        self.hidden_pos = self.w32.move_offscreen(hwnd)
        self.hide_btn.configure(text="숨긴 게임 창 되돌리기")
        self.log("게임 창을 화면 밖으로 옮겼습니다. 미리보기가 계속 움직이면 정상 동작 중이에요.")

    def relaunch_admin(self):
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, subprocess.list2cmdline(sys.argv[1:])
        else:
            exe, params = sys.executable, subprocess.list2cmdline([os.path.abspath(__file__)] + sys.argv[1:])
        if self.w32.relaunch_as_admin(exe, params):
            self.on_close()
        else:
            self.log("관리자 권한 실행이 취소되었습니다.", "warn")

    # ---- 템플릿
    def refresh_templates(self):
        self.tree.delete(*self.tree.get_children())
        for t, custom in eng.all_templates():
            self.tree.insert("", "end", iid=t.name, text=t.name,
                             values=("사용자 추가" if custom else "기본",
                                     f"{t.ref_width}×{t.ref_height}" if t.ref_width else "-"))

    def delete_template(self):
        sel = self.tree.selection()
        if not sel:
            return
        name = sel[0]
        if not name.startswith("custom_"):
            messagebox.showinfo("EclipseSkip", "기본 템플릿은 삭제할 수 없어요.", parent=self.root)
            return
        if messagebox.askyesno("EclipseSkip", f"{name} 을(를) 삭제할까요?", parent=self.root):
            try:
                os.remove(os.path.join(eng.USER_TEMPLATE_DIR, name))
            except OSError as e:
                self.log(f"삭제 실패: {e}", "warn")
            self.refresh_templates()
            self.engine.reload_templates()

    def open_template_dir(self):
        os.makedirs(eng.USER_TEMPLATE_DIR, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(eng.USER_TEMPLATE_DIR)

    def add_template(self):
        if not self.engine.hwnd:
            messagebox.showinfo("EclipseSkip", "게임 창을 먼저 찾아야 해요.", parent=self.root)
            return
        self.engine.request_frame(lambda frame: self.root.after(0, lambda: TemplateDialog(self, frame)))

    # ---- 이벤트 처리
    def poll(self):
        frame_evt = None
        try:
            for _ in range(200):
                kind, val = self.engine.events.get_nowait()
                if kind == "frame":
                    frame_evt = val  # 가장 최근 화면만 그린다
                else:
                    self.handle(kind, val)
        except Exception:
            pass
        if frame_evt is not None and self.settings.preview:
            self.draw_preview(*frame_evt)
        self.root.after(80, self.poll)

    def handle(self, kind, val):
        if kind == "log":
            self.log(val)
        elif kind == "state":
            self.set_state(val)
        elif kind == "window":
            self.window_info = val
            if val:
                self.set_info("window", val["title"][:28], GREEN)
                self.set_info("size", f"{val['size'][0]} × {val['size'][1]}")
                self.set_state("running" if self.engine.running.is_set() else "paused")
            else:
                self.set_info("window", "찾는 중...", MUTED)
                self.set_info("capture", "-")
                self.set_state("searching")
                self.canvas.delete("frame")
                self.canvas.itemconfigure(self.canvas_text, text="게임 창을 찾는 중...", state="normal")
        elif kind == "capture":
            if val == "minimized":
                self.set_info("capture", "멈춤 (최소화됨)", RED)
                self.set_state("minimized")
                return
            if val == "failed":
                self.set_info("capture", "PrintWindow 실패", RED)
                return
            self.set_info("capture", "PrintWindow (가려져도 동작)", GREEN)
            self.set_state("running" if self.engine.running.is_set() else "paused")
        elif kind == "resize":
            self.set_info("size", f"{val[0]} × {val[1]}")
        elif kind == "method":
            self.set_info("method", eng.METHODS.get(val, val) + " (자동 전환됨)", GOLD)
        elif kind == "score":
            self.draw_meter(val.score if val else 0.0)
        elif kind == "skip":
            self.count_lbl.configure(text=str(self.engine.skip_count))
            self.last_lbl.configure(text=datetime.datetime.now().strftime("%H:%M:%S"))
            name = val.name.split("@")[0].replace("skip_", "")
            self.log(f"Skip 넘김 ({name}, 일치도 {val.score:.2f})", "skip")
        elif kind == "capture_fail":
            self.on_capture_fail(val)

    def on_capture_fail(self, d):
        what = "입력을 보내지" if d.get("input") else "화면을 캡처하지"
        ge = d["game_elevated"]
        self.log(f"게임 {what} 못했습니다. (오류 {d['error']}, 게임 관리자 권한: "
                 f"{'예' if ge else '아니오' if ge is False else '확인 불가'})", "warn")
        if not d["admin"]:
            self.show_banner(f"게임 {what} 못했어요. 게임이 관리자 권한으로 실행 중이라 막힌 것 같아요.",
                             "관리자 권한으로 다시 실행", self.relaunch_admin)
        elif not d.get("input"):
            self.show_banner("게임 화면을 캡처하지 못했어요. 게임이 창 모드인지 확인해 주세요. "
                             "화면이 다시 잡히면 자동으로 이어서 동작합니다.")

    def draw_preview(self, frame, match):
        img = frame
        if match:
            img = frame.copy()
            x0, y0 = match.x - match.w // 2, match.y - int(match.h * 0.3)
            cv2.rectangle(img, (x0 - 3, y0 - 3), (x0 + match.w + 3, y0 + match.h + 3), (78, 168, 214), 3)
        self.preview_img, _ = to_photo(img, PREVIEW_W, PREVIEW_H)
        self.canvas.delete("frame")
        self.canvas.create_image(PREVIEW_W // 2, PREVIEW_H // 2, image=self.preview_img, tags="frame")
        self.canvas.itemconfigure(self.canvas_text, state="hidden")
        self.preview_note.configure(text=f"갱신 {datetime.datetime.now():%H:%M:%S}")

    def on_close(self):
        self.engine.stop()
        if self.hidden_pos is not None and self.engine.hwnd:
            self.w32.move_window(self.engine.hwnd, *self.hidden_pos)  # 숨긴 게임 창은 꼭 되돌린다
        self.root.destroy()

    def finish_selftest(self):
        ok = self.engine.is_alive()
        with open(self.selftest_out, "w", encoding="utf-8") as f:
            f.write("ok" if ok else "engine dead")
        self.on_close()


class TemplateDialog:
    """캡처 화면 위에서 드래그로 Skip 영역을 골라 템플릿으로 저장."""

    def __init__(self, app, frame):
        self.app, self.frame = app, frame
        top = self.top = tk.Toplevel(app.root, bg=BG)
        top.title("Skip 템플릿 추가")
        top.transient(app.root)
        top.grab_set()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        self.photo, self.scale = to_photo(frame, int(sw * 0.85), int(sh * 0.7))
        ttk.Label(top, text="Skip ▸| 버튼과 아래 'Space' 라벨을 함께 드래그로 감싸 주세요.",
                  font=(app.F, 11, "bold")).pack(padx=16, pady=(14, 8), anchor="w")
        self.c = tk.Canvas(top, width=self.photo.width(), height=self.photo.height(), highlightthickness=0,
                           cursor="crosshair")
        self.c.pack(padx=16)
        self.c.create_image(0, 0, anchor="nw", image=self.photo)
        self.rect, self.start, self.box = None, None, None
        self.c.bind("<ButtonPress-1>", self.down)
        self.c.bind("<B1-Motion>", self.drag)
        bar = ttk.Frame(top)
        bar.pack(fill="x", padx=16, pady=12)
        self.info = ttk.Label(bar, text="", style="Sub.TLabel")
        self.info.pack(side="left")
        ttk.Button(bar, text="취소", command=top.destroy).pack(side="right")
        self.save_btn = ttk.Button(bar, text="저장", style="Gold.TButton", command=self.save, state="disabled")
        self.save_btn.pack(side="right", padx=8)

    def down(self, e):
        self.start = (e.x, e.y)
        if self.rect:
            self.c.delete(self.rect)
        self.rect = self.c.create_rectangle(e.x, e.y, e.x, e.y, outline=GOLD, width=2)

    def drag(self, e):
        x0, y0 = self.start
        self.c.coords(self.rect, x0, y0, e.x, e.y)
        fx0, fx1 = sorted((x0, e.x))
        fy0, fy1 = sorted((y0, e.y))
        s = self.scale
        h, w = self.frame.shape[:2]
        self.box = (max(0, int(fx0 / s)), max(0, int(fy0 / s)), min(w, int(fx1 / s)), min(h, int(fy1 / s)))
        bw, bh = self.box[2] - self.box[0], self.box[3] - self.box[1]
        self.info.configure(text=f"선택 영역 {bw} × {bh}px")
        self.save_btn.configure(state="normal" if bw >= 12 and bh >= 8 else "disabled")

    def save(self):
        name = eng.save_custom_template(self.frame, self.box)
        self.app.log(f"템플릿 추가: {name}")
        self.app.refresh_templates()
        self.app.engine.reload_templates()
        self.top.destroy()


def main():
    selftest_out = None
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        selftest_out = sys.argv[i + 1] if i + 1 < len(sys.argv) else "selftest.txt"
    if sys.platform != "win32" and not os.environ.get("ECLIPSESKIP_FAKE_W32"):
        sys.exit("Windows 에서만 동작합니다.")
    import win32_utils as w32
    w32.set_dpi_aware()
    root = tk.Tk()
    App(root, w32, selftest_out)
    root.mainloop()


if __name__ == "__main__":
    main()
