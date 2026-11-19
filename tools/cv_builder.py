from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm
from xml.sax.saxutils import escape

def build_cv(data, output_path):
    styles = getSampleStyleSheet()
    title = ParagraphStyle("CVTitle", parent=styles["Title"], textColor=colors.HexColor("#17365D"), spaceAfter=8)
    heading = ParagraphStyle("CVHeading", parent=styles["Heading2"], textColor=colors.HexColor("#17365D"), spaceBefore=10, spaceAfter=4)
    body = styles["BodyText"]
    story = [Paragraph(escape(data["full_name"]), title)]
    contact = " | ".join(x for x in [data.get("email"), data.get("phone"), data.get("location")] if x)
    if contact: story.append(Paragraph(escape(contact), body))
    sections = [("Professional Summary","summary"),("Education","education"),("Work Experience","experience"),("Skills","skills")]
    for label, key in sections:
        value = data.get(key, "")
        if value:
            story += [Paragraph(label, heading), Paragraph(escape(value).replace("\n","<br/>"), body), Spacer(1, 4*mm)]
    SimpleDocTemplate(output_path, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm).build(story)
