import re
from html import escape
from io import BytesIO

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def export_markdown(title, content):
    return ("# " + title + "\n\n" + content + "\n").encode("utf-8")


def export_pdf(title, content):
    # Pure Python PDF export avoids a system-wide pandoc/GTK installation.
    # Escape all input: external Markdown images/HTML are never fetched.
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    for name in ("Normal", "Heading1", "Heading2"):
        styles[name].fontName = "STSong-Light"
        styles[name].wordWrap = "CJK"
        styles[name].leading = 17 if name == "Normal" else 24
    story = [Paragraph(escape(title), styles["Heading1"]), Spacer(1, 16)]
    for line in content.splitlines():
        if not line.strip():
            story.append(Spacer(1, 8))
            continue
        heading = line.startswith("#")
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = escape(line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        story.append(Paragraph(line, styles["Heading2" if heading else "Normal"]))
    output = BytesIO()
    SimpleDocTemplate(output, title=title).build(story)
    return output.getvalue()

