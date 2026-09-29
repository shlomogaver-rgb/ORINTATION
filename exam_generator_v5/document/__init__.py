"""Full-document reconstruction (MODE B): PDF / page images -> FullDocumentModel -> questions -> editable DOCX."""
from .model import FullDocumentModel, PageRole, VisualRole  # noqa: F401
from .structure import build_document  # noqa: F401
