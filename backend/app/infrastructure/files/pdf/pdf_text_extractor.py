import pdfplumber
from backend.app.infrastructure.files.pdf.models import PDFTextPage
from loguru import logger


class PDFTextExtractor:

    def extract(self, pdf_path: str) -> list[PDFTextPage]:
        pages = []
        logger.info("Start text extraction from PDF. path={}", pdf_path)

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if not text:
                    continue

                pages.append(
                    PDFTextPage(
                        page=page_num,
                        text=text,
                    )
                )

        logger.info("Text extraction completed. path={} pages_with_text={}", pdf_path, len(pages))
        return pages
