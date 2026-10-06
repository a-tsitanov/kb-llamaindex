// LAN exposure for dsh web. dsh itself refuses to bind anything but 127.0.0.1
// (its UI drives an agent with a bash tool). This L4 proxy forwards
// LAN_BIND (e.g. 10.10.113.11:3080) -> 127.0.0.1:3080, byte-for-byte, so the
// browser's Host header reaches dsh unchanged (allowed via --trusted-host) and
// WebSockets work. Only clients inside LAN_ALLOW CIDRs are accepted; dsh's own
// token/cookie auth still applies to every request.
import net from 'node:net'

const [bindHost, bindPort] = (process.env.LAN_BIND ?? '').split(':')
const target = { host: '127.0.0.1', port: Number(process.env.LAN_TARGET_PORT ?? 3080) }
const allow = (process.env.LAN_ALLOW ?? '10.10.0.0/16').split(/[\s,]+/).filter(Boolean).map((c) => {
  const [ip, bits = '32'] = c.split('/')
  const n = ip.split('.').reduce((a, o) => (a << 8) + Number(o), 0) >>> 0
  const mask = Number(bits) === 0 ? 0 : (~0 << (32 - Number(bits))) >>> 0
  return { net: (n & mask) >>> 0, mask }
})
const ipNum = (ip) => ip.replace(/^::ffff:/, '').split('.').reduce((a, o) => (a << 8) + Number(o), 0) >>> 0
const allowed = (ip) => /^(::ffff:)?\d+\.\d+\.\d+\.\d+$/.test(ip) && allow.some((r) => ((ipNum(ip) & r.mask) >>> 0) === r.net)

if (!bindHost || !bindPort) { console.error('lan-proxy: LAN_BIND=<ip>:<port> required'); process.exit(1) }

net.createServer((client) => {
  const ip = client.remoteAddress ?? ''
  if (!allowed(ip)) { console.error(`lan-proxy: refused ${ip}`); client.destroy(); return }
  const upstream = net.connect(target)
  client.pipe(upstream).pipe(client)
  const close = () => { client.destroy(); upstream.destroy() }
  client.on('error', close); upstream.on('error', close)
}).listen(Number(bindPort), bindHost, () => {
  console.error(`lan-proxy: ${bindHost}:${bindPort} -> ${target.host}:${target.port} allow=${process.env.LAN_ALLOW ?? '10.10.0.0/16'}`)
})
