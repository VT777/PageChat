/**
 * 导出对话记录
 */

export function exportConversation(messages: any[], format: 'json' | 'markdown' = 'markdown'): string {
  if (format === 'json') {
    return JSON.stringify(messages, null, 2)
  }

  // Markdown format
  const lines: string[] = ['# 对话记录\n']
  for (const msg of messages) {
    const role = msg.role === 'user' ? '用户' : '助手'
    lines.push(`## ${role}\n`)
    lines.push(`${msg.content}\n`)
  }
  return lines.join('\n')
}

export function downloadFile(content: string, filename: string, mimeType: string = 'text/plain') {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
