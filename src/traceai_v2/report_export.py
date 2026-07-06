from __future__ import annotations

import csv
from io import BytesIO, StringIO
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

def export_csv(matrix: dict, project_name: str) -> StringIO:
    """Export the traceability matrix as CSV."""
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Requirement Key",
        "Requirement Text",
        "Match Status",
        "Best Match File",
        "Best Match Score",
        "Explanation"
    ])
    
    for row in matrix.get("rows", []):
        best_link = row["links"][0] if row.get("links") else None
        file_path = best_link["file_path"] if best_link else "N/A"
        score = f"{best_link['score']:.4f}" if best_link else "0.0000"
        explanation = best_link["explanation"] if best_link else ""
        
        writer.writerow([
            row.get("req_key", ""),
            row.get("text", ""),
            row.get("best_label", "Missing"),
            file_path,
            score,
            explanation
        ])
        
    output.seek(0)
    return output

def export_pdf(matrix: dict, project_name: str, run_details: dict) -> BytesIO:
    """Export a beautiful, formatted PDF report of the traceability matrix."""
    buffer = BytesIO()
    
    # Page layout
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    # Custom colors
    primary_color = colors.HexColor("#0f172a") # Sleek slate/dark mode primary
    accent_color = colors.HexColor("#3b82f6") # Bright brand accent
    text_muted = colors.HexColor("#64748b")
    border_color = colors.HexColor("#e2e8f0")
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=primary_color,
        spaceAfter=15
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=text_muted,
        spaceAfter=20
    )
    
    section_heading = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=primary_color,
        spaceBefore=15,
        spaceAfter=10
    )
    
    cell_text = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1e293b")
    )
    
    cell_text_bold = ParagraphStyle(
        'CellTextBold',
        parent=cell_text,
        fontName='Helvetica-Bold'
    )
    
    cell_header = ParagraphStyle(
        'CellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.white
    )

    story = []
    
    # Title & Header
    story.append(Paragraph(f"TraceAI Traceability Report", title_style))
    
    # Run Info Metadata
    date_str = datetime.fromisoformat(run_details["created_at"]).strftime("%B %d, %Y at %I:%M %p")
    commit_sha = run_details.get("commit_sha", "")
    commit_txt = f" (Commit: {commit_sha[:7]})" if commit_sha else ""
    story.append(Paragraph(
        f"<b>Project:</b> {project_name} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"<b>Run Date:</b> {date_str}{commit_txt}",
        subtitle_style
    ))
    
    # Summary Cards Table
    stats_data = [
        [
            Paragraph("<b>Requirements</b>", cell_text_bold),
            Paragraph("<b>Code Units</b>", cell_text_bold),
            Paragraph("<b>Trace Links</b>", cell_text_bold),
            Paragraph("<b>Completion</b>", cell_text_bold),
        ],
        [
            Paragraph(str(matrix.get("requirements_total", 0)), cell_text),
            Paragraph(str(run_details.get("code_units_count", 0)), cell_text),
            Paragraph(str(matrix.get("requirements_linked", 0)), cell_text),
            Paragraph(f"{matrix.get('completion_percentage', 0.0):.1f}%", cell_text),
        ]
    ]
    
    stats_table = Table(stats_data, colWidths=[130, 130, 130, 130])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TEXTCOLOR', (0, 0), (-1, 0), primary_color),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('BOX', (0, 0), (-1, -1), 1, border_color),
    ]))
    
    story.append(stats_table)
    story.append(Spacer(1, 20))
    
    # Traceability Matrix Table Section
    story.append(Paragraph("Requirements Traceability Matrix", section_heading))
    
    # Table headers
    matrix_headers = [
        Paragraph("Req Key", cell_header),
        Paragraph("Requirement Text", cell_header),
        Paragraph("Status", cell_header),
        Paragraph("Best Match", cell_header),
        Paragraph("Score", cell_header),
    ]
    
    table_data = [matrix_headers]
    
    # Populate rows
    for row in matrix.get("rows", []):
        best_link = row["links"][0] if row.get("links") else None
        
        status_label = row.get("best_label", "Missing")
        # Color match status
        if status_label == "Implemented":
            status_html = '<font color="#10b981"><b>Implemented</b></font>'
        elif status_label == "Partial":
            status_html = '<font color="#f59e0b"><b>Partial</b></font>'
        else:
            status_html = '<font color="#ef4444"><b>Missing</b></font>'
            
        file_path = best_link["file_path"] if best_link else "N/A"
        score = f"{best_link['score']:.3f}" if best_link else "–"
        
        table_data.append([
            Paragraph(row.get("req_key", ""), cell_text_bold),
            Paragraph(row.get("text", ""), cell_text),
            Paragraph(status_html, cell_text),
            Paragraph(file_path, cell_text),
            Paragraph(score, cell_text),
        ])
        
    # Table column widths (Total width: 532 points)
    matrix_table = Table(table_data, colWidths=[55, 187, 75, 175, 40])
    matrix_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    
    story.append(matrix_table)
    
    # Build Document
    doc.build(story)
    buffer.seek(0)
    return buffer
