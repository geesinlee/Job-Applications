export const meta \= {                                                                                       ╎  
  name: 'deep-research',                                                                                    ╎  
  description: 'Deep research harness — fan-out web searches, fetch sourc                                   ╎  
es, adversarially verify claims, synthesize a cited report.',                                               ╎  
  whenToUse: 'When the user wants a deep, multi-source, fact-checked rese                                   ╎  
arch report on any topic. BEFORE invoking, check if the question is speci                                   ╎  
fic enough to research directly — if underspecified (e.g., "what car to b                                   ╎  
uy" without budget/use-case/region), ask 2-3 clarifying questions to narr                                   ╎  
ow scope. Then pass the refined question as args, weaving the answers in.                                   ╎  
',                                                                                                          ╎  
  phases: \[{"title":"Scope","detail":"Decompose question (from args) into                                   ╎  
 5 search angles"},{"title":"Search","detail":"5 parallel WebSearch agent                                   ╎  
s, one per angle"},{"title":"Fetch","detail":"URL-dedup, fetch top 15 sou                                   ╎  
rces, extract falsifiable claims"},{"title":"Verify","detail":"3-vote adv                                   ╎  
ersarial verification per claim (need 2/3 refutes to kill)"},{"title":"Sy                                   ╎  
nthesize","detail":"Merge semantic dupes, rank by confidence, cite source                                   ╎  
s"}\],                                                                                                       ╎  
}                                                                              ╎  
                                                                                                            ╎  
// deep-research: Scope → pipeline(Seact) →                                    ╎  
3-vote Verify → Synthesize                                                                                  ╎  
// Ported from bughunter architectureof git/                                   ╎  
grep.                                                                                                       ╎  
// Question is passed via Workflow({n\<questi                                   ╎  
on\>'}).                                                                                                     ╎  
                                                                               ╎  
const VOTES\_PER\_CLAIM \= 3                                                                                   ╎  
const REFUTATIONS\_REQUIRED \= 2                                                 ╎  
const MAX\_FETCH \= 15                                                                                        ╎  
const MAX\_VERIFY\_CLAIMS \= 25                                                   ╎  
                                                                                                            ╎  
// ─── Schemas ───                                                             ╎  
const SCOPE\_SCHEMA \= {                                                                                      ╎  
  type: "object", required: \["questio                                          ╎  
  properties: {                                                                                             ╎  
    question: { type: "string" },                                              ╎  
    summary: { type: "string" },                                                                            ╎  
    angles: { type: "array", minItems                                          ╎  
      type: "object", required: \["label", "query"\],                                                         ╎  
      properties: {                                                            ╎  
        label: { type: "string" },                                                                          ╎  
        query: { type: "string" },                                             ╎  
        rationale: { type: "string" },                                                                      ╎  
      },                                                                       ╎  
    }},                                                                                                     ╎  
  },                                                                           ╎  
}                                                                                                           ╎  
const SEARCH\_SCHEMA \= {                                                        ╎  
  type: "object", required: \["results"\],                                                                    ╎  
  properties: {                                                                ╎  
    results: { type: "array", maxItems: 6, items: {                                                         ╎  
      type: "object", required: \["url                                          ╎  
      properties: {                                                                                         ╎  
        url: { type: "string" },                                               ╎  
        title: { type: "string" },                                                                          ╎  
        snippet: { type: "string" },                                           ╎  
        relevance: { enum: \["high", "medium", "low"\] },                                                     ╎  
      },                                                                       ╎  
    }},                                                                                                     ╎  
  },                                                                           ╎  
}                                                                                                           ╎  
const EXTRACT\_SCHEMA \= {                                                       ╎  
  type: "object", required: \["claims", "sourceQuality"\],                                                    ╎  
  properties: {                                                                ╎  
    sourceQuality: { enum: \["primary", "secondary", "blog", "forum", "unr                                   ╎  
eliable"\] },                                                                   ╎  
    publishDate: { type: "string" },                                                                        ╎  
    claims: { type: "array", maxItems                                          ╎  
      type: "object", required: \["claim", "quote", "importance"\],                                           ╎  
      properties: {                                                            ╎  
        claim: { type: "string" },                                                                          ╎  
        quote: { type: "string" },                                             ╎  
        importance: { enum: \["central", "supporting", "tangential"\] },                                      ╎  
      },                                                                       ╎  
    }},                                                                                                     ╎  
  },                                                                           ╎  
}                                                                                                           ╎  
const VERDICT\_SCHEMA \= {                                                       ╎  
  type: "object", required: \["refuted", "evidence", "confidence"\],                                          ╎  
  properties: {                                                                ╎  
    refuted: { type: "boolean" },                                                                           ╎  
    evidence: { type: "string" },                                              ╎  
    confidence: { enum: \["high", "medium", "low"\] },                                                        ╎  
    counterSource: { type: "string" }                                          ╎  
  },                                                                                                        ╎  
}                                                                              ╎  
const REPORT\_SCHEMA \= {                                                                                     ╎  
  type: "object", required: \["summary                                          ╎  
  properties: {                                                                                             ╎  
    summary: { type: "string" },                                               ╎  
    findings: { type: "array", items: {                                                                     ╎  
      type: "object", required: \["cla "evide                                   ╎  
nce"\],                                                                                                      ╎  
      properties: {                                                            ╎  
        claim: { type: "string" },                                                                          ╎  
        confidence: { enum: \["high",                                           ╎  
        sources: { type: "array", items: { type: "string" } },                                              ╎  
        evidence: { type: "string" },                                          ╎  
        vote: { type: "string" },                                                                           ╎  
      },                                                                       ╎  
    }},                                                                                                     ╎  
    caveats: { type: "string" },                                               ╎  
    openQuestions: { type: "array", items: { type: "string" } },                                            ╎  
  },                                                                           ╎  
}                                                                                                           ╎  
                                                                               ╎  
// ─── Phase 0: Scope — decompose question into search angles ───                                           ╎  
phase("Scope")                                                                 ╎  
const QUESTION \= (typeof args \=== "string" && args.trim()) || ""                                            ╎  
if (\!QUESTION) {                                                               ╎  
  return { error: "No research question provided. Pass it as args: Workfl                                   ╎  
ow({name: 'deep-research', args: '\<qu                                          ╎  
}                                                                                                           ╎  
const scope \= await agent(                                                     ╎  
  "Decompose this research question into complementary search angles.\\n\\n                                   ╎  
" \+                                                                            ╎  
  "\#\# Question\\n" \+ QUESTION \+ "\\n\\n" \+                                                                     ╎  
  "\#\# Task\\n" \+                                                                ╎  
  "Generate 5 distinct web search queries that together cover the questio                                   ╎  
n from different angles. Pick angles in. Exa                                   ╎  
mples:\\n" \+                                                                                                 ╎  
  "- broad/primary  · academic/techniian/ske                                   ╎  
ptical  · practitioner/implementation\\n" \+                                                                  ╎  
  "- For medical: anatomy · common ca· autho                                   ╎  
ritative refs · red flags\\n" \+                                                                              ╎  
  "- For tech: state-of-art · benchmaadoptio                                   ╎  
n · cost/tradeoffs\\n\\n" \+                                                                                   ╎  
  "Make queries specific enough to suoid red                                   ╎  
undancy.\\n" \+                                                                                               ╎  
  "Return: the question (verbatim or ntence                                    ╎  
decomposition strategy, and the angles.\\n\\nStructured output only.",                                        ╎  
  { label: "scope", schema: SCOPE\_SCH                                          ╎  
)                                                                                                           ╎  
if (\!scope) {                                                                  ╎  
  return { error: "Scope agent returned no result — cannot decompose the                                    ╎  
research question." }                                                          ╎  
}                                                                                                           ╎  
log("Q: " \+ QUESTION.slice(0, 80\) \+ (""))                                      ╎  
log("Decomposed into " \+ scope.angles.length \+ " angles: " \+ scope.angles                                   ╎  
.map(a \=\> a.label).join(", "))                                                 ╎  
                                                                                                            ╎  
// ─── Dedup state — accumulates acro ───                                      ╎  
const normURL \= u \=\> {                                                                                      ╎  
  try {                                                                        ╎  
    const p \= new URL(u)                                                                                    ╎  
    return (p.hostname.replace(/^www\\/\\/$/,                                    ╎  
"")).toLowerCase()                                                                                          ╎  
  } catch { return u.toLowerCase() }                                           ╎  
}                                                                                                           ╎  
const seen \= new Map()                                                         ╎  
const dupes \= \[\]                                                                                            ╎  
const budgetDropped \= \[\]                                                       ╎  
const relRank \= { high: 0, medium: 1, low: 2 }                                                              ╎  
let fetchSlots \= MAX\_FETCH                                                     ╎  
                                                                                                            ╎  
// ─── Prompts ───                                                             ╎  
const SEARCH\_PROMPT \= (angle) \=\>                                                                            ╎  
  "\#\# Web Searcher: " \+ angle.label \+                                          ╎  
  "Research question: \\"" \+ QUESTION \+ "\\"\\n\\n" \+                                                           ╎  
  "Your angle: \*\*" \+ angle.label \+ "\*") \+ "\\                                   ╎  
n" \+                                                                                                        ╎  
  "Search query: \`" \+ angle.query \+ "                                          ╎  
  "\#\# Task\\nUse WebSearch with the query above (or a refined version). Re                                   ╎  
turn the top 4-6 most relevant result                                          ╎  
  "Rank by relevance to the ORIGINAL question, not just the search query.                                   ╎  
 Skip obvious SEO spam/content farms.                                          ╎  
  "Include a short snippet capturing why each result is relevant.\\n\\nStru                                   ╎  
ctured output only."                                                           ╎  
                                                                                                            ╎  
const FETCH\_PROMPT \= (source, angle)                                           ╎  
  "\#\# Source Extractor\\n\\n" \+                                                                               ╎  
  "Research question: \\"" \+ QUESTION                                           ╎  
  "Fetch and extract key claims from this source:\\n" \+                                                      ╎  
  "\*\*URL:\*\* " \+ source.url \+ "\\n\*\*Tit\*Found                                    ╎  
via:\*\* " \+ angle \+ " search\\n\\n" \+                                                                          ╎  
  "\#\# Task\\n1. Use WebFetch to retrie                                          ╎  
  "2. Assess source quality: primary research/institution? secondary repo                                   ╎  
rting? blog/opinion? forum? unreliabl                                          ╎  
  "3. Extract 2-5 FALSIFIABLE claims that bear on the research question.                                    ╎  
Each claim must:\\n" \+                                                          ╎  
  "   \- be a concrete, checkable statement (not vague generalities)\\n" \+                                    ╎  
  "   \- include a direct quote from t                                          ╎  
  "   \- be rated central/supporting/tangential to the research question\\n                                   ╎  
" \+                                                                            ╎  
  "4. Note publish date if available.\\n\\n" \+                                                                ╎  
  "If the fetch fails or the page is claims:                                   ╎  
 \[\] and sourceQuality: \\"unreliable\\".\\n\\nStructured output only."                                          ╎  
                                                                               ╎  
const VERIFY\_PROMPT \= (claim, v) \=\>                                                                         ╎  
  "\#\# Adversarial Claim Verifier (votPER\_CLA                                   ╎  
IM \+ ")\\n\\n" \+                                                                                              ╎  
  "Be SKEPTICAL. Try to REFUTE this cED \+ "/                                   ╎  
" \+ VOTES\_PER\_CLAIM \+ " refutations kill it.\\n\\n" \+                                                         ╎  
  "\#\# Research question\\n" \+ QUESTION                                          ╎  
  "\#\# Claim under review\\n\\"" \+ claim.claim \+ "\\"\\n\\n" \+                                                    ╎  
  "\*\*Source:\*\* " \+ claim.sourceUrl \+ ")\\n" \+                                   ╎  
  "\*\*Supporting quote:\*\* \\"" \+ claim.quote \+ "\\"\\n\\n" \+                                                     ╎  
  "\#\# Checklist\\n" \+                                                           ╎  
  "1. Is the claim actually supported by the quote, or is it an overreach                                   ╎  
/misread?\\n" \+                                                                 ╎  
  "2. WebSearch for contradicting evidence — does any credible source dis                                   ╎  
pute or heavily qualify this?\\n" \+                                             ╎  
  "3. Is the source quality sufficient for the claim's strength? (extraor                                   ╎  
dinary claims need primary sources)\\n                                          ╎  
  "4. Is the claim outdated? (check dates — old claims about fast-moving                                    ╎  
fields are suspect)\\n" \+                                                       ╎  
  "5. Is this a marketing claim / press release / cherry-picked benchmark                                   ╎  
 / forum speculation?\\n\\n" \+                                                   ╎  
  "\*\*refuted=true\*\* if: unsupported by quote / contradicted / low-quality                                   ╎  
 source for strong claim / outdated /                                          ╎  
  "\*\*refuted=false\*\* ONLY if: claim is well-supported, current, and sourc                                   ╎  
e quality matches claim strength.\\n"                                           ╎  
  "Default to refuted=true if uncertain.\\n\\nStructured output only. Evide                                   ╎  
nce MUST be specific."                                                         ╎  
                                                                                                            ╎  
// ─── Pipeline: search → dedup → fet                                          ╎  
const searchResults \= await pipeline(                                                                       ╎  
  scope.angles,                                                                ╎  
                                                                                                            ╎  
  angle \=\> agent(SEARCH\_PROMPT(angle)                                          ╎  
    label: "search:" \+ angle.label, phase: "Search", schema: SEARCH\_SCHEM                                   ╎  
A                                                                              ╎  
  }).then(r \=\> {                                                                                            ╎  
    if (\!r) return null                                                        ╎  
    log(angle.label \+ ": " \+ r.results.length \+ " results")                                                 ╎  
    return { angle: angle.label, resu                                          ╎  
  }),                                                                                                       ╎  
                                                                               ╎  
  searchResult \=\> {                                                                                         ╎  
    const sorted \= \[...searchResult.rk\[a.rel                                   ╎  
evance\] \- relRank\[b.relevance\])                                                                             ╎  
    const novel \= sorted.filter(r \=\>                                           ╎  
      const key \= normURL(r.url)                                                                            ╎  
      if (seen.has(key)) {                                                     ╎  
        dupes.push({ ...r, angle: searchResult.angle, dupOf: seen.get(key                                   ╎  
) })                                                                           ╎  
        return false                                                                                        ╎  
      }                                                                        ╎  
      if (fetchSlots \<= 0 && relRank\[r.relevance\] \>= 1\) {                                                   ╎  
        budgetDropped.push({ ...r, an                                          ╎  
        return false                                                                                        ╎  
      }                                                                        ╎  
      seen.set(key, { angle: searchResult.angle, title: r.title })                                          ╎  
      fetchSlots--                                                             ╎  
      return true                                                                                           ╎  
    })                                                                         ╎  
    if (novel.length \< searchResult.results.length) {                                                       ╎  
      log(searchResult.angle \+ ": " \+(search                                   ╎  
Result.results.length \- novel.length) \+ " filtered)")                                                       ╎  
    }                                                                          ╎  
    return parallel(                                                                                        ╎  
      novel.map(source \=\> () \=\> {                                              ╎  
        let host \= "unknown"                                                                                ╎  
        try { host \= new URL(source.u, "") }                                   ╎  
 catch {}                                                                                                   ╎  
        return agent(FETCH\_PROMPT(sou                                          ╎  
          label: "fetch:" \+ host,                                                                           ╎  
          phase: "Fetch",                                                      ╎  
          schema: EXTRACT\_SCHEMA,                                                                           ╎  
        }).then(ext \=\> {                                                       ╎  
          // User-skip → null; drop it (filtered by searchResults.flat().                                   ╎  
filter(Boolean))                                                               ╎  
          // rather than throwing into .catch() and mislabeling it "unrel                                   ╎  
iable".                                                                        ╎  
          if (\!ext) return null                                                                             ╎  
          return {                                                             ╎  
            url: source.url, title: source.title, angle: searchResult.ang                                   ╎  
le,                                                                            ╎  
            sourceQuality: ext.sourceQuality, publishDate: ext.publishDat                                   ╎  
e,                                                                             ╎  
            claims: ext.claims.map(c \=\> ({ ...c, sourceUrl: source.url, s                                   ╎  
ourceQuality: ext.sourceQuality })),                                           ╎  
          }                                                                                                 ╎  
        }).catch(e \=\> {                                                        ╎  
          log("fetch failed: " \+ source.url \+ " — " \+ (e.message || e))                                     ╎  
          return { url: source.url, tarchRes                                   ╎  
ult.angle, sourceQuality: "unreliable", claims: \[\] }                                                        ╎  
        })                                                                     ╎  
      })                                                                                                    ╎  
    )                                                                          ╎  
  }                                                                                                         ╎  
)                                                                              ╎  
                                                                                                            ╎  
const allSources \= searchResults.flat                                          ╎  
const allClaims \= allSources.flatMap(s \=\> s.claims)                                                         ╎  
const impRank \= { central: 0, support                                          ╎  
const qualRank \= { primary: 0, secondary: 1, blog: 2, forum: 3, unreliabl                                   ╎  
e: 4 }                                                                         ╎  
                                                                                                            ╎  
const rankedClaims \= \[...allClaims\]                                            ╎  
  .sort((a, b) \=\> (impRank\[a.importance\] \- impRank\[b.importance\]) || (qua                                   ╎  
lRank\[a.sourceQuality\] \- qualRank\[b.s                                          ╎  
  .slice(0, MAX\_VERIFY\_CLAIMS)                                                                              ╎  
                                                                               ╎  
log("Fetched " \+ allSources.length \+ " sources → " \+ allClaims.length \+ "                                   ╎  
 claims → verifying top " \+ rankedCla                                          ╎  
                                                                                                            ╎  
if (rankedClaims.length \=== 0\) {                                               ╎  
  return {                                                                                                  ╎  
    question: QUESTION,                                                        ╎  
    summary: "No claims extracted. " \+ allSources.length \+ " sources fetc                                   ╎  
hed, all empty/failed. " \+ dupes.lengropped.                                   ╎  
length \+ " budget-dropped.",                                                                                ╎  
    findings: \[\], refuted: \[\], source: s.url                                   ╎  
, quality: s.sourceQuality })),                                                                             ╎  
    stats: { angles: scope.angles.lenth, cla                                   ╎  
ims: 0, dupes: dupes.length },                                                                              ╎  
  }                                                                            ╎  
}                                                                                                           ╎  
                                                                               ╎  
// ─── Verify: 3-vote adversarial ───                                                                       ╎  
// Barrier here is intentional — claid befor                                   ╎  
e ranking/verification.                                                                                     ╎  
phase("Verify")                                                                ╎  
const voted \= (await parallel(                                                                              ╎  
  rankedClaims.map(claim \=\> () \=\>                                              ╎  
    parallel(                                                                                               ╎  
      Array.from({ length: VOTES\_PER\_                                          ╎  
        agent(VERIFY\_PROMPT(claim, v), {                                                                    ╎  
          label: "v" \+ v \+ ":" \+ clai                                          ╎  
          phase: "Verify",                                                                                  ╎  
          schema: VERDICT\_SCHEMA,                                              ╎  
        })                                                                                                  ╎  
      )                                                                        ╎  
    ).then(verdicts \=\> {                                                                                    ╎  
      // A vote can be null (user-skiabstain                                   ╎  
.                                                                                                           ╎  
      const valid \= verdicts.filter(B                                          ╎  
      const refuted \= valid.filter(v \=\> v.refuted).length                                                   ╎  
      // Survive only if the claim warum of                                    ╎  
      // valid votes AND fewer than REFUTATIONS\_REQUIRED refuting. Too ma                                   ╎  
ny                                                                             ╎  
      // abstentions \= unverified, which must NOT pass into the report                                      ╎  
      // (otherwise all-abstain → ref                                          ╎  
      const abstained \= VOTES\_PER\_CLAIM \- valid.length                                                      ╎  
      const survives \= valid.length \>uted \<                                    ╎  
REFUTATIONS\_REQUIRED                                                                                        ╎  
      log("\\"" \+ claim.claim.slice(0,h \- ref                                   ╎  
uted) \+ "-" \+ refuted \+ (abstained \> 0 ? " (" \+ abstained \+ " abstain)" :                                   ╎  
 "") \+ " " \+ (survives ? "✓" : "✗"))                                           ╎  
      return { ...claim, verdicts: valid, refutedVotes: refuted, survives                                   ╎  
 }                                                                             ╎  
    })                                                                                                      ╎  
  )                                                                            ╎  
)).filter(Boolean)                                                                                          ╎  
                                                                               ╎  
const confirmed \= voted.filter(c \=\> c.survives)                                                             ╎  
const killed \= voted.filter(c \=\> \!c.s                                          ╎  
log("Verify done: " \+ voted.length \+ " claims → " \+ confirmed.length \+ "                                    ╎  
confirmed, " \+ killed.length \+ " kill                                          ╎  
                                                                                                            ╎  
if (confirmed.length \=== 0\) {                                                  ╎  
  return {                                                                                                  ╎  
    question: QUESTION,                                                        ╎  
    summary: "All " \+ voted.length \+ " claims refuted by adversarial veri                                   ╎  
fication. Research inconclusive — souaims ov                                   ╎  
erstated.",                                                                                                 ╎  
    findings: \[\],                                                              ╎  
    refuted: killed.map(c \=\> ({ claim: c.claim, vote: (c.verdicts.length                                    ╎  
\- c.refutedVotes) \+ "-" \+ c.refutedVo                                          ╎  
    sources: allSources.map(s \=\> ({ url: s.url, quality: s.sourceQuality,                                   ╎  
 claimCount: s.claims.length })),                                              ╎  
    stats: { angles: scope.angles.length, sources: allSources.length, cla                                   ╎  
ims: allClaims.length, verified: voted: kill                                   ╎  
ed.length },                                                                                                ╎  
  }                                                                            ╎  
}                                                                                                           ╎  
                                                                               ╎  
// ─── Synthesize ───                                                                                       ╎  
phase("Synthesize")                                                            ╎  
const confRank \= { high: 0, medium: 1, low: 2 }                                                             ╎  
const block \= confirmed.map((c, i) \=\>                                          ╎  
  const best \= c.verdicts.filter(v \=\> \!v.refuted).sort((a, b) \=\> confRank                                   ╎  
\[a.confidence\] \- confRank\[b.confidenc                                          ╎  
  return "\#\#\# \[" \+ i \+ "\] " \+ c.claim \+ "\\n" \+                                                              ╎  
    "Vote: " \+ (c.verdicts.length \- ctedVote                                   ╎  
s \+ " · Source: " \+ c.sourceUrl \+ " (" \+ c.sourceQuality \+ ")\\n" \+                                          ╎  
    "Quote: \\"" \+ c.quote \+ "\\"\\nVeridence \+                                   ╎  
 "): " \+ best.evidence \+ "\\n"                                                                               ╎  
}).join("\\n")                                                                  ╎  
                                                                                                            ╎  
const killedBlock \= killed.length \> 0                                          ╎  
  ? "\\n\#\# Refuted claims (for transparency)\\n" \+                                                            ╎  
    killed.map(c \=\> "- \\"" \+ c.claim ote " \+                                   ╎  
 (c.verdicts.length \- c.refutedVotes) \+ "-" \+ c.refutedVotes \+ ")").join(                                   ╎  
"\\n")                                                                          ╎  
  : ""                                                                                                      ╎  
                                                                               ╎  
const report \= await agent(                                                                                 ╎  
  "\#\# Synthesis: research report\\n\\n"                                          ╎  
  "\*\*Question:\*\* " \+ QUESTION \+ "\\n\\n" \+                                                                    ╎  
  confirmed.length \+ " claims survivee adver                                   ╎  
sarial verification. Merge semantic duplicates and synthesize.\\n\\n" \+                                       ╎  
  "\#\# Confirmed claims\\n" \+ block \+ "                                          ╎  
  "\#\# Instructions\\n" \+                                                                                     ╎  
  "1. Identify claims that say the sae their                                   ╎  
 sources.\\n" \+                                                                                              ╎  
  "2. Group related claims into coherould di                                   ╎  
rectly address the research question.\\n" \+                                                                  ╎  
  "3. Assign confidence per finding: s, unan                                   ╎  
imous votes), medium (secondary sources or split votes), low (single sour                                   ╎  
ce or blog-quality).\\n" \+                                                      ╎  
  "4. Write a 3-5 sentence executive summary answering the research quest                                   ╎  
ion.\\n" \+                                                                      ╎  
  "5. Note caveats: what's uncertain, what sources were weak, what time-s                                   ╎  
ensitivity applies.\\n" \+                                                       ╎  
  "6. List 2-4 open questions that emerged but weren't answered.\\n\\nStruc                                   ╎  
tured output only.",                                                           ╎  
  { label: "synthesize", schema: REPORT\_SCHEMA }                                                            ╎  
)                                                                              ╎  
                                                                                                            ╎  
if (\!report) {                                                                 ╎  
  // Synthesis skipped/errored — salvage the verified claims raw rather                                     ╎  
  // than throwing on report.findings.                                         ╎  
  return {                                                                                                  ╎  
    question: QUESTION,                                                        ╎  
    summary: "Synthesis step was skipped or failed — returning " \+ confir                                   ╎  
med.length \+ " verified claims unmerg                                          ╎  
    findings: \[\],                                                                                           ╎  
    confirmed: confirmed.map(c \=\> ({ rceUrl,                                   ╎  
 quote: c.quote, vote: (c.verdicts.length \- c.refutedVotes) \+ "-" \+ c.ref                                   ╎  
utedVotes })),                                                                 ╎  
    refuted: killed.map(c \=\> ({ claim: c.claim, vote: (c.verdicts.length                                    ╎  
\- c.refutedVotes) \+ "-" \+ c.refutedVo                                          ╎  
    sources: allSources.map(s \=\> ({ url: s.url, quality: s.sourceQuality,                                   ╎  
 claimCount: s.claims.length })),                                              ╎  
    stats: { angles: scope.angles.length, sources: allSources.length, cla                                   ╎  
ims: allClaims.length, verified: voted.lengt                                   ╎  
h, killed: killed.length, afterSynthesis: 0 },                                                              ╎  
  }                                                                            ╎  
}                                                                                                           ╎  
                                                                               ╎  
return {                                                                                                    ╎  
  question: QUESTION,                                                          ╎  
  ...report,                                                                                                ╎  
  refuted: killed.map(c \=\> ({ claim: ngth \-                                    ╎  
c.refutedVotes) \+ "-" \+ c.refutedVotes, source: c.sourceUrl })),                                            ╎  
  sources: allSources.map(s \=\> ({ urllity, a                                   ╎  
ngle: s.angle, claimCount: s.claims.length })),                                                             ╎  
  stats: {                                                                     ╎  
    angles: scope.angles.length,                                                                            ╎  
    sourcesFetched: allSources.length                                          ╎  
    claimsExtracted: allClaims.length,                                                                      ╎  
    claimsVerified: voted.length,                                              ╎  
    confirmed: confirmed.length,                                                                            ╎  
    killed: killed.length,                                                     ╎  
    afterSynthesis: report.findings.length,                                                                 ╎  
    urlDupes: dupes.length,                                                    ╎  
    budgetDropped: budgetDropped.length,                                                                    ╎  
    agentCalls: 1 \+ scope.angles.lenged.leng                                   ╎  
th \* VOTES\_PER\_CLAIM) \+ 1,                                                                                  ╎  
  },                                                                           ╎  
}  
