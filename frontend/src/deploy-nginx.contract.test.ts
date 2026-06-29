import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('Docker nginx static asset contract', () => {
  it('serves Vite mjs chunks such as pdf.worker with a JavaScript MIME type', () => {
    const config = readFileSync(new URL('../../deploy/nginx/pagechat.conf', import.meta.url), 'utf8')

    expect(config).toContain('location ~* \\.mjs$')
    expect(config).toContain('default_type application/javascript;')
  })
})
