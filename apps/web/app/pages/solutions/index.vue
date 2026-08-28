<script setup lang="ts">
import { ArrowRight, BriefcaseBusiness, Clapperboard, GraduationCap, Menu, Sparkles, Users, X } from 'lucide-vue-next'

const auth = useAuth()
const menuOpen = ref(false)
const primaryCta = computed(() => auth.accessToken.value ? '/app' : '/register')
const primaryLabel = computed(() => auth.accessToken.value ? 'Open studio' : 'Create account')
const solutions = [
  { slug: 'studios-media-teams', title: 'Studios & media teams', text: 'Keep trailers, behind-the-scenes stories, release education and fan content moving without adding another production queue.', icon: Clapperboard, accent: 'purple' },
  { slug: 'creators-experts', title: 'Creators & experts', text: 'Turn your expertise and audience questions into a balanced stream of useful, entertaining and promotional videos.', icon: Users, accent: 'blue' },
  { slug: 'small-businesses', title: 'Small businesses', text: 'Stay visible with regular video even when nobody on the team has time to research, script, render and post every week.', icon: BriefcaseBusiness, accent: 'amber' },
  { slug: 'education-teams', title: 'Education teams', text: 'Translate courses, research and teaching insight into short videos that inform learners and attract the right audience.', icon: GraduationCap, accent: 'green' },
]

useSeoMeta({
  title: 'Framewise Solutions — Autonomous Video for Every Content Team',
  description: 'See how Framewise automates topic research, AI video production, publishing and performance learning for studios, creators, businesses and education teams.',
  ogTitle: 'Framewise solutions for always-on video',
  ogDescription: 'One autonomous production workflow, adapted to the audience and content goals of your team.',
})
useHead({ link: [{ rel: 'canonical', href: 'https://studio.subschool.us/solutions' }] })
</script>

<template>
  <div class="solutions-page">
    <header class="public-header">
      <div class="public-container public-header__inner">
        <NuxtLink class="public-brand" to="/"><span><Clapperboard :size="20" /></span><strong>Framewise</strong></NuxtLink>
        <nav><NuxtLink to="/#product">Product</NuxtLink><NuxtLink class="active" to="/solutions">Solutions</NuxtLink><NuxtLink to="/#workflow">How it works</NuxtLink><NuxtLink to="/#examples">Examples</NuxtLink><NuxtLink to="/#pricing">Pricing</NuxtLink></nav>
        <div class="public-actions"><NuxtLink v-if="!auth.accessToken.value" to="/login">Sign in</NuxtLink><NuxtLink class="public-button" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="14" /></NuxtLink></div>
        <button class="public-menu" type="button" aria-label="Toggle navigation" @click="menuOpen=!menuOpen"><X v-if="menuOpen" /><Menu v-else /></button>
      </div>
      <div v-if="menuOpen" class="mobile-nav"><NuxtLink to="/">Product</NuxtLink><NuxtLink to="/solutions">Solutions</NuxtLink><NuxtLink to="/#workflow">How it works</NuxtLink><NuxtLink to="/login">Sign in</NuxtLink></div>
    </header>

    <main>
      <section class="solutions-hero">
        <div class="orb orb--one" /><div class="orb orb--two" />
        <div class="public-container">
          <span class="eyebrow">Solutions by audience</span>
          <h1>One autonomous studio.<br><em>Different jobs to be done.</em></h1>
          <p>Framewise learns the context once, then adapts research, content mix, video format and publishing cadence to the audience your team needs to reach.</p>
        </div>
      </section>

      <section class="solutions-grid-section">
        <div class="public-container solutions-grid">
          <NuxtLink v-for="item in solutions" :key="item.slug" :to="`/solutions/${item.slug}`" :class="['solution-card',`solution-card--${item.accent}`]">
            <span class="solution-card__icon"><component :is="item.icon" :size="24" /></span>
            <div><h2>{{ item.title }}</h2><p>{{ item.text }}</p></div>
            <span class="solution-card__link">Explore solution <ArrowRight :size="15" /></span>
          </NuxtLink>
        </div>
      </section>

      <section class="shared-engine">
        <div class="public-container shared-engine__inner">
          <div><span class="eyebrow">The shared engine</span><h2>Every solution closes the same content loop.</h2><p>Audience-aware research discovers what is worth saying. Gemini plans and critiques it. Veo creates it. Connected channels publish it. Measured performance becomes a cautious signal for the next research cycle.</p></div>
          <div class="engine-steps"><span><b>01</b> Learn</span><span><b>02</b> Research</span><span><b>03</b> Create</span><span><b>04</b> Publish</span><span><b>05</b> Improve</span></div>
        </div>
      </section>

      <section class="solutions-cta"><div class="public-container"><Sparkles :size="24" /><h2>Start with your website, not a blank prompt.</h2><p>Choose the workflow depth that fits your team—from research only to fully automatic publication.</p><NuxtLink class="public-button public-button--light" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="15" /></NuxtLink></div></section>
    </main>

    <footer><div class="public-container"><NuxtLink class="public-brand public-brand--footer" to="/"><span><Clapperboard :size="18" /></span><strong>Framewise</strong></NuxtLink><span>Autonomous research, video creation and publishing.</span><div><NuxtLink to="/solutions">Solutions</NuxtLink><NuxtLink to="/login">Sign in</NuxtLink></div></div></footer>
  </div>
</template>

