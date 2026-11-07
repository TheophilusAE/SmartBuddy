const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        page: token('page'),
        sidebar: token('sidebar'),
        surface: token('surface'),
        raised: token('raised'),
        line: token('line'),
        ink: token('ink'),
        'ink-2': token('ink-2'),
        muted: token('muted'),
        accent: token('accent'),
        'accent-ink': token('accent-ink'),
        good: token('good'),
        'good-ink': token('good-ink'),
        warn: token('warn'),
        'warn-ink': token('warn-ink'),
        danger: token('danger'),
        'danger-ink': token('danger-ink'),
        temp: token('temp'),
        hum: token('hum'),
        lux: token('lux'),
        motion: token('motion'),
        gas: token('gas'),
        rain: token('rain'),
      },
      fontFamily: {
        sans: ['"Inter Variable"', 'Inter', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      borderRadius: {
        card: '20px',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
      },
    },
  },
  plugins: [],
}
