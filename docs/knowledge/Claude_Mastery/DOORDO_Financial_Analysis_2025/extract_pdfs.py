"""キーページを抽出"""
import pdfplumber

key_pages = [5, 7, 23, 24, 25, 32, 33, 34, 35, 36, 37, 62, 63, 64, 70, 71, 72, 73, 74]  # 0-indexed

with pdfplumber.open('R7.12月度　決算書一式　DOORDO.pdf') as pdf:
    total = len(pdf.pages)
    lines = [f'=== Tax Return key pages (total {total}) ===', '']
    for i in key_pages:
        if i < total:
            text = pdf.pages[i].extract_text() or ''
            lines.append(f'--- Page {i+1} ---')
            lines.append(text)
            lines.append('')

with open('tax_key_pages.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('done')
