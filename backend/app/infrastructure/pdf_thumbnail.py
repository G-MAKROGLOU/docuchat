"""PageRenderer adapter with PyMuPDF."""

import pymupdf


class PyMuPdfPageRenderer:
    def render_first_page(self, pdf: bytes, width: int) -> bytes:
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            page = doc[0]
            scale = width / page.rect.width
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            png: bytes = pixmap.tobytes("png")
            return png
