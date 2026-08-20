/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./static/**/*.{html,js}",
    "./src/**/*.{ts,tsx,html}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        header: ['Outfit', 'Inter', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      colors: {
        primary: '#2563eb',
        accent: '#0f766e',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}
