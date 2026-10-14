// Packages the Windows x64 build with @electron/packager:
//   release/NeonRush-win32-x64/NeonRush.exe  (+ runtime files)
//   release/NeonRush-win32-x64.zip
// Works on Windows, macOS and Linux (no Wine needed). The exe icon/version info
// is set with `resedit` (pure JS) so no Windows-only tools are required.
import { packager } from '@electron/packager';
import { existsSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const electronVersion = JSON.parse(readFileSync(join(root, 'node_modules/electron/package.json'), 'utf8')).version;
const platform = process.argv.includes('--linux') ? 'linux' : 'win32';
const zipDir = join(root, '.cache/electron-zips');

if (!existsSync(join(root, 'dist/index.html'))) throw new Error('Run `npm run build` first.');

const out = join(root, 'release');
const [appPath] = await packager({
  dir: root,
  name: 'NeonRush',
  executableName: 'NeonRush',
  platform,
  arch: 'x64',
  electronVersion,
  out,
  overwrite: true,
  asar: true,
  prune: true,
  // Only ship what the game needs at runtime.
  ignore: (p) => p !== '' && !/^\/(dist|electron|package\.json)(\/|$)/.test(p),
  // Use pre-downloaded Electron zips when present (offline / proxied builds).
  ...(existsSync(join(zipDir, `electron-v${electronVersion}-${platform}-x64.zip`)) ? { electronZipDir: zipDir } : {}),
  appCopyright: 'Neon Rush',
  win32metadata: { CompanyName: 'Neon Rush', ProductName: 'Neon Rush', FileDescription: 'Neon Rush - arcade street racing' },
});
console.log('Packaged:', appPath);

if (platform === 'win32') {
  // Set icon + version resources without Wine.
  const ResEdit = await import('resedit');
  const exePath = join(appPath, 'NeonRush.exe');
  const exe = ResEdit.NtExecutable.from(readFileSync(exePath), { ignoreCert: true });
  const res = ResEdit.NtExecutableResource.from(exe);
  const icoPath = join(root, 'build/icon.ico');
  if (existsSync(icoPath)) {
    const ico = ResEdit.Data.IconFile.from(readFileSync(icoPath));
    const groups = ResEdit.Resource.IconGroupEntry.fromEntries(res.entries);
    const id = groups.length ? groups[0].id : 1;
    const lang = groups.length ? groups[0].lang : 1033;
    ResEdit.Resource.IconGroupEntry.replaceIconsForResource(res.entries, id, lang, ico.icons.map((i) => i.data));
  }
  const vi = ResEdit.Resource.VersionInfo.fromEntries(res.entries)[0];
  if (vi) {
    const [a, b, c] = pkg.version.split('.').map(Number);
    vi.setFileVersion(a, b, c, 0, 1033);
    vi.setProductVersion(a, b, c, 0, 1033);
    vi.setStringValues({ lang: 1033, codepage: 1200 }, { ProductName: 'Neon Rush', FileDescription: 'Neon Rush - arcade street racing', CompanyName: 'Neon Rush', OriginalFilename: 'NeonRush.exe' });
    vi.outputToResourceEntries(res.entries);
  }
  res.outputResource(exe);
  writeFileSync(exePath, Buffer.from(exe.generate()));
  console.log('Patched exe resources:', exePath);
}

// Bundle the run instructions next to the exe.
writeFileSync(join(appPath, 'README.txt'), readFileSync(join(root, 'docs/PLAYING.txt'), 'utf8'));
const zip = `${appPath}.zip`;
rmSync(zip, { force: true });
try {
  execFileSync('zip', ['-qr9', zip, '.'], { cwd: appPath });
} catch {
  // Windows: use PowerShell's archiver instead of `zip`
  execFileSync('powershell', ['-NoProfile', '-Command', `Compress-Archive -Path '${appPath}\\*' -DestinationPath '${zip}' -Force`]);
}
console.log('Zipped:', zip);
