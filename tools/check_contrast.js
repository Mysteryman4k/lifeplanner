// Checks text contrast for every colour theme in light and dark.  Run: node tools/check_contrast.js
global.window = { matchMedia: () => ({ matches: false, addEventListener(){} }) };
global.document = { documentElement: { style: { setProperty(){} }, dataset: {} }, querySelector: () => null };
global.localStorage = { getItem: () => null };
const src = require('fs').readFileSync(require('path').join(__dirname, '..', 'static', 'theme.js'),'utf8') + '\nmodule.exports={THEMES,neutrals};';
const m = new module.constructor(); m._compile(src, 'theme.js'); const {THEMES, neutrals} = m.exports;
const hex2rgb = h => [1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255);
const hsl2rgb = s => { const [h,S,L]=s.match(/[\d.]+/g).map(Number); const sat=S/100,l=L/100; const k=n=>(n+h/30)%12; const a=sat*Math.min(l,1-l); const f=n=>l-a*Math.max(-1,Math.min(k(n)-3,9-k(n),1)); return [f(0),f(8),f(4)]; };
const lum = rgb => { const c=rgb.map(v=>v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4); return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2]; };
const cr = (x,y) => { const a=lum(x), b=lum(y); return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05); };
let fails=0;
for (const [k,t] of Object.entries(THEMES)) for (const mode of ['light','dark']) {
  const n = neutrals(t.hue,t.sat,mode==='dark'); const c=t[mode];
  const surf = hsl2rgb(n['--surface']), bg=hsl2rgb(n['--bg']), s2=hsl2rgb(n['--surface-2']);
  const checks = {
    'accent text/surface': cr(hex2rgb(c.text), surf), 'accent text/bg': cr(hex2rgb(c.text), bg),
    'btn text/grad a': cr(hex2rgb(c.on), hex2rgb(c.a)), 'btn text/grad b': cr(hex2rgb(c.on), hex2rgb(c.b)),
    'ink/surface': cr(hsl2rgb(n['--ink']), surf), 'muted/surface': cr(hsl2rgb(n['--muted']), surf), 'muted/surface-2': cr(hsl2rgb(n['--muted']), s2),
    'grad a/surface (bars)': cr(hex2rgb(c.a), surf),
  };
  const bad = Object.entries(checks).filter(([name,v]) => v < (name.includes('bars') ? 3 : 4.5));
  if (bad.length) { fails++; console.log(k, mode, 'LOW:', bad.map(([n,v])=>`${n} ${v.toFixed(2)}`).join(', ')); }
}
console.log(fails ? `${fails} theme/mode combos need work` : 'all themes pass');
