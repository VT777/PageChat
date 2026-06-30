export async function fetchPdfBlobUrl(fileUrl: string): Promise<string> {
  const token = localStorage.getItem('token')
  const response = await fetch(fileUrl, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })

  if (!response.ok) {
    const detail = await readShortResponseText(response)
    throw new Error(`PDF request failed (${response.status})${detail ? `: ${detail}` : ''}`)
  }

  const contentType = response.headers.get('content-type') || ''
  const blob = await response.blob()
  if (!isPdfBlob(contentType, blob)) {
    const detail = await readShortBlobText(blob)
    throw new Error(`Preview returned ${contentType || 'unknown content type'}${detail ? `: ${detail}` : ''}`)
  }

  return URL.createObjectURL(blob)
}

async function readShortResponseText(response: Response): Promise<string> {
  try {
    return shorten(await response.clone().text())
  } catch {
    return ''
  }
}

async function readShortBlobText(blob: Blob): Promise<string> {
  try {
    return shorten(await blob.slice(0, 240).text())
  } catch {
    return ''
  }
}

function isPdfBlob(contentType: string, blob: Blob): boolean {
  const normalized = contentType.toLowerCase()
  return normalized.includes('application/pdf') || blob.type.toLowerCase().includes('application/pdf')
}

function shorten(value: string): string {
  return value.replace(/\s+/g, ' ').trim().slice(0, 180)
}
