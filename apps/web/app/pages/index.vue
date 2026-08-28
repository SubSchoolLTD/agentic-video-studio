<script setup lang="ts">
import {
  ArrowRight,
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
  charge_cents: number
  charge_usd: number
}

interface PublicPricing {
  currency: string
  minimum_topup_usd: number
  prices: PublicPrice[]
}

const auth = useAuth()
const config = useRuntimeConfig()
const menuOpen = ref(false)

const fallbackPricing: PublicPricing = {
  currency: 'USD',
  minimum_topup_usd: 12,
  prices: [
    { feature_key: 'project.website_analysis', label: 'Website and brand analysis', unit: 'analysis', charge_cents: 3, charge_usd: 0.03 },
    { feature_key: 'research.run', label: 'Agentic web research', unit: 'research run', charge_cents: 6, charge_usd: 0.06 },
    { feature_key: 'video.generate', label: 'AI video production', unit: 'generated second / aspect ratio', charge_cents: 24, charge_usd: 0.24 },
    { feature_key: 'video.generate_native_audio', label: 'AI video with native speech', unit: 'generated second / aspect ratio', charge_cents: 48, charge_usd: 0.48 },
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
const primaryLabel = computed(() => auth.accessToken.value ? 'Open studio' : 'Create account')
const publicPriceKeys = ['project.website_analysis', 'research.run', 'video.generate', 'video.generate_native_audio']
const displayedPrices = computed(() => publicPriceKeys
  .map(key => pricing.value.prices.find(item => item.feature_key === key))
  .filter((item): item is PublicPrice => Boolean(item)))

const workflow = [
  { number: '01', title: 'Learn your business once', text: 'Add your website during onboarding. Framewise maps the product, audience, customer problem, solution, brand voice and the keywords worth watching.', icon: Globe2 },
  { number: '02', title: 'Build a balanced topic pipeline', text: 'Choose how much of your content should sell, teach or entertain. The system searches relevant sources, avoids repeated angles and scores every candidate.', icon: Radar },
  { number: '03', title: 'Turn the best ideas into videos', text: 'Gemini writes and reviews the full script, character map and scene direction. Veo creates the footage and native audio in the right social format.', icon: WandSparkles },
  { number: '04', title: 'Publish to connected accounts', text: 'Connect your channels once and choose full autopilot. Finished videos go to your publishing queue and can be posted automatically on schedule.', icon: Zap },
  { number: '05', title: 'Keep the engine running', text: 'Framewise watches the backlog, budget and performance signals, then starts the next research and production cycle without another prompt from you.', icon: BarChart3 },
]

const features = [
  { title: 'Always-on topic research', text: 'Fresh searches use your product, customer problems and audience interests to keep the idea backlog relevant.', icon: Search },
  { title: 'A healthy content mix', text: 'Selling, informative and viral ideas are balanced to your strategy instead of drifting toward the same safe format.', icon: Layers3 },
  { title: 'Ideas ranked before spending', text: 'Opportunity, relevance, freshness and confidence scores help the system produce the strongest concepts first.', icon: Radar },
  { title: 'No prompt writing', text: 'Every production includes a researched message, hook, script, character map, locations, dialogue and detailed scene direction.', icon: WandSparkles },
  { title: 'Publishing on autopilot', text: 'Choose the full automation mode and connected channels receive completed videos without a repetitive upload routine.', icon: RefreshCw },
  { title: 'A simple dollar balance', text: 'No subscription. Set a monthly budget, top up from $12 and see the real cost of every production in one ledger.', icon: CircleDollarSign },
]

const showcaseVideos = [
  { src: '/showcase/framewise-example-01.mp4', poster: '/showcase/framewise-example-01.jpg', youtube: 'https://youtube.com/shorts/hBCFkrmh6RY', label: 'Autonomous example 01', format: 'Short-form AI video' },
  { src: '/showcase/framewise-example-02.mp4', poster: '/showcase/framewise-example-02.jpg', youtube: 'https://youtube.com/shorts/3v477HqSojU', label: 'Autonomous example 02', format: 'Short-form AI video' },
  { src: '/showcase/framewise-example-03.mp4', poster: '/showcase/framewise-example-03.jpg', youtube: 'https://youtube.com/shorts/GZ2AjzDTJw4', label: 'Autonomous example 03', format: 'Short-form AI video' },
]

const faqs = [
  { question: 'How hands-off can Framewise be?', answer: 'After onboarding, you can choose full automation: Framewise researches topics, selects ideas, writes scripts, generates videos and publishes to connected channels. You return when you want to inspect results or top up the balance.' },
  { question: 'Do I need to write prompts or scripts?', answer: 'No. Your website, audience profile and content goals provide the context. Framewise researches the topic and creates the hook, message, script, characters, dialogue, locations and detailed scene prompts automatically.' },
  { question: 'What happens during onboarding?', answer: 'You add a website, confirm the product and audience analysis, choose your selling, informative and viral content mix, set weekly volume and duration, then connect the channels you want to automate.' },
  { question: 'Can I review videos before they publish?', answer: 'Yes. Automation has clear levels: research only, scripts, video creation or full publishing. You can keep review in your workflow or let approved settings run end to end.' },
  { question: 'Which AI providers does it use?', answer: 'The live pipeline uses Parallel for web research and Google Cloud for Gemini planning and QA, Veo video generation, Text-to-Speech, storage and workflow infrastructure.' },
  { question: 'How much does it cost?', answer: 'There is no subscription. You top up a dollar balance from $12 and pay only for usage. AI prices are based on provider cost plus a 20% platform markup.' },
]

useSeoMeta({
  title: 'Framewise — Automatic AI Video Creation & Publishing',
  description: 'Turn your website into an automatic social video engine. Framewise researches topics, scores ideas, generates videos and publishes them to connected accounts.',
  ogTitle: 'Framewise — One setup. A steady stream of social video.',
  ogDescription: 'Automatic topic research, AI video generation and social publishing built around your product and audience.',
  ogType: 'website',
  ogUrl: 'https://studio.subschool.us/',
  ogSiteName: 'Framewise',
  twitterCard: 'summary_large_image',
  twitterTitle: 'Framewise — Automatic AI Video Content',
  twitterDescription: 'Connect your website and channels once. Framewise keeps researching, creating and publishing videos.',
  robots: 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1',
})

useHead({
  link: [{ rel: 'canonical', href: 'https://studio.subschool.us/' }],
  meta: [{ name: 'keywords', content: 'automatic video creation, AI social media automation, AI video generator, automated content creation, automatic social media posting, Veo video generator, content research automation, AI content engine' }],
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
        description: 'Automatic AI content engine for topic research, video generation and social publishing.',
        offers: { '@type': 'Offer', price: '12', priceCurrency: 'USD', description: 'Usage-based AI balance with a $12 minimum top-up and no subscription.' },
        featureList: ['Automatic topic research', 'Audience and product analysis', 'AI video generation', 'Balanced content planning', 'Automatic social publishing'],
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
          <NuxtLink to="/solutions">Solutions</NuxtLink>
          <a href="#workflow">How it works</a>
          <a href="#examples">Examples</a>
          <a href="#pricing">Pricing</a>
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
        <NuxtLink to="/solutions" @click="menuOpen = false">Solutions</NuxtLink>
        <a href="#workflow" @click="menuOpen = false">How it works</a>
        <a href="#examples" @click="menuOpen = false">Examples</a>
        <a href="#pricing" @click="menuOpen = false">Pricing</a>
        <NuxtLink v-if="!auth.accessToken.value" to="/login" @click="menuOpen = false">Sign in</NuxtLink>
        <NuxtLink class="landing-button" :to="primaryCta" @click="menuOpen = false">{{ primaryLabel }} <ArrowRight :size="15" /></NuxtLink>
      </div>
    </header>

    <main>
      <section class="landing-hero">
        <div class="landing-glow landing-glow--one" /><div class="landing-glow landing-glow--two" />
        <div class="landing-container landing-hero__grid">
          <div class="landing-hero__copy">
            <div class="landing-pill"><span /><strong>Automatic research, creation and publishing</strong></div>
            <h1>Turn one website into a <em>self-running video channel.</em></h1>
            <p>Connect your website and social accounts once. Framewise learns your audience, finds fresh topics, writes and generates the videos, then publishes them while you focus on the business.</p>
            <div class="landing-hero__actions">
              <NuxtLink class="landing-button landing-button--primary" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="17" /></NuxtLink>
              <a class="landing-button landing-button--ghost" href="#examples"><Play :size="15" /> Watch real examples</a>
            </div>
            <div class="landing-hero__note"><Check :size="15" /> One-time setup <span>·</span> No prompt writing <span>·</span> No subscription</div>
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
                <div class="preview-heading"><div><small>Autopilot / Today</small><strong>Why your best lesson already exists</strong></div><span>87<small>score</small></span></div>
                <div class="preview-stage">
                  <div class="preview-video"><span class="preview-play"><Play :size="16" /></span><div class="preview-caption">New video ready to publish</div><small>00:30</small></div>
                  <div class="preview-timeline">
                    <span class="done"><Check :size="10" /><b>Audience match</b><small>High relevance</small></span>
                    <span class="done"><Check :size="10" /><b>Topic selected</b><small>87 opportunity</small></span>
                    <span class="done"><Sparkles :size="10" /><b>Video created</b><small>5 scenes</small></span>
                    <span class="live"><Bot :size="10" /><b>Publishing</b><small>Today · 18:30</small></span>
                  </div>
                </div>
                <div class="preview-footer"><span><ShieldCheck :size="11" /> Script reviewed</span><span><Clock3 :size="11" /> Schedule active</span><strong>Autopilot on</strong></div>
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
          <article><strong>1 setup</strong><span>to learn your product and audience</span></article>
          <article><strong>Daily</strong><span>automatic topic discovery</span></article>
          <article><strong>4 formats</strong><span>matched to each content idea</span></article>
          <article><strong>0 prompts</strong><span>required from your team</span></article>
        </div>
      </section>

      <section id="product" class="landing-section landing-problem">
        <div class="landing-container">
          <div class="section-intro section-intro--split">
            <div><span class="landing-eyebrow">Consistency without a content team</span><h2>Regular video should not depend on finding <em>another free afternoon.</em></h2></div>
            <p>Framewise replaces the recurring work around content—not just the render. It keeps the topic pipeline full, decides what is worth producing and carries every winning idea all the way to publication.</p>
          </div>
          <div class="comparison-grid">
            <article class="comparison-card comparison-card--old">
              <span>The usual content routine</span><h3>Start from zero every week</h3>
              <ul><li><X :size="15" /> Search for topics manually</li><li><X :size="15" /> Guess what the audience wants</li><li><X :size="15" /> Write scripts and prompts again</li><li><X :size="15" /> Export, upload and schedule every post</li></ul>
            </article>
            <article class="comparison-card comparison-card--new">
              <span>The Framewise autopilot</span><h3>Set the strategy once</h3>
              <ul><li><Check :size="15" /> Fresh topics arrive automatically</li><li><Check :size="15" /> Ideas are scored before generation spend</li><li><Check :size="15" /> Scripts and video are created end to end</li><li><Check :size="15" /> Connected channels stay consistently active</li></ul>
            </article>
          </div>
        </div>
      </section>

      <section id="workflow" class="landing-section landing-workflow">
        <div class="landing-container">
          <div class="section-intro"><span class="landing-eyebrow">How Framewise works</span><h2>From your website to an always-on content engine.</h2><p>You choose the goals, volume and budget. Framewise turns that strategy into a repeating research, production and publishing cycle.</p></div>
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

      <section id="examples" class="landing-section landing-showcase">
        <div class="landing-container">
          <div class="showcase-intro">
            <div><span class="landing-eyebrow">Real autonomous outputs</span><h2>Made without a human in the production loop.</h2></div>
            <p>These videos were generated end to end by Framewise—without manual editing, prompt rewrites or any other human intervention.</p>
          </div>
          <div class="showcase-grid">
            <article v-for="video in showcaseVideos" :key="video.src" class="showcase-card">
              <div class="showcase-player">
                <video :src="video.src" :poster="video.poster" :aria-label="video.label" controls preload="metadata" playsinline />
              </div>
              <div class="showcase-card__copy"><span>{{ video.format }}</span><strong>{{ video.label }}</strong><a :href="video.youtube" target="_blank" rel="noopener">Watch on YouTube <ArrowRight :size="13" /></a></div>
            </article>
          </div>
        </div>
      </section>

      <section class="landing-section landing-features">
        <div class="landing-container">
          <div class="section-intro"><span class="landing-eyebrow">More than video generation</span><h2>The decisions around every video are automated too.</h2></div>
          <div class="feature-grid">
            <article v-for="feature in features" :key="feature.title" class="feature-card"><span><component :is="feature.icon" :size="20" /></span><h3>{{ feature.title }}</h3><p>{{ feature.text }}</p></article>
          </div>
        </div>
      </section>

      <section id="pricing" class="landing-section landing-pricing">
        <div class="landing-container pricing-layout">
          <div class="pricing-copy">
            <span class="landing-eyebrow">Simple usage pricing</span>
            <h2>Top up the engine. Let it keep publishing.</h2>
            <p>There is no subscription or seat fee. Add a dollar balance, choose a monthly budget and pay only for the research and content the system actually produces.</p>
            <ul><li><Check :size="15" /> No subscription or monthly platform fee</li><li><Check :size="15" /> Provider cost plus 20%</li><li><Check :size="15" /> Budget limits stay under your control</li><li><Check :size="15" /> Promo codes add balance without payment</li></ul>
          </div>
          <article class="pricing-card">
            <div class="pricing-card__head"><div><span>Dollar balance</span><h3>Pay as you generate</h3></div><span class="pricing-badge">Available now</span></div>
            <div class="pricing-value"><strong>${{ pricing.minimum_topup_usd }}</strong><span>minimum top-up</span></div>
            <p>No recurring charge. Unused balance remains in your workspace.</p>
            <div class="pricing-lines">
              <div v-for="item in displayedPrices" :key="item.feature_key"><span><strong>{{ item.label }}</strong><small>per {{ item.unit }}</small></span><b>${{ Number(item.charge_usd).toFixed(2) }}</b></div>
            </div>
            <NuxtLink class="landing-button landing-button--primary landing-button--wide" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="16" /></NuxtLink>
            <small class="pricing-fineprint">Top up with PayPal or activate a promo code separately. A valid promo credits your balance without a PayPal transaction.</small>
          </article>
        </div>
      </section>

      <section id="security" class="landing-section landing-security">
        <div class="landing-container security-card">
          <div class="security-card__copy"><span class="landing-eyebrow">Connect once, stay in control</span><h2>Autopilot for the repetitive work—not for your budget.</h2><p>Your channels, content strategy and spending limits stay attached to your workspace. Change the automation level whenever you want, from research only to full publication.</p><NuxtLink class="landing-button landing-button--light" :to="primaryCta">Set up your content engine <ArrowRight :size="16" /></NuxtLink></div>
          <div class="security-grid"><article><LockKeyhole :size="22" /><strong>One-time connections</strong><span>Link publishing accounts once and keep tokens encrypted.</span></article><article><CircleDollarSign :size="22" /><strong>Visible spend</strong><span>See the cost of every production and set a monthly budget.</span></article><article><FileCheck2 :size="22" /><strong>Optional review</strong><span>Keep script or video review when your workflow needs it.</span></article><article><RefreshCw :size="22" /><strong>Reliable recovery</strong><span>Interrupted jobs resume from completed work instead of starting over.</span></article></div>
        </div>
      </section>

      <section class="landing-section landing-faq">
        <div class="landing-container faq-layout">
          <div class="section-intro"><span class="landing-eyebrow">Frequently asked</span><h2>What happens after you switch it on?</h2><p>Choose as much automation as you want. The full mode is designed to keep content moving without a weekly production routine.</p></div>
          <div class="faq-list"><details v-for="(item, index) in faqs" :key="item.question" :open="index === 0"><summary>{{ item.question }}<span>+</span></summary><p>{{ item.answer }}</p></details></div>
        </div>
      </section>

      <section class="landing-final-cta">
        <div class="landing-glow landing-glow--three" />
        <div class="landing-container"><span class="landing-eyebrow">Consistent content starts with one setup</span><h2>Let your next video lead to the one after it.</h2><p>Add your website, choose the strategy and switch on the level of automation that fits your business.</p><div><NuxtLink class="landing-button landing-button--primary" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="17" /></NuxtLink><NuxtLink v-if="!auth.accessToken.value" class="landing-button landing-button--dark" to="/login">Sign in</NuxtLink></div></div>
      </section>
    </main>

    <footer class="landing-footer">
      <div class="landing-container landing-footer__grid">
        <div><NuxtLink class="landing-brand landing-brand--footer" to="/"><span class="landing-brand__mark"><Clapperboard :size="20" /></span><span><strong>Framewise</strong><small>Agentic video studio</small></span></NuxtLink><p>Automatic topic research, AI video creation and social publishing from one product website.</p></div>
        <div><strong>Product</strong><NuxtLink to="/solutions">Solutions</NuxtLink><a href="#workflow">How it works</a><a href="#examples">Examples</a><a href="#pricing">Pricing</a></div>
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
.landing-showcase{background:#fff}.showcase-intro{display:grid;grid-template-columns:1.05fr .95fr;align-items:end;gap:80px;margin-bottom:46px}.showcase-intro h2{max-width:670px;margin:13px 0 0;font-family:var(--font-display);font-size:clamp(32px,4vw,49px);font-weight:650;line-height:1.06;letter-spacing:-.055em}.showcase-intro>p{max-width:480px;margin:0 0 5px;color:var(--landing-muted);font-size:14px;line-height:1.75}.showcase-grid{display:grid;grid-template-columns:repeat(3,minmax(0,280px));justify-content:center;gap:18px}.showcase-card{overflow:hidden;border:1px solid #e2d9e4;border-radius:19px;background:#fff;box-shadow:0 22px 55px rgb(42 24 47 / 9%)}.showcase-player{position:relative;overflow:hidden;aspect-ratio:9/16;background:#17131f}.showcase-player video{width:100%;height:100%;background:#17131f;object-fit:contain}.showcase-card__copy{display:grid;gap:4px;padding:18px}.showcase-card__copy>span{color:#8d2ea3;font-size:8px;font-weight:850;text-transform:uppercase;letter-spacing:.12em}.showcase-card__copy>strong{font-family:var(--font-display);font-size:15px;letter-spacing:-.025em}.showcase-card__copy>a{display:inline-flex;align-items:center;gap:5px;margin-top:8px;color:#6e287e;font-size:9px;font-weight:800}.showcase-card__copy>a:hover{color:#982eb3}
.landing-features{background:#1a151f;color:white}.landing-features .landing-eyebrow{color:#d798e7}.landing-features .section-intro{max-width:780px}.feature-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.feature-card{min-height:226px;padding:25px;border:1px solid rgb(255 255 255 / 8%);border-radius:15px;background:linear-gradient(145deg,rgb(255 255 255 / 6%),rgb(255 255 255 / 2%))}.feature-card>span{display:grid;width:40px;height:40px;place-items:center;border:1px solid rgb(215 152 231 / 19%);border-radius:11px;background:rgb(162 76 184 / 13%);color:#d798e7}.feature-card h3{margin:32px 0 9px;font-family:var(--font-display);font-size:17px;letter-spacing:-.03em}.feature-card p{margin:0;color:#bbb3bf;font-size:10px;line-height:1.65}
.landing-pricing{background:#fff}.pricing-layout{display:grid;grid-template-columns:.88fr 1.12fr;align-items:center;gap:90px}.pricing-copy ul{margin-top:28px}.pricing-copy li svg{color:#25915f}.pricing-card{padding:34px;border:1px solid #dacee0;border-radius:21px;background:linear-gradient(150deg,#fff,#faf5fb);box-shadow:0 27px 75px rgb(51 26 59 / 9%)}.pricing-card__head{display:flex;align-items:start;justify-content:space-between;gap:20px}.pricing-card__head>div{display:grid;gap:5px}.pricing-card__head>div>span{color:#8d2ea3;font-size:8px;font-weight:850;text-transform:uppercase;letter-spacing:.13em}.pricing-card__head h3{margin:0;font-family:var(--font-display);font-size:20px}.pricing-badge{padding:6px 8px;border-radius:99px;background:#e7f6ee;color:#21885a;font-size:8px;font-weight:800}.pricing-value{display:flex;align-items:end;gap:8px;margin:27px 0 5px}.pricing-value strong{font-family:var(--font-display);font-size:58px;line-height:1;letter-spacing:-.07em}.pricing-value span{padding-bottom:7px;color:var(--landing-muted);font-size:11px}.pricing-card>p{margin:0 0 24px;color:var(--landing-muted);font-size:11px}.pricing-card>p b{color:#76208a}.pricing-lines{display:grid;margin-bottom:25px;border-top:1px solid var(--landing-line)}.pricing-lines>div{display:flex;align-items:center;justify-content:space-between;gap:15px;padding:12px 0;border-bottom:1px solid var(--landing-line)}.pricing-lines span{display:grid;gap:2px}.pricing-lines strong{font-size:10px}.pricing-lines small{color:var(--landing-muted);font-size:8px}.pricing-lines b{font-size:10px}.pricing-fineprint{display:block;margin-top:12px;color:#8a838e;font-size:8px;line-height:1.5;text-align:center}
.landing-security{background:#f4eff5}.security-card{position:relative;display:grid;grid-template-columns:.92fr 1.08fr;overflow:hidden;border-radius:23px;background:linear-gradient(145deg,#3e1848,#18131e);color:white;box-shadow:0 25px 70px rgb(40 23 45 / 13%)}.security-card__copy{padding:57px}.security-card__copy .landing-eyebrow{color:#daa0e8}.security-card__copy>p{color:#c7bdca}.security-card__copy .landing-button{margin-top:27px}.security-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:rgb(255 255 255 / 9%)}.security-grid article{display:grid;align-content:center;gap:8px;min-height:215px;padding:30px;background:#211827}.security-grid svg{margin-bottom:12px;color:#d798e7}.security-grid strong{font-family:var(--font-display);font-size:14px}.security-grid span{color:#aea5b2;font-size:9px;line-height:1.6}
.landing-faq{background:#fff}.faq-layout{display:grid;grid-template-columns:.75fr 1.25fr;gap:100px}.faq-layout .section-intro{margin:0}.faq-list{display:grid}.faq-list details{border-bottom:1px solid var(--landing-line)}.faq-list summary{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:19px 0;cursor:pointer;font-family:var(--font-display);font-size:13px;font-weight:700;list-style:none}.faq-list summary::-webkit-details-marker{display:none}.faq-list summary span{display:grid;width:24px;height:24px;place-items:center;border-radius:50%;background:#f5e8f8;color:#8d2ea3;font-size:15px;transition:.18s}.faq-list details[open] summary span{transform:rotate(45deg)}.faq-list details p{margin:-3px 42px 21px 0;color:var(--landing-muted);font-size:10px;line-height:1.7}
.landing-final-cta{position:relative;padding:105px 0;overflow:hidden;background:#17131f;color:white;text-align:center}.landing-glow--three{top:-180px;left:calc(50% - 340px);width:680px;height:420px;background:radial-gradient(circle,rgb(178 91 198 / 25%),transparent 66%)}.landing-final-cta .landing-container{position:relative}.landing-final-cta .landing-eyebrow{color:#d798e7}.landing-final-cta h2{max-width:850px;margin:15px auto;font-family:var(--font-display);font-size:clamp(38px,5vw,62px);font-weight:650;line-height:1.03;letter-spacing:-.06em}.landing-final-cta p{margin:0;color:#bbb3bf;font-size:13px}.landing-final-cta .landing-container>div{display:flex;justify-content:center;gap:10px;margin-top:27px}.landing-footer{padding:58px 0 25px;background:#100d14;color:#b7afbb}.landing-footer__grid{display:grid;grid-template-columns:2fr repeat(3,1fr);gap:55px}.landing-brand--footer{color:white}.landing-footer__grid>div{display:grid;align-content:start;gap:10px}.landing-footer__grid>div:first-child p{max-width:310px;margin:9px 0 0;color:#8f8794;font-size:10px;line-height:1.6}.landing-footer__grid>div:not(:first-child)>strong{margin-bottom:5px;color:white;font-size:9px;text-transform:uppercase;letter-spacing:.12em}.landing-footer__grid a,.landing-footer__grid span{font-size:9px}.landing-footer__grid a:hover{color:white}.landing-footer__bottom{display:flex;justify-content:space-between;margin-top:48px;padding-top:19px;border-top:1px solid rgb(255 255 255 / 7%);color:#706976;font-size:8px}
@media(max-width:1050px){.landing-hero__grid{grid-template-columns:1fr;gap:55px}.landing-hero__copy{max-width:760px}.studio-preview{width:min(760px,100%);margin:auto;transform:none}.section-intro--split{grid-template-columns:1fr;gap:10px}.showcase-intro{grid-template-columns:1fr;gap:13px}.showcase-intro>p{max-width:720px}.pricing-layout,.faq-layout{grid-template-columns:1fr;gap:55px}.pricing-card{max-width:680px}.security-card{grid-template-columns:1fr}.security-grid article{min-height:180px}.feature-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:760px){.landing-container{width:min(100% - 30px,1180px)}.landing-header__inner{height:66px}.landing-nav,.landing-header__actions{display:none}.landing-menu{display:grid;margin-left:auto}.landing-mobile-nav{display:grid;gap:3px;padding:7px 15px 16px;border-top:1px solid var(--landing-line);background:#fbfaf8}.landing-mobile-nav>a{padding:10px;border-radius:8px;font-size:11px;font-weight:700}.landing-mobile-nav .landing-button{margin-top:4px;color:white}.landing-hero{padding-top:58px}.landing-hero h1{font-size:43px}.landing-hero__copy>p{font-size:14px}.landing-hero__actions{align-items:stretch;flex-direction:column}.landing-hero__actions .landing-button{width:100%}.studio-preview__body{grid-template-columns:1fr}.preview-sidebar{display:none}.preview-main{padding:13px}.preview-stage{grid-template-columns:1fr}.preview-timeline{display:none}.preview-video{min-height:270px}.provider-strip{align-items:flex-start;flex-direction:column;margin-top:58px}.provider-strip div{gap:16px 23px}.landing-section{padding:75px 0}.outcome-grid{grid-template-columns:1fr 1fr}.outcome-grid article{padding:23px}.outcome-grid article:nth-child(2){border-right:0}.outcome-grid article:nth-child(-n+2){border-bottom:1px solid var(--landing-line)}.comparison-grid,.feature-grid{grid-template-columns:1fr}.showcase-grid{grid-template-columns:minmax(0,300px)}.section-intro h2,.showcase-intro h2,.pricing-copy h2,.security-card__copy h2{font-size:34px}.workflow-item{grid-template-columns:36px 1fr;padding:18px}.workflow-item__number{grid-row:1}.workflow-item__icon{grid-row:1}.workflow-item div{grid-column:1/-1}.workflow-item>svg{display:none}.pricing-layout{gap:38px}.pricing-card{padding:24px 19px}.pricing-value strong{font-size:50px}.security-card__copy{padding:39px 25px}.security-grid{grid-template-columns:1fr}.security-grid article{min-height:auto;padding:25px}.faq-layout{gap:20px}.landing-final-cta{padding:78px 0}.landing-final-cta .landing-container>div{flex-direction:column}.landing-footer__grid{grid-template-columns:1fr 1fr;gap:38px}.landing-footer__grid>div:first-child{grid-column:1/-1}.landing-footer__bottom{align-items:flex-start;flex-direction:column;gap:8px}}
@media(max-width:420px){.landing-hero h1{font-size:37px}.outcome-grid{grid-template-columns:1fr}.outcome-grid article{border-right:0;border-bottom:1px solid var(--landing-line)}.landing-footer__grid{grid-template-columns:1fr}.landing-footer__grid>div:first-child{grid-column:auto}.pricing-card__head{align-items:flex-start;flex-direction:column}.security-grid{grid-template-columns:1fr}}
</style>
