-- Solo Worker OS — Seed data for demo video (English)
-- Run AFTER schema.sql + poc_schema.sql + auth-migration.sql in Supabase SQL editor.
-- Scenario: Independent full-stack developer managing 6 clients, with knowledge base.

truncate agent_actions, messages, knowledge_docs, notifications, workflow_steps, projects restart identity cascade;

-- ──────────────────────────────────────────────────────────
-- Projects
-- ──────────────────────────────────────────────────────────
insert into projects (id, client_name, project_type, budget, currency, deadline, status, casper_address, created_at, updated_at) values
  ('a1000000-0000-0000-0000-000000000001', 'Sarah Chen', 'SaaS Dashboard UI Kit', 4800, 'USD', '2026-07-20', 'invoiced', '0106ca7c39cd272dbf21a86eeb3b36b7c26e2e9b94af64292419f7862936bca2', '2026-06-01 09:00:00+00', '2026-07-10 14:00:00+00'),
  ('a1000000-0000-0000-0000-000000000002', 'Marcus Rivera', 'E-commerce Platform', 15000, 'USD', '2026-08-15', 'active', '0103a1a0e8c5e7b9d2f4a6c8e0b2d4f6a8c0e2b4d6f8a0c2e4b6d8f0a2c4e6b8', '2026-06-20 11:00:00+00', '2026-07-05 09:00:00+00'),
  ('a1000000-0000-0000-0000-000000000003', 'Aiko Tanaka', 'Brand Identity & Website', 6200, 'USD', '2026-06-30', 'paid', '0203a1a0e8c5e7b9d2f4a6c8e0b2d4f6a8c0e2b4d6f8a0c2e4b6d8f0a2c4e6b8d0', '2026-05-15 10:00:00+00', '2026-06-28 16:00:00+00'),
  ('a1000000-0000-0000-0000-000000000004', 'James Okafor', 'Mobile App Backend API', 9000, 'USD', '2026-07-01', 'delivered', '0104b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1', '2026-05-01 14:00:00+00', '2026-06-29 10:00:00+00'),
  ('a1000000-0000-0000-0000-000000000005', 'Elena Volkov', 'Newsletter Platform MVP', 7500, 'USD', '2026-09-01', 'active', NULL, '2026-07-01 09:00:00+00', '2026-07-01 09:00:00+00'),
  ('a1000000-0000-0000-0000-000000000006', 'Raj Patel', 'DeFi Analytics Dashboard', 11000, 'USD', '2026-08-30', 'active', '0105c4d3e2f1a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5', '2026-07-08 08:00:00+00', '2026-07-08 08:00:00+00');

