import { useState, type FormEvent } from 'react'
import { useAppStore } from '../store/appStore'
import { agentChat } from '../api/client'
import { ChatIcon, ArrowRightIcon } from './icons'

const QUICK_ACTIONS = ['Increase shadow density', 'Rotate slightly', 'Switch to cartoon', 'Make base thicker', 'Export STL']

export function AiAssistant() {
  const { chatMessages, plan, addChatMessage } = useAppStore()
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  const send = async (text: string) => {
    if (!text.trim()) return
    addChatMessage({ role: 'user', content: text })
    setInput('')
    setLoading(true)

    try {
      const result = await agentChat(text, plan)
      addChatMessage({ role: 'agent', content: result.response })
    } catch (err) {
      addChatMessage({ role: 'agent', content: 'Sorry, the AI assistant is temporarily unavailable.' })
    } finally {
      setLoading(false)
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    send(input)
  }

  return (
    <div className="flex h-full flex-col rounded-2xl border border-neutral-300 bg-white/60">
      <div className="flex items-center gap-2 border-b border-neutral-300 p-4">
        <ChatIcon className="h-5 w-5 text-neutral-600" />
        <h3 className="text-sm font-semibold text-neutral-800">AI Assistant</h3>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {chatMessages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`
                max-w-[90%] rounded-2xl px-3 py-2 text-sm
                ${msg.role === 'user'
                  ? 'rounded-br-md bg-neutral-800 text-white'
                  : 'rounded-bl-md bg-neutral-200 text-neutral-800'}
              `}
            >
              {msg.content}
              {msg.actions && msg.role === 'agent' && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {msg.actions.map((action) => (
                    <button
                      key={action}
                      type="button"
                      onClick={() => send(action)}
                      className="rounded-full border border-neutral-400 bg-white px-2 py-1 text-[10px] text-neutral-700 hover:bg-neutral-100"
                    >
                      {action}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-md bg-neutral-200 px-3 py-2 text-sm text-neutral-500">Thinking…</div>
          </div>
        )}
      </div>

      <div className="border-t border-neutral-300 p-4">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {QUICK_ACTIONS.map((action) => (
            <button
              key={action}
              type="button"
              onClick={() => send(action)}
              className="rounded-md border border-neutral-300 bg-white px-2 py-1 text-[10px] text-neutral-600 hover:border-neutral-500"
            >
              {action}
            </button>
          ))}
        </div>
        <form onSubmit={onSubmit} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything…"
            className="flex-1 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="rounded-lg bg-neutral-800 px-3 py-2 text-white transition hover:bg-neutral-700 disabled:opacity-50"
          >
            <ArrowRightIcon className="h-4 w-4" />
          </button>
        </form>
      </div>
    </div>
  )
}
