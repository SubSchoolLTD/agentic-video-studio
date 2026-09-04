// Generate the editable, code-native gallery layouts. No UI or metrics are fabricated.
// Input: live browser captures in output/playwright/launch (account chrome is clipped).
// Preview at 70% to fit a normal browser capture; crop the actual 1050x700 canvas.
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const root = process.cwd()
const capture = resolve(root, 'output/playwright/launch')
await mkdir(capture, { recursive: true })
const image = async (path, mime = 'image/png') => `data:${mime};base64,${(await readFile(resolve(root, path))).toString('base64')}`
const screen = async (name) => image(`output/playwright/launch/${name}.png`)
const still = async (number) => image(`apps/web/public/showcase/framewise-example-0${number}.jpg`, 'image/jpeg')
const icon = '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m4 8 15-4 1 4-15 4-1-4Z"/><path d="M5 12v8h15V9M8 7l3 3m2-5 3 3"/></svg>'
const css = `
*{box-sizing:border-box}html,body{margin:0;width:1280px;height:720px;overflow:hidden}
body{font-family:Arial,Helvetica,sans-serif;background:#f5f1f8;color:#24182e;-webkit-font-smoothing:antialiased}
.canvas{position:relative;width:1500px;height:1000px;padding:54px 64px;overflow:hidden;transform:scale(.7);transform-origin:top left;background:radial-gradient(ellipse at 95% 15%,#e4c7f4 0,transparent 45%),#f7f3f8}
.canvas.dark{background:radial-gradient(ellipse at 90% 20%,#773894 0,transparent 48%),radial-gradient(ellipse at 20% 100%,#462454 0,transparent 55%),#1d1226;color:#fff}
.brand{display:flex;align-items:center;gap:13px;font-size:28px;font-weight:750;letter-spacing:-1px}
.brand-icon{display:grid;place-items:center;background:#9634b1;color:#fff;width:50px;height:50px;border-radius:15px;box-shadow:0 6px 22px #862a9d24}
.edition{position:absolute;right:66px;top:73px;font-size:15px;letter-spacing:2.4px;text-transform:uppercase;opacity:.65}
.copy{position:absolute;left:66px;top:248px;width:440px;z-index:3}
.eyebrow{font-size:15px;font-weight:700;letter-spacing:2.2px;text-transform:uppercase;color:#942dac;margin-bottom:24px}
.dark .eyebrow{color:#d9a2ed}h1{font-size:66px;line-height:1.02;letter-spacing:-3.5px;margin:0 0 27px;font-weight:760}
.copy p{font-size:24px;line-height:1.42;color:#6c5a74;margin:0;max-width:415px}.dark .copy p{color:#d1c1da}
.tags{display:flex;flex-wrap:wrap;gap:10px;margin-top:32px}.tag{font-size:13px;font-weight:700;letter-spacing:.3px;background:#eee5f2;color:#744786;padding:11px 13px;border-radius:8px}.dark .tag{background:#ffffff0d;color:#edcfef;border:1px solid #ffffff18}
.foot{position:absolute;left:66px;right:66px;bottom:42px;display:flex;justify-content:space-between;align-items:center;font-size:13px;letter-spacing:.3px;color:#8b7893}.dark .foot{color:#bda4c9}.foot b{font-size:16px;color:#87309f}.dark .foot b{color:#e3b1f2}
.window{position:absolute;left:554px;top:176px;width:868px;height:733px;background:#f7f5f2;border:1px solid #e8dcec;border-radius:25px;box-shadow:0 25px 65px #42205324;overflow:hidden}
.bar{height:40px;display:flex;align-items:center;justify-content:center;background:#fff;color:#8b7b92;font-size:12px;border-bottom:1px solid #ece5ee;position:relative}.dots{position:absolute;left:17px;display:flex;gap:5px}.dots i{width:7px;height:7px;background:#d9cedf;border-radius:50%}
.viewport{height:693px;overflow:hidden;position:relative}.viewport img{position:absolute;display:block;width:869px;max-width:none;left:0;top:-65px}
.window.director{top:154px;height:761px}.director .viewport{height:721px}.director .viewport img{top:-17px;left:-5px}
.hero .copy{top:245px;width:580px}.hero h1{font-size:83px;letter-spacing:-4.5px}.hero .copy p{max-width:485px;font-size:25px}
.hero-visual{position:absolute;left:680px;top:193px;width:785px;height:690px}
.phone{position:absolute;border:7px solid #fff;border-radius:28px;overflow:hidden;box-shadow:0 30px 70px #06000b65;background:#180f20}.phone img{width:100%;height:100%;object-fit:cover;display:block}
.phone.one{width:288px;height:515px;left:35px;top:110px;transform:rotate(-7deg)}.phone.two{width:309px;height:550px;left:298px;top:25px;transform:rotate(7deg)}
.clip-label{position:absolute;bottom:14px;left:13px;right:13px;padding:13px 10px;border-radius:12px;background:#21112be0;color:#fff;font-size:13px;font-weight:700;backdrop-filter:blur(10px)}
.proof{position:absolute;top:634px;left:120px;display:flex;align-items:center;gap:10px;color:#dfbde9;font-size:14px}.proof span{height:7px;width:7px;border-radius:50%;background:#d49fe7}
.path{position:absolute;left:66px;bottom:129px;display:flex;gap:9px;align-items:center}.path span{font-size:14px;font-weight:700;color:#dfc8e7;border:1px solid #8d699c59;padding:13px 17px;border-radius:10px}.path em{font-style:normal;color:#c496d3}
`
const frame = (inner, name, num, dark = false, extra = '') => `<!doctype html><html lang="en"><meta charset="utf-8"><title>${name}</title><style>${css}</style><body><main class="canvas ${dark ? 'dark' : ''} ${extra}"><div class="brand"><span class="brand-icon">${icon}</span>Framewise</div><div class="edition">Your always-on video team</div>${inner}<footer class="foot"><span>${num} / 06 · Actual product screens & generated footage</span><b>studio.subschool.us ↗</b></footer></main></body></html>`
const window = (src, cls = '') => `<div class="window ${cls}"><div class="bar"><div class="dots"><i></i><i></i><i></i></div>Framewise · live product</div><div class="viewport"><img src="${src}" alt="Actual Framewise screen"></div></div>`
const copy = (kicker, title, sub, tags) => `<section class="copy"><div class="eyebrow">${kicker}</div><h1>${title}</h1><p>${sub}</p><div class="tags">${tags.map(t => `<span class="tag">${t}</span>`).join('')}</div></section>`
const pages = [
  ['01-always-on-studio', frame(`${copy('From website to video channel','Your business.<br>Your stories.<br>On autopilot.','Research, creation and publishing—one video team that keeps your content moving.',['Google Cloud + Gemini','Veo + Parallel Search'])}<div class="hero-visual"><div class="phone one"><img src="${await still(1)}"><span class="clip-label">Creator-led · actual generated video</span></div><div class="phone two"><img src="${await still(2)}"><span class="clip-label">Storytelling · actual generated video</span></div><div class="proof"><span></span>Frames from the public Framewise showcase</div></div><div class="path"><span>Your website</span><em>→</em><span>Fresh ideas</span><em>→</em><span>Videos</span><em>→</em><span>Your channels</span></div>`, 'Framewise — Your always-on video team', '01', true, 'hero')],
  ['02-research', frame(copy('01 · Discover','Find the next<br>story worth<br>telling.','Parallel searches the live web. Framewise turns sources and audience context into scored video ideas.',['Evidence + source links','Audience + format fit']) + window(await screen('research')), 'Framewise — Research', '02')],
  ['03-director', frame(copy('02 · Write & direct','More than<br>a voiceover.<br>A real scene.','Gemini plans the cast, exact dialogue, setting, action and camera—then reviews the complete story before video generation.',['Character map','Story critique','Editable scenes']) + window(await screen('director'), 'director'), 'Framewise — Scene direction', '03', true)],
  ['04-automation', frame(copy('03 · Keep showing up','Set a cadence.<br>Get your<br>time back.','Choose how far to automate: research, scripts, videos or publishing. Your content plan keeps its rhythm.',['Five automation levels','Cadence + budget controls']) + window(await screen('automation')), 'Framewise — Automation', '04')],
  ['05-production', frame(copy('04 · Produce','The story.<br>The footage.<br>The finished cut.','Veo scenes become a finished video. Inspect the process, download captions, or continue to publication.',['Native Veo speech','Recoverable workflow','Clean-cut assembly']) + window(await screen('production')), 'Framewise — Production', '05', true)],
  ['06-agent-access', frame(copy('05 · Connect','Your agent.<br>Your studio.<br>One workflow.','Let your own agent research, configure and operate Framewise through scoped REST and MCP access.',['Remote MCP','Project-scoped keys','Same API permissions']) + window(await screen('developer')), 'Framewise — Agent access', '06')],
]
for (const [name, html] of pages) {
  await writeFile(resolve(capture, `${name}.html`), html)
  console.log(name)
}
