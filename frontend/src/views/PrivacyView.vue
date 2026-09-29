<template>
  <section class="container account-page">
    <header class="account-heading">
      <p class="eyebrow">校内试运行说明</p>
      <h1>隐私与账号注销</h1>
      <p>以下说明对应当前平台功能；正式试运行前，联系方式和保存期限还需运营负责人确认。</p>
    </header>
    <article class="account-panel sessions-panel">
      <h2>我们处理哪些信息</h2>
      <p>
        登录邮箱、昵称和密码哈希用于账号与找回；校园邮箱及主动提交的申诉材料用于认证；商品、聊天、订单、评价和举报用于校内交易与治理。
      </p>
      <p>
        商品与昵称可公开展示。聊天正文、申诉和举报材料由权限接口读取。请求日志只记录请求编号、路径、状态与耗时，不记录密码、验证码或消息正文。
      </p>
    </article>
    <article class="account-panel sessions-panel">
      <h2>保存与清理</h2>
      <p>
        验证码与聊天票据会短期失效；审计导出文件一小时后过期。校园申诉材料按当前配置保留 180
        天，常驻清理任务会删除到期文件。备份保留窗口在试运行前确认。
      </p>
    </article>
    <article class="account-panel sessions-panel">
      <h2>注销账号</h2>
      <p>
        登录后可在账户与安全页申请注销。未完成订单、待处理举报或申诉需要先处理；后台人员须先移交职责。注销会退出所有设备、清除登录标识并隐藏发布，私有材料和商品图片由清理任务随后删除。已完成交易和治理记录可能保留去标识关联。
      </p>
      <RouterLink class="identity-action" to="/account">前往账户与安全</RouterLink>
    </article>
  </section>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>
