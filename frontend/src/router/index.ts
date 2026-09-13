import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: () => import('../layouts/PublicLayout.vue'),
      children: [
        { path: '', name: 'home', component: () => import('../views/HomeView.vue') },
        { path: 'login', name: 'login', component: () => import('../views/LoginView.vue') },
        {
          path: 'forgot-password',
          name: 'forgot-password',
          component: () => import('../views/ForgotPasswordView.vue'),
        },
        {
          path: 'register',
          name: 'register',
          component: () => import('../views/RegisterView.vue'),
        },
        { path: 'account', name: 'account', component: () => import('../views/AccountView.vue') },
        {
          path: 'my-products',
          name: 'my-products',
          component: () => import('../views/AccountCollectionView.vue'),
          meta: { title: '我的发布', description: '商品发布功能将在商品阶段开放。' },
        },
        {
          path: 'favorites',
          name: 'favorites',
          component: () => import('../views/AccountCollectionView.vue'),
          meta: { title: '我的收藏', description: '当前没有可展示的收藏。' },
        },
        {
          path: 'orders',
          name: 'orders',
          component: () => import('../views/AccountCollectionView.vue'),
          meta: { title: '我的订单', description: '订单功能将在交易阶段开放。' },
        },
        {
          path: ':pathMatch(.*)*',
          name: 'not-found',
          component: () => import('../views/NotFoundView.vue'),
        },
      ],
    },
    {
      path: '/admin',
      component: () => import('../layouts/AdminLayout.vue'),
      children: [{ path: '', name: 'admin', component: () => import('../views/AdminView.vue') }],
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

export default router
