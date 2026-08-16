<script setup lang="ts">
import {
  ArrowRight,
  BadgeCheck,
  BarChart3,
  Bot,
  Check,
  ChevronRight,
  CircleDollarSign,
  Clapperboard,
  Clock3,
  FileCheck2,
  Film,
  Globe2,
  Layers3,
  LockKeyhole,
  Menu,
  Play,
  Radar,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  WandSparkles,
  X,
  Zap,
} from 'lucide-vue-next'

interface PublicPrice {
  feature_key: string
  label: string
  unit: string
  charge_tokens: number
}

interface PublicPricing {
  beta_monthly_usd: number
  welcome_tokens: number
  prices: PublicPrice[]
}

const auth = useAuth()
const config = useRuntimeConfig()
const menuOpen = ref(false)

const fallbackPricing: PublicPricing = {
  beta_monthly_usd: 0,
  welcome_tokens: 1000,
  prices: [
    { feature_key: 'project.website_analysis', label: 'Website and brand analysis', unit: 'analysis', charge_tokens: 30 },
    { feature_key: 'research.run', label: 'Agentic web research', unit: 'research run', charge_tokens: 75 },
    { feature_key: 'video.scene_regenerate', label: 'AI scene regeneration', unit: 'scene', charge_tokens: 100 },
    { feature_key: 'video.generate', label: 'AI video production', unit: 'variant / aspect ratio', charge_tokens: 500 },
  ],
}

const { data: pricing } = await useAsyncData<PublicPricing>('landing-pricing', async () => {
  try {
    return await $fetch<PublicPricing>('/v1/billing/public-pricing', { baseURL: config.public.apiBase })
  }
  catch {
    return fallbackPricing
  }
}, { default: () => fallbackPricing })

const primaryCta = computed(() => auth.accessToken.value ? '/app' : '/register')
const primaryLabel = computed(() => auth.accessToken.value ? 'Open studio' : 'Start free')

const workflow = [
  { number: '01', title: 'Understand your brand', text: 'Framewise reads your website, builds a private brand profile and keeps claims, tone and visual rules attached to every production.', icon: Globe2 },
  { number: '02', title: 'Find evidence-backed ideas', text: 'Parallel searches fresh demand and primary sources. Every proposed angle keeps its citations and an explainable opportunity score.', icon: Radar },
  { number: '03', title: 'Generate the production', text: 'Gemini plans the script and storyboard. Veo creates native scenes, Google voices the narration and the studio assembles every format.', icon: WandSparkles },
  { number: '04', title: 'Review before publishing', text: 'Technical and editorial QA catches weak claims, format issues and policy risks. You approve the final version—never a black box.', icon: FileCheck2 },
  { number: '05', title: 'Publish, measure, learn', text: 'Publish through official provider flows, collect 24-hour and 7-day signals, and turn observed performance into the next strategy.', icon: BarChart3 },
]

const features = [
  { title: 'Research with provenance', text: 'Fresh web research, source controls, deduplication and citations that remain attached from idea to script.', icon: Search },
  { title: 'One production, every format', text: 'Generate native 9:16 and 16:9 versions with narration, downloadable subtitles, optional clean captions, manifests and immutable revision history.', icon: Layers3 },
  { title: 'Durable agent workflows', text: 'Every expensive stage is checkpointed. Interrupted jobs resume without silently repeating finished provider work.', icon: RefreshCw },
  { title: 'Human approval gates', text: 'Pause automation, regenerate a scene, compare revisions and require explicit consent before external publication.', icon: BadgeCheck },
  { title: 'Private by architecture', text: 'Tenant-isolated projects, signed media links, scoped API keys and encrypted OAuth credentials protect every workspace.', icon: LockKeyhole },
  { title: 'Costs you can inspect', text: 'Token charges, provider costs and every balance change appear in an immutable ledger—before and after production.', icon: CircleDollarSign },
]

const faqs = [
  { question: 'Is Framewise another prompt-to-video generator?', answer: 'No. Framewise is an agentic video production system. It researches the topic, preserves evidence, plans the script and scenes, renders each format, runs QA, asks for approval and measures the result.' },
  { question: 'Which AI providers does it use?', answer: 'The live pipeline uses Parallel for web research and Google Cloud for Gemini planning and QA, Veo video generation, Text-to-Speech, storage and workflow infrastructure.' },
  { question: 'Can Framewise publish without my approval?', answer: 'Not unless you deliberately configure an approval policy that allows it. External publishing is capability-aware, audited and protected by confirmation gates.' },
  { question: 'Is my project data visible to other customers?', answer: 'No. Accounts receive separate organizations and projects. API authorization, media delivery and database access are tenant-scoped.' },
  { question: 'What happens when an AI provider fails?', answer: 'Production stages are persisted and retryable. Framewise reports provider failures honestly and resumes from completed checkpoints instead of inventing results.' },
  { question: 'How much does it cost?', answer: 'The public beta has no monthly fee and includes 1,000 welcome AI tokens after email verification. Usage is charged transparently by operation; the current rates are shown below.' },
]

