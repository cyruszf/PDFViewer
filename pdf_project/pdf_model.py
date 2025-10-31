# pdf_model.py
import fitz  # PyMuPDF
from typing import List, Tuple, Optional

class PDFModel:
    """
    The Model class responsible for handling the PDF document.
    It encapsulates all interactions with the PyMuPDF (fitz) library.
    """
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.doc: Optional[fitz.Document] = fitz.open(filepath)
        self.page_count = self.doc.page_count if self.doc else 0
        self.page_text_cache = {}

    def get_page(self, page_num: int):
        """Returns a page object from the document."""
        if self.doc and 0 <= page_num < self.page_count:
            return self.doc.load_page(page_num)
        return None

    def get_page_size(self, page_num: int) -> Optional[fitz.Rect]:
        """Returns the dimensions of a specific page."""
        page = self.get_page(page_num)
        return page.rect if page else None

    def search(self, text: str) -> List[Tuple[int, fitz.Rect]]:
        """Searches for text within the entire document."""
        results = []
        if not self.doc:
            return results

        for i in range(self.page_count):
            if i not in self.page_text_cache:
                self.page_text_cache[i] = self.get_page(i).get_text()
            for hit in self.get_page(i).search_for(text):
                results.append((i, hit))
        return results

    def close(self):
        """Closes the PDF document."""
        if self.doc:
            self.doc.close()
            self.doc = None