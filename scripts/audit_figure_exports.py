"""File-level scientific figure QA, complementing manual PNG inspection."""
import hashlib,json
from pathlib import Path
import fitz
from PIL import Image

root=Path('figures');report=[]
pngs=sorted(root.glob('*.png'));assert len(pngs)==6
for png in pngs:
 pdf=png.with_suffix('.pdf');svg=png.with_suffix('.svg');assert pdf.is_file() and svg.is_file()
 with Image.open(png) as image:
  assert image.width>1000 and image.height>600
  dpi=image.info.get('dpi');assert dpi and min(dpi)>299
  size=list(image.size)
 with fitz.open(pdf) as doc:
  assert len(doc)==1
  page=doc[0];fonts=page.get_fonts(full=True)
  assert fonts and all('Type3' not in str(font) for font in fonts)
  assert all(doc.extract_font(font[0])[3] for font in fonts),'Unembedded font'
  assert not page.get_images(full=True),'Unexpected raster image in vector plot'
  for block in page.get_text('blocks'):
   rect=fitz.Rect(block[:4]);assert rect.x0>=-1 and rect.y0>=-1 and rect.x1<=page.rect.width+1 and rect.y1<=page.rect.height+1
  dimensions=[page.rect.width,page.rect.height]
  names=[font[3] for font in fonts]
 text=svg.read_text(encoding='utf-8');assert '<text' in text,'SVG text converted to paths'
 report.append({'base':png.stem,'png_pixels':size,'png_dpi':list(dpi),'pdf_pages':1,'pdf_size_pt':dimensions,
                'pdf_fonts':names,'fonts_embedded':True,'no_type3':True,'no_raster_images_in_pdf':True,'text_within_pdf_page':True,
                'svg_has_editable_text':True,'sha256':{p.suffix:hashlib.sha256(p.read_bytes()).hexdigest() for p in [png,pdf,svg]}})
payload={'file_checks_passed':True,'figure_count':len(report),'manual_visual_qa':'All six final PNGs viewed; primary tick collision and mixed-denominator comparison scale repaired before release.',
         'scope':'This QA verifies exports/layout properties, not statistical validity or study completion.','figures':report}
Path('provenance/FIGURE_QA.json').write_text(json.dumps(payload,indent=2),encoding='utf-8');print(json.dumps({'passed':True,'figures':len(report),'no_type3':True,'vector_pdfs':True}))
