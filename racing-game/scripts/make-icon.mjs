// Renders the game icon (procedurally, in Chromium) and writes build/icon.png + build/icon.ico.
import { chromium } from 'playwright';
import { writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const browser = await chromium.launch();
const page = await browser.newPage();
const sizes = [256, 48, 32, 16];
const pngs = await page.evaluate((sizes) => {
  return sizes.map((S) => {
    const c = document.createElement('canvas');
    c.width = c.height = S;
    const g = c.getContext('2d');
    const k = S / 256;
    const r = 52 * k;
    g.beginPath();
    g.roundRect(8 * k, 8 * k, 240 * k, 240 * k, r);
    const bg = g.createLinearGradient(0, 0, S, S);
    bg.addColorStop(0, '#2a0f5c');
    bg.addColorStop(1, '#07051a');
    g.fillStyle = bg;
    g.fill();
    g.lineWidth = Math.max(1, 8 * k);
    g.strokeStyle = '#00e5ff';
    g.shadowColor = '#00e5ff';
    g.shadowBlur = 16 * k;
    g.stroke();
    // road lines in perspective
    g.shadowBlur = 0;
    g.strokeStyle = '#ff2fd0';
    g.lineWidth = Math.max(1, 6 * k);
    g.beginPath();
    g.moveTo(40 * k, 230 * k); g.lineTo(118 * k, 120 * k);
    g.moveTo(216 * k, 230 * k); g.lineTo(138 * k, 120 * k);
    g.stroke();
    // "NR" monogram
    g.font = `italic 900 ${Math.round(120 * k)}px "Segoe UI", Arial, sans-serif`;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillStyle = '#ffffff';
    g.shadowColor = '#ff2fd0';
    g.shadowBlur = 18 * k;
    g.fillText('NR', 128 * k, 104 * k);
    return c.toDataURL('image/png').split(',')[1];
  });
}, sizes);
await browser.close();
const bufs = pngs.map((b) => Buffer.from(b, 'base64'));
writeFileSync(join(root, 'build/icon.png'), bufs[0]);
// ICO container with PNG-compressed images.
const header = Buffer.alloc(6);
header.writeUInt16LE(0, 0); header.writeUInt16LE(1, 2); header.writeUInt16LE(bufs.length, 4);
const dir = Buffer.alloc(16 * bufs.length);
let offset = 6 + dir.length;
bufs.forEach((b, i) => {
  const s = sizes[i];
  dir.writeUInt8(s >= 256 ? 0 : s, i * 16);
  dir.writeUInt8(s >= 256 ? 0 : s, i * 16 + 1);
  dir.writeUInt8(0, i * 16 + 2); dir.writeUInt8(0, i * 16 + 3);
  dir.writeUInt16LE(1, i * 16 + 4); dir.writeUInt16LE(32, i * 16 + 6);
  dir.writeUInt32LE(b.length, i * 16 + 8); dir.writeUInt32LE(offset, i * 16 + 12);
  offset += b.length;
});
writeFileSync(join(root, 'build/icon.ico'), Buffer.concat([header, dir, ...bufs]));
console.log('icon written', bufs.map((b) => b.length));
