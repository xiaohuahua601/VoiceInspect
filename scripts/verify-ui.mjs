import { readFile } from 'node:fs/promises'

const css = await readFile('frontend/src/styles.css', 'utf8')
const app = await readFile('frontend/src/App.vue', 'utf8')
const required = [
  ['reduced motion', css.includes('prefers-reduced-motion')],
  ['visible focus', css.includes('focus-visible')],
  ['textarea resize contract', css.includes('resize: none')],
  ['native dialog avoidance', !app.includes('window.alert') && !app.includes('window.confirm')],
  ['app-owned form validation', app.includes('novalidate')],
  ['aria live state', app.includes('aria-live')],
]
const failures = required.filter(([, ok]) => !ok)
for (const [name, ok] of required) console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`)
if (failures.length) process.exit(1)
