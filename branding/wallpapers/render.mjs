import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
const js = fs.readFileSync('wallpapers.js','utf8');
const OUT = process.argv[2] || '../../packages/sysible-artwork/backgrounds';
fs.mkdirSync(OUT, {recursive:true});
// Render at 8K so the art DOWNSCALES (crisp) on 4K/5K/6K/8K and HiDPI-scaled
// displays instead of upscaling (which is what read as pixelation). The scenes
// are smooth gradients + thin strokes with no transparency, so JPEG q0.92 is a
// fraction of PNG size (an 8K PNG of the hex mesh is ~25MB; JPEG is ~1-2MB) with
// no visible artefacts. imageSmoothingQuality 'high' keeps gradient scaling clean.
const W=7680, H=4320, Q=0.92;
const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome'});
const p = await b.newPage();
await p.setContent('<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>');
await p.addScriptTag({content: js});
// Composite the REAL canonical marks so the wallpaper logo can't drift from the icon.
const markSvg = fs.readFileSync('../logo/sysible-mark.svg','utf8');
const termSvg = fs.readFileSync('../../live-build/config/includes.chroot/usr/share/icons/hicolor/scalable/apps/io.systerm.SysTerm.svg','utf8');
await p.evaluate(async ({m,t})=>{
  async function mk(u){const i=new Image();i.src=u;await i.decode();return i;}
  window.SYS_MARK = await mk('data:image/svg+xml;base64,'+m);
  window.SYS_TERM = await mk('data:image/svg+xml;base64,'+t);
}, {m:Buffer.from(markSvg).toString('base64'), t:Buffer.from(termSvg).toString('base64')});
const keys = await p.evaluate(()=>window.SYS.keys);
for (const key of keys){
  const dataUrl = await p.evaluate(({key,W,H,Q})=>{
    const c=document.createElement('canvas'); c.width=W; c.height=H;
    const x=c.getContext('2d'); x.imageSmoothingEnabled=true; x.imageSmoothingQuality='high';
    window.SYS.render(key,x,W,H);
    return c.toDataURL('image/jpeg',Q);
  }, {key,W,H,Q});
  const buf = Buffer.from(dataUrl.split(',')[1],'base64');
  const f = path.join(OUT, 'sysible-'+key+'.jpg');
  fs.writeFileSync(f, buf);
  console.log('wrote', f, (buf.length/1048576).toFixed(2)+'MB');
}
await b.close();
