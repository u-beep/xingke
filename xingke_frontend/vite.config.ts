import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API 代理目标：优先取环境变量 SHAPEAI_API_TARGET（如后端 cloudflared 隧道地址），
// 未设置时回退到本地后端 http://localhost:28900
const API_TARGET = process.env.SHAPEAI_API_TARGET || 'http://localhost:28900'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // 监听 0.0.0.0,局域网其他设备可访问
    allowedHosts: true, // 允许任意 Host 头(内网穿透隧道域名随机生成)
    port: 3000,
    open: true,
    proxy: {
      // 将 /api 和 /health 请求代理到后端服务（SHAPEAI_API_TARGET 可指向 cloudflared 隧道）
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
      '/health': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
})
