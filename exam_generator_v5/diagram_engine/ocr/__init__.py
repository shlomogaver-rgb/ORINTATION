"""Independent OCR channel (Tesseract). Never uses the vision model: its readings are independent evidence."""
from .engine import available, labels, numbers, table_cells  # noqa: F401
