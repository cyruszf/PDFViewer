# main.py
import io
import os
import sys
import fitz  # PyMuPDF
from PIL import Image, ImageTk, ImageDraw
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
from collections import deque
import base64
import ctypes
from typing import Dict, List, Optional, Tuple
from io import BytesIO
from tooltip import Tooltip
from config import ICON_DATA, THEMES, CACHE_SIZE_LIMIT, RENDER_BUFFER_PAGES
from icon_loader import load_icons

class RenderWorker(threading.Thread):
    """Renderar PDF-sidor i bakgrunden."""
    def __init__(self, pdf_doc, result_queue):
        super().__init__(daemon=True)
        self.pdf_doc = pdf_doc
        self.result_queue = result_queue
        self.render_queue = queue.Queue()
        self.start()

    def run(self):
        while True:
            page_index, zoom, rotation = self.render_queue.get()
            if page_index is None:
                break
            try:
                page = self.pdf_doc.load_page(page_index)
                mat = fitz.Matrix(zoom, zoom).prerotate(rotation)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                self.result_queue.put((page_index, zoom, rotation, img))
            except Exception as e:
                print(f"Renderingsfel: {e}")

    def render(self, page_index, zoom, rotation):
        self.render_queue.put((page_index, zoom, rotation))

    def stop(self):
        self.render_queue.put((None, None, None))


class PDFViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self._setup_dpi_awareness()

        self.title("PDF-viewer")
        self.geometry("1200x900")

        self.theme = THEMES["dark"]
        self.fit_to_width = True
        self.buffer_pages = RENDER_BUFFER_PAGES

        self.pdf_path: Optional[str] = None
        self.doc: Optional[fitz.Document] = None
        self.page_count = 0
        self.current_page = 0
        self.zoom = 1.0
        self.rotation = 0

        self.result_queue = queue.Queue()
        self.renderer = None

        self.page_dims: List[Tuple[int, int]] = []
        self.page_positions: List[int] = []
        self.cache: Dict[int, ImageTk.PhotoImage] = {}
        self.cache_keys = deque()
        self.canvas_items: List[int] = []
        self.placeholder = ImageTk.PhotoImage(Image.new("RGBA", (16, 16), (0, 0, 0, 0)))

        self.search_active = False
        self.search_term = ""
        self.search_results: List[Tuple[int, fitz.Rect]] = []
        self.current_search_hit = 0
        self.page_text_cache: Dict[int, str] = {}
        self.search_highlight_items: List[int] = []

        # create queues BEFORE starting worker thread
        self.render_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.render_thread = None  # vi startar ingen tråd direkt längre

        self.placeholder = ImageTk.PhotoImage(Image.new("RGBA", (16, 16), (0, 0, 0, 0)))
        self.icons = load_icons(self.placeholder)

        self._setup_styles()
        self._build_ui()
        self._bind_events()
        self._check_result_queue()

        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.gui_scaling_factor = 1.0

        if len(sys.argv) > 1:
            self.load_pdf(sys.argv[1])

    def _setup_dpi_awareness(self):
        self.pdf_render_scale = 1.0
        self.gui_scaling_factor = 1.0
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            self.gui_scaling_factor = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
            self.tk.call('tk', 'scaling', self.gui_scaling_factor)
        except (AttributeError, OSError):
            pass

    # -------------------------
    # Styles & UI
    # -------------------------
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

    def _build_ui(self):
        self.configure(bg=self.theme["bg"])
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

    def _bind_events(self):
        self.bind("<Control-o>", lambda e: self.open_pdf())
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

    # -------------------------
    # PDF loading / rendering
    # -------------------------
    def load_pdf(self, path: str):
        # rensa gamla köer
        while not self.render_queue.empty():
            try:
                self.render_queue.get_nowait()
            except Exception:
                break
        while not self.result_queue.empty():
            try:
                self.result_queue.get_nowait()
            except Exception:
                break

        try:
            self.doc = fitz.open(path)
            self.pdf_path = path
            self.page_count = self.doc.page_count

            # skapa renderaren här:
            self.renderer = RenderWorker(self.doc, self.result_queue)

            self._reset_state()
            self.after(100, self._initial_layout_and_render)
        except Exception as e:
            messagebox.showerror("Fel vid öppning", str(e))
            self.doc = None

    def _initial_layout_and_render(self):
        self._precalculate_layout()
        self._request_render_visible_pages()
        self.scroll_to_page(0)

    def _reset_state(self):
        self.current_page = 0
        self.rotation = 0
        self.zoom = 1.0
        self.page_dims.clear()
        self.page_positions.clear()
        self.cache.clear()
        self.cache_keys.clear()
        self.canvas.delete("all")
        # create placeholder image items for each page
        self.canvas_items = [self.canvas.create_image(0, 0, anchor="nw", image=self.placeholder) for _ in
                             range(self.page_count)]
        self._clear_search()
        self._update_statusbar()

    def _precalculate_layout(self):
        y_pos, spacing = 10, 20
        canvas_w = self.canvas.winfo_width()
        if canvas_w <= 1:
            return

        total_height = y_pos
        for i in range(self.page_count):
            page = self.doc.load_page(i)
            # correct scaling: when fit_to_width, include self.zoom multiplier once
            if self.fit_to_width:
                scale = (canvas_w / page.rect.width) * self.zoom
            else:
                scale = self.zoom

            w, h = int(page.rect.width * scale), int(page.rect.height * scale)
            self.page_dims.append((w, h))
            self.page_positions.append(total_height)

            x_centered = max((canvas_w - w) // 2, 0)
            try:
                self.canvas.coords(self.canvas_items[i], x_centered, total_height)
            except Exception:
                img_id = self.canvas.create_image(x_centered, total_height, anchor="nw", image=self.placeholder)
                if i < len(self.canvas_items):
                    self.canvas_items[i] = img_id
                else:
                    self.canvas_items.append(img_id)

            total_height += h + spacing

        self.canvas.config(scrollregion=(0, 0, canvas_w, total_height))

    def _check_result_queue(self):
        try:
            while not self.result_queue.empty():
                page_index, zoom, rotation, img = self.result_queue.get_nowait()
                # place rendered image (best-effort)
                self._place_rendered_image(page_index, img)
        finally:
            self.after(50, self._check_result_queue)

    def _request_render_visible_pages(self, force_rerender=False):
        if not self.doc or not self.page_positions:
            return
        y0 = self.canvas.canvasy(0)
        y1 = y0 + self.canvas.winfo_height()
        indices_to_render = set()
        for i, y_pos in enumerate(self.page_positions):
            h = self.page_dims[i][1]
            if (y_pos + h) >= y0 and y_pos <= y1:
                indices_to_render.add(i)

        if indices_to_render:
            min_vis, max_vis = min(indices_to_render), max(indices_to_render)
            start, end = max(0, min_vis - self.buffer_pages), min(self.page_count - 1, max_vis + self.buffer_pages)
            for i in range(start, end + 1):
                indices_to_render.add(i)

        for i in sorted(list(indices_to_render)):
            if force_rerender or i not in self.cache:
                scale = self._page_scale(i)
                if 0 <= i < self.page_count:
                    self.renderer.render(i, scale, self.rotation)

        self._manage_cache(indices_to_render)
        self._update_current_page_from_scroll()

    def _place_rendered_image(self, page_index, img: Image.Image):
        tk_img = ImageTk.PhotoImage(img)
        self.cache[page_index] = tk_img
        try:
            self.canvas.itemconfig(self.canvas_items[page_index], image=tk_img)
        except Exception:
            if page_index < len(self.canvas_items):
                self.canvas_items[page_index] = self.canvas.create_image(0, self.page_positions[page_index], anchor="nw", image=tk_img)
            else:
                self.canvas_items.append(self.canvas.create_image(0, self.page_positions[page_index], anchor="nw", image=tk_img))

        if page_index in self.cache_keys:
            self.cache_keys.remove(page_index)
        self.cache_keys.append(page_index)

    def _manage_cache(self, visible_indices: set):
        if len(self.cache) > len(visible_indices) + CACHE_SIZE_LIMIT:
            keys_to_remove = [k for k in self.cache_keys if k not in visible_indices][:CACHE_SIZE_LIMIT]
            for key in keys_to_remove:
                if key in self.cache:
                    del self.cache[key]
                if key in self.cache_keys:
                    self.cache_keys.remove(key)
                try:
                    self.canvas.itemconfig(self.canvas_items[key], image=self.placeholder)
                except Exception:
                    pass

    # -------------------------
    # Navigation / UI helpers
    # -------------------------
    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF-filer", "*.pdf")])
        if path:
            self.load_pdf(path)

    def scroll_to_page(self, page_index: int):
        if not self.doc or not self.page_positions:
            return
        scroll_region_str = self.canvas.cget("scrollregion")
        if not scroll_region_str:
            return
        total_height = float(scroll_region_str.split()[3])
        if total_height > 0:
            y = self.page_positions[page_index]
            self.canvas.yview_moveto(y / total_height)
        self._request_render_visible_pages()

    def prev_page(self):
        if self.current_page > 0:
            self.scroll_to_page(self.current_page - 1)

    def next_page(self):
        if self.current_page < self.page_count - 1:
            self.scroll_to_page(self.current_page + 1)

    def goto_page_event(self, event=None):
        try:
            n = int(self.page_entry.get()) - 1
            if 0 <= n < self.page_count:
                self.scroll_to_page(n)
        except ValueError:
            pass

    def _on_resize(self, event=None):
        if self.fit_to_width and self.doc:
            self._relayout_and_rerender()

    def _on_mousewheel(self, event):
        delta = event.delta if hasattr(event, "delta") else (120 if event.num == 4 else -120)
        self.canvas.yview_scroll(-1 * (delta // 120), "units")
        self._request_render_visible_pages()

    def _relayout_and_rerender(self):
        for item in self.search_highlight_items:
            self.canvas.delete(item)
        self.search_highlight_items.clear()
        self.after(50, self._clear_cache_and_rerender)

    def _clear_cache_and_rerender(self):
        if not self.doc:
            return
        while not self.render_queue.empty():
            try:
                self.render_queue.get_nowait()
            except Exception:
                break
        self.cache.clear()
        self.cache_keys.clear()
        self._precalculate_layout()
        self._request_render_visible_pages(force_rerender=True)
        self.after(50, lambda: self.scroll_to_page(self.current_page))

    def _zoom_in(self):
        self.zoom = min(self.zoom * 1.2, 5.0)
        self._relayout_and_rerender()

    def _zoom_out(self):
        self.zoom = max(self.zoom / 1.2, 0.1)
        self._relayout_and_rerender()

    def _set_zoom_event(self, event=None):
        try:
            val = self.zoom_entry.get().replace('%', '')
            new_zoom = float(val) / 100.0
            if 0.1 <= new_zoom <= 5.0:
                self.zoom = new_zoom
                self._relayout_and_rerender()
        except ValueError:
            self._update_statusbar()

    def _rotate(self):
        self.rotation = (self.rotation + 90) % 360
        if not self.doc:
            return
        while not self.render_queue.empty():
            try:
                self.render_queue.get_nowait()
            except Exception:
                break
        self.cache.clear()
        self.cache_keys.clear()
        self._request_render_visible_pages(force_rerender=True)
        self._update_statusbar()

    # -------------------------
    # Search
    # -------------------------
    def _search_event(self, event=None):
        term = self.search_entry.get()
        if not term:
            self._clear_search()
            return
        if term != self.search_term:
            self.search_term = term
            self._perform_search()
        self._next_search_hit()

    def _perform_search(self):
        if not self.doc:
            return
        self._clear_search(keep_term=True)
        self.search_active = True
        for i in range(self.page_count):
            if i not in self.page_text_cache:
                self.page_text_cache[i] = self.doc.load_page(i).get_text()
            for hit in self.doc.load_page(i).search_for(self.search_term):
                self.search_results.append((i, hit))
        if self.search_results:
            self.current_search_hit = -1
            self.search_prev_btn.config(state=tk.NORMAL)
            self.search_next_btn.config(state=tk.NORMAL)
        self._update_statusbar()

    def _clear_search(self, keep_term=False):
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
        self._update_statusbar()

    def _jump_to_search_hit(self):
        if not self.search_results:
            return
        page_index, rect = self.search_results[self.current_search_hit]
        self.scroll_to_page(page_index)
        self.after(200, lambda: self._highlight_rect(page_index, rect))
        self._update_statusbar()

    def _highlight_rect(self, page_index, rect):
        for item in self.search_highlight_items:
            self.canvas.delete(item)
        self.search_highlight_items.clear()
        if not self.doc or not self.page_dims:
            return

        scale = self._page_scale(page_index)
        x_offset = max((self.canvas.winfo_width() - self.page_dims[page_index][0]) // 2, 0)
        y_offset = self.page_positions[page_index]

        transform = fitz.Matrix(scale, scale).prerotate(self.rotation)
        r_on_canvas = rect * transform + fitz.Point(x_offset, y_offset)

        item = self.canvas.create_rectangle(r_on_canvas.x0, r_on_canvas.y0, r_on_canvas.x1, r_on_canvas.y1,
                                            fill=self.theme["highlight"], stipple="gray50", outline="")
        self.search_highlight_items.append(item)

    def _next_search_hit(self):
        if not self.search_results:
            return
        self.current_search_hit = (self.current_search_hit + 1) % len(self.search_results)
        self._jump_to_search_hit()

    def _prev_search_hit(self):
        if not self.search_results:
            return
        self.current_search_hit = (self.current_search_hit - 1) % len(self.search_results)
        self._jump_to_search_hit()

    # -------------------------
    # Helpers / Statusbar
    # -------------------------
    def _page_scale(self, page_index: int) -> float:
        if not self.doc or self.page_count <= page_index:
            return self.zoom
        page_width = self.doc.load_page(page_index).rect.width
        if self.fit_to_width and page_width > 0:
            return (self.canvas.winfo_width() / page_width) * self.zoom
        return self.zoom

    def _update_current_page_from_scroll(self):
        y_center = self.canvas.canvasy(0) + self.canvas.winfo_height() / 2
        for i, pos in reversed(list(enumerate(self.page_positions))):
            if y_center >= pos:
                if self.current_page != i:
                    self.current_page = i
                    self._update_statusbar()
                break

    def _update_statusbar(self):
        if not self.doc:
            self.info_lbl_left.config(text="Ingen fil öppen")
            self.info_lbl_right.config(text="Sida: -/- | Zoom: - | Rot: -")
            self.title("PDF-viewer")
            return

        filename = self.pdf_path.split('/')[-1].split('\\')[-1]
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

    def _on_closing(self):
        try:
            self.render_queue.put((None, None, None, None))
            self.render_thread.join(timeout=1)
        except Exception:
            pass
        if self.renderer:
            self.renderer.stop()
        self.destroy()


def main():
    app = PDFViewer()
    app.mainloop()


if __name__ == "__main__":
    main()