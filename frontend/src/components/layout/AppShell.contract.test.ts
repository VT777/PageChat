import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

describe('AppShell chat history menu contract', () => {
  it('renders the chat history action menu through a fixed body layer', () => {
    const source = readFileSync(new URL('./AppShell.vue', import.meta.url), 'utf-8')

    expect(source).toContain("import { calculatePopoverPosition }")
    expect(source).toContain('<Teleport to="body">')
    expect(source).toContain('pc-chat-menu-layer')
    expect(source).toContain(':style="chatMenuStyle"')
    expect(source).toContain('window.addEventListener(\'scroll\', closeChatMenu, true)')
    expect(source).toContain('window.addEventListener(\'keydown\', handleMenuKeydown)')
    expect(source).toContain('position: fixed;')
    expect(source).not.toContain('class="pc-chat-menu"\n              @click.stop')
  })
})