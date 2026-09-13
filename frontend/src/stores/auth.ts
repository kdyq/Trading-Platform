import { defineStore } from 'pinia'

import type { UserSummary } from '../api/auth'
import { loginAccount, logoutAccount, refreshAccount, registerAccount } from '../api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: null as string | null,
    user: null as UserSummary | null,
    restoring: false,
  }),
  actions: {
    applySession(accessToken: string, user: UserSummary) {
      this.accessToken = accessToken
      this.user = user
    },
    async login(email: string, password: string) {
      const result = await loginAccount(email, password)
      this.applySession(result.access_token, result.user)
    },
    async register(input: Parameters<typeof registerAccount>[0]) {
      const result = await registerAccount(input)
      this.applySession(result.access_token, result.user)
    },
    async restore() {
      if (this.restoring || this.user) return
      this.restoring = true
      try {
        const result = await refreshAccount()
        this.applySession(result.access_token, result.user)
      } catch {
        this.accessToken = null
        this.user = null
      } finally {
        this.restoring = false
      }
    },
    async logout() {
      try {
        await logoutAccount()
      } finally {
        this.accessToken = null
        this.user = null
      }
    },
  },
})
