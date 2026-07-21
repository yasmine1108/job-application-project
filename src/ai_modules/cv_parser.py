from src.models import ParsedDocument, ParsedTable
import pymupdf4llm
from pathlib import Path
import pymupdf
import os
import re


class CVParser:
    def __init__(self, cv_path):
        self.cv_path = Path("data/cv/",cv_path)
        self.filename = ".".join(cv_path.split(".")[:-1])
        tesseract_default_path = r"C:\Program Files\Tesseract-OCR\tessdata"
        
        if os.path.exists(tesseract_default_path):
            os.environ["TESSDATA_PREFIX"] = tesseract_default_path
        else:
            print("[Attention] Le dossier Tesseract-OCR est introuvable au chemin par défaut.")
        
        
    def extract_text(self):
        markdown_text = ""
        extracted_links = []
        extracted_tables = []
        if not self.cv_path.exists():
            raise FileNotFoundError(f"Le CV introuvable au chemin : {self.cv_path}")
        
        ext = self.cv_path.suffix.lower()
        print(ext)
        if ext in [".png", ".jpg", ".jpeg"]:
            markdown_text = self._ocr_pure_image()

        else:
            # Si c'est un PDF, pymupdf4llm peut travailler avec blur
            markdown_text = self._extract_pdf()
            extracted_links = self._extract_links()
            extracted_tables = self._extract_tables()

        Path("data/cache/",self.filename+".md").write_bytes(markdown_text.encode())
        print(extracted_links)
        return ParsedDocument(
            file_name=self.cv_path,
            file_type=ext,
            content=markdown_text,
            links=extracted_links,
            tables=extracted_tables
        )
        
    
    def _ocr_pure_image(self):
        print("ocr for pure image")
        doc = pymupdf.open()
        pix = pymupdf.Pixmap(self.cv_path)
        # Supprime le canal alpha (transparence) obligatoire pour l'OCR
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
            
        page = doc.new_page(width=pix.width, height=pix.height)
        page.insert_image(page.rect, pixmap=pix)
            
            # Convert the in-memory document directly to Markdown using forced OCR
        markdown_text = pymupdf4llm.to_markdown(
                doc=doc, 
                force_ocr=True, 
                ocr_language="fra+eng"
            )
        
        return markdown_text
    
    def _extract_pdf(self):
        print("pdf method worked")
        md_text = pymupdf4llm.to_markdown(doc = self.cv_path,ocr_language="fra+eng")
        return md_text
    
    def _extract_links(self):
        doc = pymupdf.open(self.cv_path)

        links = []

        for page in doc:
            for link in page.get_links():
                uri = link.get("uri")

                if uri:
                    links.append(uri)

        return links

    def _extract_tables(self):
        doc = pymupdf.open(self.cv_path)
        parsed_tables = []
        for page_num, page in enumerate(doc):
            tables = list(page.find_tables(strategy="lines_strict").tables)

            if not tables:
                # No ruled lines found — fall back to text-position based detection,
                # which catches borderless/invisible-grid layouts (common in CV templates)
                tables = list(page.find_tables(strategy="text").tables)

            for table in tables:
                rows = table.extract()
                if rows and any(any(cell for cell in row) for row in rows):
                    parsed_tables.append(
                        ParsedTable(
                            page=page_num,
                            rows=self._clean_table_rows(rows)
                        )
                    )
        return parsed_tables

    def _clean_table_rows(self, rows):
        cleaned_rows = []
        for row in rows:
            cleaned_row = []
            for cell in row:
                if cell:
                    cell = cell.replace("<br>", " ").replace("<br/>", " ")
                    cell = re.sub(r"\*\*|_", "", cell)   # strip stray markdown emphasis
                    cell = re.sub(r"\s+", " ", cell).strip()
                cleaned_row.append(cell)
            cleaned_rows.append(cleaned_row)
        return cleaned_rows
    
    
