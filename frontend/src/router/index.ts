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
        { path: 'privacy', name: 'privacy', component: () => import('../views/PrivacyView.vue') },
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
          component: () => import('../views/FavoritesView.vue'),
        },
        {
          path: 'messages/:id?',
          name: 'messages',
          component: () => import('../views/ChatView.vue'),
        },
        {
          path: 'notifications',
          name: 'notifications',
          component: () => import('../views/NotificationsView.vue'),
        },
        {
          path: 'reports',
          name: 'reports',
          component: () => import('../views/ReportsView.vue'),
        },
        {
          path: 'appeals/:reportId',
          name: 'report-appeal',
          component: () => import('../views/AppealView.vue'),
        },
        {
          path: 'orders',
          name: 'orders',
          component: () => import('../views/OrdersView.vue'),
        },
        {
          path: 'orders/:id',
          name: 'order-detail',
          component: () => import('../views/OrderDetailView.vue'),
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
      children: [
        { path: '', name: 'admin', component: () => import('../views/AdminView.vue') },
        {
          path: 'dashboard',
          name: 'admin-dashboard',
          component: () => import('../views/AdminDashboardView.vue'),
        },
        {
          path: 'users',
          name: 'admin-users',
          component: () => import('../views/AdminUsersView.vue'),
        },
        {
          path: 'products',
          name: 'admin-products',
          component: () => import('../views/AdminProductsView.vue'),
        },
        {
          path: 'campus-appeals',
          name: 'admin-campus-appeals',
          component: () => import('../views/AdminCampusView.vue'),
        },
        {
          path: 'catalog',
          name: 'admin-catalog',
          component: () => import('../views/AdminCatalogView.vue'),
        },
        {
          path: 'staff',
          name: 'admin-staff',
          component: () => import('../views/AdminStaffView.vue'),
        },
        {
          path: 'audit',
          name: 'admin-audit',
          component: () => import('../views/AdminAuditView.vue'),
        },
      ],
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

export default router
