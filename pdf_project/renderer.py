# renderer.py
import threading
import queue
import fitz  # PyMuPDF
from PIL import Image

class RenderWorker(threading.Thread):
    """
    A worker thread that renders PDF pages in the background.
    """
    def __init__(self, pdf_doc, result_queue):
        super().__init__(daemon=True)
        self.pdf_doc = pdf_doc
        self.result_queue = result_queue
        self.render_queue = queue.Queue()
        self.start()

    def run(self):
        while True:
            page_index, zoom, rotation = self.render_queue.get()
            if page_index is None:  # Sentinel value to stop the thread
                break

            try:
                page = self.pdf_doc.load_page(page_index)
                mat = fitz.Matrix(zoom, zoom).prerotate(rotation)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                self.result_queue.put((page_index, zoom, rotation, img))
            except Exception as e:
                print(f"Rendering error on page {page_index}: {e}")

    def render(self, page_index, zoom, rotation):
        """Adds a page rendering request to the queue."""
        self.render_queue.put((page_index, zoom, rotation))

    def stop(self):
        """Stops the worker thread."""
        self.render_queue.put((None, None, None))