<style scoped>
.solutions-page{--ink:#17131f;--muted:#69616e;--line:#e7dfe9;min-height:100vh;background:#fbfaf8;color:var(--ink)}.public-container{width:min(1180px,calc(100% - 44px));margin:auto}.public-header{position:relative;z-index:20;border-bottom:1px solid rgb(40 26 44/8%);background:rgb(251 250 248/90%);backdrop-filter:blur(18px)}.public-header__inner{display:flex;height:76px;align-items:center}.public-brand{display:flex;align-items:center;gap:9px;font-family:var(--font-display);font-size:16px}.public-brand>span{display:grid;width:36px;height:36px;place-items:center;border-radius:10px;background:linear-gradient(145deg,#c37ad4,#792a8d);color:white}.public-header nav{display:flex;gap:28px;margin:auto}.public-header nav a,.public-actions>a:first-child{color:#5d5762;font-size:11px;font-weight:700}.public-header nav a.active,.public-header nav a:hover{color:#78258b}.public-actions{display:flex;align-items:center;gap:18px}.public-button{display:inline-flex;min-height:40px;align-items:center;justify-content:center;gap:7px;padding:0 16px;border-radius:10px;background:#19141e;color:white;font-size:10px;font-weight:800}.public-menu,.mobile-nav{display:none}.solutions-hero{position:relative;overflow:hidden;padding:106px 0 96px;background:radial-gradient(circle at 65% 18%,rgb(211 156 223/22%),transparent 31%)}.orb{position:absolute;border-radius:50%;pointer-events:none}.orb--one{top:-180px;right:-140px;width:520px;height:520px;border:1px solid rgb(150 73 168/11%);box-shadow:0 0 0 70px rgb(150 73 168/3%),0 0 0 140px rgb(150 73 168/2%)}.eyebrow{color:#8e2fa3;font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.16em}.solutions-hero h1{max-width:900px;margin:18px 0 23px;font-family:var(--font-display);font-size:clamp(45px,6vw,76px);line-height:1;letter-spacing:-.065em}.solutions-hero h1 em{color:#7b278e;font-style:normal}.solutions-hero p{max-width:720px;margin:0;color:var(--muted);font-size:15px;line-height:1.72}.solutions-grid-section{padding:0 0 110px}.solutions-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.solution-card{display:grid;min-height:280px;padding:30px;border:1px solid var(--line);border-radius:19px;background:white;box-shadow:0 20px 55px rgb(42 24 47/7%);transition:.2s}.solution-card:hover{transform:translateY(-3px);box-shadow:0 26px 65px rgb(42 24 47/11%)}.solution-card__icon{display:grid;width:50px;height:50px;place-items:center;border-radius:14px;background:#f7eafa;color:#8e2fa3}.solution-card--blue .solution-card__icon{background:#eaf3fb;color:#337aad}.solution-card--amber .solution-card__icon{background:#fff2dc;color:#a36b11}.solution-card--green .solution-card__icon{background:#e8f6ed;color:#248555}.solution-card h2{margin:34px 0 8px;font-family:var(--font-display);font-size:25px;letter-spacing:-.04em}.solution-card p{max-width:480px;margin:0;color:var(--muted);font-size:11px;line-height:1.65}.solution-card__link{display:flex;align-items:center;gap:7px;align-self:end;margin-top:25px;color:#78258b;font-size:10px;font-weight:850}.shared-engine{padding:105px 0;background:#19141e;color:white}.shared-engine__inner{display:grid;grid-template-columns:1fr 1fr;align-items:center;gap:100px}.shared-engine h2{margin:14px 0;font-family:var(--font-display);font-size:42px;line-height:1.05;letter-spacing:-.055em}.shared-engine p{margin:0;color:#bdb4c1;font-size:12px;line-height:1.75}.engine-steps{display:grid;border:1px solid rgb(255 255 255/9%);border-radius:16px}.engine-steps span{display:flex;align-items:center;gap:17px;padding:17px 20px;border-bottom:1px solid rgb(255 255 255/8%);font-size:12px;font-weight:700}.engine-steps span:last-child{border:0}.engine-steps b{color:#d895e7;font-size:9px}.solutions-cta{padding:105px 0;background:linear-gradient(135deg,#9d45b3,#642174);color:white;text-align:center}.solutions-cta h2{margin:17px auto 10px;font-family:var(--font-display);font-size:44px;letter-spacing:-.055em}.solutions-cta p{margin:0 0 25px;color:#efdff2;font-size:12px}.public-button--light{background:white;color:#5d196b}footer{padding:35px 0;background:#100d14;color:#a79faa}footer>.public-container{display:flex;align-items:center;gap:18px}footer>.public-container>span{font-size:9px}footer>.public-container>div{display:flex;gap:20px;margin-left:auto;font-size:9px}.public-brand--footer{color:white;font-size:13px}.public-brand--footer>span{width:30px;height:30px}@media(max-width:800px){.public-header nav,.public-actions{display:none}.public-menu{display:grid;margin-left:auto;background:transparent}.mobile-nav{display:grid;gap:4px;padding:8px 22px 17px}.mobile-nav a{padding:9px;font-size:11px}.solutions-hero{padding:75px 0}.solutions-grid,.shared-engine__inner{grid-template-columns:1fr}.shared-engine__inner{gap:45px}.solutions-cta h2{font-size:35px}}@media(max-width:520px){.public-container{width:min(100% - 30px,1180px)}.solutions-hero h1{font-size:43px}.solution-card{min-height:250px;padding:24px}footer>.public-container{align-items:flex-start;flex-direction:column}footer>.public-container>div{margin-left:0}}
</style>