useSeoMeta({
  title: 'Framewise — Agentic AI Video Studio for Evidence-Backed Content',
  description: 'Research, script, generate, review and publish evidence-backed social video with Parallel, Gemini and Veo. Private workspaces, human approvals and transparent usage pricing.',
  ogTitle: 'Framewise — From verified idea to publish-ready video',
  ogDescription: 'An agentic AI video studio that researches first, generates with Google Veo, checks every output and keeps you in control.',
  ogType: 'website',
  ogUrl: 'https://studio.subschool.us/',
  ogSiteName: 'Framewise',
  twitterCard: 'summary_large_image',
  twitterTitle: 'Framewise — Agentic AI Video Studio',
  twitterDescription: 'Evidence-backed research, AI video production, QA, approval and publishing in one private workspace.',
  robots: 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1',
})

useHead({
  link: [{ rel: 'canonical', href: 'https://studio.subschool.us/' }],
  meta: [{ name: 'keywords', content: 'AI video generator, agentic video studio, automated video production, evidence based content, AI social media video, Veo video generator, content research automation, video content workflow' }],
  script: [
    {
      type: 'application/ld+json',
      innerHTML: JSON.stringify({
        '@context': 'https://schema.org',
        '@type': 'SoftwareApplication',
        name: 'Framewise',
        applicationCategory: 'MultimediaApplication',
        operatingSystem: 'Web',
        url: 'https://studio.subschool.us/',
        description: 'Agentic AI video studio for evidence-backed research, generation, review, publishing and analytics.',
        offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD', description: 'Public beta with 1,000 welcome AI tokens.' },
        featureList: ['Agentic web research', 'AI video generation', 'Human approval workflows', 'Multi-format rendering', 'Publishing analytics'],
      }),
    },
    {
      type: 'application/ld+json',
      innerHTML: JSON.stringify({
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: faqs.map(item => ({
          '@type': 'Question',
          name: item.question,
          acceptedAnswer: { '@type': 'Answer', text: item.answer },
        })),
      }),
    },
  ] as any,
})
</script>

