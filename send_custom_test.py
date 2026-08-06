import os
import json
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

import generator
import sender
import db

def generate_sample_pdf(pdf_path="resume.pdf"):
    """
    Generates a professional sample resume PDF for testing attachments.
    """
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=4
    )
    
    sub_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569'),
        spaceAfter=12
    )

    heading_style = ParagraphStyle(
        'SectionHead',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0284C7'),
        spaceBefore=10,
        spaceAfter=6
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=4
    )

    story = []
    story.append(Paragraph("SHUBRANSHU SHEKHAR", title_style))
    story.append(Paragraph("Senior Software Engineer | Backend &amp; Cloud Systems<br/>Email: shubranshu@example.com | LinkedIn: linkedin.com/in/shubranshu", sub_style))
    
    story.append(Paragraph("SUMMARY", heading_style))
    story.append(Paragraph("Software Engineer with 3+ years of experience designing and scaling distributed microservices, REST APIs, and cloud infrastructure on AWS. Strong track record of improving system latency, optimizing databases, and deploying fault-tolerant architectures.", body_style))
    
    story.append(Spacer(1, 8))
    story.append(Paragraph("KEY HIGHLIGHTS &amp; ACHIEVEMENTS", heading_style))
    story.append(Paragraph("• <b>High-Throughput Services:</b> Led development of a microservice handling 10,000+ requests/sec, reducing latency by 40%.", body_style))
    story.append(Paragraph("• <b>Authentication Engine:</b> Architected and deployed multi-tenant user authentication across 3 production products.", body_style))
    story.append(Paragraph("• <b>Cloud &amp; Infrastructure:</b> Managed AWS deployments (ECS, RDS, Lambda, S3) with CI/CD automated pipelines.", body_style))
    
    story.append(Spacer(1, 8))
    story.append(Paragraph("TECHNICAL SKILLS", heading_style))
    story.append(Paragraph("<b>Languages:</b> Python, JavaScript, TypeScript, SQL<br/><b>Frameworks &amp; Tools:</b> Node.js, Next.js, FastAPI, Docker, Git, Redis<br/><b>Cloud Platform:</b> AWS (ECS, RDS, S3, CloudWatch, Lambda)", body_style))
    
    doc.build(story)
    print(f"✓ Generated test resume PDF at: {os.path.abspath(pdf_path)}")

def main():
    load_dotenv()
    print("==================================================")
    print("    PITCHDOCK OUTREACH TEST: SEND 2 TEST EMAILS    ")
    print("==================================================")
    
    # Generate test PDF resume
    pdf_path = "resume.pdf"
    generate_sample_pdf(pdf_path)
    
    # Test Recipient Email Addresses
    recipients = [
        {"email": "shubranshugudsol@gmail.com", "name": "Shubranshu (Gudsol)", "company": "Gudsol Tech"},
        {"email": "shubranshumishra28092002@gmail.com", "name": "Shubranshu Mishra", "company": "Tech Innovations"}
    ]
    
    # Candidate profile data for Gemini AI synthesis
    candidate_profile = {
        "full_name": "Shubranshu Shekhar",
        "phone_number": "+91 98765 43210",
        "linkedin_profile": "https://linkedin.com/in/shubranshushekhar",
        "current_designation": "Software Engineer",
        "experience_years": "3+",
        "industry_domain": "Backend Systems & Cloud Infrastructure",
        "target_role": "Senior Software Engineer",
        "achievements": [
            "Engineered high-throughput microservices handling 10k+ req/sec, slashing API response latency by 40%.",
            "Built and scaled multi-tenant OAuth and JWT authentication systems across enterprise applications.",
            "Optimized PostgreSQL database query execution plans, boosting query performance by 65%."
        ]
    }
    
    client = generator.get_gemini_client()
    
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    print(f"\nOutbound SMTP Sender Account: {sender_email}")
    if not sender_email or not sender_password:
        print("❌ Error: SENDER_EMAIL or SENDER_PASSWORD not configured in .env!")
        return

    # Update or insert a dummy user profile in outreach.db to use these SMTP credentials
    db.init_db()
    conn = db.get_connection()
    c = conn.cursor()
    from datetime import datetime
    now_str = datetime.now().isoformat()
    c.execute("""
        INSERT OR REPLACE INTO users (id, email, password_hash, created_at, full_name, sender_email, sender_password, sending_channel, smtp_server, smtp_port)
        VALUES (1, 'test@pitchdock.xyz', 'hash', ?, 'Shubranshu Shekhar', ?, ?, 'smtp', 'smtp.gmail.com', '587')
    """, (now_str, sender_email, sender_password))
    conn.commit()
    conn.close()

    results = []

    for idx, target in enumerate(recipients, start=1):
        print(f"\n--------------------------------------------------")
        print(f"[{idx}/2] Generating AI Tailored Pitch for: {target['email']}")
        print(f"Target Name: {target['name']} | Company: {target['company']}")
        
        contact_info = {
            "name": target["name"],
            "title": "Engineering Lead / Recruiter",
            "company": target["company"],
            "category": "MNC Product"
        }
        
        # Generate tailored email using Gemini AI
        try:
            subject, body = generator.generate_email_draft(contact_info, candidate_profile, client=client)
        except Exception as e:
            print(f"⚠️ Gemini AI generation failed: {e}. Falling back to default template.")
            subject = f"Exploring Senior Software Engineer opportunities - {candidate_profile['full_name']}"
            body = f"Hi {target['name']},\n\nI am a Software Engineer with 3+ years experience in backend and cloud infrastructure.\n\nKey highlights:\n- {candidate_profile['achievements'][0]}\n- {candidate_profile['achievements'][1]}\n\nMy resume is attached.\n\nBest regards,\n{candidate_profile['full_name']}"

        print(f"\n📧 Generated Subject: {subject}")
        print("---------------- Body Preview ----------------")
        print(body[:250] + "..." if len(body) > 250 else body)
        print("----------------------------------------------")

        print(f"\n🚀 Sending email to {target['email']} (with resume.pdf attached)...")
        
        success, err = sender.send_single_email(
            to_email=target["email"],
            subject=subject,
            body=body,
            user_id=1,
            attachment_path=pdf_path
        )
        
        if success:
            print(f"✅ SUCCESS: Email successfully delivered to {target['email']}!")
            results.append({"email": target["email"], "status": "SUCCESS", "subject": subject})
        else:
            print(f"❌ FAILURE delivering to {target['email']}: {err}")
            results.append({"email": target["email"], "status": "FAILED", "error": err})

    print("\n==================================================")
    print("               FINAL EXECUTION SUMMARY            ")
    print("==================================================")
    for r in results:
        status_icon = "✅" if r["status"] == "SUCCESS" else "❌"
        print(f"{status_icon} {r['email']}: {r['status']}")

if __name__ == "__main__":
    main()
