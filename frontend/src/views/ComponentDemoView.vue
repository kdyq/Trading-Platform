<script setup lang="ts">
import { ref } from 'vue'

import ProductCard from '../components/market/ProductCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiChip from '../components/ui/UiChip.vue'
import UiDialog from '../components/ui/UiDialog.vue'
import UiField from '../components/ui/UiField.vue'
import UiSkeleton from '../components/ui/UiSkeleton.vue'
import UiToast from '../components/ui/UiToast.vue'

const dialogOpen = ref(false)
const selected = ref(false)
const toast = ref('')
</script>

<template>
  <section class="container component-demo">
    <div class="section-heading">
      <p class="eyebrow">设计系统校样</p>
      <h1>拾光集市组件基元</h1>
      <p>本页只展示组件状态和交互合同，商品内容均为明确标注的组件示例。</p>
    </div>

    <section class="demo-section" aria-labelledby="demo-actions">
      <h2 id="demo-actions">按钮、筛选与反馈</h2>
      <div class="demo-row">
        <UiButton @click="toast = '操作已完成'">主要操作</UiButton>
        <UiButton variant="secondary" @click="dialogOpen = true">打开对话框</UiButton>
        <UiButton variant="danger">危险操作</UiButton>
        <UiButton disabled>不可操作</UiButton>
        <UiChip interactive :selected="selected" @click="selected = !selected">九成新</UiChip>
        <UiChip tone="trust">已认证</UiChip>
      </div>
      <UiToast :message="toast" />
    </section>

    <section class="demo-section" aria-labelledby="demo-field">
      <h2 id="demo-field">字段与加载状态</h2>
      <div class="demo-field-grid">
        <UiField id="demo-title" label="商品标题" help="示例字段，不会保存">
          <template #default="{ describedby }">
            <input id="demo-title" :aria-describedby="describedby" value="自行车灯（组件示例）" />
          </template>
        </UiField>
        <UiField id="demo-price" label="价格" error="请输入有效价格">
          <template #default="{ describedby }">
            <input id="demo-price" aria-invalid="true" :aria-describedby="describedby" value="-1" />
          </template>
        </UiField>
      </div>
      <UiSkeleton height="96px" rounded />
    </section>

    <section class="demo-section" aria-labelledby="demo-products">
      <h2 id="demo-products">商品卡四种状态</h2>
      <div class="product-grid">
        <ProductCard
          title="台灯（组件示例）"
          price="36"
          campus="校区示例"
          condition="九成新"
          published-at="刚刚"
        />
        <ProductCard
          title="教材（组件示例）"
          price="18"
          campus="校区示例"
          condition="轻微使用"
          published-at="昨天"
          state="sold"
        />
        <ProductCard
          title="耳机（组件示例）"
          price="80"
          campus="校区示例"
          condition="全新"
          published-at="今天"
          state="pending"
        />
        <ProductCard state="loading" />
      </div>
    </section>

    <UiDialog :open="dialogOpen" title="组件示例" @close="dialogOpen = false">
      <p>对话框支持键盘焦点循环、Escape 关闭和关闭后的焦点恢复。</p>
      <UiButton variant="secondary" @click="dialogOpen = false">知道了</UiButton>
    </UiDialog>
  </section>
</template>
