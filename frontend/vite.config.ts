import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  // 仅供开发服务器使用；代理地址不会注入前端页面。
  const env = loadEnv(mode, '.', 'VITE_');
  return {
  plugins: [react()],
  server: {
    port: Number(env.VITE_PORT || 5173),
    strictPort: true,
    proxy: {
      '/api': {
        target: env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        // SSE 需要关闭缓冲
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache';
          });
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
          graph: ['d3-force'],
        },
      },
    },
  },
  };
});
