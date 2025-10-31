# view.py
import tkinter as tk
from tkinter import ttk
from collections import deque
from PIL import Image, ImageTk
import ctypes
import fitz

from tooltip import Tooltip
from icon_loader import load_icons
from config import THEMES, CACHE_SIZE_LIMIT, RENDER_BUFFER_PAGES

class View(tk.Tk):
    """
    The View class responsible for the entire GUI of the PDF Viewer.
    """
    def __init__(self):
        super().__init__()

        self.theme = THEMES["dark"]
        self.fit_to_width = True
        self.buffer_pages = RENDER_BUFFER_PAGES

        self.page_count = 0
        self.current_page = 0
        self.zoom = 1.0
        self.rotation = 0

        self.page_dims = []
        self.page_positions = []
        self.cache = {}
        self.cache_keys = deque()
        self.canvas_items = []

        self.search_active = False
        self.search_term = ""
        self.search_results = []
        self.current_search_hit = 0
        self.search_highlight_items = []

        self._setup_window()
        self._setup_styles()
        self._create_widgets()
        self._bind_ui_events()

    def _setup_window(self):
        self.title("PDF Viewer")
        self.geometry("1200x900")
        self.configure(bg=self.theme["bg"])
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            gui_scaling_factor = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
            self.tk.call('tk', 'scaling', gui_scaling_factor)
        except (AttributeError, OSError):
            pass

    def _setup_styles(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except Exception:
            pass
        self.style.configure('TButton', background=self.theme['btn_bg'], foreground=self.theme['fg'], borderwidth=1,
                             focusthickness=3, focuscolor='none')
        self.style.map('TButton', background=[('active', '#5A5A5A')])
        self.style.configure('TEntry', fieldbackground=self.theme['entry_bg'], foreground=self.theme['fg'],
                             insertcolor=self.theme['fg'])
        self.style.configure('TScrollbar', background=self.theme['bg'], troughcolor=self.theme['canvas_bg'])
        self.style.configure('TFrame', background=self.theme['bg'])
        self.style.configure('TLabel', background=self.theme['bg'], foreground=self.theme['fg'])
        self.style.configure('TSeparator', background=self.theme['canvas_bg'])

    def _create_widgets(self):
        self.placeholder = ImageTk.PhotoImage(Image.new("RGBA", (16, 16), (0, 0, 0, 0)))
        self.icons = load_icons(self.placeholder)

        self._create_toolbar()
        self._create_main_content()
        self._create_statusbar()

    def _create_toolbar(self):
        toolbar = ttk.Frame(self, style='TFrame', padding=5)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        btn_open = ttk.Button(toolbar, image=self.icons.get('open', self.placeholder), command=self.open_pdf)
        btn_open.pack(side=tk.LEFT, padx=5)
        Tooltip(btn_open, "Öppna PDF (Ctrl+O)")

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=5, fill='y')

        btn_prev = ttk.Button(toolbar, text="◀", command=self.prev_page, width=3)
        btn_prev.pack(side=tk.LEFT, padx=(5, 0))
        self.page_entry = ttk.Entry(toolbar, width=4, justify="center")
        self.page_entry.pack(side=tk.LEFT, padx=2)
        self.page_entry.bind("<Return>", self.goto_page_event)
        btn_next = ttk.Button(toolbar, text="▶", command=self.next_page, width=3)
        btn_next.pack(side=tk.LEFT, padx=(0, 5))
        Tooltip(btn_prev, "Föregående sida (Vänsterpil)")
        Tooltip(btn_next, "Nästa sida (Högerpil)")

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=5, fill='y')

        btn_zoom_out = ttk.Button(toolbar, image=self.icons.get('zoom_out', self.placeholder), command=self._zoom_out)
        btn_zoom_out.pack(side=tk.LEFT, padx=(5, 0))
        self.zoom_entry = ttk.Entry(toolbar, width=6, justify="center")
        self.zoom_entry.insert(0, f"{self.zoom * 100:.0f}%")
        self.zoom_entry.pack(side=tk.LEFT, padx=2)
        self.zoom_entry.bind("<Return>", self._set_zoom_event)
        btn_zoom_in = ttk.Button(toolbar, image=self.icons.get('zoom_in', self.placeholder), command=self._zoom_in)
        btn_zoom_in.pack(side=tk.LEFT, padx=(0, 5))
        Tooltip(btn_zoom_in, "Zooma in (Ctrl+Plus)")
        Tooltip(btn_zoom_out, "Zooma ut (Ctrl+Minus)")

        btn_rotate = ttk.Button(toolbar, image=self.icons.get('rotate', self.placeholder), command=self._rotate)
        btn_rotate.pack(side=tk.LEFT, padx=5)
        Tooltip(btn_rotate, "Rotera (Ctrl+R)")

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=5, fill='y')

        self.search_entry = ttk.Entry(toolbar, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=5, ipady=1)
        self.search_entry.bind("<Return>", self._search_event)
        Tooltip(self.search_entry, "Sök i dokumentet (Ctrl+F)")

        btn_search = ttk.Button(toolbar, image=self.icons.get('search', self.placeholder), command=self._search_event)
        btn_search.pack(side=tk.LEFT, padx=(0, 2))
        self.search_prev_btn = ttk.Button(toolbar, image=self.icons.get('up', self.placeholder), state=tk.DISABLED,
                                          command=self._prev_search_hit)
        self.search_prev_btn.pack(side=tk.LEFT)
        self.search_next_btn = ttk.Button(toolbar, image=self.icons.get('down', self.placeholder), state=tk.DISABLED,
                                          command=self._next_search_hit)
        self.search_next_btn.pack(side=tk.LEFT, padx=(0, 5))
        Tooltip(self.search_prev_btn, "Föregående träff")
        Tooltip(self.search_next_btn, "Nästa träff")

    def _create_main_content(self):
        main_frame = ttk.Frame(self, style='TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.canvas = tk.Canvas(main_frame, bg=self.theme["canvas_bg"], highlightthickness=0)
        self.scroll_y = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll_y.set)
        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _create_statusbar(self):
        statusbar = ttk.Frame(self, style='TFrame', padding=(5, 2))
        statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.info_lbl_left = ttk.Label(statusbar, text="Ingen fil öppen", anchor="w")
        self.info_lbl_left.pack(side=tk.LEFT, padx=10)
        self.info_lbl_right = ttk.Label(statusbar, text="Sida: -/- | Zoom: - | Rot: -", anchor="e")
        self.info_lbl_right.pack(side=tk.RIGHT, padx=10)

    def _bind_ui_events(self):
        self.bind("<Left>", lambda e: self.prev_page())
        self.bind("<Right>", lambda e: self.next_page())
        self.bind("<Prior>", lambda e: self.prev_page())
        self.bind("<Next>", lambda e: self.next_page())
        self.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.bind("<Control-r>", lambda e: self._rotate())
        self.bind("<Control-plus>", lambda e: self._zoom_in())
        self.bind("<Control-minus>", lambda e: self._zoom_out())
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)

    def reset_ui_for_new_pdf(self, page_count):
        self.page_count = page_count
        self.current_page = 0
        self.rotation = 0
        self.zoom = 1.0
        self.page_dims.clear()
        self.page_positions.clear()
        self.cache.clear()
        self.cache_keys.clear()
        self.canvas.delete("all")
        self.canvas_items = [self.canvas.create_image(0, 0, anchor="nw", image=self.placeholder) for _ in
                             range(self.page_count)]
        self.clear_search()
        self.update_statusbar()

    def update_statusbar(self):
        if not self.pdf_model:
            self.info_lbl_left.config(text="Ingen fil öppen")
            self.info_lbl_right.config(text="Sida: -/- | Zoom: - | Rot: -")
            self.title("PDF-viewer")
            return

        filename = self.pdf_model.filepath.split('/')[-1].split('\\')[-1]
        self.info_lbl_left.config(text=filename)

        page_info = f"Sida: {self.current_page + 1}/{self.page_count}"
        zoom_info = f"Zoom: {self.zoom * 100:.0f}%"
        rot_info = f"Rot: {self.rotation}°"

        if self.search_active:
            search_info = f" | Träff: {self.current_search_hit + 1}/{len(self.search_results)}" if self.search_results else " | Inga träffar"
            page_info += search_info

        self.info_lbl_right.config(text=f"{page_info} | {zoom_info} | {rot_info}")
        if self.focus_get() != self.page_entry:
            self.page_entry.delete(0, tk.END)
            self.page_entry.insert(0, str(self.current_page + 1))
        if self.focus_get() != self.zoom_entry:
            self.zoom_entry.delete(0, tk.END)
            self.zoom_entry.insert(0, f"{self.zoom * 100:.0f}%")

        self.title(f"{filename} - Sida {self.current_page + 1}/{self.page_count}")

    def clear_search(self, keep_term=False):
        for item in self.search_highlight_items:
            self.canvas.delete(item)
        self.search_highlight_items.clear()
        self.search_results.clear()
        self.current_search_hit = 0
        self.search_active = False
        if not keep_term:
            self.search_term = ""
            self.search_entry.delete(0, tk.END)
        self.search_prev_btn.config(state=tk.DISABLED)
        self.search_next_btn.config(state=tk.DISABLED)
        self.update_statusbar()

    def highlight_rect(self, page_index, rect):
        for item in self.search_highlight_items:
            self.canvas.delete(item)
        self.search_highlight_items.clear()
        if not self.pdf_model or not self.page_dims:
            return

        page_width = self.pdf_model.get_page_size(page_index).width
        scale = self.get_page_scale(page_width)

        x_offset = max((self.canvas.winfo_width() - self.page_dims[page_index][0]) // 2, 0)
        y_offset = self.page_positions[page_index]

        transform = fitz.Matrix(scale, scale).prerotate(self.rotation)
        r_on_canvas = rect * transform + fitz.Point(x_offset, y_offset)

        item = self.canvas.create_rectangle(r_on_canvas.x0, r_on_canvas.y0, r_on_canvas.x1, r_on_canvas.y1,
                                            fill=self.theme["highlight"], stipple="gray50", outline="")
        self.search_highlight_items.append(item)

    def get_page_scale(self, page_width):
        if self.fit_to_width and page_width > 0:
            return (self.canvas.winfo_width() / page_width) * self.zoom
        return self.zoom