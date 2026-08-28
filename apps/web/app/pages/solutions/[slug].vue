<script setup lang="ts">
import { ArrowRight, Check, Clapperboard, Menu, Sparkles, X } from 'lucide-vue-next'

type CopyItem = { title: string, text: string }
type FaqItem = { question: string, answer: string }
type Solution = {
  title: string
  eyebrow: string
  promise: string
  description: string
  audience: string
  problemHeading: string
  problems: CopyItem[]
  outcomes: string[]
  pillars: CopyItem[]
  workflow: CopyItem[]
  formats: CopyItem[]
  setup: CopyItem[]
  feedback: string
  examples: string[]
  faqs: FaqItem[]
}

const solutions: Record<string, Solution> = {
  'studios-media-teams': {
    title: 'Studios & media teams',
    eyebrow: 'Autonomous release marketing',
    promise: 'Keep the story alive between the trailer and the premiere.',
    description: 'Framewise turns a film, series, channel or media property into an always-on short-form production desk. It researches audience angles, develops complete concepts, generates the footage and keeps connected channels active without adding another queue to the production team.',
    audience: 'Built for independent studios, production companies, distributors, streaming teams and media brands that have a rich property to promote—but a lean team responsible for every release asset.',
    problemHeading: 'The property has a world. The campaign keeps collapsing into the same trailer cutdowns.',
    problems: [
      { title: 'The launch calendar outruns the team', text: 'Production, approvals and distribution already consume the people who would otherwise keep social channels active.' },
      { title: 'Good material becomes repetitive', text: 'Without continuous research, the campaign circles around the synopsis, cast announcement and the same behind-the-scenes clip.' },
      { title: 'Audience signals arrive too late', text: 'Questions, reactions and adjacent cultural moments are noticed manually, after their useful window has passed.' },
      { title: 'Every post restarts production', text: 'Even a 30-second idea still needs an angle, script, shot logic, edit, QA, caption and upload.' },
    ],
    outcomes: [
      'A researched backlog of audience questions, cultural hooks and property-specific angles.',
      'A deliberate mix of release education, world-building, fan conversation and conversion content.',
      'Complete scripts with characters, dialogue, locations, action and scene-level Veo direction before video spend.',
      'A recoverable production pipeline where one failed scene can retry without discarding completed work.',
      'Publishing performance becomes a cautious signal for the next editorial cycle.',
      'Budget limits keep the autonomous campaign financially bounded.',
    ],
    pillars: [
      { title: 'World and character', text: 'Explain motivations, relationships, locations and details that invite the audience deeper into the property.' },
      { title: 'Release education', text: 'Answer where, when and why to watch without repeating a conventional trailer message.' },
      { title: 'Behind the story', text: 'Turn creative decisions, research and production context into accessible short-form narratives.' },
      { title: 'Audience conversation', text: 'Respond to emerging questions and adjacent topics while the discussion is still timely.' },
    ],
    workflow: [
      { title: 'Learn the property', text: 'Add the website, synopsis, audience, release context, rights and brand constraints once.' },
      { title: 'Research the audience moment', text: 'Parallel searches current questions, adjacent themes and primary evidence instead of recycling generic prompts.' },
      { title: 'Score the opportunity', text: 'Gemini evaluates relevance, freshness, evidence, filmability and the intended role in the campaign.' },
      { title: 'Direct the complete story', text: 'The system chooses a format and authors the hook, character map, dialogue, action, locations and individual scene prompts.' },
      { title: 'Generate and check', text: 'Veo creates each scene; automated QA checks speech, continuity, framing and render integrity before assembly.' },
      { title: 'Publish and adapt', text: 'Approved channels receive the finished cut and measured response informs future research without blindly chasing one result.' },
    ],
    formats: [
      { title: 'Storytelling sketch', text: 'A small dramatic situation with roles and dialogue—useful for audience dilemmas, character parallels and campaign hooks.' },
      { title: 'Cinematic sequence', text: 'Visual world-building where action and atmosphere carry the message with minimal exposition.' },
      { title: 'Creator-led UGC', text: 'A consistent on-camera voice explains context, reacts to a question or introduces the property naturally.' },
      { title: 'Motion graphics', text: 'Structured timelines, facts and release information when clarity matters more than a performed scene.' },
    ],
    setup: [
      { title: 'Property context', text: 'Website, synopsis, audience, differentiators, campaign dates and approved claims.' },
      { title: 'Editorial balance', text: 'How much output should build awareness, deepen fandom, inform or drive a release action.' },
      { title: 'Production defaults', text: 'Preferred formats, duration, aspect ratio, voice quality, continuation rules and brand treatment.' },
      { title: 'Cadence and budget', text: 'Videos per week, research interval, monthly ceiling and the automation stage allowed to run.' },
    ],
    feedback: 'Framewise associates 24-hour and 7-day publication observations with the original idea, objective, candidate type and visual format. Strong and weak patterns influence later searches, while at least 20% of research remains exploratory so one early result cannot flatten the campaign.',
    examples: ['Independent film release campaigns', 'Streaming and episodic social teams', 'Festival and distribution campaigns', 'Production-company thought leadership', 'Fan education and behind-the-scenes content', 'Media-property audience development'],
    faqs: [
      { question: 'Does Framewise need access to unreleased footage?', answer: 'No. It can work from approved public context and generate original short-form scenes. Teams can still add protected context and explicit rights constraints when appropriate.' },
      { question: 'Can the team review scripts before Veo spends?', answer: 'Yes. Script review can be required globally or per production. Character maps and every detailed scene prompt remain editable before generation.' },
      { question: 'Will every video look like the same trailer?', answer: 'No. Research balances distinct editorial purposes and selects among UGC, storytelling, cinematic and motion-graphics formats according to the idea.' },
      { question: 'Can it run only during a release window?', answer: 'Yes. Cadence, publication windows, budgets and emergency pause controls are project settings.' },
    ],
  },
  'creators-experts': {
    title: 'Creators & experts',
    eyebrow: 'Expertise-to-channel automation',
    promise: 'Turn expertise into a channel that keeps moving without a blank page.',
    description: 'Framewise learns what you know, who you help and what your audience keeps asking. It then researches, scripts, generates and publishes a balanced stream of useful, entertaining and commercial videos—without asking you to invent another prompt every morning.',
    audience: 'Built for consultants, coaches, researchers, authors, educators and founder-creators whose expertise is valuable but whose publishing cadence depends on finding spare time.',
    problemHeading: 'You do not lack knowledge. You lack a repeatable way to package it every week.',
    problems: [
      { title: 'The blank-page tax', text: 'Every post begins with deciding what to say, even though the audience has already supplied dozens of real questions.' },
      { title: 'Expert language is not a hook', text: 'Correct information still needs a sharp promise, a concrete situation and visual action to work as short-form video.' },
      { title: 'Promotion overwhelms the mix', text: 'When time is limited, content drifts toward announcements and offers instead of earning sustained attention.' },
      { title: 'The voice changes with every tool', text: 'Disconnected scripts, avatars and generators lose the expert’s role, tone and point of view.' },
    ],
    outcomes: [
      'Fresh topics grounded in audience problems, current sources and your defined expertise.',
      'A controlled ratio of informative, entertaining and selling videos.',
      'Hooks and scripts that deliver one concrete takeaway instead of generic motivational copy.',
      'Reusable creator and character profiles for stronger visual and vocal continuity.',
      'The option to approve scripts—or let a proven workflow continue automatically.',
      'A searchable library of evidence, scripts, captions, videos and performance history.',
    ],
    pillars: [
      { title: 'Teach one useful thing', text: 'Answer a narrow question with a specific insight the viewer can use immediately.' },
      { title: 'Reframe the problem', text: 'Challenge a common assumption and show why the audience’s current approach keeps failing.' },
      { title: 'Show the work', text: 'Turn methods, decisions, mistakes and behind-the-scenes expertise into credible stories.' },
      { title: 'Invite the next step', text: 'Connect a relevant audience problem to the product or service without turning every video into an advertisement.' },
    ],
    workflow: [
      { title: 'Map the expertise', text: 'The onboarding analysis extracts your offer, audience, problem, solution, authority and searchable topic territories.' },
      { title: 'Find real questions', text: 'Research combines fresh evidence with themes you selected, rejected and published before.' },
      { title: 'Choose the editorial role', text: 'Each candidate is classified as informative, entertaining or selling and balanced against your target mix.' },
      { title: 'Write for speech and action', text: 'Gemini develops the hook, argument, examples, dialogue, gestures, location and camera logic—not just narration.' },
      { title: 'Critique before spending', text: 'A separate quality pass checks whether the script is useful, interesting, accurate and aligned with the actual offer.' },
      { title: 'Create, publish and learn', text: 'Veo or TTS produces the configured format, connected channels publish it and response informs the next research cycle.' },
    ],
    formats: [
      { title: 'Creator-led UGC', text: 'A reusable on-camera expert delivers a concise idea with consistent role, tone and visual identity.' },
      { title: 'Storytelling sketch', text: 'Characters dramatize a customer misconception, decision or before-and-after situation.' },
      { title: 'Cinematic example', text: 'A visual metaphor or lived situation makes an abstract professional idea tangible.' },
      { title: 'Motion graphics', text: 'Frameworks, comparisons and sequences become clear visual explanations.' },
    ],
    setup: [
      { title: 'Expert profile', text: 'Role, background, point of view, prohibited claims, tone and preferred call to action.' },
      { title: 'Audience map', text: 'Who you help, what they are trying to achieve and what prevents progress.' },
      { title: 'Content mix', text: 'The percentage of useful, entertaining and commercial ideas expected in each research batch.' },
      { title: 'Publishing system', text: 'Weekly volume, duration, default video settings, budget and connected channels.' },
    ],
    feedback: 'Selections, rejections and publication observations are stored with their topic, objective and format. Later research can pursue promising patterns or avoid weak treatments, but the system labels these as low-confidence signals and preserves exploration.',
    examples: ['Coaches and consultants', 'Authors and researchers', 'Founder-led channels', 'Professional educators', 'Subject-matter experts', 'Knowledge-based service businesses'],
    faqs: [
      { question: 'Do I need to record myself?', answer: 'No. Framewise can generate creator-led, storytelling, cinematic or motion-graphics video. A reusable visual character is optional.' },
      { question: 'Can I keep final approval?', answer: 'Yes. You can automate only research, continue through scripts, create videos, or enable full publication.' },
      { question: 'How does it avoid inventing expertise?', answer: 'Project context, source evidence, mandatory points and prohibited claims travel through the production workflow, followed by factual and quality review.' },
      { question: 'Can different video types use different defaults?', answer: 'Yes. Voice source, duration, aspect ratio, continuation and other defaults can be configured separately for all four formats.' },
    ],
  },
  'small-businesses': {
    title: 'Small businesses',
    eyebrow: 'An autonomous content department',
    promise: 'Stay visible every week without turning marketing into a second job.',
    description: 'Framewise replaces the recurring work around topic research, planning, scripting, generation and uploading. Your team sets the business context, goals, weekly volume and budget once; the engine keeps the content pipeline moving.',
    audience: 'Built for SaaS companies, local and professional services, consumer brands and founder-led teams that need regular video but cannot justify a full internal production department.',
    problemHeading: 'Regular video works. Rebuilding the entire process every week does not.',
    problems: [
      { title: 'Marketing competes with delivery', text: 'The same small team that serves customers and builds the product is expected to research, script, edit and publish.' },
      { title: 'Agencies still need management', text: 'Briefs, approvals and revisions move the work outside the company but do not remove the operating burden.' },
      { title: 'Generic AI misses the business', text: 'A one-line prompt does not understand the actual customer, product limitation, positioning or buying context.' },
      { title: 'Consistency disappears first', text: 'Content pauses as soon as a launch, customer issue or busy week takes priority.' },
    ],
    outcomes: [
      'The website becomes a structured product, customer and positioning brief.',
      'Research watches product topics, customer problems and audience interests continuously.',
      'Opportunity scoring directs generation budget toward stronger, more filmable ideas first.',
      'Selling, informative and entertaining output follows the ratio the business chose.',
      'A dollar balance and monthly ceiling bound automation without a subscription.',
      'Connected channels can receive finished videos without a repetitive upload routine.',
    ],
    pillars: [
      { title: 'Customer problems', text: 'Make the audience feel understood by showing the real situation before introducing a solution.' },
      { title: 'Useful guidance', text: 'Answer related questions that build trust before a customer is ready to buy.' },
      { title: 'Product value in context', text: 'Show how the offer changes an outcome rather than listing features in isolation.' },
      { title: 'Entertaining relevance', text: 'Use recognizable moments, contrasts and sketches that fit the audience without forcing a trend.' },
    ],
    workflow: [
      { title: 'Connect the business', text: 'Start with the existing website; AI extracts the offer, audience, problem, solution and three keyword territories.' },
      { title: 'Confirm the plan', text: 'Choose the content mix, videos per week, average length, quality and maximum monthly spend.' },
      { title: 'Research continuously', text: 'Parallel searches fresh sources and Gemini turns the best evidence into scored candidate concepts.' },
      { title: 'Produce the right format', text: 'The system chooses UGC, storytelling, cinematic or motion graphics and creates the complete production package.' },
      { title: 'Respect the balance', text: 'Estimated cost is checked before generation; low balance pauses the next expensive action and requests a top-up.' },
      { title: 'Publish and improve', text: 'Connected channels receive finished work and measured response cautiously changes future topic and format choices.' },
    ],
    formats: [
      { title: 'Creator-led UGC', text: 'A founder, specialist or customer-facing character explains one problem and useful solution.' },
      { title: 'Storytelling sketch', text: 'A short customer situation makes the pain and transformation understandable without showing a fragile fake interface.' },
      { title: 'Cinematic product story', text: 'People, places and physical action express the category, aspiration or outcome.' },
      { title: 'Motion graphics', text: 'Numbers, steps and comparisons are visualized when a clear explanation is the strongest creative choice.' },
    ],
    setup: [
      { title: 'Business context', text: 'Website, customer, offer, differentiators, prohibited claims and brand voice.' },
      { title: 'Growth priorities', text: 'The desired balance between selling, informing and entertaining content.' },
      { title: 'Operating limits', text: 'Weekly volume, duration, research backlog, monthly budget and publication windows.' },
      { title: 'Channels and defaults', text: 'Connected accounts plus format-specific video and audio preferences.' },
    ],
    feedback: 'Every published video keeps its original audience, message, objective and format context. Framewise compares later observations with those decisions and supplies winning or weak patterns to research as suggestions—not as guaranteed causes.',
    examples: ['Local and professional services', 'SaaS and online products', 'Consumer brands', 'Founder-led small teams', 'Marketplaces and apps', 'Specialist B2B companies'],
    faqs: [
      { question: 'Is there a monthly subscription?', answer: 'No. The workspace uses a dollar balance. Provider usage receives a 20% platform markup, and automation respects the configured monthly budget.' },
      { question: 'What happens when the balance is too low?', answer: 'Research can continue when inexpensive, but the next video generation pauses and presents calculated top-up options before spending.' },
      { question: 'Does somebody need to approve every post?', answer: 'Only if you choose a review stage. Full publication mode is designed to continue without mandatory confirmation.' },
      { question: 'Can we change what the AI learned from the website?', answer: 'Yes. Product, audience, problem, solution and keyword territories are editable project context.' },
    ],
  },
  'education-teams': {
    title: 'Education teams',
    eyebrow: 'Evidence-aware educational video',
    promise: 'Make useful educational video as reusable as the knowledge behind it.',
    description: 'Framewise turns curriculum, product context and real learner questions into short-form videos that teach something concrete while consistently introducing the right audience to the learning experience.',
    audience: 'Built for course businesses, schools, tutoring products, learning platforms and instructional teams that already own valuable knowledge but struggle to translate it into platform-native video.',
    problemHeading: 'The knowledge exists. The short-form production system around it does not.',
    problems: [
      { title: 'Curriculum is not a content calendar', text: 'A lesson or PDF still needs a focused audience question, one takeaway, a hook and a visual situation.' },
      { title: 'Accuracy and attention pull apart', text: 'Educational teams cannot trade correctness for reach, but correct content can still be too abstract to hold attention.' },
      { title: 'Learner questions remain scattered', text: 'Misconceptions live across search, support, classrooms and communities instead of becoming a structured idea backlog.' },
      { title: 'Useful assets remain one-off', text: 'Evidence, scripts and captions are rarely kept as reusable production memory after publication.' },
    ],
    outcomes: [
      'Research identifies learner questions, misconceptions and timely primary evidence.',
      'Every candidate states its audience, learning value, problem, solution and reason it can hold attention.',
      'Claims remain connected to sources and uncertain outcomes are not invented.',
      'Storytelling turns abstract learning problems into filmable human situations.',
      'Evidence, scripts, captions, character maps and final videos remain reusable assets.',
      'Performance signals refine later research without replacing instructional judgment.',
    ],
    pillars: [
      { title: 'Misconception correction', text: 'Start with a believable wrong assumption and replace it with one memorable, defensible model.' },
      { title: 'Practical technique', text: 'Teach a small action, method or diagnostic the learner can apply immediately.' },
      { title: 'Why it matters', text: 'Use a story or real-world consequence to connect an abstract concept to lived experience.' },
      { title: 'Learning pathway', text: 'Show when the audience needs deeper instruction and how the product supports that next step.' },
    ],
    workflow: [
      { title: 'Understand the learning product', text: 'Framewise maps learners, their problem, the instructional approach and relevant topic territories.' },
      { title: 'Discover teachable moments', text: 'Fresh research finds narrow questions and evidence capable of supporting one useful takeaway.' },
      { title: 'Design the learning beat', text: 'The concept defines prior belief, tension, explanation, example and the observable learner payoff.' },
      { title: 'Author for attention', text: 'Gemini creates a fast hook, accurate dialogue, human action and the visual logic for each scene.' },
      { title: 'Review before generation', text: 'Quality and factual passes check usefulness, completeness, source support and fit with the actual learning product.' },
      { title: 'Build a reusable library', text: 'Generated work, captions, sources and outcomes remain connected so future research starts with accumulated memory.' },
    ],
    formats: [
      { title: 'Creator-led explanation', text: 'A teacher or expert delivers one clear idea with a stable role and approachable voice.' },
      { title: 'Storytelling sketch', text: 'Teacher, learner or parent roles dramatize a misconception, frustration or breakthrough.' },
      { title: 'Cinematic learning moment', text: 'Physical action and environment make an otherwise abstract principle visible.' },
      { title: 'Motion graphics', text: 'Processes, evidence, comparisons and mental models become structured visual explanations.' },
    ],
    setup: [
      { title: 'Learning context', text: 'Product, learners, prerequisite knowledge, instructional promise and important boundaries.' },
      { title: 'Evidence policy', text: 'Preferred source types, freshness, claim restrictions and topics that require additional review.' },
      { title: 'Content balance', text: 'How much output should teach, entertain or introduce the learning product.' },
      { title: 'Delivery system', text: 'Weekly cadence, duration, video defaults, budget and connected publication channels.' },
    ],
    feedback: 'Editorial choices and publication observations help Framewise notice which questions, explanations and formats deserve more investigation. The signal is never treated as proof that a teaching method works, and unexplored learner needs remain part of every research cycle.',
    examples: ['Course businesses', 'Schools and tutoring products', 'Instructional creators', 'Learning-platform marketing teams', 'Academic outreach teams', 'Professional training providers'],
    faqs: [
      { question: 'Does Framewise cite the research it uses?', answer: 'Research candidates retain their evidence packet and links. The production workflow carries mandatory facts and uncertainty constraints into the script.' },
      { question: 'Can an educator review the script first?', answer: 'Yes. Script-first production exposes the character map, timed dialogue and every detailed scene prompt before generation.' },
      { question: 'Is it only for promotional content?', answer: 'No. The content mix is configurable. A project can prioritize genuinely informative and learner-focused output while reserving a smaller share for promotion.' },
      { question: 'Can it create captions separately?', answer: 'Yes. Captions remain downloadable as SRT/VTT and are only burned into video when explicitly requested.' },
    ],
  },
}

