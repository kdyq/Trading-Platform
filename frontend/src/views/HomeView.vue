<script setup lang="ts">
import { gsap } from 'gsap'
import { onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

const root = ref<HTMLElement | null>(null)
let motionContext: gsap.Context | undefined
let media: gsap.MatchMedia | undefined

onMounted(() => {
  if (!root.value) return

  motionContext = gsap.context(() => {
    media = gsap.matchMedia()
    media.add('(prefers-reduced-motion: no-preference)', () => {
      gsap.from('.hero-copy > *', {
        autoAlpha: 0,
        y: 24,
        duration: 0.6,
        stagger: 0.08,
        ease: 'power2.out',
      })
      gsap.from('.market-note', {
        autoAlpha: 0,
        y: 20,
        rotation: 2,
        duration: 0.75,
        ease: 'back.out(1.25)',
      })
    })
  }, root.value)
})

onUnmounted(() => {
  media?.revert()
  motionContext?.revert()
})
</script>

<template>
  <section ref="root" class="container hero">
    <div class="hero-copy">
      <p class="eyebrow">校园里的周末市集</p>
      <h1>闲置好物，换个主人继续发光</h1>
      <p class="hero-description">从同学手里发现好物，也让自己的闲置重新派上用场。</p>
      <div class="hero-actions">
        <RouterLink class="button button-primary" to="/login"> 登录后发布 </RouterLink>
        <a class="button button-ghost" href="#ready">了解当前进度</a>
      </div>
    </div>
    <article id="ready" class="market-note">
      <span class="note-tape" aria-hidden="true" />
      <p class="eyebrow">工程基线</p>
      <h2>市集正在搭摊</h2>
      <p>路由、状态与设计令牌已经就位。真实商品和账号功能会按开发阶段逐步接入。</p>
      <RouterLink class="text-link" to="/admin"> 查看管理端外壳 </RouterLink>
    </article>
  </section>
</template>
