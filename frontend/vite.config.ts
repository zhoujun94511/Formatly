import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import type { IncomingMessage } from 'node:http'
import { isIP } from 'node:net'
import { networkInterfaces } from 'node:os'
import path from 'node:path'

const bindHost = process.env.FORMATLY_DEV_HOST ?? '0.0.0.0'
const bindPort = Number(process.env.FORMATLY_DEV_PORT ?? '5173')
if (bindHost !== 'localhost' && isIP(bindHost) !== 4) {
  throw new Error('FORMATLY_DEV_HOST must be localhost or an IPv4 address')
}
if (!Number.isInteger(bindPort) || bindPort < 1 || bindPort > 65535) {
  throw new Error('FORMATLY_DEV_PORT must be an integer from 1 to 65535')
}

const apiTarget = new URL(process.env.FORMATLY_API_TARGET ?? 'http://127.0.0.1:8765')
if (apiTarget.protocol !== 'http:' || apiTarget.username || apiTarget.password ||
    apiTarget.pathname !== '/' || apiTarget.search || apiTarget.hash ||
    (apiTarget.hostname !== 'localhost' && isIP(apiTarget.hostname) !== 4) ||
    apiTarget.hostname === '0.0.0.0') {
  throw new Error('FORMATLY_API_TARGET must be an HTTP origin using localhost or an IPv4 address')
}

const localHosts = new Set(['127.0.0.1', 'localhost'])
for (const addresses of Object.values(networkInterfaces())) {
  for (const address of addresses ?? []) {
    if (address.family === 'IPv4') localHosts.add(address.address)
  }
}

function hostsForBinding(host: string | boolean | undefined): Set<string> {
  if (host === true || host === '0.0.0.0') return localHosts
  if (host === 'localhost' || host === '127.0.0.1' || host === undefined || host === false) {
    return new Set(['127.0.0.1', 'localhost'])
  }
  return new Set([host])
}

let developmentHosts = hostsForBinding(bindHost)

function requestOrigin(request: IncomingMessage): string | undefined {
  const host = request.headers.host
  if (!host || /[\s\\/@?#]/.test(host)) return undefined
  try {
    const origin = new URL(`http://${host}`)
    if (!developmentHosts.has(origin.hostname) || Number(origin.port || '80') !== request.socket.localPort) {
      return undefined
    }
    return origin.origin
  } catch {
    return undefined
  }
}

export default defineConfig({
  plugins: [vue(), {
    name: 'formatly-development-origin',
    configureServer(server) {
      developmentHosts = hostsForBinding(server.config.server.host)
      server.middlewares.use((request, response, next) => {
        const origin = requestOrigin(request)
        const isApi = request.url?.startsWith('/api')
        if (!origin || (isApi && request.headers.origin && request.headers.origin !== origin)) {
          response.writeHead(403, { 'Content-Type': 'application/json; charset=utf-8' })
          response.end(JSON.stringify({ error: '开发服务仅接受本机服务地址及同源 API 请求' }))
          return
        }
        next()
      })
    }
  }],
  base: '/',
  server: {
    host: bindHost,
    port: bindPort,
    strictPort: true,
    allowedHosts: [...localHosts],
    cors: false,
    proxy: {
      '/api': {
        target: apiTarget.origin,
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (proxyRequest, request) => {
            // Preserve the API's same-origin boundary through the development proxy.
            if (request.headers.origin && request.headers.origin === requestOrigin(request)) {
              proxyRequest.setHeader('Origin', apiTarget.origin)
            }
          })
        }
      }
    }
  },
  build: {
    outDir: path.resolve(__dirname, 'dist'),
    emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: 'assets/[name]-[hash].js', chunkFileNames: 'assets/[name]-[hash].js', assetFileNames: 'assets/[name]-[hash][extname]' } }
  }
})
