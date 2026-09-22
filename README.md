<p align="center">
  <img src="assets/banner.png" alt="Advisor Intelligence & Paper Companion Agent" width="100%">
</p>

<h1 align="center">Advisor Intelligence & Paper Companion Agent 🎓</h1>

> A local agent that helps you **find labs, read papers, sharpen your thinking, and plan your path into a research group.**
> Built on LLM function calling with multi-layer anti-hallucination checks — **every claim traces back to the source; if it can't be found, it says so.**

---

## What can this agent do for you?

| Scenario | How one sentence solves it |
|---|---|
| You want to apply to a lab, but the official site is outdated and recruiting status is scattered | Start from a single sentence like "tell me about University X": the agent navigates the official site, locates the school, crawls the faculty roster, and generates advisor cards tagged with recruiting signals 🟢🟡⚪ |
| You want to know what an advisor really works on, and whether they take students | Automatically fetches personal and lab homepages and produces a seven-dimension profile (research-trajectory shifts, GitHub engineering footprint, where former students ended up, …) |
| You can't decide between several advisors | Scores 2–5 candidates across seven criteria, every score backed by a verbatim quote from the source |
| You finished a paper but can't tell whether your understanding is right | Submit your own write-up; the agent checks it against the original text, asks Feynman-style follow-ups, and distills it into paragraphs you can paste into an application |
| You want into a specific group but don't know what project to build | Works backwards from the advisor's needs and your skill profile to propose a "door-knocking project", with a compute red-line check |
| You're afraid of missing your target advisor's updates | Bookmark them and the agent periodically scans their homepage / arXiv / GitHub, producing an intelligence brief; can also run daily on a schedule |

---

## Quick start

```bash
git clone https://github.com/Vankleben/advisor-agent.git
cd advisor_agent

# Dependencies
pip install openai requests beautifulsoup4 pymupdf

# Configure your API key (deepseek / moonshot supported)
cp config.example.py config.py
# Edit config.py and fill in your key

# Launch (pick one)
python main.py          # terminal UI
python web_server.py    # then open http://127.0.0.1:8080
```

