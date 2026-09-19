import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: () => import('../layouts/PublicLayout.vue'),
      children: [
        { path: '', name: 'home', component: () => import('../views/HomeView.vue') },
        { path: 'market', name: 'market', component: () => import('../views/MarketView.vue') },
        {
          path: 'products/:id',
          name: 'product-detail',
          component: () => import('../views/ProductDetailView.vue'),
        },
        {
          path: 'design-system',
          name: 'design-system',
          component: () => import('../views/ComponentDemoView.vue'),
        },
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
          path: 'campus-verification',
          name: 'campus-verification',
          component: () => import('../views/CampusVerificationView.vue'),
        },
        {
          path: 'my-products',
          name: 'my-products',
          component: () => import('../views/MyProductsView.vue'),
        },
        {
          path: 'sell',
          name: 'product-create',
          component: () => import('../views/ProductPublishView.vue'),
        },
        {
          path: 'sell/:id',
          name: 'product-edit',
          component: () => import('../views/ProductPublishView.vue'),
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
