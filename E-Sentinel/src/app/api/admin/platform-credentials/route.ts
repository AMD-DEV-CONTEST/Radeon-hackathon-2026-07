// ============================================================================
// GET /api/admin/platform-credentials — check which platform credentials are configured.
// Used by PlatformManagementPanel to show credential status per platform.
// Only returns presence/absence — never actual credential values.
// ============================================================================

import { NextResponse } from "next/server";
import { authorizeRequest } from "@/lib/api-auth";

interface CredentialStatus {
  key: string;
  label: string;
  description: string;
  configured: boolean;
}

interface PlatformCredentialInfo {
  platform: string;
  authMethod: string;
  authDescription: string;
  credentials: CredentialStatus[];
}

export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;
  const platforms: PlatformCredentialInfo[] = [
    {
      platform: "feishu",
      authMethod: "OAuth 2.0 (client_credentials)",
      authDescription:
        "飞书开放平台 → 应用凭证 → 获取 tenant_access_token（有效期 2 小时，自动续期）",
      credentials: [
        {
          key: "FEISHU_APP_ID",
          label: "App ID",
          description: "飞书应用的唯一标识，用于获取 tenant_access_token",
          configured: !!process.env.FEISHU_APP_ID,
        },
        {
          key: "FEISHU_APP_SECRET",
          label: "App Secret",
          description: "飞书应用的密钥，配合 App ID 换取 tenant_access_token",
          configured: !!process.env.FEISHU_APP_SECRET,
        },
        {
          key: "FEISHU_VERIFY_TOKEN",
          label: "Verify Token",
          description: "飞书事件订阅 URL 验证时比对，防假冒推送",
          configured: !!process.env.FEISHU_VERIFY_TOKEN,
        },
        {
          key: "FEISHU_EVENT_ENCRYPT_KEY",
          label: "Event Encrypt Key",
          description: "飞书事件消息 AES-256-CBC 解密密钥 + SHA256 签名验证",
          configured: !!process.env.FEISHU_EVENT_ENCRYPT_KEY,
        },
        {
          key: "FEISHU_GROUP_CHAT_ID",
          label: "群聊 ID (可选)",
          description: "三级告警路由：全局群聊通知目标",
          configured: !!process.env.FEISHU_GROUP_CHAT_ID,
        },
        {
          key: "FEISHU_WEBHOOK_URL",
          label: "Webhook URL (可选)",
          description: "四级告警路由兜底 + 机器人回复降级通道",
          configured: !!process.env.FEISHU_WEBHOOK_URL,
        },
      ],
    },
    {
      platform: "tmall",
      authMethod: "OAuth 2.0 (authorization_code)",
      authDescription:
        "天猫开放平台 TOP → 应用管理 → 获取 access_token（有效期 7 天，refresh_token 30 天）",
      credentials: [
        {
          key: "TMALL_APP_KEY",
          label: "App Key",
          description: "天猫开放平台应用标识",
          configured: !!process.env.TMALL_APP_KEY,
        },
        {
          key: "TMALL_APP_SECRET",
          label: "App Secret",
          description: "天猫开放平台应用密钥，用于签名和 OAuth",
          configured: !!process.env.TMALL_APP_SECRET,
        },
        {
          key: "TMALL_SELLER_NICK",
          label: "卖家昵称",
          description: "天猫店铺主账号昵称",
          configured: !!process.env.TMALL_SELLER_NICK,
        },
      ],
    },
  ];

  return NextResponse.json({ platforms });
}
