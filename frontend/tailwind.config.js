/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: { 50: '#eaf4ff', 500: '#0084ff', 600: '#0070d9' },
        ink: '#1a1a1a',
        muted: '#6b7280',
        paper: '#f7f8fa',
        mood: { pos: '#22c55e', neu: '#94a3b8', neg: '#f97316' },
        player: '#0084ff',
        npc: '#94a3b8',
        me: '#f59e0b',
      },
      fontFamily: {
        sans: ['-apple-system', 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', 'sans-serif'],
      },
      borderRadius: { card: '16px' },
      keyframes: {
        pulseRing: {
          '0%, 100%': { opacity: '0.25', transform: 'scale(1)' },
          '50%': { opacity: '0.55', transform: 'scale(1.035)' },
        },
        fadeUp: {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'pulse-ring': 'pulseRing 2.4s ease-in-out infinite',
        'fade-up': 'fadeUp 0.28s ease-out both',
      },
    },
  },
  plugins: [],
};
