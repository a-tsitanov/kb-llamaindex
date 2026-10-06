// dsh-kb-ingest — upload documents into the knowledge base from DeepSeek Harness.
//
// Talks to the KB web UI backend (deploy/offline/webui/app.py), which already
// owns the KB API key and the docs2md conversion:
//   POST {webuiUrl}/api/convert   multipart file -> {markdown, metadata}
//   POST {webuiUrl}/api/ingest    form {markdown, filename, document_date?} -> {job_id}
//   GET  {webuiUrl}/api/ingest/ID -> {status, error, ...}
//
// Surfaces:
//   /kb-ingest [YYYY-MM-DD]   slash command with attached files (no model call)
//   /kb-status [job_id ...]   status of given jobs, or of this process's recent jobs
//   kb_ingest_file / kb_ingest_status   agent tools (path of an attached/workspace file)
import { readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'kb-ingest'
export const inject = ['commands', 'attachments', 'tools']

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const RECENT_MAX = 50

// ── HTTP helpers (exported for tests) ───────────────────────────────

async function relayJson(res, what) {
  const text = await res.text()
  let body
  try { body = text ? JSON.parse(text) : {} } catch { body = { raw: text.slice(0, 300) } }
  if (!res.ok) {
    const detail = body.detail ?? body.error ?? body.message ?? body.raw ?? text.slice(0, 300)
    const msg = typeof detail === 'string' ? detail : JSON.stringify(detail)
    throw new Error(`${what}: HTTP ${res.status} ${msg}`)
  }
  return body
}

export async function convertAndIngest(webuiUrl, bytes, filename, documentDate, signal) {
  const fd = new FormData()
  fd.append('file', new Blob([bytes]), filename)
  const conv = await relayJson(
    await fetch(`${webuiUrl}/api/convert`, { method: 'POST', body: fd, signal }),
    'convert',
  )
  const markdown = conv.markdown ?? ''
  if (!markdown.trim()) throw new Error('convert: empty text (scan/image without OCR?)')
  const form = new FormData()
  form.append('markdown', markdown)
  form.append('filename', filename)
  if (documentDate) form.append('document_date', documentDate)
  const ing = await relayJson(
    await fetch(`${webuiUrl}/api/ingest`, { method: 'POST', body: form, signal }),
    'ingest',
  )
  if (!ing.job_id) throw new Error(`ingest: no job_id in response ${JSON.stringify(ing).slice(0, 200)}`)
  return { job_id: String(ing.job_id), chars: markdown.length, format: conv.metadata?.detected_format ?? '' }
}

export async function jobStatus(webuiUrl, jobId, signal) {
  const s = await relayJson(await fetch(`${webuiUrl}/api/ingest/${encodeURIComponent(jobId)}`, { signal }), 'status')
  return { job_id: jobId, status: String(s.status ?? 'unknown'), error: s.error ? String(s.error) : '' }
}

async function readAttachment(ctx, ref, signal) {
  const chunks = []
  let size = 0
  for await (const chunk of ctx.attachments.readFileStream(ref, signal)) {
    chunks.push(chunk)
    size += chunk.byteLength
  }
  const out = new Uint8Array(size)
  let off = 0
  for (const c of chunks) { out.set(c, off); off += c.byteLength }
  return out
}

// ── plugin ──────────────────────────────────────────────────────────

export function apply(ctx, config = {}) {
  const webuiUrl = String(config.webuiUrl ?? 'http://10.10.113.12:8090').replace(/\/+$/, '')
  const recent = [] // {job_id, filename, at}

  const remember = (job_id, filename) => {
    recent.unshift({ job_id, filename, at: new Date().toISOString() })
    if (recent.length > RECENT_MAX) recent.length = RECENT_MAX
  }
  const nameOf = (jobId) => recent.find((r) => r.job_id === jobId)?.filename ?? ''

  ctx.commands.register({
    name: 'kb-ingest',
    description: 'Загрузить прикреплённые документы в базу знаний (опционально дата документа ГГГГ-ММ-ДД)',
    input: { hint: '[ГГГГ-ММ-ДД]', attachments: true },
    handler: async ({ rawInput, attachments, signal }) => {
      const arg = rawInput.trim()
      if (arg && !DATE_RE.test(arg)) return { kind: 'error', text: `Дата должна быть в формате ГГГГ-ММ-ДД, получено: "${arg}"` }
      if (!attachments.length) return { kind: 'error', text: 'Прикрепите один или несколько файлов и повторите /kb-ingest' }
      const lines = []
      let ok = 0
      for (const block of attachments) {
        if (block.type !== 'file') {
          lines.push('✗ изображение: картинки не загружаются (OCR выключен) — прикрепите документ с текстом')
          continue
        }
        const fname = block.attachment.name
        try {
          const bytes = await readAttachment(ctx, block.attachment, signal)
          const r = await convertAndIngest(webuiUrl, bytes, fname, arg, signal)
          remember(r.job_id, fname)
          ok++
          lines.push(`✓ ${fname} → job ${r.job_id} (${r.chars} символов текста)`)
        } catch (e) {
          lines.push(`✗ ${fname}: ${e instanceof Error ? e.message : String(e)}`)
        }
      }
      const head = `Отправлено в базу: ${ok} из ${attachments.length}.`
      const tail = ok ? '\nСтатус обработки: /kb-status' : ''
      return ok ? { kind: 'success', text: `${head}\n${lines.join('\n')}${tail}` } : { kind: 'error', text: `${head}\n${lines.join('\n')}` }
    },
  })

  ctx.commands.register({
    name: 'kb-status',
    description: 'Статус загрузки документов в базу знаний (job_id через пробел или последние загрузки)',
    input: { hint: '[job_id ...]' },
    handler: async ({ rawInput, signal }) => {
      const ids = rawInput.trim() ? rawInput.trim().split(/\s+/) : recent.slice(0, 20).map((r) => r.job_id)
      if (!ids.length) return { kind: 'success', text: 'Нет загрузок в этом сеансе dsh. Укажите job_id: /kb-status <job_id>' }
      const lines = []
      for (const id of ids) {
        try {
          const s = await jobStatus(webuiUrl, id, signal)
          const label = nameOf(id) || id
          const mark = s.status === 'completed' ? '✓' : s.status === 'failed' ? '✗' : '…'
          lines.push(`${mark} ${label}: ${s.status}${s.error ? ` — ${s.error}` : ''}`)
        } catch (e) {
          lines.push(`? ${id}: ${e instanceof Error ? e.message : String(e)}`)
        }
      }
      return { kind: 'success', text: lines.join('\n') }
    },
  })

  ctx.tools.register(defineTool({
    name: 'kb_ingest_file',
    description: 'Upload one document file into the knowledge base (KB). Use for files the user attached (their saved path is given in the conversation) or files in the workspace. Text-bearing formats only (PDF with text layer, DOCX, TXT, MD, HTML, XLSX...); scans/images are rejected (no OCR). Returns a job_id; ingestion is asynchronous — check it with kb_ingest_status.',
    parameters: {
      path: { type: 'string', required: true, description: 'Absolute path of the file to upload.' },
      document_date: { type: 'string', description: 'Optional document date YYYY-MM-DD (what the document is dated, not today).' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          filename: { type: 'string', required: true },
          job_id: { type: 'string', required: true },
          chars: { type: 'integer', required: true },
        },
      },
      render: (_args, v) => [{ type: 'text', text: `Uploaded ${v.filename} to the KB: job_id=${v.job_id} (${v.chars} chars). Ingestion is asynchronous; check with kb_ingest_status.` }],
    },
    timeoutMs: 600000,
    async execute(args, exec) {
      const date = (args.document_date ?? '').trim()
      if (date && !DATE_RE.test(date)) throw new Error('document_date must be YYYY-MM-DD')
      const bytes = await readFile(args.path)
      const fname = basename(args.path)
      const r = await convertAndIngest(webuiUrl, bytes, fname, date, exec.signal)
      remember(r.job_id, fname)
      return { filename: fname, job_id: r.job_id, chars: r.chars }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'kb_ingest_status',
    description: 'Check the ingestion status of a document previously uploaded with kb_ingest_file (pending → processing → completed | failed).',
    parameters: {
      job_id: { type: 'string', required: true, description: 'job_id returned by kb_ingest_file.' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          job_id: { type: 'string', required: true },
          status: { type: 'string', required: true },
          error: { type: 'string', required: true },
        },
      },
      render: (_args, v) => [{ type: 'text', text: `job ${v.job_id}: ${v.status}${v.error ? ` — ${v.error}` : ''}` }],
    },
    async execute(args, exec) {
      return jobStatus(webuiUrl, args.job_id, exec.signal)
    },
  }))
}
