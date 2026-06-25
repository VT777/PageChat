import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUserStore } from './user'

function installLocalStorage() {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
    clear: () => storage.clear(),
  })
}

function jsonResponse(payload: unknown, ok = true) {
  return {
    ok,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response
}

describe('user auth store', () => {
  beforeEach(() => {
    installLocalStorage()
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn())
  })

  it('surfaces backend validation detail when registration returns 422', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        {
          detail: [
            {
              msg: '用户名只能包含字母、数字和下划线',
            },
            {
              msg: 'value is not a valid email address',
            },
          ],
        },
        false,
      ),
    )
    const store = useUserStore()

    await expect(
      store.register('中文用户', 'bad@example.test', 'password123'),
    ).rejects.toThrow('用户名只能包含字母、数字和下划线')
  })

  it('surfaces backend business errors during registration', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        success: false,
        error: '密码必须包含大写字母',
      }),
    )
    const store = useUserStore()

    await expect(
      store.register('debug_user', 'debug@outlook.com', 'password123'),
    ).rejects.toThrow('密码必须包含大写字母')
  })
})
