"""
UPSC-specific prompts for Gemini. The taxonomy below is the actual filter — keep it tight.
A loose prompt will return everything as 'relevant'.
"""

UPSC_SYLLABUS_TAXONOMY = """
UPSC CSE SYLLABUS REFERENCE (Prelims + Mains):

PRELIMS:
- Current events of national & international importance
- History of India and Indian National Movement
- Indian and World Geography (physical, social, economic)
- Indian Polity & Governance — Constitution, Political System, Panchayati Raj, Public Policy, Rights Issues
- Economic and Social Development — Sustainable Development, Poverty, Inclusion, Demographics, Social Sector Initiatives
- Environmental Ecology, Biodiversity, Climate Change (no subject specialisation required)
- General Science

MAINS GS-1: Indian Heritage & Culture, History (modern Indian, post-independence consolidation, world history), Geography (physical, resource distribution, factors of location of industries, geophysical phenomena), Indian Society (diversity, women, population, urbanisation, globalisation effects, communalism, secularism, regionalism)

MAINS GS-2: Constitution (features, amendments, basic structure), Functions of Union & States, Separation of Powers, Comparison with other constitutions, Parliament & State Legislatures, Executive & Judiciary, Pressure Groups, Representation of People's Act, Statutory/Regulatory/Quasi-Judicial Bodies, Government Policies & Interventions, Development Processes & NGOs, Welfare Schemes (vulnerable sections), Health/Education/Human Resources, Poverty & Hunger issues, Governance/Transparency/Accountability, Civil Services role, India & neighbourhood, Bilateral/Regional/Global groupings, Effect of policies of developed/developing countries on India's interests, Indian diaspora, International institutions

MAINS GS-3: Indian Economy (planning, mobilization of resources, growth, development, employment), Inclusive Growth, Government Budgeting, Agriculture (cropping patterns, irrigation, storage, transport, marketing, e-tech, subsidies, MSP, PDS, food security, technology missions, animal rearing economics, food processing), Land Reforms, Effects of liberalization, Infrastructure (energy, ports, roads, airports, railways), Investment models, Science & Technology (developments, indigenization, achievements of Indians, IT/Space/Computers/Robotics/Nano/Biotech/IPR), Conservation, Environmental Pollution & Degradation, EIA, Disaster Management, Linkages between development & spread of extremism, Internal Security challenges (external state/non-state actors, communication networks, social media, cyber security, money laundering), Border management, Security forces & their mandate

MAINS GS-4: Ethics, Integrity, Aptitude — ethics & human interface, attitude, aptitude & foundational values for civil services, emotional intelligence, contributions of moral thinkers, public/civil service values, probity in governance, case studies

NOT UPSC-RELEVANT (filter OUT):
- Bollywood/celebrity news, entertainment gossip, OTT reviews
- Cricket/IPL match reports (unless a policy/governance angle)
- Stock market daily movements, individual company quarterly results
- Local crime briefs without policy implication
- Lifestyle, fashion, food blogs, travel diaries
- Political party internal squabbles, election campaign tactics (unless RPA/ECI/electoral reform angle)
- Opinion pieces that are pure partisan commentary
"""


CLASSIFICATION_PROMPT = """You are a UPSC Civil Services Exam (CSE) preparation assistant trained on the official syllabus.

{taxonomy}

TASK: Read the article and decide if it is UPSC-relevant.

Article Title: {title}
Article Section: {section}
Article URL: {url}
Article Content (first 3000 chars):
{content}

Output a JSON object with EXACTLY these fields. No prose, no markdown fences:
{{
  "relevant": true | false,
  "relevance_score": 1-10 integer (10 = essential UPSC content, 1 = irrelevant),
  "primary_paper": "Prelims" | "GS1" | "GS2" | "GS3" | "GS4" | "None",
  "secondary_papers": ["..."] (other papers it touches; empty list if none),
  "topics": ["3-5 specific syllabus topics it maps to"],
  "reason": "ONE sentence — why it is or isn't UPSC-relevant"
}}

Be STRICT. If you wouldn't actually use this article in a Mains answer or remember it for Prelims, mark relevant=false. Score >= 6 means worth reading.
"""


SUMMARIZATION_PROMPT = """You are creating UPSC-style notes for a serious aspirant. No fluff, no rephrasing the article. Extract what's exam-useful.

Article Title: {title}
Section: {section}
URL: {url}
Primary Paper: {primary_paper}
Topics: {topics}

Full article:
{content}

Produce JSON with EXACTLY these fields:
{{
  "headline": "the article's headline as-is",
  "one_line_summary": "single sentence — what's the news/issue",
  "context": "2-3 sentences — background/why this is happening now",
  "key_facts": ["bullet 1", "bullet 2", ...] (5-8 specific facts: names, numbers, dates, schemes, articles of constitution, treaties, locations, institutions — things you'd need for Prelims),
  "prelims_pointers": ["specific factual hooks that could be MCQ material"],
  "mains_angle": "2-4 sentences — the analytical/argumentative angle for Mains. What's the issue, stakeholders, way forward.",
  "possible_questions": ["1-2 plausible Mains questions in UPSC style"],
  "related_topics": ["other syllabus topics this connects to for revision"]
}}

Rules:
- Use specific terms from the syllabus taxonomy.
- If the article mentions a constitutional article, scheme, act, treaty, institution, or report — name it explicitly.
- If a number/date/name isn't in the article, do NOT invent it. Skip it.
- Keep prose tight. Aspirants don't have time.
"""