<template>
  <div class="landing">
    <header class="landing-header">
      <div class="landing-container landing-header__inner">
        <NuxtLink class="landing-brand" to="/" aria-label="Framewise home">
          <span class="landing-brand__mark"><Clapperboard :size="21" /></span>
          <span><strong>Framewise</strong><small>Agentic video studio</small></span>
        </NuxtLink>

        <nav class="landing-nav" aria-label="Main navigation">
          <a href="#product">Product</a>
          <a href="#workflow">How it works</a>
          <a href="#pricing">Pricing</a>
          <a href="#security">Security</a>
        </nav>

        <div class="landing-header__actions">
          <NuxtLink v-if="!auth.accessToken.value" class="landing-link" to="/login">Sign in</NuxtLink>
          <NuxtLink class="landing-button landing-button--small" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="15" /></NuxtLink>
        </div>

        <button class="landing-menu" type="button" :aria-expanded="menuOpen" aria-label="Toggle navigation" @click="menuOpen = !menuOpen">
          <X v-if="menuOpen" :size="22" /><Menu v-else :size="22" />
        </button>
      </div>
      <div v-if="menuOpen" class="landing-mobile-nav">
        <a href="#product" @click="menuOpen = false">Product</a>
        <a href="#workflow" @click="menuOpen = false">How it works</a>
        <a href="#pricing" @click="menuOpen = false">Pricing</a>
        <a href="#security" @click="menuOpen = false">Security</a>
        <NuxtLink v-if="!auth.accessToken.value" to="/login" @click="menuOpen = false">Sign in</NuxtLink>
        <NuxtLink class="landing-button" :to="primaryCta" @click="menuOpen = false">{{ primaryLabel }} <ArrowRight :size="15" /></NuxtLink>
      </div>
    </header>

    <main>
      <section class="landing-hero">
        <div class="landing-glow landing-glow--one" /><div class="landing-glow landing-glow--two" />
        <div class="landing-container landing-hero__grid">
          <div class="landing-hero__copy">
            <div class="landing-pill"><span /><strong>Live with Parallel + Google Cloud</strong></div>
            <h1>The AI video studio that <em>checks the facts</em> before it hits render.</h1>
            <p>Framewise turns your website and fresh evidence into publish-ready social video—research, script, Veo scenes, narration, QA, approval and analytics in one private workflow.</p>
            <div class="landing-hero__actions">
              <NuxtLink class="landing-button landing-button--primary" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="17" /></NuxtLink>
              <a class="landing-button landing-button--ghost" href="#workflow"><Play :size="15" /> See how it works</a>
            </div>
            <div class="landing-hero__note"><Check :size="15" /> 1,000 welcome tokens <span>·</span> No card required <span>·</span> Private workspace</div>
          </div>

          <div class="studio-preview" aria-label="Framewise production workflow preview">
            <div class="studio-preview__topbar">
              <div class="studio-preview__brand"><span><Clapperboard :size="13" /></span> Framewise</div>
              <div class="studio-preview__status"><i /> Systems operational</div>
            </div>
            <div class="studio-preview__body">
              <aside class="preview-sidebar">
                <div class="preview-project"><span>SS</span><div><strong>SubSchool</strong><small>Active project</small></div></div>
                <div class="preview-nav"><span class="active"><Zap :size="12" /> Overview</span><span><Radar :size="12" /> Research</span><span><Film :size="12" /> Productions</span><span><BarChart3 :size="12" /> Analytics</span></div>
              </aside>
              <div class="preview-main">
                <div class="preview-heading"><div><small>Production / In progress</small><strong>Why AI-native teams move faster</strong></div><span>82<small>score</small></span></div>
                <div class="preview-stage">
                  <div class="preview-video"><span class="preview-play"><Play :size="16" /></span><div class="preview-caption">Build once. Learn every time.</div><small>00:18 / 00:30</small></div>
                  <div class="preview-timeline">
                    <span class="done"><Check :size="10" /><b>Research</b><small>4 sources</small></span>
                    <span class="done"><Check :size="10" /><b>Script</b><small>3 variants</small></span>
                    <span class="live"><Sparkles :size="10" /><b>Veo scenes</b><small>Generating 4/5</small></span>
                    <span><Bot :size="10" /><b>Final QA</b><small>Queued</small></span>
                  </div>
                </div>
                <div class="preview-footer"><span><ShieldCheck :size="11" /> 7 claims sourced</span><span><Clock3 :size="11" /> Checkpoint saved</span><strong>$2.14 live cost</strong></div>
              </div>
            </div>
          </div>
        </div>

        <div class="landing-container provider-strip">
          <span>Built on production APIs from</span>
          <div><strong>Parallel</strong><strong>Google Gemini</strong><strong>Veo 3.1</strong><strong>YouTube</strong><strong>Cloud Run</strong></div>
        </div>
      </section>

      <section class="landing-section landing-outcomes">
        <div class="landing-container outcome-grid">
          <article><strong>5</strong><span>durable production stages</span></article>
          <article><strong>2</strong><span>native aspect ratios per brief</span></article>
          <article><strong>24h + 7d</strong><span>performance learning windows</span></article>
          <article><strong>100%</strong><span>tenant-isolated project data</span></article>
        </div>
      </section>

      <section id="product" class="landing-section landing-problem">
        <div class="landing-container">
          <div class="section-intro section-intro--split">
            <div><span class="landing-eyebrow">From tool sprawl to one system</span><h2>AI can make clips. Your team still has to make the <em>content operation.</em></h2></div>
            <p>Most generators start at the prompt and stop at the file. Framewise connects the decisions before and after generation, so every video is grounded, reviewable and useful to the next one.</p>
          </div>
          <div class="comparison-grid">
            <article class="comparison-card comparison-card--old">
              <span>Disconnected workflow</span><h3>Seven tabs, no memory</h3>
              <ul><li><X :size="15" /> Ideas detached from evidence</li><li><X :size="15" /> Prompts rebuilt for every format</li><li><X :size="15" /> Failed renders restart from zero</li><li><X :size="15" /> Analytics never reaches the next brief</li></ul>
            </article>
            <article class="comparison-card comparison-card--new">
              <span>The Framewise loop</span><h3>One brief that keeps learning</h3>
              <ul><li><Check :size="15" /> Sources follow claims into the script</li><li><Check :size="15" /> Brand rules travel through every agent</li><li><Check :size="15" /> Durable checkpoints protect provider spend</li><li><Check :size="15" /> Real outcomes propose the next strategy</li></ul>
            </article>
          </div>
        </div>
      </section>

      <section id="workflow" class="landing-section landing-workflow">
        <div class="landing-container">
          <div class="section-intro"><span class="landing-eyebrow">How Framewise works</span><h2>From your website to a production system.</h2><p>Each agent has a bounded job, visible inputs and a checkpoint. You can inspect, pause or approve the workflow at every meaningful decision.</p></div>
          <div class="workflow-list">
            <article v-for="item in workflow" :key="item.number" class="workflow-item">
              <span class="workflow-item__number">{{ item.number }}</span>
              <span class="workflow-item__icon"><component :is="item.icon" :size="20" /></span>
              <div><h3>{{ item.title }}</h3><p>{{ item.text }}</p></div>
              <ChevronRight :size="18" />
            </article>
          </div>
        </div>
      </section>

      <section class="landing-section landing-features">
        <div class="landing-container">
          <div class="section-intro"><span class="landing-eyebrow">A studio, not a slot machine</span><h2>Everything your AI video workflow needs to stay credible.</h2></div>
          <div class="feature-grid">
            <article v-for="feature in features" :key="feature.title" class="feature-card"><span><component :is="feature.icon" :size="20" /></span><h3>{{ feature.title }}</h3><p>{{ feature.text }}</p></article>
          </div>
        </div>
      </section>

      <section id="pricing" class="landing-section landing-pricing">
        <div class="landing-container pricing-layout">
          <div class="pricing-copy">
            <span class="landing-eyebrow">Transparent public beta pricing</span>
            <h2>Start with a real production, not a sales call.</h2>
            <p>Create a workspace, confirm your email and use the included tokens across the same live Parallel and Google pipeline used by the production studio.</p>
            <ul><li><Check :size="15" /> No monthly platform fee during beta</li><li><Check :size="15" /> Every charge appears in your ledger</li><li><Check :size="15" /> Admin-controlled prices update transparently</li><li><Check :size="15" /> Pause before any expensive generation</li></ul>
          </div>
          <article class="pricing-card">
            <div class="pricing-card__head"><div><span>Public beta</span><h3>Starter workspace</h3></div><span class="pricing-badge">Available now</span></div>
            <div class="pricing-value"><strong>${{ pricing.beta_monthly_usd }}</strong><span>/ month</span></div>
            <p><b>{{ Number(pricing.welcome_tokens).toLocaleString() }}</b> AI tokens included after email verification.</p>
            <div class="pricing-lines">
              <div v-for="item in pricing.prices" :key="item.feature_key"><span><strong>{{ item.label }}</strong><small>per {{ item.unit }}</small></span><b>{{ Number(item.charge_tokens).toLocaleString() }} tokens</b></div>
            </div>
            <NuxtLink class="landing-button landing-button--primary landing-button--wide" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="16" /></NuxtLink>
            <small class="pricing-fineprint">Need more capacity? Additional beta credits are issued through workspace promo codes. Self-serve paid top-ups are not enabled yet.</small>
          </article>
        </div>
      </section>

      <section id="security" class="landing-section landing-security">
        <div class="landing-container security-card">
          <div class="security-card__copy"><span class="landing-eyebrow">Private by architecture</span><h2>Your campaign is not somebody else’s context window.</h2><p>Framewise separates organizations at the API, data and media layers. Provider credentials stay encrypted, files use expiring links and every external action is attributable.</p><NuxtLink class="landing-button landing-button--light" :to="primaryCta">Create a private workspace <ArrowRight :size="16" /></NuxtLink></div>
          <div class="security-grid"><article><ShieldCheck :size="22" /><strong>Tenant isolation</strong><span>Organization and project scopes on every resource.</span></article><article><LockKeyhole :size="22" /><strong>Encrypted secrets</strong><span>OAuth tokens and API credentials never reach the browser.</span></article><article><FileCheck2 :size="22" /><strong>Audited actions</strong><span>Approvals, costs and publications keep immutable history.</span></article><article><RefreshCw :size="22" /><strong>Safe recovery</strong><span>Idempotency and checkpoints prevent duplicate side effects.</span></article></div>
        </div>
      </section>

      <section class="landing-section landing-faq">
        <div class="landing-container faq-layout">
          <div class="section-intro"><span class="landing-eyebrow">Frequently asked</span><h2>The practical questions, answered.</h2><p>Framewise is live software, not a concept page. These answers describe the current production service.</p></div>
          <div class="faq-list"><details v-for="(item, index) in faqs" :key="item.question" :open="index === 0"><summary>{{ item.question }}<span>+</span></summary><p>{{ item.answer }}</p></details></div>
        </div>
      </section>

      <section class="landing-final-cta">
        <div class="landing-glow landing-glow--three" />
        <div class="landing-container"><span class="landing-eyebrow">Your next video can start with evidence</span><h2>Turn one website into a repeatable content engine.</h2><p>Research the opportunity. Generate the story. Keep the final decision.</p><div><NuxtLink class="landing-button landing-button--primary" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="17" /></NuxtLink><NuxtLink v-if="!auth.accessToken.value" class="landing-button landing-button--dark" to="/login">Sign in</NuxtLink></div></div>
      </section>
    </main>

    <footer class="landing-footer">
      <div class="landing-container landing-footer__grid">
        <div><NuxtLink class="landing-brand landing-brand--footer" to="/"><span class="landing-brand__mark"><Clapperboard :size="20" /></span><span><strong>Framewise</strong><small>Agentic video studio</small></span></NuxtLink><p>Evidence-first AI video production for teams that care what they publish.</p></div>
        <div><strong>Product</strong><a href="#workflow">How it works</a><a href="#pricing">Pricing</a><a href="#security">Security</a></div>
        <div><strong>Workspace</strong><NuxtLink to="/register">Create account</NuxtLink><NuxtLink to="/login">Sign in</NuxtLink><a href="https://github.com/SubSchoolLTD/agentic-video-studio" rel="noopener">GitHub</a></div>
        <div><strong>Technology</strong><span>Parallel Search</span><span>Google Gemini</span><span>Google Veo</span></div>
      </div>
      <div class="landing-container landing-footer__bottom"><span>© {{ new Date().getFullYear() }} Framewise</span><span>Built for the Agentic Cinema Hackathon</span></div>
    </footer>
  </div>