-- ──────────────────────────────────────────────────────────
-- Agent actions
-- ──────────────────────────────────────────────────────────
insert into agent_actions (project_id, action_type, payload, created_at) values
  ('a1000000-0000-0000-0000-000000000001', 'project_created', '{"client":"Sarah Chen","type":"SaaS Dashboard UI Kit","budget":4800,"currency":"USD"}', '2026-06-01 09:01:00+00'),
  ('a1000000-0000-0000-0000-000000000001', 'contract_generated', '{"contract":"# Service Agreement\n\n## Client\nSarah Chen\n\n## Project\nSaaS Dashboard UI Kit\n\n## Scope\n- 12 dashboard screen designs\n- Design system: colors, typography, components\n- Figma file with auto-layout\n- 2 rounds of revisions\n\n## Payment Terms\n- 50% deposit (USD 2,400) upon signing\n- 50% upon final delivery\n\n## Timeline\n- Start: 2026-06-01\n- Delivery: 2026-07-15\n\n## Intellectual Property\nFull ownership transfers upon final payment.\n\n---\n\nSigned: _______________ Date: _______________"}', '2026-06-02 10:30:00+00'),
  ('a1000000-0000-0000-0000-000000000001', 'status_updated', '{"status":"invoiced"}', '2026-07-10 14:00:00+00'),
  ('a1000000-0000-0000-0000-000000000001', 'followup_generated', '{"tone":"polite","days_overdue":8}', '2026-07-18 09:00:00+00'),
  ('a1000000-0000-0000-0000-000000000002', 'project_created', '{"client":"Marcus Rivera","type":"E-commerce Platform","budget":15000,"currency":"USD"}', '2026-06-20 11:01:00+00'),
  ('a1000000-0000-0000-0000-000000000002', 'contract_generated', '{"contract":"# Service Agreement\n\n## Client\nMarcus Rivera\n\n## Project\nE-commerce Platform Development\n\n## Scope\n- Next.js storefront with catalog, cart, checkout\n- Stripe payment integration\n- Admin dashboard\n- Responsive design\n- 3 rounds of revisions\n\n## Payment Terms\n- 30% deposit (USD 4,500)\n- 40% at prototype approval\n- 30% upon final delivery\n\n## Timeline\n- Start: 2026-06-20\n- Delivery: 2026-08-15\n\n---\n\nSigned: _______________ Date: _______________"}', '2026-06-21 09:00:00+00'),
  ('a1000000-0000-0000-0000-000000000003', 'project_created', '{"client":"Aiko Tanaka","type":"Brand Identity & Website","budget":6200,"currency":"USD"}', '2026-05-15 10:01:00+00'),
  ('a1000000-0000-0000-0000-000000000003', 'contract_generated', '{"contract":"# Service Agreement\n\n## Client\nAiko Tanaka\n\n## Project\nBrand Identity & Website\n\n## Scope\n- Logo design (3 concepts, 2 revisions)\n- Brand guidelines\n- 5-page marketing website\n\n## Payment Terms\n- 50% deposit (USD 3,100)\n- 50% upon final delivery\n\n## Timeline\n- Start: 2026-05-15\n- Delivery: 2026-06-15\n\n---\n\nSigned: _______________ Date: _______________"}', '2026-05-16 10:00:00+00'),
  ('a1000000-0000-0000-0000-000000000003', 'status_updated', '{"status":"paid"}', '2026-06-28 16:00:00+00'),
  ('a1000000-0000-0000-0000-000000000004', 'project_created', '{"client":"James Okafor","type":"Mobile App Backend API","budget":9000,"currency":"USD"}', '2026-05-01 14:01:00+00'),
  ('a1000000-0000-0000-0000-000000000004', 'contract_generated', '{"contract":"# Service Agreement\n\n## Client\nJames Okafor\n\n## Project\nMobile App Backend API\n\n## Scope\n- RESTful API (Node.js + Express)\n- PostgreSQL database schema\n- JWT authentication\n- Docker deployment\n- Swagger documentation\n\n## Payment Terms\n- 30% deposit (USD 2,700)\n- 40% at API completion\n- 30% upon final deployment\n\n## Timeline\n- Start: 2026-05-01\n- Delivery: 2026-06-15\n\n---\n\nSigned: _______________ Date: _______________"}', '2026-05-02 10:00:00+00'),
  ('a1000000-0000-0000-0000-000000000004', 'status_updated', '{"status":"delivered"}', '2026-06-29 10:00:00+00'),
  ('a1000000-0000-0000-0000-000000000006', 'project_created', '{"client":"Raj Patel","type":"DeFi Analytics Dashboard","budget":11000,"currency":"USD"}', '2026-07-08 08:01:00+00');

