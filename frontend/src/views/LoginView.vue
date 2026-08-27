<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { loginApi } from '@/utils/auth-api'

const router = useRouter()
const { setAuth } = useAuth()

// 表单状态
const username = ref('')
const password = ref('')
const showPassword = ref(false)
const rememberMe = ref(false)
const loading = ref(false)
const errorMsg = ref('')

onMounted(() => {
  // 恢复记住的账号
  const saved = localStorage.getItem('login_username')
  if (saved) {
    username.value = saved
    rememberMe.value = true
  }
})

async function handleLogin() {
  errorMsg.value = ''
  if (!username.value.trim()) {
    errorMsg.value = '请输入用户名或邮箱'
    return
  }
  if (!password.value) {
    errorMsg.value = '请输入密码'
    return
  }

  loading.value = true
  try {
    const res = await loginApi({ username: username.value, password: password.value })
    const { access_token, refresh_token, user } = res.data.data
    setAuth(access_token, user, refresh_token)

    // 保存记住我
    if (rememberMe.value) {
      localStorage.setItem('login_username', username.value)
    } else {
      localStorage.removeItem('login_username')
    }

    // 直接跳转，不再设置角色
    router.push('/chat')
  } catch (err: any) {
    errorMsg.value = err?.message || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <!-- 左侧品牌区 -->
    <div class="brand-side">
      <div class="brand-header">
        <span class="brand-dot"></span>
        <span class="brand-name">等保测评助手</span>
      </div>

      <div class="brand-body">
        <h1 class="brand-title">智能驱动等级保护<br />测评全流程</h1>
        <p class="brand-subtitle">从招投标到测评核查，AI Agent 赋能商务与技术双线协作</p>

        <ul class="feature-list">
          <li><svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> 招投标文件智能搜索与废标检查</li>
          <li><svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> 测评截图 VLM 自动核查</li>
          <li><svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> 等保知识库双路 RAG 检索</li>
          <li><svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> 人工审核闭环 Human-in-the-loop</li>
        </ul>
      </div>

      <div class="brand-footer">© 2026 等保测评助手 · 企业版</div>
    </div>

    <!-- 右侧表单区 -->
    <div class="form-side">
      <div class="form-card">
        <h2 class="form-title">欢迎回来</h2>
        <p class="form-subtitle">登录以继续使用等保测评助手</p>

        <!-- 错误提示 -->
        <div v-if="errorMsg" class="error-tip">{{ errorMsg }}</div>

        <!-- 账号 -->
        <label class="field-label">账号</label>
        <div class="input-wrapper">
          <svg class="input-icon" viewBox="0 0 20 20" fill="currentColor"><path d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z"/></svg>
          <input v-model="username" type="text" placeholder="请输入用户名或邮箱" class="input-field" />
        </div>

        <!-- 密码 -->
        <label class="field-label">密码</label>
        <div class="input-wrapper">
          <svg class="input-icon" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd"/></svg>
          <input
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            placeholder="请输入密码"
            class="input-field"
            @keydown.enter="handleLogin"
          />
          <button class="toggle-pwd" type="button" @click="showPassword = !showPassword">
            {{ showPassword ? '隐藏' : '显示' }}
          </button>
        </div>

        <!-- 记住密码 / 忘记密码 -->
        <div class="form-options">
          <label class="checkbox-label">
            <input v-model="rememberMe" type="checkbox" />
            <span class="checkmark"></span>
            记住密码
          </label>
          <a href="#" class="forgot-link">忘记密码？</a>
        </div>

        <!-- 登录按钮 -->
        <button class="login-btn" :disabled="loading" @click="handleLogin">
          {{ loading ? '登录中...' : '登录' }}
          <svg v-if="!loading" class="btn-arrow" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
        </button>

        <!-- 分割线 -->
        <div class="divider"><span>其他登录方式</span></div>

        <!-- 底部链接 -->
        <p class="form-footer">还没有账号？<a href="#" class="contact-admin">联系管理员开通</a></p>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── 整体双栏 ── */
.login-page {
  display: flex;
  height: 100vh;
  background: #f5f7ff;
}

/* ── 左侧品牌区 ── */
.brand-side {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 48px 56px;
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  position: relative;
}
.brand-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 600;
  color: var(--primary);
}
.brand-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--primary);
}
.brand-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.brand-title {
  font-size: 32px;
  font-weight: 700;
  color: #1e1b4b;
  line-height: 1.4;
  margin-bottom: 16px;
}
.brand-subtitle {
  font-size: 16px;
  color: #6366f1;
  margin-bottom: 40px;
}
.feature-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.feature-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
  color: #3730a3;
}
.feature-list svg {
  width: 20px;
  height: 20px;
  color: var(--primary);
  flex-shrink: 0;
}
.brand-footer {
  font-size: 13px;
  color: #818cf8;
}

/* ── 右侧表单区 ── */
.form-side {
  width: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  background: var(--surface);
}
.form-card {
  width: 100%;
  max-width: 380px;
}
.form-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text);
}
.form-subtitle {
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: 4px;
  margin-bottom: 24px;
}

/* 角色卡片 */
.role-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 20px;
}
.role-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 14px 16px;
  border: 2px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  cursor: pointer;
  transition: all 0.2s;
}
.role-card.active {
  border-color: var(--primary);
  background: var(--primary-light);
}
.role-card:hover {
  border-color: var(--primary);
}
.role-icon {
  width: 22px;
  height: 22px;
  color: var(--primary);
}
.role-label {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.role-desc {
  font-size: 12px;
  color: var(--text-muted);
}

/* 错误提示 */
.error-tip {
  padding: 10px 14px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  font-size: 13px;
  color: var(--danger);
  margin-bottom: 16px;
}

/* 输入框 */
.field-label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 8px;
}
.input-wrapper {
  position: relative;
  margin-bottom: 16px;
}
.input-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  width: 18px;
  height: 18px;
  color: var(--text-muted);
  pointer-events: none;
}
.input-field {
  width: 100%;
  padding: 12px 14px 12px 42px;
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 14px;
  color: var(--text);
  background: #f9fafb;
  outline: none;
  transition: border-color 0.2s;
}
.input-field:focus {
  border-color: var(--primary);
  background: var(--surface);
}
.toggle-pwd {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  border: none;
  background: transparent;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
}

/* 选项行 */
.form-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
}
.checkbox-label input {
  accent-color: var(--primary);
  width: 16px;
  height: 16px;
}
.forgot-link {
  font-size: 13px;
  color: var(--primary);
  text-decoration: none;
}

/* 登录按钮 */
.login-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px;
  border: none;
  border-radius: 10px;
  background: var(--primary);
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}
.login-btn:hover:not(:disabled) {
  background: var(--primary-hover);
}
.login-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.btn-arrow {
  width: 18px;
  height: 18px;
}

/* 分割线 */
.divider {
  display: flex;
  align-items: center;
  gap: 16px;
  margin: 24px 0;
}
.divider::before,
.divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}
.divider span {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

/* 底部 */
.form-footer {
  text-align: center;
  font-size: 13px;
  color: var(--text-secondary);
}
.contact-admin {
  color: var(--primary);
  text-decoration: none;
}
</style>
