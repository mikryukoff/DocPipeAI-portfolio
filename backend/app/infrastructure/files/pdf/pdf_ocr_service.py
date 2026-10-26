class PDFOCRService:

    def __init__(self, poppler_path: str):
        self.poppler_path = poppler_path

    def apply_ocr(self, input_pdf: str, output_pdf: str) -> None:
        import ocrmypdf

        ocrmypdf.ocr(
            input_file=input_pdf,
            output_file=output_pdf,
            language="rus+eng",
            deskew=True,
            force_ocr=True,
        )
