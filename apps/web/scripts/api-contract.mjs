import { mkdir, mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import process from 'node:process'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const webDirectory = resolve(scriptDirectory, '..')
const inputPath = resolve(webDirectory, '..', 'api', 'openapi.json')
const generatedPath = resolve(
  webDirectory,
  'src',
  'api',
  'generated',
  'schema.d.ts',
)

function generate(outputPath) {
  const generatorPath = resolve(
    webDirectory,
    'node_modules',
    'openapi-typescript',
    'bin',
    'cli.js',
  )
  execFileSync(process.execPath, [generatorPath, inputPath, '-o', outputPath], {
    cwd: webDirectory,
    stdio: 'inherit',
  })
}

async function main() {
  const mode = process.argv[2] ?? 'generate'
  if (mode === 'generate') {
    await mkdir(dirname(generatedPath), { recursive: true })
    generate(generatedPath)
    return
  }

  if (mode !== 'check') throw new Error(`Unknown API contract mode: ${mode}`)

  const temporaryDirectory = await mkdtemp(
    resolve(tmpdir(), `bipme-api-${process.pid}-`),
  )
  const temporaryPath = resolve(temporaryDirectory, 'schema.d.ts')
  try {
    generate(temporaryPath)
    const [expected, actual] = await Promise.all([
      readFile(generatedPath, 'utf8'),
      readFile(temporaryPath, 'utf8'),
    ])
    if (expected !== actual) {
      throw new Error(
        'Generated API types are stale. Run `pnpm generate:api` and commit the result.',
      )
    }
  } finally {
    await rm(temporaryDirectory, { recursive: true, force: true })
  }
}

await main()
