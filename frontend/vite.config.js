import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'
import { resolveCodespacesSandbox } from './sandboxConfig.js'
import { DICE_SAME_ORIGIN } from './sandboxConstants.js'

export default defineConfig(({ mode }) => {
  console.log(`🔧 Vite config loading for mode: ${mode}`)

  // Vite automatically loads .env files, but we'll also load our custom env files
  const envFile = mode === 'production' ? 'env.production' : 'env.development'
  const envPath = path.resolve(__dirname, envFile)

  let envVars = {}
  if (fs.existsSync(envPath)) {
    const envContent = fs.readFileSync(envPath, 'utf-8')
    envContent.split('\n').forEach(line => {
      const [key, ...valueParts] = line.split('=')
      if (key && valueParts.length > 0) {
        envVars[key.trim()] = valueParts.join('=').trim()
      }
    })
  }

  // For production builds, always use production URLs
  const isProduction = mode === 'production'
  const codespacesSandbox = resolveCodespacesSandbox()
  if (isProduction && codespacesSandbox) {
    throw new Error('The Dice Codespaces sandbox cannot run in production mode')
  }
  const clientEnv = (name, fallback) => (
    process.env[name] || envVars[name] || fallback
  )
  const apiUrl = codespacesSandbox
    ? '/api'
    : clientEnv('VITE_API_URL', isProduction ? '' : 'http://localhost:8000')
  const supabaseUrl = codespacesSandbox
    ? DICE_SAME_ORIGIN
    : clientEnv('VITE_SUPABASE_URL', '')
  const supabaseKey = codespacesSandbox
    ? process.env.VITE_SUPABASE_ANON_KEY || ''
    : clientEnv('VITE_SUPABASE_ANON_KEY', '')
  const eveAgentUrl = clientEnv('VITE_EVE_AGENT_URL', 'http://localhost:3000')
  const localHarness = codespacesSandbox
    ? process.env.VITE_DICE_LOCAL_HARNESS || ''
    : clientEnv('VITE_DICE_LOCAL_HARNESS', 'false')
  const localDiceEmail = codespacesSandbox
    ? process.env.VITE_LOCAL_DICE_EMAIL || ''
    : clientEnv('VITE_LOCAL_DICE_EMAIL', '')
  const localDicePassword = codespacesSandbox
    ? process.env.VITE_LOCAL_DICE_PASSWORD || ''
    : clientEnv('VITE_LOCAL_DICE_PASSWORD', '')
  const codespacesOrigin = codespacesSandbox?.origin || ''
  if (isProduction && (!apiUrl || !supabaseUrl || !supabaseKey)) {
    throw new Error(
      'Production builds require VITE_API_URL, VITE_SUPABASE_URL, and VITE_SUPABASE_ANON_KEY',
    )
  }
  if (codespacesSandbox) {
    const productionKey = envVars.VITE_SUPABASE_ANON_KEY || ''
    const validLocalKey =
      supabaseKey.startsWith('sb_publishable_') &&
      supabaseKey !== productionKey
    if (
      localHarness !== 'true' ||
      !validLocalKey ||
      localDiceEmail !== 'referee@dice.local' ||
      localDicePassword !== 'local-dice-password'
    ) {
      throw new Error(
        'Codespaces requires the verified local Supabase key and exact synthetic Dice account',
      )
    }
  }

  return {
    plugins: [
      react(),
      {
        name: 'generate-config',
        writeBundle() {
          // Generate config.json based on environment
          const config = {
            API_URL: apiUrl,
            SUPABASE_URL: supabaseUrl,
            SUPABASE_ANON_KEY: supabaseKey
          }

          const configPath = path.resolve(__dirname, 'dist/config.json')
          fs.writeFileSync(configPath, JSON.stringify(config, null, 2))
          console.log('✅ Generated config.json for', mode, 'environment with API_URL:', apiUrl)
        }
      }
    ],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: "./src/setupTests.js",
      css: true,
    },
    server: {
      port: 8080,
      host: true,
      allowedHosts: codespacesSandbox
        ? [codespacesSandbox.host, 'localhost', '127.0.0.1']
        : undefined,
      proxy: codespacesSandbox ? {
        '^/api/dice(?:/|$)': {
          target: 'http://127.0.0.1:8000',
          rewrite: (requestPath) => requestPath.replace(/^\/api/, ''),
        },
        '^/api/health$': {
          target: 'http://127.0.0.1:8000',
          rewrite: (requestPath) => requestPath.replace(/^\/api/, ''),
        },
        '^/(auth|rest|storage)/v1': {
          target: 'http://127.0.0.1:54321',
          changeOrigin: true,
        },
      } : undefined,
      headers: codespacesSandbox
        ? { 'Content-Security-Policy': "connect-src 'self'" }
        : undefined,
    },
    optimizeDeps: {
      exclude: ['@myriaddreamin/typst-ts-web-compiler'],
    },
    assetsInclude: ['**/*.wasm'],
    define: {
      // Make environment variables available to the client via import.meta.env
      'import.meta.env.VITE_API_URL': JSON.stringify(apiUrl),
      'import.meta.env.VITE_SUPABASE_URL': JSON.stringify(supabaseUrl),
      'import.meta.env.VITE_SUPABASE_ANON_KEY': JSON.stringify(supabaseKey),
      'import.meta.env.VITE_EVE_AGENT_URL': JSON.stringify(eveAgentUrl),
      'import.meta.env.VITE_DICE_LOCAL_HARNESS': JSON.stringify(localHarness),
      'import.meta.env.VITE_DICE_CODESPACES_ORIGIN': JSON.stringify(codespacesOrigin),
      'import.meta.env.VITE_LOCAL_DICE_EMAIL': JSON.stringify(localDiceEmail),
      'import.meta.env.VITE_LOCAL_DICE_PASSWORD': JSON.stringify(localDicePassword),
    },
  }
})
