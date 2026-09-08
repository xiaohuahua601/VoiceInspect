<template>
  <section class="page-view state-page">
    <span class="eyebrow">ACCESS CONTROL</span>
    <h2>没有访问权限</h2>
    <p>当前账号没有访问此页面的权限。请联系系统管理员调整角色或数据范围。</p>
    <div class="state-actions">
      <RouterLink class="button primary" to="/dashboard">返回运营总览</RouterLink>
      <RouterLink class="button secondary" to="/account">查看账号安全</RouterLink>
    </div>
  </section>
</template>