const solutionLinks = [
  { to: '/solutions/studios-media-teams', label: 'Studios & media teams' },
  { to: '/solutions/creators-experts', label: 'Creators & experts' },
  { to: '/solutions/small-businesses', label: 'Small businesses' },
  { to: '/solutions/education-teams', label: 'Education teams' },
]

const route = useRoute()
const auth = useAuth()
const menuOpen = ref(false)
const solution = computed(() => solutions[String(route.params.slug)] || null)
if (!solution.value) throw createError({ statusCode: 404, statusMessage: 'Solution not found' })
const primaryCta = computed(() => auth.accessToken.value ? '/app' : '/register')
const primaryLabel = computed(() => auth.accessToken.value ? 'Open studio' : 'Create account')
const otherSolutions = computed(() => solutionLinks.filter(item => item.to !== route.path))
useSeoMeta({ title: () => `${solution.value!.title} — Framewise`, description: () => solution.value!.description, robots: 'index, follow' })
useHead({ link: [{ rel: 'canonical', href: `https://studio.subschool.us/solutions/${String(route.params.slug)}` }] })
</script>

<template>
  <div v-if="solution" class="solution-page">
    <header>
      <div class="container header-inner">
        <NuxtLink class="brand" to="/"><span><Clapperboard :size="20" /></span><strong>Framewise</strong></NuxtLink>
        <nav aria-label="Main navigation"><NuxtLink to="/#product">Product</NuxtLink><PublicSolutionsDropdown /><NuxtLink to="/#workflow">How it works</NuxtLink><NuxtLink to="/#examples">Examples</NuxtLink><NuxtLink to="/#pricing">Pricing</NuxtLink></nav>
        <div class="actions"><NuxtLink v-if="!auth.accessToken.value" to="/login">Sign in</NuxtLink><NuxtLink class="button" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="14" /></NuxtLink></div>
        <button class="menu" type="button" aria-label="Toggle navigation" :aria-expanded="menuOpen" @click="menuOpen=!menuOpen"><X v-if="menuOpen" /><Menu v-else /></button>
      </div>
      <div v-if="menuOpen" class="mobile"><span>Solutions</span><NuxtLink v-for="item in solutionLinks" :key="item.to" :to="item.to" @click="menuOpen=false">{{ item.label }}</NuxtLink><NuxtLink to="/" @click="menuOpen=false">Product overview</NuxtLink><NuxtLink to="/login" @click="menuOpen=false">Sign in</NuxtLink></div>
    </header>

    <main>
      <section class="hero"><div class="container"><div class="breadcrumb"><NuxtLink to="/">Framewise</NuxtLink><span>/</span><strong>{{ solution.title }}</strong></div><span class="eyebrow">{{ solution.eyebrow }}</span><h1>{{ solution.promise }}</h1><p>{{ solution.description }}</p><NuxtLink class="button button--primary" :to="primaryCta">Build your content engine <ArrowRight :size="15" /></NuxtLink></div></section>
      <section class="audience"><div class="container audience-grid"><div><span class="eyebrow">Who it is for</span><h2>{{ solution.audience }}</h2></div><div class="audience-note"><Sparkles :size="19" /><p>One onboarding creates the context. Research, production, budget control, publishing and feedback keep running from it.</p></div></div></section>
      <section class="problems"><div class="container"><div class="section-heading"><span class="eyebrow">The operating problem</span><h2>{{ solution.problemHeading }}</h2></div><div class="problem-grid"><article v-for="item in solution.problems" :key="item.title"><h3>{{ item.title }}</h3><p>{{ item.text }}</p></article></div></div></section>
      <section class="outcomes"><div class="container"><div class="section-heading"><span class="eyebrow">What changes</span><h2>A working content operation, not another generation tool.</h2></div><div class="outcome-grid"><article v-for="item in solution.outcomes" :key="item"><Check :size="18" /><p>{{ item }}</p></article></div></div></section>
      <section class="pillars"><div class="container"><div class="section-heading section-heading--light"><span class="eyebrow">Audience-specific content plan</span><h2>Research is shaped around the work this audience actually needs.</h2></div><div class="pillar-grid"><article v-for="(item,index) in solution.pillars" :key="item.title"><b>0{{ index+1 }}</b><h3>{{ item.title }}</h3><p>{{ item.text }}</p></article></div></div></section>
      <section class="workflow"><div class="container"><div class="section-heading"><span class="eyebrow">The autonomous workflow</span><h2>From one project context to the next published video.</h2></div><div class="workflow-list"><article v-for="(item,index) in solution.workflow" :key="item.title"><b>0{{ index+1 }}</b><div><h3>{{ item.title }}</h3><p>{{ item.text }}</p></div></article></div></div></section>
      <section class="formats"><div class="container"><div class="section-heading"><span class="eyebrow">Creative direction</span><h2>The idea chooses the format. The format does not limit the ideas.</h2></div><div class="format-grid"><article v-for="item in solution.formats" :key="item.title"><span><Clapperboard :size="18" /></span><h3>{{ item.title }}</h3><p>{{ item.text }}</p></article></div></div></section>
      <section class="setup"><div class="container setup-grid"><div><span class="eyebrow">Configure once</span><h2>Your operating rules become the agent’s boundaries.</h2><p>Every value remains editable later. Automation can stop after research, after scripts, after video creation or continue through publication.</p></div><div class="setup-list"><article v-for="item in solution.setup" :key="item.title"><Check :size="16" /><div><h3>{{ item.title }}</h3><p>{{ item.text }}</p></div></article></div></div></section>
      <section class="feedback"><div class="container feedback-card"><span class="eyebrow">Closed-loop improvement</span><h2>Publishing is not the end of the workflow.</h2><p>{{ solution.feedback }}</p><div><span>24-hour observation</span><span>7-day observation</span><span>Selection &amp; rejection memory</span><span>20% exploration floor</span></div></div></section>
      <section class="use-cases"><div class="container"><div class="section-heading"><span class="eyebrow">Where it fits</span><h2>Designed for real teams and repeatable output.</h2></div><div class="case-list"><span v-for="item in solution.examples" :key="item"><Sparkles :size="14" /> {{ item }}</span></div></div></section>
      <section class="faq"><div class="container faq-grid"><div><span class="eyebrow">Questions</span><h2>What teams usually need to know.</h2></div><div><details v-for="item in solution.faqs" :key="item.question"><summary>{{ item.question }}</summary><p>{{ item.answer }}</p></details></div></div></section>
      <section class="other"><div class="container"><span class="eyebrow">Other solutions</span><div><NuxtLink v-for="item in otherSolutions" :key="item.to" :to="item.to">{{ item.label }} <ArrowRight :size="14" /></NuxtLink></div></div></section>
      <section class="cta"><div class="container"><h2>Give Framewise the context once.</h2><p>Let the next research, script, video and publication move without another blank prompt.</p><NuxtLink class="button button--light" :to="primaryCta">{{ primaryLabel }} <ArrowRight :size="15" /></NuxtLink></div></section>
    </main>

    <footer><div class="container"><NuxtLink class="brand" to="/"><span><Clapperboard :size="17" /></span><strong>Framewise</strong></NuxtLink><div><NuxtLink v-for="item in solutionLinks" :key="item.to" :to="item.to">{{ item.label }}</NuxtLink></div></div></footer>
  </div>