-- ──────────────────────────────────────────────────────────
-- Knowledge base
-- ──────────────────────────────────────────────────────────
insert into knowledge_docs (id, title, content, doc_type, tags, created_at) values
  ('b1000000-0000-0000-0000-000000000001', 'Standard Service Agreement Template', '# Service Agreement Template\n\n## Terms\n- 50% deposit required before work begins\n- Final 50% due upon delivery\n- 2 rounds of revisions included\n- Additional revisions billed at $150/hr\n\n## Cancellation\nEither party may cancel with 7 days notice. Deposit is non-refundable once work has started.\n\n## Intellectual Property\nClient receives full ownership upon final payment. I retain the right to display work in my portfolio.', 'template', '{contract,legal,standard}', '2026-05-01 10:00:00+00'),
  ('b1000000-0000-0000-0000-000000000002', 'Email Template: New Project Inquiry', 'Subject: Re: Project Inquiry — Next Steps\n\nHi [Client Name],\n\nThank you for reaching out! I would love to discuss your project.\n\nTo provide an accurate quote, could you share:\n- Project scope and deliverables\n- Target timeline\n- Budget range\n- Any reference designs or examples you like\n\nI typically respond to inquiries within 24 hours.\n\nBest,\n[Your Name]', 'email', '{template,inquiry,response}', '2026-05-01 10:05:00+00'),
  ('b1000000-0000-0000-0000-000000000003', 'Payment Reminder Templates', '# Payment Reminders\n\n## Friendly (7 days overdue)\nSubject: Quick nudge — Invoice #[NUMBER] for [PROJECT]\n\nHi [Client],\nJust a friendly reminder that invoice #[NUMBER] was due on [DATE]. No rush — let me know if you have any questions.\n\n## Firm (14 days overdue)\nSubject: Overdue Invoice #[NUMBER]\n\nHi [Client],\nThis is a follow-up on invoice #[NUMBER], due on [DATE]. As of today, it is [DAYS] days overdue. Please arrange payment at your earliest convenience.\n\n## Final Notice (30 days overdue)\nSubject: FINAL NOTICE — Invoice #[NUMBER]\n\nHi [Client],\nThis is the final notice. If payment is not received within 7 days, I will need to pause all active work.\n\nBest,\n[Name]', 'template', '{payment,reminder,invoice}', '2026-05-01 10:10:00+00'),
  ('b1000000-0000-0000-0000-000000000004', 'Client Preferences & Notes', '# Client Notes\n\n## Sarah Chen\n- Prefers email over Slack\n- Likes minimal, clean design\n- Payment: always on time\n- Casper: 0106ca7c...\n\n## Marcus Rivera\n- Fast decision maker\n- Wants aggressive timelines\n- Weekly check-ins on Monday\n\n## Aiko Tanaka\n- Detail-oriented\n- Needs Japanese + English deliverables\n- Prefers Wise transfer\n\n## James Okafor\n- Technical client — likes API docs\n- Prefers async communication\n- Uses GitHub for code review\n\n## Elena Volkov\n- Content-first approach\n- Likes to iterate on copy before design\n- Prefers Telegram\n\n## Raj Patel\n- DeFi / crypto native\n- Wants on-chain payment tracking\n- Casper: 0105c4d3...', 'note', '{clients,preferences,personal}', '2026-07-01 12:00:00+00'),
  ('b1000000-0000-0000-0000-000000000005', 'Casper Network Integration Guide', '# Casper Network — Quick Reference\n\n## Testnet RPC Endpoints\n- Primary: https://node.testnet.casper.network/rpc\n- Backup: https://node.testnet.cspr.cloud/rpc\n- Explorer: https://testnet.cspr.live\n- Faucet: https://testnet.cspr.live/tools/faucet\n\n## Key Concepts\n- CSPR: Native token of Casper Network\n- Public Key: 01-prefix (Ed25519) or 02-prefix (Secp256k1)\n- Account Hash: human-readable address\n- Deploy: A transaction on Casper Network\n- Purse: Where CSPR tokens are stored\n\n## When to Check On-Chain\n- After invoicing a client with a Casper address\n- When a client says "I sent the payment"\n- Before marking a project as paid\n\n## Workflow\n1. Get client''s public key (store in project.casper_address)\n2. Use casper_query_account to check balance\n3. Compare balance to invoice amount\n4. If sufficient → mark project as paid\n5. If insufficient → send payment reminder', 'note', '{casper,blockchain,reference}', '2026-07-01 12:30:00+00');

