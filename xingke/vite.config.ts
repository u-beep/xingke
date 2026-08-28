import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // 监听 0.0.0.0,局域网其他设备可访问
    allowedHosts: true, // 允许任意 Host 头(内网穿透隧道域名随机生成)
    port: 3000,
    open: true,
    proxy: {
      // 将 /api 和 /health 请求代理到后端服务
      // 注: 8900/18900 被占用,后端改用 28900
      '/api': {
        target: 'http://localhost:28900',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:28900',
        changeOrigin: true,
      },
    },
  },
})
