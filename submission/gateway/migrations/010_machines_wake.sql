-- 010_machines_wake.sql
-- Add SSH wake fields to machines table for remote agent restart capability.
-- Root cause: agents on 24/7 servers go offline when WS drops + systemd burst limit
-- exhausts. This migration adds the data needed for POST /agents/{id}/wake.

ALTER TABLE machines
    ADD COLUMN IF NOT EXISTS ssh_host     TEXT,
    ADD COLUMN IF NOT EXISTS ssh_port     INTEGER NOT NULL DEFAULT 22,
    ADD COLUMN IF NOT EXISTS ssh_user     TEXT NOT NULL DEFAULT 'root',
    ADD COLUMN IF NOT EXISTS ssh_key_path TEXT,
    ADD COLUMN IF NOT EXISTS wake_cmd     TEXT,
    ADD COLUMN IF NOT EXISTS always_on    BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS wake_note    TEXT;

CREATE INDEX IF NOT EXISTS idx_machines_always_on ON machines(always_on) WHERE always_on = true;

-- Seed known always-on machines
INSERT INTO machines (name, host, launcher_port, os, ssh_host, ssh_user, ssh_port, wake_cmd, always_on, wake_note)
VALUES
    (
        'jd-ecs',
        '111.228.42.18',
        9001,
        'linux',
        '111.228.42.18',
        'root',
        22,
        'systemctl restart scc-agent.service',
        true,
        'JD-ECS 主服务器，SSH 免密（本机公钥已授权），SCC 在此运行'
    ),
    (
        'hk-aws-01',
        '18.162.0.0',
        9001,
        'linux',
        '18.162.0.0',
        'ubuntu',
        22,
        'systemctl restart ua-agent.service',
        true,
        'AWS HK 节点，需配置 SSH key 路径（ssh_key_path 待填）'
    )
ON CONFLICT (name) DO UPDATE SET
    ssh_host   = EXCLUDED.ssh_host,
    ssh_user   = EXCLUDED.ssh_user,
    ssh_port   = EXCLUDED.ssh_port,
    wake_cmd   = EXCLUDED.wake_cmd,
    always_on  = EXCLUDED.always_on,
    wake_note  = EXCLUDED.wake_note;
