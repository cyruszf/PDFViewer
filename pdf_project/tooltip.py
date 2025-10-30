# tooltip.py

import tkinter as tk
from tkinter import ttk


class Tooltip:
    """Hjälpklass för Tooltips."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        # Bind events only once in the constructor
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)
        # Prevent binding multiple times on the same widget, just in case
        self.widget.bind("<ButtonPress>", self.hide_tooltip)

    def show_tooltip(self, event):
        # Do not show if another window is already active or if text is empty
        if self.tooltip_window or not self.text:
            return

        try:
            # Calculate position: x, y, width, height relative to the widget
            x, y, _, _ = self.widget.bbox("insert")
        except Exception:
            # Fallback for widgets without an 'insert' position
            x = y = 0

        # Convert widget coordinates to screen coordinates and add offset
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

        # Create the tooltip window
        self.tooltip_window = tk.Toplevel(self.widget)
        # Hide the border and title bar
        self.tooltip_window.wm_overrideredirect(True)
        # Position the window
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        # Create the label inside the window
        label = tk.Label(self.tooltip_window,
                         text=self.text,
                         background="#FFFFE0",
                         relief="solid",
                         borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(padx=1, pady=1)

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None