</template>

<style scoped>
.landing{--landing-ink:#17131f;--landing-muted:#67616d;--landing-line:#e8e2e9;--landing-purple:#a64fbc;--landing-purple-dark:#732386;overflow:hidden;background:#fbfaf8;color:var(--landing-ink)}
.landing-container{width:min(1180px,calc(100% - 44px));margin:0 auto}.landing-header{position:relative;z-index:80;border-bottom:1px solid rgb(37 27 42 / 7%);background:rgb(251 250 248 / 88%);backdrop-filter:blur(18px)}.landing-header__inner{display:flex;height:76px;align-items:center}.landing-brand{display:inline-flex;align-items:center;gap:10px}.landing-brand__mark{display:grid;width:37px;height:37px;place-items:center;border-radius:11px;background:linear-gradient(145deg,#c37ad4,#792a8d);color:white;box-shadow:0 8px 22px rgb(142 49 163 / 24%)}.landing-brand>span:last-child{display:grid;gap:0}.landing-brand strong{font-family:var(--font-display);font-size:16px;letter-spacing:-.035em}.landing-brand small{color:#89818d;font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.12em}.landing-nav{display:flex;gap:31px;margin:auto}.landing-nav a,.landing-link{color:#5d5762;font-size:12px;font-weight:650;transition:.18s}.landing-nav a:hover,.landing-link:hover{color:var(--landing-purple-dark)}.landing-header__actions{display:flex;align-items:center;gap:19px}.landing-menu{display:none;background:transparent}.landing-mobile-nav{display:none}
.landing-button{display:inline-flex;min-height:48px;align-items:center;justify-content:center;gap:8px;padding:0 20px;border:1px solid transparent;border-radius:11px;font-size:12px;font-weight:800;transition:transform .18s,box-shadow .18s,background .18s}.landing-button:hover{transform:translateY(-1px)}.landing-button--small{min-height:39px;padding:0 15px;background:var(--landing-ink);color:white}.landing-button--primary{background:linear-gradient(135deg,#b25bc6,#7e2a92);color:white;box-shadow:0 13px 30px rgb(126 42 146 / 23%)}.landing-button--primary:hover{box-shadow:0 17px 36px rgb(126 42 146 / 31%)}.landing-button--ghost{border-color:#dcd4de;background:rgb(255 255 255 / 65%)}.landing-button--dark{border-color:rgb(255 255 255 / 17%);background:rgb(255 255 255 / 6%);color:white}.landing-button--light{background:white;color:#4f195d}.landing-button--wide{width:100%}
.landing-hero{position:relative;padding:83px 0 0;background:radial-gradient(circle at 62% 18%,rgb(237 210 243 / 45%),transparent 27%),linear-gradient(180deg,#fbfaf8 0,#f8f5f8 100%)}.landing-glow{position:absolute;border-radius:50%;filter:blur(2px);pointer-events:none}.landing-glow--one{top:40px;right:-170px;width:430px;height:430px;background:radial-gradient(circle,rgb(195 122 212 / 16%),transparent 68%)}.landing-glow--two{bottom:20px;left:-160px;width:380px;height:380px;background:radial-gradient(circle,rgb(105 166 217 / 10%),transparent 68%)}.landing-hero__grid{position:relative;display:grid;grid-template-columns:minmax(0,.89fr) minmax(570px,1.11fr);align-items:center;gap:66px}.landing-pill{display:inline-flex;align-items:center;gap:8px;padding:7px 11px;border:1px solid #e2d7e5;border-radius:99px;background:rgb(255 255 255 / 65%);color:#6b476f;font-size:9px;letter-spacing:.05em;text-transform:uppercase}.landing-pill span{width:7px;height:7px;border-radius:50%;background:#32a46c;box-shadow:0 0 0 4px rgb(50 164 108 / 11%)}.landing-hero h1{max-width:650px;margin:24px 0 20px;font-family:var(--font-display);font-size:clamp(45px,5vw,72px);font-weight:650;line-height:.99;letter-spacing:-.065em}.landing-hero h1 em,.section-intro h2 em{color:var(--landing-purple-dark);font-style:normal}.landing-hero__copy>p{max-width:610px;margin:0;color:var(--landing-muted);font-size:16px;line-height:1.72}.landing-hero__actions{display:flex;gap:11px;margin-top:30px}.landing-hero__note{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:17px;color:#746d79;font-size:10px}.landing-hero__note svg{color:#26905d}.landing-hero__note span{color:#b8b0ba}
.studio-preview{position:relative;overflow:hidden;border:1px solid rgb(60 39 67 / 12%);border-radius:19px;background:#fff;box-shadow:0 35px 90px rgb(38 23 44 / 16%),0 3px 9px rgb(38 23 44 / 5%);transform:rotate(1deg)}.studio-preview::before{position:absolute;z-index:3;inset:0;border:1px solid rgb(255 255 255 / 75%);border-radius:inherit;content:'';pointer-events:none}.studio-preview__topbar{display:flex;height:43px;align-items:center;justify-content:space-between;padding:0 13px;border-bottom:1px solid #ede9ee;background:#faf9fa}.studio-preview__brand{display:flex;align-items:center;gap:6px;font-size:9px;font-weight:800}.studio-preview__brand span{display:grid;width:20px;height:20px;place-items:center;border-radius:6px;background:#8d2ea3;color:white}.studio-preview__status{display:flex;align-items:center;gap:5px;color:#77717b;font-size:7px}.studio-preview__status i{width:5px;height:5px;border-radius:50%;background:#28a169}.studio-preview__body{display:grid;min-height:380px;grid-template-columns:128px 1fr}.preview-sidebar{padding:13px 9px;background:#1a1520;color:#eee9f0}.preview-project{display:flex;align-items:center;gap:7px;padding:7px;border:1px solid rgb(255 255 255 / 7%);border-radius:8px;background:rgb(255 255 255 / 5%)}.preview-project>span{display:grid;width:25px;height:25px;place-items:center;border-radius:7px;background:#f1e0f5;color:#76208a;font-size:7px;font-weight:900}.preview-project div{display:grid;gap:1px}.preview-project strong{font-size:7px}.preview-project small{color:#a9a0ae;font-size:6px}.preview-nav{display:grid;gap:3px;margin-top:15px}.preview-nav span{display:flex;align-items:center;gap:7px;padding:7px;border-radius:7px;color:#aaa2af;font-size:7px}.preview-nav span.active{background:linear-gradient(90deg,rgb(162 76 184 / 28%),rgb(162 76 184 / 7%));color:white}.preview-main{min-width:0;padding:17px;background:#f7f6f4}.preview-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.preview-heading>div{display:grid;gap:3px}.preview-heading small{color:#8a848e;font-size:6px}.preview-heading strong{font-family:var(--font-display);font-size:12px}.preview-heading>span{display:grid;width:42px;height:42px;place-items:center;align-content:center;border:4px solid #ead7ee;border-top-color:#9e43b4;border-radius:50%;color:#76208a;font-family:var(--font-display);font-size:12px;font-weight:800}.preview-heading>span small{font-family:var(--font-sans);font-size:5px;font-weight:600}.preview-stage{display:grid;grid-template-columns:1.24fr .76fr;gap:9px;margin-top:15px}.preview-video{position:relative;display:grid;min-height:245px;place-items:center;overflow:hidden;border-radius:11px;background:radial-gradient(circle at 50% 33%,#5f3a69,#1b1420 66%);color:white}.preview-video::before{position:absolute;width:170px;height:170px;border:1px solid rgb(255 255 255 / 8%);border-radius:50%;box-shadow:0 0 0 24px rgb(255 255 255 / 2%),0 0 0 49px rgb(255 255 255 / 1%);content:''}.preview-play{position:relative;z-index:1;display:grid;width:42px;height:42px;place-items:center;border:1px solid rgb(255 255 255 / 18%);border-radius:50%;background:rgb(255 255 255 / 10%);backdrop-filter:blur(5px)}.preview-caption{position:absolute;right:16px;bottom:34px;left:16px;padding:6px;background:rgb(0 0 0 / 38%);font-size:8px;font-weight:800;text-align:center}.preview-video>small{position:absolute;right:10px;bottom:10px;color:#d4ccd7;font-size:6px}.preview-timeline{display:grid;align-content:start;gap:0;padding:9px;border:1px solid #e8e3e9;border-radius:11px;background:white}.preview-timeline span{position:relative;display:grid;min-height:52px;grid-template-columns:21px 1fr;align-content:center;padding-left:2px}.preview-timeline span:not(:last-child)::after{position:absolute;top:35px;bottom:-7px;left:12px;width:1px;background:#e5e0e6;content:''}.preview-timeline svg{grid-row:1/3;display:grid;width:21px;height:21px;align-self:center;margin-right:6px;padding:5px;border:1px solid #ded8e0;border-radius:50%;color:#958d99}.preview-timeline b{font-size:7px}.preview-timeline small{font-size:6px}.preview-timeline .done svg{border-color:#45a979;background:#e9f7ef;color:#268f60}.preview-timeline .live svg{border-color:#b764c9;background:#f7ecf9;color:#8d2ea3;box-shadow:0 0 0 4px rgb(162 76 184 / 7%)}.preview-timeline .live small{color:#8d2ea3}.preview-footer{display:flex;align-items:center;gap:9px;margin-top:11px;color:#7c7580;font-size:6px}.preview-footer span{display:flex;align-items:center;gap:3px}.preview-footer strong{margin-left:auto;color:#312935}.provider-strip{position:relative;display:flex;align-items:center;justify-content:space-between;gap:25px;margin-top:83px;padding:24px 0;border-top:1px solid rgb(44 29 49 / 8%)}.provider-strip>span{color:#8b848f;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.11em}.provider-strip div{display:flex;flex-wrap:wrap;gap:31px;color:#443c48}.provider-strip strong{font-family:var(--font-display);font-size:11px}
.landing-section{padding:105px 0}.landing-outcomes{padding:0;background:#fff}.outcome-grid{display:grid;grid-template-columns:repeat(4,1fr);border-right:1px solid var(--landing-line);border-left:1px solid var(--landing-line)}.outcome-grid article{display:grid;gap:4px;padding:34px;border-right:1px solid var(--landing-line)}.outcome-grid article:last-child{border:0}.outcome-grid strong{font-family:var(--font-display);font-size:26px;letter-spacing:-.05em}.outcome-grid span{color:var(--landing-muted);font-size:9px;line-height:1.4;text-transform:uppercase;letter-spacing:.07em}.landing-eyebrow{color:#8d2ea3;font-size:9px;font-weight:850;text-transform:uppercase;letter-spacing:.16em}.section-intro{max-width:760px;margin-bottom:47px}.section-intro h2,.pricing-copy h2,.security-card__copy h2{margin:13px 0 16px;font-family:var(--font-display);font-size:clamp(32px,4vw,49px);font-weight:650;line-height:1.06;letter-spacing:-.055em}.section-intro p,.pricing-copy>p,.security-card__copy>p{margin:0;color:var(--landing-muted);font-size:14px;line-height:1.75}.section-intro--split{display:grid;max-width:none;grid-template-columns:1.25fr .75fr;align-items:end;gap:80px}.section-intro--split p{padding-bottom:7px}.landing-problem{background:#fff}.comparison-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.comparison-card{padding:29px;border:1px solid var(--landing-line);border-radius:17px}.comparison-card>span{font-size:9px;font-weight:850;text-transform:uppercase;letter-spacing:.12em}.comparison-card h3{margin:10px 0 22px;font-family:var(--font-display);font-size:22px;letter-spacing:-.04em}.comparison-card ul,.pricing-copy ul{display:grid;gap:12px;margin:0;padding:0;list-style:none}.comparison-card li,.pricing-copy li{display:flex;align-items:center;gap:9px;color:#68616c;font-size:11px}.comparison-card--old{background:#f8f6f7}.comparison-card--old>span,.comparison-card--old svg{color:#b05d65}.comparison-card--new{border-color:#dbc6df;background:linear-gradient(145deg,#fbf5fc,#fff)}.comparison-card--new>span,.comparison-card--new svg{color:#268f60}
.landing-workflow{background:#f5f1f6}.workflow-list{display:grid;overflow:hidden;border:1px solid #e2d9e4;border-radius:18px;background:white}.workflow-item{display:grid;grid-template-columns:52px 48px 1fr auto;align-items:center;gap:16px;padding:22px 25px;border-bottom:1px solid var(--landing-line);transition:.18s}.workflow-item:last-child{border:0}.workflow-item:hover{background:#fdfafd}.workflow-item__number{color:#aaa2ad;font-family:var(--font-display);font-size:10px}.workflow-item__icon{display:grid;width:42px;height:42px;place-items:center;border-radius:12px;background:#f5e8f8;color:#8d2ea3}.workflow-item div{display:grid;gap:4px}.workflow-item h3{margin:0;font-family:var(--font-display);font-size:16px;letter-spacing:-.03em}.workflow-item p{max-width:760px;margin:0;color:var(--landing-muted);font-size:10px;line-height:1.55}.workflow-item>svg{color:#bbb3bd}
.landing-features{background:#1a151f;color:white}.landing-features .landing-eyebrow{color:#d798e7}.landing-features .section-intro{max-width:780px}.feature-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.feature-card{min-height:226px;padding:25px;border:1px solid rgb(255 255 255 / 8%);border-radius:15px;background:linear-gradient(145deg,rgb(255 255 255 / 6%),rgb(255 255 255 / 2%))}.feature-card>span{display:grid;width:40px;height:40px;place-items:center;border:1px solid rgb(215 152 231 / 19%);border-radius:11px;background:rgb(162 76 184 / 13%);color:#d798e7}.feature-card h3{margin:32px 0 9px;font-family:var(--font-display);font-size:17px;letter-spacing:-.03em}.feature-card p{margin:0;color:#bbb3bf;font-size:10px;line-height:1.65}
.landing-pricing{background:#fff}.pricing-layout{display:grid;grid-template-columns:.88fr 1.12fr;align-items:center;gap:90px}.pricing-copy ul{margin-top:28px}.pricing-copy li svg{color:#25915f}.pricing-card{padding:34px;border:1px solid #dacee0;border-radius:21px;background:linear-gradient(150deg,#fff,#faf5fb);box-shadow:0 27px 75px rgb(51 26 59 / 9%)}.pricing-card__head{display:flex;align-items:start;justify-content:space-between;gap:20px}.pricing-card__head>div{display:grid;gap:5px}.pricing-card__head>div>span{color:#8d2ea3;font-size:8px;font-weight:850;text-transform:uppercase;letter-spacing:.13em}.pricing-card__head h3{margin:0;font-family:var(--font-display);font-size:20px}.pricing-badge{padding:6px 8px;border-radius:99px;background:#e7f6ee;color:#21885a;font-size:8px;font-weight:800}.pricing-value{display:flex;align-items:end;gap:8px;margin:27px 0 5px}.pricing-value strong{font-family:var(--font-display);font-size:58px;line-height:1;letter-spacing:-.07em}.pricing-value span{padding-bottom:7px;color:var(--landing-muted);font-size:11px}.pricing-card>p{margin:0 0 24px;color:var(--landing-muted);font-size:11px}.pricing-card>p b{color:#76208a}.pricing-lines{display:grid;margin-bottom:25px;border-top:1px solid var(--landing-line)}.pricing-lines>div{display:flex;align-items:center;justify-content:space-between;gap:15px;padding:12px 0;border-bottom:1px solid var(--landing-line)}.pricing-lines span{display:grid;gap:2px}.pricing-lines strong{font-size:10px}.pricing-lines small{color:var(--landing-muted);font-size:8px}.pricing-lines b{font-size:10px}.pricing-fineprint{display:block;margin-top:12px;color:#8a838e;font-size:8px;line-height:1.5;text-align:center}
.landing-security{background:#f4eff5}.security-card{position:relative;display:grid;grid-template-columns:.92fr 1.08fr;overflow:hidden;border-radius:23px;background:linear-gradient(145deg,#3e1848,#18131e);color:white;box-shadow:0 25px 70px rgb(40 23 45 / 13%)}.security-card__copy{padding:57px}.security-card__copy .landing-eyebrow{color:#daa0e8}.security-card__copy>p{color:#c7bdca}.security-card__copy .landing-button{margin-top:27px}.security-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:rgb(255 255 255 / 9%)}.security-grid article{display:grid;align-content:center;gap:8px;min-height:215px;padding:30px;background:#211827}.security-grid svg{margin-bottom:12px;color:#d798e7}.security-grid strong{font-family:var(--font-display);font-size:14px}.security-grid span{color:#aea5b2;font-size:9px;line-height:1.6}
.landing-faq{background:#fff}.faq-layout{display:grid;grid-template-columns:.75fr 1.25fr;gap:100px}.faq-layout .section-intro{margin:0}.faq-list{display:grid}.faq-list details{border-bottom:1px solid var(--landing-line)}.faq-list summary{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:19px 0;cursor:pointer;font-family:var(--font-display);font-size:13px;font-weight:700;list-style:none}.faq-list summary::-webkit-details-marker{display:none}.faq-list summary span{display:grid;width:24px;height:24px;place-items:center;border-radius:50%;background:#f5e8f8;color:#8d2ea3;font-size:15px;transition:.18s}.faq-list details[open] summary span{transform:rotate(45deg)}.faq-list details p{margin:-3px 42px 21px 0;color:var(--landing-muted);font-size:10px;line-height:1.7}
.landing-final-cta{position:relative;padding:105px 0;overflow:hidden;background:#17131f;color:white;text-align:center}.landing-glow--three{top:-180px;left:calc(50% - 340px);width:680px;height:420px;background:radial-gradient(circle,rgb(178 91 198 / 25%),transparent 66%)}.landing-final-cta .landing-container{position:relative}.landing-final-cta .landing-eyebrow{color:#d798e7}.landing-final-cta h2{max-width:850px;margin:15px auto;font-family:var(--font-display);font-size:clamp(38px,5vw,62px);font-weight:650;line-height:1.03;letter-spacing:-.06em}.landing-final-cta p{margin:0;color:#bbb3bf;font-size:13px}.landing-final-cta .landing-container>div{display:flex;justify-content:center;gap:10px;margin-top:27px}.landing-footer{padding:58px 0 25px;background:#100d14;color:#b7afbb}.landing-footer__grid{display:grid;grid-template-columns:2fr repeat(3,1fr);gap:55px}.landing-brand--footer{color:white}.landing-footer__grid>div{display:grid;align-content:start;gap:10px}.landing-footer__grid>div:first-child p{max-width:310px;margin:9px 0 0;color:#8f8794;font-size:10px;line-height:1.6}.landing-footer__grid>div:not(:first-child)>strong{margin-bottom:5px;color:white;font-size:9px;text-transform:uppercase;letter-spacing:.12em}.landing-footer__grid a,.landing-footer__grid span{font-size:9px}.landing-footer__grid a:hover{color:white}.landing-footer__bottom{display:flex;justify-content:space-between;margin-top:48px;padding-top:19px;border-top:1px solid rgb(255 255 255 / 7%);color:#706976;font-size:8px}
@media(max-width:1050px){.landing-hero__grid{grid-template-columns:1fr;gap:55px}.landing-hero__copy{max-width:760px}.studio-preview{width:min(760px,100%);margin:auto;transform:none}.section-intro--split{grid-template-columns:1fr;gap:10px}.pricing-layout,.faq-layout{grid-template-columns:1fr;gap:55px}.pricing-card{max-width:680px}.security-card{grid-template-columns:1fr}.security-grid article{min-height:180px}.feature-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:760px){.landing-container{width:min(100% - 30px,1180px)}.landing-header__inner{height:66px}.landing-nav,.landing-header__actions{display:none}.landing-menu{display:grid;margin-left:auto}.landing-mobile-nav{display:grid;gap:3px;padding:7px 15px 16px;border-top:1px solid var(--landing-line);background:#fbfaf8}.landing-mobile-nav>a{padding:10px;border-radius:8px;font-size:11px;font-weight:700}.landing-mobile-nav .landing-button{margin-top:4px;color:white}.landing-hero{padding-top:58px}.landing-hero h1{font-size:43px}.landing-hero__copy>p{font-size:14px}.landing-hero__actions{align-items:stretch;flex-direction:column}.landing-hero__actions .landing-button{width:100%}.studio-preview__body{grid-template-columns:1fr}.preview-sidebar{display:none}.preview-main{padding:13px}.preview-stage{grid-template-columns:1fr}.preview-timeline{display:none}.preview-video{min-height:270px}.provider-strip{align-items:flex-start;flex-direction:column;margin-top:58px}.provider-strip div{gap:16px 23px}.landing-section{padding:75px 0}.outcome-grid{grid-template-columns:1fr 1fr}.outcome-grid article{padding:23px}.outcome-grid article:nth-child(2){border-right:0}.outcome-grid article:nth-child(-n+2){border-bottom:1px solid var(--landing-line)}.comparison-grid,.feature-grid{grid-template-columns:1fr}.section-intro h2,.pricing-copy h2,.security-card__copy h2{font-size:34px}.workflow-item{grid-template-columns:36px 1fr;padding:18px}.workflow-item__number{grid-row:1}.workflow-item__icon{grid-row:1}.workflow-item div{grid-column:1/-1}.workflow-item>svg{display:none}.pricing-layout{gap:38px}.pricing-card{padding:24px 19px}.pricing-value strong{font-size:50px}.security-card__copy{padding:39px 25px}.security-grid{grid-template-columns:1fr}.security-grid article{min-height:auto;padding:25px}.faq-layout{gap:20px}.landing-final-cta{padding:78px 0}.landing-final-cta .landing-container>div{flex-direction:column}.landing-footer__grid{grid-template-columns:1fr 1fr;gap:38px}.landing-footer__grid>div:first-child{grid-column:1/-1}.landing-footer__bottom{align-items:flex-start;flex-direction:column;gap:8px}}
@media(max-width:420px){.landing-hero h1{font-size:37px}.outcome-grid{grid-template-columns:1fr}.outcome-grid article{border-right:0;border-bottom:1px solid var(--landing-line)}.landing-footer__grid{grid-template-columns:1fr}.landing-footer__grid>div:first-child{grid-column:auto}.pricing-card__head{align-items:flex-start;flex-direction:column}.security-grid{grid-template-columns:1fr}}
</style>
