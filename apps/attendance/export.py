import csv
import io
from django.http import HttpResponse
from django.utils.timezone import localtime
from django.utils import timezone
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import openpyxl

def generate_csv_export(queryset, filename="attendance_report.csv"):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Student Name', 'ID/Roll', 'Section', 'Date', 'Time', 'Status', 'Method'])

    for record in queryset:
        start_time = localtime(record.session.started_at)
        writer.writerow([
            record.student.full_name,
            record.student.student_id,
            record.session.section.course_code,
            start_time.strftime('%Y-%m-%d'),
            start_time.strftime('%H:%M:%S'),
            record.status,
            record.verification_method
        ])

    return response

def generate_excel_export(queryset, filename="attendance_report.xlsx"):
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Attendance'

    headers = ['Student Name', 'ID/Roll', 'Section', 'Date', 'Time', 'Status', 'Method']
    sheet.append(headers)

    for record in queryset:
        start_time = localtime(record.session.started_at)
        sheet.append([
            record.student.full_name,
            record.student.student_id,
            record.session.section.course_code,
            start_time.strftime('%Y-%m-%d'),
            start_time.strftime('%H:%M:%S'),
            record.status,
            record.verification_method
        ])

    workbook.save(response)
    return response

def generate_pdf_export(queryset, filename="attendance_report.pdf"):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    # Using landscape to fit more data beautifully
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import Spacer
    from reportlab.lib.styles import ParagraphStyle

    doc = SimpleDocTemplate(response, pagesize=landscape(letter),
                            rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    styles = getSampleStyleSheet()
    
    # Custom Title Style
    title_style = ParagraphStyle(
        name='CustomTitle', 
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        spaceAfter=15,
        textColor=colors.HexColor("#1e3a8a"),
        alignment=1 # Center
    )
    
    # Custom Subtitle Style
    subtitle_style = ParagraphStyle(
        name='Subtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor("#6b7280"),
        alignment=1,
        spaceAfter=20
    )

    elements.append(Paragraph("SmartAttend – Official Attendance Report", title_style))
    
    gen_time = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"Generated on: {gen_time} | Total Records: {queryset.count()}", subtitle_style))
    elements.append(Spacer(1, 12))

    # Define table headers
    data = [['Date', 'Time', 'Student Name', 'Current Roll', 'Course', 'Class Section', 'Status']]
    
    for record in queryset:
        start_time = localtime(record.session.started_at)
        # Handle cases where student_id is empty or missing, fallback to roll number
        roll_no = record.student.university_roll_number or record.student.student_id or 'N/A'
        
        data.append([
            start_time.strftime('%Y-%m-%d'),
            start_time.strftime('%H:%M:%S'),
            record.student.full_name,
            roll_no,
            record.session.section.course_code,
            record.session.section.section_identifier,
            record.status
        ])

    # Dynamic Column Widths
    col_widths = [1.1*inch, 1.0*inch, 2.3*inch, 1.4*inch, 1.2*inch, 1.2*inch, 1.0*inch]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    
    style = TableStyle([
        # Header Style
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        
        # Body Styles
        ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        
        # Grid/Border Styles
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#9ca3af")),
    ])
    
    # Striped rows effect
    for i in range(1, len(data)):
        bg_color = colors.HexColor("#f8fafc") if i % 2 == 0 else colors.white
        style.add('BACKGROUND', (0, i), (-1, i), bg_color)
        
        # Highlight Status
        status_val = data[i][-1]
        text_color = colors.black
        if status_val == 'PRESENT':
            text_color = colors.HexColor("#166534") # dark green
        elif status_val == 'ABSENT':
            text_color = colors.HexColor("#991b1b") # dark red
        elif status_val == 'EXCUSED':
            text_color = colors.HexColor("#854d0e") # dark yellow/brown
        elif status_val == 'LATE':
            text_color = colors.HexColor("#9a3412") # orange/red
            
        style.add('TEXTCOLOR', (-1, i), (-1, i), text_color)
        style.add('FONTNAME', (-1, i), (-1, i), 'Helvetica-Bold')

    table.setStyle(style)
    elements.append(table)
    
    # Build Document
    doc.build(elements)
    return response
