# Tooling Notes

Дата проверки: 2026-04-26.

Для текущих материалов дополнительных инструментов ставить не нужно. С уже
скачанными `PDF`, `DOCX`, `XLSX` и `HTML` можно работать надежно обычными
средствами извлечения текста и OpenXML-разбором.

## Что Уже Достаточно

- `pdftotext`, `pdfinfo`, `pdftoppm` - извлечение текста, проверка количества
  страниц, размера страниц, PDF-метаданных и рендер страниц.
- `pandoc` - быстрый просмотр `DOCX` как plain text/Markdown.
- `tesseract` - OCR для сканов без текстового слоя.
- `unzip` и OpenXML - точечная проверка структуры `DOCX`/`XLSX`.

## Что Может Улучшить Качество Позже

- `qpdf` - проверка структуры PDF, диагностика поврежденных PDF, низкоуровневый
  осмотр объектов.
- `mutool` из MuPDF - быстрый рендер и низкоуровневая инспекция PDF.
- `LibreOffice`/`soffice` - headless-конвертация и визуальная проверка офисных
  документов, если понадобится сравнивать верстку `DOCX`/`XLSX`.

Эти инструменты не стоит добавлять в Docker-сборщик диплома заранее. Они нужны
для отдельного будущего режима нормоконтроля/аудита PDF, а не для компиляции
LaTeX-шаблона.

## Источники По Инструментам

- Poppler `pdfinfo` manpage:
  `https://manpages.debian.org/bookworm/poppler-utils/pdfinfo.1.en.html`
- Tesseract documentation:
  `https://tesseract-ocr.github.io/`
- Pandoc User's Guide:
  `https://pandoc.org/MANUAL.html`
- QPDF manual:
  `https://qpdf.readthedocs.io/_/downloads/en/latest/pdf/`
- MuPDF documentation:
  `https://mupdf.readthedocs.io/`
