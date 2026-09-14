<script setup lang="ts">
import type { PublicCampus, PublicCategory } from '../../api/market'
import UiButton from '../ui/UiButton.vue'
import UiField from '../ui/UiField.vue'

withDefaults(
  defineProps<{
    categories: PublicCategory[]
    campuses: PublicCampus[]
    idPrefix?: string
  }>(),
  { idPrefix: 'market-filter' },
)

const category = defineModel<string>('category', { required: true })
const campus = defineModel<string>('campus', { required: true })
const minPrice = defineModel<string>('minPrice', { required: true })
const maxPrice = defineModel<string>('maxPrice', { required: true })
const condition = defineModel<string>('condition', { required: true })
const negotiable = defineModel<string>('negotiable', { required: true })
const status = defineModel<string>('status', { required: true })

defineEmits<{
  apply: []
  clear: []
}>()
</script>

<template>
  <form class="filter-form" @submit.prevent="$emit('apply')">
    <UiField :id="`${idPrefix}-category`" label="分类">
      <template #default="{ describedby }">
        <select :id="`${idPrefix}-category`" v-model="category" :aria-describedby="describedby">
          <option value="">全部分类</option>
          <option v-for="item in categories" :key="item.id" :value="item.code">
            {{ item.name }}
          </option>
        </select>
      </template>
    </UiField>

    <UiField :id="`${idPrefix}-campus`" label="校区">
      <template #default="{ describedby }">
        <select :id="`${idPrefix}-campus`" v-model="campus" :aria-describedby="describedby">
          <option value="">全部校区</option>
          <option v-for="item in campuses" :key="item.id" :value="item.id">
            {{ item.school_name }} {{ item.name }}
          </option>
        </select>
      </template>
    </UiField>

    <div class="price-fields">
      <UiField :id="`${idPrefix}-min-price`" label="最低价">
        <template #default="{ describedby }">
          <input
            :id="`${idPrefix}-min-price`"
            v-model="minPrice"
            type="number"
            min="0"
            :aria-describedby="describedby"
          />
        </template>
      </UiField>
      <UiField :id="`${idPrefix}-max-price`" label="最高价">
        <template #default="{ describedby }">
          <input
            :id="`${idPrefix}-max-price`"
            v-model="maxPrice"
            type="number"
            min="0"
            :aria-describedby="describedby"
          />
        </template>
      </UiField>
    </div>

    <UiField :id="`${idPrefix}-condition`" label="成色">
      <template #default="{ describedby }">
        <select :id="`${idPrefix}-condition`" v-model="condition" :aria-describedby="describedby">
          <option value="">不限成色</option>
          <option value="new">全新</option>
          <option value="like_new">近新</option>
          <option value="good">使用良好</option>
          <option value="fair">明显使用</option>
        </select>
      </template>
    </UiField>

    <UiField :id="`${idPrefix}-negotiable`" label="议价">
      <template #default="{ describedby }">
        <select :id="`${idPrefix}-negotiable`" v-model="negotiable" :aria-describedby="describedby">
          <option value="">不限</option>
          <option value="true">可议价</option>
          <option value="false">一口价</option>
        </select>
      </template>
    </UiField>

    <UiField :id="`${idPrefix}-status`" label="状态">
      <template #default="{ describedby }">
        <select :id="`${idPrefix}-status`" v-model="status" :aria-describedby="describedby">
          <option value="">在售与预订</option>
          <option value="on_sale">仅在售</option>
          <option value="reserved">已预订</option>
          <option value="sold">已售</option>
        </select>
      </template>
    </UiField>

    <div class="filter-actions">
      <UiButton type="submit">应用筛选</UiButton>
      <UiButton type="button" variant="secondary" @click="$emit('clear')">清空条件</UiButton>
    </div>
  </form>
</template>
