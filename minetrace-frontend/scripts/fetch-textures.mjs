// Downloads the globe textures into public/textures so the app runs offline.
// Run once with internet:  npm run textures

import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'textures')
const files = {
  'earth_atmos_2048.jpg': 'https://threejs.org/examples/textures/planets/earth_atmos_2048.jpg',
  'earth_clouds_1024.png': 'https://threejs.org/examples/textures/planets/earth_clouds_1024.png'
}

await mkdir(root, { recursive: true })

for (const [name, url] of Object.entries(files)) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`Could not download ${url} (${response.status})`)
  await writeFile(join(root, name), Buffer.from(await response.arrayBuffer()))
  console.log(`Saved public/textures/${name}`)
}
