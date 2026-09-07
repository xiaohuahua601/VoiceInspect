import { readFile } from 'node:fs/promises'
import { readdir } from 'node:fs/promises'
import { join } from 'node:path'

const css = await readFile('frontend/src/styles.css', 'utf8')
const files = ['frontend/src/App.vue']
for (const name of await readdir('frontend/src/views')) files.push(join('frontend/src/views', name))
const app = (await Promise.all(files.map((file) => readFile(file, 'utf8')))).join('\n')
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
