# app.py
import sys
import queue
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

from view import View
from pdf_model import PDFModel
from renderer import RenderWorker
from config import CACHE_SIZE_LIMIT

class PdfApplication(View):
    """
    The main application class for the PDF Viewer.
    Acts as the controller, managing state and communication between model and view.
    """
    def __init__(self):
        super().__init__()

        self.pdf_model = None
        self.renderer = None
        self.result_queue = queue.Queue()

        self._bind_app_events()
        self._check_result_queue()

        if len(sys.argv) > 1:
            self.load_pdf(sys.argv[1])

    def _bind_app_events(self):
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.bind("<Control-o>", lambda e: self.open_pdf())

    def _on_closing(self):
        if self.renderer:
            self.renderer.stop()
        self.destroy()

    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.load_pdf(path)

    def load_pdf(self, path: str):
        try:
            if self.renderer:
                self.renderer.stop()
            if self.pdf_model:
                self.pdf_model.close()

            self.pdf_model = PDFModel(path)
            self.renderer = RenderWorker(self.pdf_model.doc, self.result_queue)

            self.reset_ui_for_new_pdf(self.pdf_model.page_count)
            self.after(100, self.initial_layout_and_render)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open PDF: {e}")
            self.pdf_model = None

    def initial_layout_and_render(self):
        self._precalculate_layout()
        self.request_render_visible_pages()
        self.scroll_to_page(0)

    def _precalculate_layout(self):
        if not self.pdf_model:
            return
        y_pos, spacing = 10, 20
        canvas_w = self.canvas.winfo_width()
        total_height = y_pos

        self.page_dims.clear()
        self.page_positions.clear()

        for i in range(self.page_count):
            page_rect = self.pdf_model.get_page_size(i)
            scale = self.get_page_scale(page_rect.width)

            w, h = int(page_rect.width * scale), int(page_rect.height * scale)
            self.page_dims.append((w, h))
            self.page_positions.append(total_height)

            x_centered = max((canvas_w - w) // 2, 0)
            self.canvas.coords(self.canvas_items[i], x_centered, total_height)
            total_height += h + spacing

        self.canvas.config(scrollregion=(0, 0, canvas_w, total_height))

    def _check_result_queue(self):
        try:
            while not self.result_queue.empty():
                page_index, zoom, rotation, img = self.result_queue.get_nowait()
                # Ensure the received image matches current settings before displaying
                if abs(zoom - self.get_page_scale(self.pdf_model.get_page_size(page_index).width)) < 0.01 and rotation == self.rotation:
                     self._place_rendered_image(page_index, img)
        finally:
            self.after(50, self._check_result_queue)

    def _place_rendered_image(self, page_index, img: Image.Image):
        tk_img = ImageTk.PhotoImage(img)
        self.cache[page_index] = tk_img
        self.canvas.itemconfig(self.canvas_items[page_index], image=tk_img)

        if page_index in self.cache_keys:
            self.cache_keys.remove(page_index)
        self.cache_keys.append(page_index)

    def request_render_visible_pages(self, force_rerender=False):
        if not self.pdf_model or not self.page_positions:
            return
        y0 = self.canvas.canvasy(0)
        y1 = y0 + self.canvas.winfo_height()
        indices_to_render = set()

        for i, y_pos in enumerate(self.page_positions):
            if i < len(self.page_dims):
                h = self.page_dims[i][1]
                if (y_pos + h) >= y0 and y_pos <= y1:
                    indices_to_render.add(i)

        if indices_to_render:
            min_vis, max_vis = min(indices_to_render), max(indices_to_render)
            start = max(0, min_vis - self.buffer_pages)
            end = min(self.page_count - 1, max_vis + self.buffer_pages)
            for i in range(start, end + 1):
                indices_to_render.add(i)

        for i in sorted(list(indices_to_render)):
            if force_rerender or i not in self.cache:
                page_width = self.pdf_model.get_page_size(i).width
                scale = self.get_page_scale(page_width)
                if self.renderer:
                    self.renderer.render(i, scale, self.rotation)

        self._manage_cache(indices_to_render)
        self._update_current_page_from_scroll()

    def _manage_cache(self, visible_indices: set):
        if len(self.cache) > len(visible_indices) + CACHE_SIZE_LIMIT:
            keys_to_remove = [k for k in self.cache_keys if k not in visible_indices][:CACHE_SIZE_LIMIT]
            for key in keys_to_remove:
                if key in self.cache:
                    del self.cache[key]
                if key in self.cache_keys:
                    self.cache_keys.remove(key)
                self.canvas.itemconfig(self.canvas_items[key], image=self.placeholder)

    def _update_current_page_from_scroll(self):
        y_center = self.canvas.canvasy(0) + self.canvas.winfo_height() / 2
        for i, pos in reversed(list(enumerate(self.page_positions))):
            if y_center >= pos:
                if self.current_page != i:
                    self.current_page = i
                    self.update_statusbar()
                break

    def scroll_to_page(self, page_index: int):
        if not self.pdf_model or not self.page_positions or page_index >= len(self.page_positions):
            return
        scroll_region_str = self.canvas.cget("scrollregion")
        if not scroll_region_str:
            return
        parts = scroll_region_str.split()
        if len(parts) < 4: return
        total_height = float(parts[3])

        if total_height > 0:
            y = self.page_positions[page_index]
            self.canvas.yview_moveto(y / total_height)
        self.request_render_visible_pages()

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
        if self.fit_to_width and self.pdf_model:
            self._relayout_and_rerender()

    def _on_mousewheel(self, event):
        delta = event.delta if hasattr(event, "delta") else (120 if event.num == 4 else -120)
        self.canvas.yview_scroll(-1 * (delta // 120), "units")
        self.request_render_visible_pages()

    def _relayout_and_rerender(self):
        for item in self.search_highlight_items:
            self.canvas.delete(item)
        self.search_highlight_items.clear()
        self.after(50, self._clear_cache_and_rerender)

    def _clear_cache_and_rerender(self):
        if not self.pdf_model:
            return
        if self.renderer:
            # Clear pending render jobs by creating a new queue
            self.renderer.render_queue = queue.Queue()
        self.cache.clear()
        self.cache_keys.clear()
        self._precalculate_layout()
        self.request_render_visible_pages(force_rerender=True)
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
            self.update_statusbar()

    def _rotate(self):
        self.rotation = (self.rotation + 90) % 360
        if not self.pdf_model:
            return
        if self.renderer:
            self.renderer.render_queue = queue.Queue()
        self.cache.clear()
        self.cache_keys.clear()
        # No need for full relayout, just re-render
        self.request_render_visible_pages(force_rerender=True)
        self.update_statusbar()

    def _search_event(self, event=None):
        term = self.search_entry.get()
        if not term:
            self.clear_search()
            return
        if term != self.search_term:
            self.search_term = term
            self.search_results = self.pdf_model.search(self.search_term)
            if self.search_results:
                self.current_search_hit = -1
                self.search_prev_btn.config(state=tk.NORMAL)
                self.search_next_btn.config(state=tk.NORMAL)
            else:
                self.clear_search(keep_term=True)
            self.search_active = True
            self.update_statusbar()
        self._next_search_hit()


    def _prev_search_hit(self):
        if not self.search_results:
            return
        self.current_search_hit = (self.current_search_hit - 1) % len(self.search_results)
        self._jump_to_search_hit()

    def _next_search_hit(self):
        if not self.search_results:
            return
        self.current_search_hit = (self.current_search_hit + 1) % len(self.search_results)
        self._jump_to_search_hit()

    def _jump_to_search_hit(self):
        if not self.search_results:
            return
        page_index, rect = self.search_results[self.current_search_hit]
        self.scroll_to_page(page_index)
        self.after(200, lambda: self.highlight_rect(page_index, rect))
        self.update_statusbar()