-- ──────────────────────────────────────────────────────────
-- Chat messages
-- ──────────────────────────────────────────────────────────
insert into messages (project_id, role, content, created_at) values
  ('a1000000-0000-0000-0000-000000000001', 'user', 'I have a new client Sarah Chen, she needs a SaaS dashboard UI kit, budget $4,800, deadline in 6 weeks, her Casper address is 0106ca7c39cd272dbf21a86eeb3b36b7c26e2e9b94af64292419f7862936bca2', '2026-06-01 09:00:00+00'),
  ('a1000000-0000-0000-0000-000000000001', 'assistant', 'Got it. Let me confirm: Sarah Chen, SaaS Dashboard UI Kit, $4,800 USD, deadline 2026-07-15, Casper address 0106ca7c... Is that correct?', '2026-06-01 09:00:30+00'),
  ('a1000000-0000-0000-0000-000000000001', 'user', 'Yes, create the project', '2026-06-01 09:01:00+00'),
  ('a1000000-0000-0000-0000-000000000001', 'assistant', 'Project created. I stored Sarah''s Casper address for payment verification. Want me to draft a contract?', '2026-06-01 09:01:30+00'),
  ('a1000000-0000-0000-0000-000000000001', 'user', 'Yes, generate a formal contract', '2026-06-02 10:29:00+00'),
  ('a1000000-0000-0000-0000-000000000001', 'assistant', 'Contract generated. It includes 50/50 payment terms and full IP transfer. You can copy or download it from the project page.', '2026-06-02 10:30:00+00'),
  ('a1000000-0000-0000-0000-000000000001', 'user', 'I just sent Sarah an invoice for $4,800. Can you check if she has the funds on Casper?', '2026-07-10 14:00:00+00'),
  ('a1000000-0000-0000-0000-000000000001', 'assistant', 'Let me check Sarah''s Casper balance... [calls casper_query_account] Sarah has 12,000 CSPR on testnet — that covers the $4,800 invoice. I''ll mark the project as invoiced.', '2026-07-10 14:00:30+00'),
  ('a1000000-0000-0000-0000-000000000001', 'user', 'Sarah still hasn''t paid. Send a friendly reminder', '2026-07-18 09:00:00+00'),
  ('a1000000-0000-0000-0000-000000000001', 'assistant', 'I generated a polite payment reminder. Sarah''s project is now 8 days overdue. You can copy the message and send it directly.', '2026-07-18 09:00:30+00'),
  ('a1000000-0000-0000-0000-000000000002', 'user', 'New client Marcus Rivera, e-commerce platform, $15,000 budget, deadline end of August', '2026-06-20 11:00:00+00'),
  ('a1000000-0000-0000-0000-000000000002', 'assistant', 'Created: Marcus Rivera — E-commerce Platform, $15,000, due 2026-08-15. Want me to draft the contract?', '2026-06-20 11:01:00+00'),
  ('a1000000-0000-0000-0000-000000000002', 'user', 'Yes, send the contract', '2026-06-21 08:59:00+00'),
  ('a1000000-0000-0000-0000-000000000002', 'assistant', 'Contract generated. 30/40/30 payment structure. Marcus has signed and deposit is in.', '2026-06-21 09:00:00+00'),
  ('a1000000-0000-0000-0000-000000000004', 'user', 'James Okafor''s backend API is done. Time to invoice.', '2026-06-29 10:00:00+00'),
  ('a1000000-0000-0000-0000-000000000004', 'assistant', 'James''s Mobile App Backend API is delivered. Invoice ready to send for $9,000. Want me to generate the invoice?', '2026-06-29 10:00:30+00'),
  ('a1000000-0000-0000-0000-000000000006', 'user', 'New client Raj Patel, DeFi analytics dashboard, $11,000, due end of August, Casper address 0105c4d3e2f1a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5', '2026-07-08 08:00:00+00'),
  ('a1000000-0000-0000-0000-000000000006', 'assistant', 'Got it. Raj Patel — DeFi Analytics Dashboard, $11,000 USD, deadline 2026-08-30, Casper address 0105c4d3... Create this project?', '2026-07-08 08:00:30+00');
