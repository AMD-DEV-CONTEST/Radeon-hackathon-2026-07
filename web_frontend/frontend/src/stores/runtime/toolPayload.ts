export function toolPayloadMessage(payload: Record<string, any> | undefined): Record<string, any> {
  const message = payload?.message
  return message && typeof message === 'object' ? message : {}
}

export function toolPayloadContent(payload: Record<string, any> | undefined): Record<string, any> {
  const message = toolPayloadMessage(payload)
  const content = message.content
  if (typeof content !== 'string' || content.trim() === '') return {}
  try {
    const parsed = JSON.parse(content)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function toolPayloadValue(payload: Record<string, any> | undefined, keys: string[]): any {
  const message = toolPayloadMessage(payload)
  const content = toolPayloadContent(payload)
  for (const key of keys) {
    if (payload?.[key] != null && payload[key] !== '') return payload[key]
    if (message?.[key] != null && message[key] !== '') return message[key]
    if (content?.[key] != null && content[key] !== '') return content[key]
  }
  return null
}

export function toolPayloadArguments(payload: Record<string, any> | undefined): Record<string, any> {
  const value = toolPayloadValue(payload, ['arguments', 'args'])
  return value && typeof value === 'object' ? value : {}
}