> The web UI has zero dependencies (Python's built-in http.server). It renders markdown tables, lets you expand and collapse evidence, shows tool calls as they happen, and keeps multi-turn sessions alive.

> Terminal extras: `/m` for multi-line input (finish with EOF); `/f <path>` to read a file; **`/history` to review past sessions** (`/history 3` for the third one, `/history <keyword>` to search). Conversations are stored locally under `archive/chat_history/` — closing the terminal loses nothing, and nothing is uploaded.

---

## Examples (real conversations)

Ask in plain language and the agent picks its own tools. Every example below has actually been run:

### ① Finding advisors — "which professors at Tsinghua's AI Institute work on LLMs?"

```
You: show me the faculty at Peking University's School of AI

🔧 fetch_url(https://www.pku.edu.cn)        # navigates by itself
🔧 fetch_url(http://sai.pku.edu.cn)         # drills down level by level
🔧 add_school('pkusai')                      # collects the roster and builds cards
🔧 list_teachers({'site': 'pkusai'})

Agent: 36 faculty collected from PKU's School of AI:

| Name | Title | Field | Recruiting | Career stage |
|---|---|---|---|---|
| Asst. Prof. A | Assistant Professor | Vision-language learning, multimodal LLMs | 🟢 | Early career |
| Asst. Prof. B | Assistant Professor | Robotics, embodied AI | ⚪ | Early career |
| Chair Prof. C | Chair Professor | Computer vision, cognitive science | ⚪ | Senior |
...
```

> 🟢 means the page explicitly welcomes students (with a verbatim quote and the crawl date); ⚪ means the page carries no recruiting information — **the agent never turns "unknown" into "welcome".**

### ② Deep dive on one advisor — "dig into Professor A"

```
🔧 advisor_deepdive({'name': 'Professor A'})

Agent:
[Recent research] <what the group works on>
  Evidence: "The XXX Laboratory ... <verbatim quote>"  <- source 1: personal homepage

[Research trajectory] Sustained focus on membrane-related structures
[Recruiting intentions] ...
[GitHub footprint] Not mentioned on the homepage — honestly reported as "no information"

✅ Anti-hallucination check: every quote matched the source verbatim
```

### ③ Side-by-side comparison — "compare Professor A and Professor B"

```
🔧 deep_compare({'names': ['Professor A', 'Professor B']})

Agent:
| Criterion | Professor A | Professor B |
|---|---|---|
| Field fit | 3/5 (cell biology, little computational work) | 5/5 (AI + biological structure) |
| Recruiting signal | ⚪ 1/5 | 🟢 4/5 |
...

Verdict: go for Professor B (AI4Science matches both your interests and your ESM-IF1 experience); keep Professor A as a fallback.
```

### ④ Reading a paper — from search to deep read

```
You: find this professor's recent papers
🔧 search_papers({'author_en': 'John Smith'})     # ⭐ flags last-author papers = PI-led work

You: make a decision card for paper #7
🔧 paper_decision({'arxiv_id': '2606.09669v2'})
Agent: Role: representative work / Fit: medium / Recommendation: skim / Prerequisites: none

You: ok, deep-read it
🔧 deep_dive({'arxiv_id': '2606.09669v2'})
Agent: [seven-section breakdown: goal -> background -> experimental setup -> method pipeline
        -> concept explanations tuned to your profile (KV cache in one line, new concepts in depth)
        -> results and limitations -> reproducibility (target device and estimated resources)]

⚠️ The check found 2 quotes missing from the original text; they are flagged — please note
```

### ⑤ Critique — hand in your own understanding after reading

```
You: /f my_thinking.txt    # submit what you wrote

🔧 critique_thinking(...)

Agent:
## Factual corrections
❌ You wrote "pretrain on experimental spectra first, then fine-tune on simulated spectra" — the order is reversed
   Original: "a shared spectral encoder is first pretrained on approximately
             60 million simulated IR spectra"
❌ "overall accuracy above 95%" — the paper never gives this number; metrics differ per task

## Feynman-style follow-ups (blind-spot probing)
1. Why these three pretraining tasks: wavelet reconstruction, fingerprint alignment, functional-group prediction?
...

## Distilled paragraph (ready to use in an application)
"What struck me most about this paper is how it carries the simulation-to-reality transfer logic through..."
```

Disagree with a verdict? 🔧 appeal_grading(...) re-checks every quote against the source, one by one.

### ⑥ Path planning — "I want to join Professor A's group. What should I do?"

```
🔧 path_analysis({'name': 'Professor A'})

Agent:
[Demand side] The group needs someone who can do image analysis / data mining (with quotes from the deep-dive report)
[Supply side] You already have: hands-on YOLO experience, Python data processing; quick to pick up: cell image segmentation
[Door-knocking project] <an image-segmentation demo on the group's material>
   -> estimated 4-6 weeks; fine-tuning an off-the-shelf segmentation model is enough
   ✅ Passed the compute red-line check (target device auto-annotated; plans beyond your local hardware are replaced)
```

### ⑦ Continuous monitoring — bookmark an advisor and watch daily

```
You: bookmark Professor B; their GitHub org is example-lab
🔧 bookmark_advisor({'name': 'Professor B', ...})

You: any updates from the advisors I bookmarked?
🔧 monitor()

Agent:
Professor B: homepage unchanged / no new topic-relevant arXiv papers / new GitHub repository
      example-lab/xxx (updated 3 days ago)

# Or register a Windows scheduled task (setup_monitor_task.bat):
# it scans every day at 9am and only writes a brief when something actually changed
```

---

## Core design: three-layer anti-hallucination checks

The most interesting part of this project — **don't trust the LLM's output, trust only the source**:

| Layer | Mechanism |
|---|---|
| Card layer | Every `evidence` field must match the official page verbatim after whitespace normalization; a personal-homepage URL must come from the detail page's outbound-link list (so the LLM cannot invent a homepage from memory) |
| Paper layer | Every quote in a deep read must be found in the full text after normalization (immune to PDF line-break and hyphenation artifacts); any miss is **flagged as suspicious, honestly** |
| Deep-dive layer | Every claim's evidence must match the text of the source it cites; an out-of-range source index also raises a warning |

In practice: when the LLM rewrote a sentence from a paper, the checker caught it immediately and flagged it. The critique module even ships an **appeal channel** — because the critic can hallucinate too.

---

## Project structure

```
advisor_agent/
├── main.py               # agent loop: 22 function-calling tools
├── web_server.py + web/  # zero-dependency web chat UI
├── tools/                # module implementations (crawling / cards / deep dive / paper reading / critique / monitoring)
├── archive/              # user profile, error-pattern library, read-paper library, target list
└── data/                 # card library, paper full texts, deep-dive reports, monitoring snapshots
```

See [docs/code.md](docs/code.md) (development log) and [design audit v0.4](docs/design-audit-v0.4.md) (full requirements design). Both are currently written in Chinese.

---

## Known limitations

- Paper search currently covers arXiv only (Scholar and DBLP are planned);
- Some university sites (e.g. Zhejiang University, Westlake University) sit behind network-level blocks or heavy JS rendering and need a working network environment; a Chrome-headless fallback is built in, but not every site is reachable;
- Output quality depends on the model behind it (deepseek-chat by default). The anti-hallucination checks stop fabrications, but cannot guarantee 100% coverage of semantic rewrites;
- Single-machine, single-user design — no multi-tenancy and no authentication.

---

## Roadmap

- [ ] Add Scholar / DBLP as paper sources
- [ ] Automatic knowledge-level evolution (papers you read update your concept profile)
- [ ] More monitoring sources (department news pages, OpenReview)
- [ ] Cold-email drafts (reusing the distilled paragraphs from the critique module)

---

## License

MIT
