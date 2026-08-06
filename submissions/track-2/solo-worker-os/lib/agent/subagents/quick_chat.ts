import type { SubagentConfig } from '../types';

/** Quick Chat subagent — lightweight chitchat, zero tools, fast response */
export const quickChatSubagent: SubagentConfig = {
  id: 'quick_chat',
  label: '闲聊陪伴',
  routingKeywords: [
    '你好', 'hello', 'hi', 'hey', '嗨',
    '谢谢', 'thank', 'thanks', '感谢',
    '天气', 'weather', '闲聊', 'chat',
    '你是谁', 'who are you', '能做什么',
    '帮助', 'help', '关于', 'about',
    '好的', 'ok', 'okay', '明白',
  ],
  routingExamples: [
    '你好！',
    'Hello!',
    '谢谢',
    'Thanks!',
    '你是什么系统？',
    'What can you do?',
  ],
  systemPrompt: `You are the Quick Chat subagent. Respond directly and conversationally. No tools needed — just be helpful and brief.
Introduce Solo Worker OS capabilities when asked. Keep responses short and friendly.`,
  tools: [],
  lightweight: true,
};