</template>

<style scoped>
.solution-page{--ink:#17131f;--muted:#68616d;--line:#e6dfe8;background:#fbfaf8;color:var(--ink)}.container{width:min(1180px,calc(100% - 44px));margin:auto}header{position:relative;z-index:80;border-bottom:1px solid rgb(40 26 44/8%);background:rgb(251 250 248/92%);backdrop-filter:blur(18px)}.header-inner{display:flex;height:76px;align-items:center}.brand{display:flex;align-items:center;gap:9px;font-family:var(--font-display);font-size:16px}.brand>span{display:grid;width:36px;height:36px;place-items:center;border-radius:10px;background:linear-gradient(145deg,#c37ad4,#792a8d);color:white}.header-inner nav{display:flex;align-items:center;gap:28px;margin:auto;color:#5d5762;font-size:11px;font-weight:700}.header-inner nav a,.actions>a:first-child{color:#5d5762;font-size:11px;font-weight:700}.actions{display:flex;align-items:center;gap:18px}.button{display:inline-flex;min-height:40px;align-items:center;justify-content:center;gap:7px;padding:0 16px;border-radius:10px;background:#19141e;color:white;font-size:10px;font-weight:850}.menu,.mobile{display:none}.mobile>span{padding:10px 9px 3px;color:#9b909e;font-size:8px;font-weight:900;text-transform:uppercase;letter-spacing:.14em}.hero{position:relative;padding:58px 0 108px;overflow:hidden;background:radial-gradient(circle at 72% 18%,rgb(213 155 226/28%),transparent 34%)}.hero::after{position:absolute;top:-260px;right:-170px;width:620px;height:620px;border:1px solid rgb(126 42 146/10%);border-radius:50%;box-shadow:0 0 0 85px rgb(126 42 146/3%),0 0 0 170px rgb(126 42 146/2%);content:''}.hero>.container{position:relative;z-index:1}.breadcrumb{display:flex;align-items:center;gap:8px;margin-bottom:62px;color:#877e8b;font-size:9px}.breadcrumb strong{color:#4c4550}.eyebrow{display:block;color:#8e2fa3;font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.16em}.hero h1{max-width:900px;margin:18px 0 23px;font-family:var(--font-display);font-size:clamp(48px,6vw,78px);line-height:.99;letter-spacing:-.067em}.hero p{max-width:800px;margin:0;color:var(--muted);font-size:15px;line-height:1.72}.button--primary{margin-top:29px;background:linear-gradient(135deg,#b25bc6,#79288d);box-shadow:0 14px 32px rgb(121 40 141/22%)}.audience,.problems,.outcomes,.workflow,.formats,.setup,.feedback,.use-cases,.faq,.other{padding:105px 0}.audience{background:#fff}.audience-grid{display:grid;grid-template-columns:1.35fr .65fr;align-items:center;gap:90px}.audience h2,.section-heading h2,.setup h2,.faq h2{margin:14px 0 0;font-family:var(--font-display);font-size:42px;line-height:1.08;letter-spacing:-.055em}.audience-note{display:flex;align-items:flex-start;gap:13px;padding:25px;border:1px solid var(--line);border-radius:16px;background:#fbf7fc}.audience-note svg{flex:none;color:#952fab}.audience-note p{margin:0;color:#655c69;font-size:11px;line-height:1.7}.problems{background:#f7f4f7}.section-heading{max-width:790px;margin-bottom:44px}.problem-grid{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);border-radius:17px;background:#fff}.problem-grid article{min-height:190px;padding:28px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.problem-grid article:nth-child(2n){border-right:0}.problem-grid article:nth-last-child(-n+2){border-bottom:0}.problem-grid h3,.pillar-grid h3,.workflow-list h3,.format-grid h3,.setup-list h3{margin:0 0 10px;font-family:var(--font-display);font-size:16px}.problem-grid p,.pillar-grid p,.workflow-list p,.format-grid p,.setup-list p{margin:0;color:var(--muted);font-size:10px;line-height:1.72}.outcomes{background:#fff}.outcome-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.outcome-grid article{display:flex;align-items:flex-start;gap:13px;padding:22px;border:1px solid var(--line);border-radius:13px;background:#fff}.outcome-grid svg{flex:none;color:#268f60}.outcome-grid p{margin:0;color:#5f5864;font-size:11px;line-height:1.65}.pillars{padding:105px 0;background:#19141e;color:#fff}.section-heading--light h2{max-width:760px}.pillar-grid{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid rgb(255 255 255/9%);border-radius:17px}.pillar-grid article{min-height:260px;padding:27px;border-right:1px solid rgb(255 255 255/8%)}.pillar-grid article:last-child{border:0}.pillar-grid b{color:#d698e5;font-size:9px}.pillar-grid h3{margin-top:65px}.pillar-grid p{color:#b9b0bd}.workflow{background:#fbfaf8}.workflow-list{display:grid}.workflow-list article{display:grid;grid-template-columns:80px 1fr;gap:22px;padding:25px 0;border-top:1px solid var(--line)}.workflow-list article:last-child{border-bottom:1px solid var(--line)}.workflow-list b{color:#9a35ae;font-size:10px}.workflow-list h3{font-size:18px}.workflow-list p{max-width:760px;font-size:11px}.formats{background:#f3edf4}.format-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.format-grid article{min-height:260px;padding:25px;border:1px solid #e2d6e5;border-radius:15px;background:#fff}.format-grid article>span{display:grid;width:42px;height:42px;place-items:center;border-radius:11px;background:#f8ebfa;color:#902ca6}.format-grid h3{margin-top:48px}.setup{background:#fff}.setup-grid{display:grid;grid-template-columns:.8fr 1.2fr;gap:95px}.setup-grid>div:first-child>p{margin:20px 0 0;color:var(--muted);font-size:12px;line-height:1.75}.setup-list{display:grid}.setup-list article{display:flex;gap:13px;padding:20px 0;border-top:1px solid var(--line)}.setup-list article:last-child{border-bottom:1px solid var(--line)}.setup-list svg{flex:none;color:#268f60}.setup-list h3{font-size:14px}.feedback{background:#fbfaf8}.feedback-card{padding:55px;border:1px solid var(--line);border-radius:22px;background:#201724;color:#fff;box-shadow:0 30px 75px rgb(37 23 42/12%)}.feedback-card h2{margin:15px 0;font-family:var(--font-display);font-size:40px;letter-spacing:-.05em}.feedback-card>p{max-width:850px;margin:0;color:#c4b9c8;font-size:12px;line-height:1.8}.feedback-card>div{display:flex;flex-wrap:wrap;gap:8px;margin-top:28px}.feedback-card>div span{padding:9px 12px;border:1px solid rgb(255 255 255/10%);border-radius:999px;color:#decde2;font-size:9px}.use-cases{background:#fff}.case-list{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.case-list span{display:flex;align-items:center;gap:9px;padding:17px;border:1px solid var(--line);border-radius:11px;color:#574f5b;font-size:10px;font-weight:750}.case-list svg{color:#922fa8}.faq{background:#f7f4f7}.faq-grid{display:grid;grid-template-columns:.75fr 1.25fr;gap:100px}.faq details{border-top:1px solid #ded5e1}.faq details:last-child{border-bottom:1px solid #ded5e1}.faq summary{padding:22px 0;font-size:12px;font-weight:800;cursor:pointer}.faq details p{margin:-7px 0 22px;color:var(--muted);font-size:10px;line-height:1.75}.other{padding-top:70px;padding-bottom:70px;background:#fff}.other .container>div{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:20px}.other a{display:flex;align-items:center;justify-content:space-between;padding:18px;border:1px solid var(--line);border-radius:11px;color:#5d196b;font-size:10px;font-weight:800}.cta{padding:100px 0;background:linear-gradient(135deg,#9b42b1,#5e1d6d);color:white;text-align:center}.cta h2{margin:0;font-family:var(--font-display);font-size:46px;letter-spacing:-.058em}.cta p{margin:12px 0 26px;color:#eedcf1;font-size:12px}.button--light{background:white;color:#5c176c}footer{padding:40px 0;background:#100d14;color:#9f97a4}footer>.container{display:flex;align-items:center;gap:30px}footer .brand{color:white;font-size:13px}footer .brand>span{width:29px;height:29px}footer>.container>div{display:flex;flex-wrap:wrap;gap:18px;margin-left:auto}footer>.container>div a{color:#b8afb9;font-size:9px}
@media(max-width:850px){.header-inner nav,.actions{display:none}.menu{display:grid;margin-left:auto;background:transparent}.mobile{display:grid;gap:4px;padding:8px 22px 17px}.mobile a{padding:9px;font-size:11px}.audience-grid,.setup-grid,.faq-grid{grid-template-columns:1fr;gap:38px}.pillar-grid,.format-grid{grid-template-columns:1fr 1fr}.pillar-grid article:nth-child(2){border-right:0}.pillar-grid article:nth-child(-n+2){border-bottom:1px solid rgb(255 255 255/8%)}.case-list{grid-template-columns:1fr 1fr}.other .container>div{grid-template-columns:1fr}}
@media(max-width:540px){.container{width:min(100% - 30px,1180px)}.hero{padding:48px 0 78px}.breadcrumb{margin-bottom:45px}.hero h1{font-size:43px}.audience,.problems,.outcomes,.pillars,.workflow,.formats,.setup,.feedback,.use-cases,.faq{padding:75px 0}.audience h2,.section-heading h2,.setup h2,.faq h2{font-size:33px}.problem-grid,.outcome-grid,.pillar-grid,.format-grid,.case-list{grid-template-columns:1fr}.problem-grid article{border-right:0}.problem-grid article:nth-last-child(2){border-bottom:1px solid var(--line)}.pillar-grid article{min-height:210px;border-right:0;border-bottom:1px solid rgb(255 255 255/8%)}.pillar-grid article:nth-child(2){border-bottom:1px solid rgb(255 255 255/8%)}.format-grid article{min-height:220px}.feedback-card{padding:34px 24px}.feedback-card h2{font-size:33px}.cta h2{font-size:36px}footer>.container{align-items:flex-start;flex-direction:column}footer>.container>div{display:grid;margin-left:0}}
</style>
