import os
import unittest
import sqlite3
import json
from email.mime.multipart import MIMEMultipart

import db
import generator
import sender

class TestOutreachAutomator(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_outreach.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        db.init_db(self.test_db)
        
    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
            
    def test_database_creation_and_operations(self):
        # 1. Verify table initialized
        conn = db.get_connection(self.test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contacts'")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()
        
        # 2. Insert dummy contact
        conn = db.get_connection(self.test_db)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO contacts (name, title, company, category, email, status)
        VALUES ('Test User', 'HR Lead', 'Test Corp', 'MNC', 'test@test.com', 'pending')
        """)
        conn.commit()
        conn.close()
        
        # 3. Retrieve and verify
        pending = db.get_contacts_by_status("pending", db_path=self.test_db)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["name"], "Test User")
        self.assertEqual(pending[0]["email"], "test@test.com")
        
        # 4. Update draft
        db.update_contact_draft(
            pending[0]["id"], 
            "Subject Text", 
            "Body Text", 
            status="drafted", 
            db_path=self.test_db
        )
        drafted = db.get_contacts_by_status("drafted", db_path=self.test_db)
        self.assertEqual(len(drafted), 1)
        self.assertEqual(drafted[0]["personalized_subject"], "Subject Text")
        self.assertEqual(drafted[0]["personalized_body"], "Body Text")
        
        # 5. Reset status
        count = db.reset_status("drafted", "pending", db_path=self.test_db)
        self.assertEqual(count, 1)
        pending_reset = db.get_contacts_by_status("pending", db_path=self.test_db)
        self.assertEqual(len(pending_reset), 1)

    def test_candidate_profile_loading(self):
        # Write dummy config if not present, then read
        profile_path = "test_profile.json"
        profile_data = {
            "full_name": "Test Name",
            "phone_number": "12345",
            "linkedin_profile": "linkedin.com",
            "current_designation": "Dev",
            "experience_years": "5",
            "industry_domain": "Tech",
            "target_role": "Lead",
            "achievements": ["Ach1", "Ach2"],
            "resume_pdf_path": "resume.pdf"
        }
        with open(profile_path, "w") as f:
            json.dump(profile_data, f)
            
        try:
            profile = generator.load_candidate_profile(profile_path)
            self.assertEqual(profile["full_name"], "Test Name")
            self.assertEqual(len(profile["achievements"]), 2)
        finally:
            if os.path.exists(profile_path):
                os.remove(profile_path)

    def test_smtp_builder_validation(self):
        # We verify that send_single_email gracefully rejects invalid config or missing file
        success, err = sender.send_single_email(
            to_email="test@test.com",
            subject="Test Subject",
            body="Test Body",
            attachment_path="nonexistent_resume_file.pdf"
        )
        self.assertFalse(success)
        self.assertIn("Attachment file not found", err)

    def test_add_manual_contacts(self):
        # 1. Add AI mode contacts (pending)
        contacts = [
            {"email": "ai1@test.com", "name": "AI Name 1", "company": "Co1"},
            {"email": "ai2@test.com", "name": "AI Name 2", "company": "Co2"},
            {"email": "invalid-email", "name": "Invalid"}, # should be ignored
        ]
        res = db.add_manual_contacts(contacts, mode="ai", db_path=self.test_db)
        self.assertEqual(res["added"], 2)
        self.assertEqual(res["invalid_or_empty"], 1)
        
        pending = db.get_contacts_by_status("pending", db_path=self.test_db)
        self.assertEqual(len(pending), 2)
        
        # 2. Add template mode contacts (approved directly)
        tpl_contacts = [
            {"email": "tpl1@test.com", "name": "John Doe", "company": "Apple"},
            {"email": "ai1@test.com", "name": "Duplicate", "company": "Co1"} # duplicate email, should be ignored
        ]
        
        # Write dummy candidate profile
        profile_path = "candidate_profile.json"
        has_original_profile = os.path.exists(profile_path)
        original_profile = None
        if has_original_profile:
            with open(profile_path, "r") as f:
                original_profile = f.read()
                
        profile_data = {
            "full_name": "Applicant Name",
            "phone_number": "999",
            "linkedin_profile": "linkedin.com/in/applicant",
            "current_designation": "Software Eng",
            "experience_years": "2",
            "industry_domain": "Tech",
            "target_role": "SWE",
            "achievements": ["Ach1"],
            "resume_pdf_path": "resume.pdf"
        }
        with open(profile_path, "w") as f:
            json.dump(profile_data, f)
        db.update_user_profile(1, profile_data, db_path=self.test_db)
            
        try:
            res_tpl = db.add_manual_contacts(
                tpl_contacts,
                mode="template",
                template_subject="Exploring {Role} opportunities at {Company}",
                template_body="Hi {first_name}, I am {my_name}",
                auto_approve=True,
                db_path=self.test_db
            )
            self.assertEqual(res_tpl["added"], 1)
            self.assertEqual(res_tpl["ignored_duplicates"], 1)
            
            approved = db.get_contacts_by_status("approved", db_path=self.test_db)
            self.assertEqual(len(approved), 1)
            self.assertEqual(approved[0]["personalized_subject"], "Exploring SWE opportunities at Apple")
            self.assertEqual(approved[0]["personalized_body"], "Hi John, I am Applicant Name")
        finally:
            if has_original_profile and original_profile is not None:
                with open(profile_path, "w") as f:
                    f.write(original_profile)
            elif os.path.exists(profile_path):
                os.remove(profile_path)

    def test_billing_and_resume_caching(self):
        # 1. Verify default billing info is 'free'
        info = db.get_billing_info(db_path=self.test_db)
        self.assertEqual(info["plan_tier"], "free")
        self.assertEqual(info["resume_rewrites_count"], 0)
        self.assertEqual(info["emails_sent_today"], 0)

        # 2. Update billing plan to premium
        db.update_billing_plan("premium", db_path=self.test_db)
        info_premium = db.get_billing_info(db_path=self.test_db)
        self.assertEqual(info_premium["plan_tier"], "premium")

        # 3. Test caching resume customizer
        company = "google"
        content = "Fabulous custom resume accomplishments for Google"
        db.save_cached_resume(company, content, db_path=self.test_db)

        # Retrieve and verify it is from cache
        cached = db.get_cached_resume(company, db_path=self.test_db)
        self.assertEqual(cached, content)

        # Make sure case-insensitive matching works
        cached_case = db.get_cached_resume("Google", db_path=self.test_db)
        self.assertEqual(cached_case, content)

        # 4. Increment usage metrics and verify
        db.increment_resume_rewrites(db_path=self.test_db)
        db.increment_emails_sent(3, db_path=self.test_db)
        info_updated = db.get_billing_info(db_path=self.test_db)
        self.assertEqual(info_updated["resume_rewrites_count"], 1)
        self.assertEqual(info_updated["emails_sent_today"], 3)

    def test_oauth_db_operations(self):
        # 1. Verify initially no tokens exist
        google_tokens = db.get_oauth_tokens("google", db_path=self.test_db)
        self.assertIsNone(google_tokens)
        
        # 2. Save tokens and verify
        db.save_oauth_tokens(
            provider="google",
            email="user@gmail.com",
            access_token="access123",
            refresh_token="refresh456",
            expires_at="2026-07-17T19:30:00",
            db_path=self.test_db
        )
        tokens = db.get_oauth_tokens("google", db_path=self.test_db)
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens["email"], "user@gmail.com")
        self.assertEqual(tokens["access_token"], "access123")
        self.assertEqual(tokens["refresh_token"], "refresh456")
        self.assertEqual(tokens["expires_at"], "2026-07-17T19:30:00")
        
        # 3. Delete tokens and verify
        db.delete_oauth_tokens("google", db_path=self.test_db)
        tokens_after_delete = db.get_oauth_tokens("google", db_path=self.test_db)
        self.assertIsNone(tokens_after_delete)

    def test_sender_dispatch_routing(self):
        # Save original env
        original_channel = os.environ.get("SENDING_CHANNEL")
        
        try:
            # 1. Test google channel with no tokens
            os.environ["SENDING_CHANNEL"] = "google"
            success, err = sender.send_single_email(
                to_email="recruiter@apple.com",
                subject="Subject",
                body="Body",
                db_path=self.test_db
            )
            self.assertFalse(success)
            self.assertIn("Google Account is not connected", err)
            
            # 2. Test google channel with token but refresh fail (expired token)
            db.save_oauth_tokens(
                provider="google",
                email="user@gmail.com",
                access_token="access",
                refresh_token="refresh",
                expires_at="2020-01-01T00:00:00", # Expired
                db_path=self.test_db
            )
            
            success, err = sender.send_single_email(
                to_email="recruiter@apple.com",
                subject="Subject",
                body="Body",
                db_path=self.test_db
            )
            self.assertFalse(success)
            # Should fail trying to refresh (client keys not set / invalid URL)
            self.assertIn("Failed to refresh Google OAuth token", err)
            
        finally:
            if original_channel is not None:
                os.environ["SENDING_CHANNEL"] = original_channel
            elif "SENDING_CHANNEL" in os.environ:
                del os.environ["SENDING_CHANNEL"]

    def test_import_from_pdf(self):
        # Verify importing from PDF if HR_Contact_List.pdf exists
        if os.path.exists("HR_Contact_List.pdf"):
            res = db.import_from_pdf("HR_Contact_List.pdf", user_id=1, seed_all_users=False, db_path=self.test_db)
            self.assertGreater(res["added"], 0)
            self.assertEqual(res["ignored_duplicates"], 0)
            
            # Verify double import ignores duplicates
            res2 = db.import_from_pdf("HR_Contact_List.pdf", user_id=1, seed_all_users=False, db_path=self.test_db)
            self.assertEqual(res2["added"], 0)
            self.assertEqual(res2["ignored_duplicates"], res["added"])

if __name__ == "__main__":
    unittest.main()

