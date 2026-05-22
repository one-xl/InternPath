export function safeParseModelJson<T>(rawText: string): T {
  const text = rawText.trim()

  try {
    return JSON.parse(text) as T
  } catch {}

  const withoutFence = text
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/i, "")
    .replace(/```$/i, "")
    .trim()

  try {
    return JSON.parse(withoutFence) as T
  } catch {}

  // Systematic curly brace searching on the raw text
  const firstBrace = text.indexOf("{")
  const lastBrace = text.lastIndexOf("}")

  if (firstBrace !== -1 && lastBrace !== -1 && lastBrace > firstBrace) {
    try {
      const jsonLike = text.slice(firstBrace, lastBrace + 1)
      return JSON.parse(jsonLike) as T
    } catch {}
  }

  // Systematic curly brace searching on the fenced text as a secondary fallback
  const fbFence = withoutFence.indexOf("{")
  const lbFence = withoutFence.lastIndexOf("}")
  if (fbFence !== -1 && lbFence !== -1 && lbFence > fbFence) {
    try {
      const jsonLike = withoutFence.slice(fbFence, lbFence + 1)
      return JSON.parse(jsonLike) as T
    } catch {}
  }

  throw new Error(
    "Gemini 返回了自然语言而非 JSON。请检查后端最终 request body 是否包含 generationConfig.responseMimeType = application/json，或尝试切换模型。"
  )
}
