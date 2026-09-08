<template>
  <section class="page-view state-page">
    <span class="eyebrow">PAGE NOT FOUND</span>
    <h2>页面不存在</h2>
    <p>这个地址没有对应的后台页面，可能已被移动或删除。</p>
    <div class="state-actions">
      <RouterLink class="button primary" to="/dashboard">返回运营总览</RouterLink>
      <RouterLink class="button secondary" to="/diagnosis">开始诊断</RouterLink>
    </div>
  </section>
</template>
