import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown'

describe('safe markdown renderer', () => {
  it('renders common markdown syntax', () => {
    const html = renderMarkdown('# 标题\n\n**加粗**、*斜体*\n\n- 一项\n- 二项\n\n> 注意\n\n```ts\nconst ok = true\n```')
    expect(html).toContain('<h1>标题</h1>')
    expect(html).toContain('<strong>加粗</strong>')
    expect(html).toContain('<em>斜体</em>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<blockquote>')
    expect(html).toContain('<code class="language-ts">const ok = true')
  })

  it('does not create html elements or unsafe links from hostile input', () => {
    const html = renderMarkdown('<script>alert(1)</script><img src=x onerror=alert(1)>[危险](javascript:alert(1))')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('&lt;script&gt;')
  })

  it('adds safe link behavior', () => {
    const html = renderMarkdown('[来源](https://example.com)')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })
})