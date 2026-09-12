import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    productName: '拾光集市',
  }),
})
