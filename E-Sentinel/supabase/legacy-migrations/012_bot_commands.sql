CREATE TABLE IF NOT EXISTS bot_commands (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  command_name TEXT NOT NULL UNIQUE,
  regex_pattern TEXT NOT NULL,
  action_type TEXT NOT NULL DEFAULT 'custom',
  reply_template TEXT,
  api_endpoint TEXT,
  api_method TEXT DEFAULT 'POST',
  is_active BOOLEAN DEFAULT true,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bot_commands_active ON bot_commands(is_active);
