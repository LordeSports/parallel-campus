/**
 * 校园地图离屏渲染预览（开发用）。
 *
 * 目的：不启动后端就能把 IsoMap 渲成 SVG/HTML，用来看真实视觉效果，
 * 避免「改完只能靠想象」。输出到 frontend/preview/（已在 .gitignore）。
 *
 * 用法：node scripts/render_map_preview.mjs
 */
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { build } from 'esbuild';
import { renderToStaticMarkup } from 'react-dom/server';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const outDir = resolve(root, 'preview');
mkdirSync(outDir, { recursive: true });

const bundlePath = resolve(outDir, '_render.cjs');
rmSync(resolve(outDir, '_render.mjs'), { force: true });

await build({
  entryPoints: [resolve(here, 'preview_entry.tsx')],
  bundle: true,
  // CJS：bundle 内 zustand 等依赖会用 require('react')，ESM 输出下会炸
  format: 'cjs',
  platform: 'node',
  outfile: bundlePath,
  jsx: 'automatic',
  loader: { '.tsx': 'tsx', '.ts': 'ts' },
  logLevel: 'warning',
  // react 系列走外部依赖：确保与下面 renderToStaticMarkup 是同一个实例
  external: ['react', 'react-dom', 'react/jsx-runtime', 'react-dom/server'],
});

const mod = await import(pathToFileURL(bundlePath).href);
const { renderPreview } = mod.default ?? mod;
const { svg, html, lib, teach, soloTower, soloMain, soloShop } = renderPreview(renderToStaticMarkup);

writeFileSync(resolve(outDir, 'campus.svg'), svg, 'utf-8');
writeFileSync(resolve(outDir, 'campus.html'), html, 'utf-8');
writeFileSync(resolve(outDir, 'detail_lib.html'), lib, 'utf-8');
writeFileSync(resolve(outDir, 'detail_teach.html'), teach, 'utf-8');
writeFileSync(resolve(outDir, 'solo_tower.html'), soloTower, 'utf-8');
writeFileSync(resolve(outDir, 'solo_main.html'), soloMain, 'utf-8');
writeFileSync(resolve(outDir, 'solo_shop.html'), soloShop, 'utf-8');
console.log(`wrote ${outDir}/campus.svg (${svg.length} bytes)`);
console.log(`wrote ${outDir}/campus.html`);
