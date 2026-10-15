// Build-time rebrand of the installed @deepseek-ai/dsh web UI (run once in the
// Dockerfile). Replaces user-visible "DeepSeek Harness"/"DSH" strings with
// BRAND_NAME/BRAND_SHORT, rewrites title/manifest/favicons and fills the
// placeholders of the kb-brand plugin. Internal ids (__DSH_*__, dsh-auth-*
// cookies, @deepseek-ai/* package names, DSH_* env) are left untouched.
// The Dockerfile greps for leftovers afterwards and fails the build.
import fs from 'node:fs'
import path from 'node:path'

const NAME = process.env.BRAND_NAME ?? ''
const SHORT = process.env.BRAND_SHORT ?? ''
const PKG = process.env.DSH_PKG ?? '/usr/local/lib/node_modules/@deepseek-ai/dsh'
const PLUGIN = process.env.BRAND_PLUGIN ?? '/opt/dsh/plugins/kb-brand'
const ASSETS = process.env.BRAND_ASSETS ?? '/opt/dsh/brand'

// Values are pasted into JS string/template literals, HTML and SVG: keep them inert.
const SAFE = /^[^"'`\\$<>&{}\n]+$/
for (const [k, v] of [['BRAND_NAME', NAME], ['BRAND_SHORT', SHORT]]) {
  if (!v.trim() || !SAFE.test(v)) throw new Error(`${k} must be non-empty and free of quotes, backslash, $, <, >, &, braces`)
}

const NM = path.join(PKG, 'node_modules/@deepseek-ai')
const DIST = path.join(NM, 'dsh-web-frontend/dist')
const edited = []
const edit = (file, fn) => {
  const before = fs.readFileSync(file, 'utf8')
  const after = fn(before)
  if (after !== before) { fs.writeFileSync(file, after); edited.push(path.relative(PKG, file)) }
}
const walk = (dir, re) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
  const p = path.join(dir, e.name)
  return e.isDirectory() ? walk(p, re) : re.test(e.name) ? [p] : []
})

// 1. frontend shell: <title>, manifest, favicons
edit(path.join(DIST, 'index.html'), (s) => s.replace(/<title>[^<]*<\/title>/, `<title>${NAME}</title>`))
edit(path.join(DIST, 'manifest.webmanifest'), (s) => {
  const m = JSON.parse(s)
  m.name = NAME
  m.short_name = SHORT
  return JSON.stringify(m, null, 2) + '\n'
})
const font = SHORT.length > 2 ? '11' : '15'
for (const [src, dst] of [['favicon-light.svg', 'favicon.svg'], ['favicon-dark.svg', 'favicon-dark.svg']]) {
  const svg = fs.readFileSync(path.join(ASSETS, src), 'utf8').replaceAll('__BRAND_SHORT__', SHORT).replaceAll('__BRAND_FONT__', font)
  fs.writeFileSync(path.join(DIST, dst), svg)
  edited.push(path.relative(PKG, path.join(DIST, dst)))
}

// 2. targeted rewrites (before the generic pass)
edit(path.join(NM, 'dsh-system-prompt/lib/index.js'), (s) =>
  s.replace('You are an AI agent powered by DeepSeek Harness.', `You are ${NAME}, an AI agent.`))
// startup log prefix: "dsh web: http://127.0.0.1:3080/?token=…" -> "agent web: …"
edit(path.join(NM, 'dsh-web-app/lib/index.js'), (s) =>
  s.replaceAll('console.log(`dsh web: ', 'console.log(`agent web: ').replaceAll('console.log("dsh web: ', 'console.log("agent web: '))
// 401 body the server sends to a browser without the login cookie
edit(path.join(NM, 'dsh-client-connection/lib/index.js'), (s) =>
  s.replaceAll('dsh web authentication required; reopen the URL printed by dsh web.',
    `${NAME}: authentication required; open the login link with the token.`))

// 3. generic pass over the shipped browser bundles + prompt + web-app host strings
const targets = [
  ...walk(DIST, /\.(js|html|webmanifest)$/),
  ...fs.readdirSync(NM).filter((d) => d.startsWith('dsh-client-ui-')).flatMap((d) => {
    const lib = path.join(NM, d, 'lib')
    return fs.existsSync(lib) ? walk(lib, /\.js$/) : []
  }),
  path.join(NM, 'dsh-system-prompt/lib/index.js'),
  ...walk(path.join(NM, 'dsh-web-app/lib'), /\.js$/),
]
// Bare "DSH" only inside prose (bounded by space/quote/punctuation), never in
// identifiers like __DSH_BOOT__ or DSH_WEB_URL.
const BARE = /(?<=[\s"'(「（])DSH(?=[\s"'.,;:!?)）」，。、：；！？])/g
for (const f of targets) {
  edit(f, (s) => {
    s = s.replaceAll('DeepSeek Harness', NAME)
    return /dsh-client-ui-/.test(f) ? s.replace(BARE, SHORT) : s
  })
}

// 4. kb-brand plugin placeholders
edit(path.join(PLUGIN, 'lib/client.js'), (s) => s.replaceAll('__BRAND_NAME__', NAME).replaceAll('__BRAND_SHORT__', SHORT))

// 5. Russian language pack: inline ru.json (with the brand name) into the plugin
const RU_PLUGIN = process.env.LOCALE_PLUGIN ?? '/opt/dsh/plugins/kb-locale-ru'
if (fs.existsSync(path.join(RU_PLUGIN, 'ru.json'))) {
  const dict = JSON.parse(fs.readFileSync(path.join(RU_PLUGIN, 'ru.json'), 'utf8').replaceAll('%BRAND_NAME%', NAME).replaceAll('%BRAND_SHORT%', SHORT))
  for (const [ns, m] of Object.entries(dict)) for (const [k, v] of Object.entries(m)) if (typeof v !== 'string') throw new Error(`ru.json ${ns}.${k} is not a string`)
  edit(path.join(RU_PLUGIN, 'lib/client.js'), (s) => s.replace('__RU_DICT__', () => JSON.stringify(dict)))
}

console.log(`rebrand:"${NAME}" / "${SHORT}", ${edited.length} files changed`)
for (const f of edited) console.log(`  ${f}`)
