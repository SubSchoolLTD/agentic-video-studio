<script setup lang="ts">
const props = defineProps<{ text?: string | null }>()

function escapeHtml(value: string) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;')
}

function inline(value: string) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
}

function renderMarkdown(value: string) {
  const output: string[] = []
  let list: 'ul' | 'ol' | null = null
  const closeList = () => { if (list) output.push(`</${list}>`); list = null }
  for (const raw of value.replace(/\r/g, '').split('\n')) {
    const line = raw.trim()
    if (!line) { closeList(); continue }
    const heading = line.match(/^(#{1,4})\s+(.+)$/)
    const bullet = line.match(/^[-*]\s+(.+)$/)
    const ordered = line.match(/^\d+[.)]\s+(.+)$/)
    if (heading) { closeList(); const level = heading[1]?.length || 1; output.push(`<h${level}>${inline(heading[2] || '')}</h${level}>`) }
    else if (bullet || ordered) {
      const nextList = bullet ? 'ul' : 'ol'
      if (list !== nextList) { closeList(); list = nextList; output.push(`<${list}>`) }
      output.push(`<li>${inline((bullet || ordered)?.[1] || '')}</li>`)
    }
    else if (line.startsWith('> ')) { closeList(); output.push(`<blockquote>${inline(line.slice(2))}</blockquote>`) }
    else { closeList(); output.push(`<p>${inline(line)}</p>`) }
  }
  closeList()
  return output.join('')
}

const rendered = computed(() => renderMarkdown(String(props.text || '')))
</script>

<template>
  <!-- renderMarkdown escapes HTML before adding the small allowlisted Markdown grammar. -->
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div class="markdown-text" v-html="rendered" />
</template>

<style scoped>
.markdown-text :deep(> :first-child){margin-top:0}.markdown-text :deep(> :last-child){margin-bottom:0}.markdown-text :deep(p){margin:.35em 0}.markdown-text :deep(ul),.markdown-text :deep(ol){margin:.45em 0;padding-left:1.35em}.markdown-text :deep(a){color:var(--primary-700);text-decoration:underline;text-underline-offset:2px}.markdown-text :deep(code){padding:.08em .28em;border-radius:4px;background:var(--surface-soft);font-size:.92em}.markdown-text :deep(strong){color:inherit}
</style>
