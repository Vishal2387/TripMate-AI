# Project Deep Dive — My Answer Material (TripMate AI)

How to use this file: read sections 1 and 2 the morning of the interview. Sections 4 to 8 are
word-for-word answers. Do not memorise them. Learn the *reason* inside each answer, because the
interviewer will ask "why" two or three times in a row.

Rule for the whole interview: **say the decision, then say why, then say the cost of it.**
Every strong answer in this file has that shape.

---

## 1. Cheat sheet — facts I must not get wrong

| Thing | Answer |
|---|---|
| One line | A multi-agent travel planner where a supervisor picks which specialist agents to run, and a human approves the draft plan before the final version is written |
| Orchestration | LangGraph StateGraph, 9 nodes, conditional edges, `interrupt()` to pause |
| Model | Groq, `llama-3.3-70b-versatile` (set by env var) |
| Tools | MCP servers: Tavily (HTTP), AviationStack (stdio subprocess), my own OpenWeather server |
| Memory | PostgreSQL, via LangGraph `PostgresSaver` and a psycopg connection pool |
| API | FastAPI: `POST /api/travel`, `POST /api/travel/approve`, `GET /health` |
| Threading | Graph run goes to a worker thread with `asyncio.to_thread`; each MCP call gets its own `asyncio.run` loop inside that thread |
| LLM calls | About 7 for a full plan, about 4 for a narrow question like "weather in Lisbon" |
| Tests | 17 tests: 10 API contract tests, 7 routing and serialization unit tests. They run with no database and no API keys |
| Code size | About 1,750 lines of Python across 20 modules |
| History | v1 was one script with globals and `nest_asyncio`. v2 is a proper package |

Be honest about what this is: **a solo personal project.** It has no real users, so I have no
revenue or adoption numbers. I do not pretend otherwise. What I *do* have is real engineering
numbers, and I lead with those.

---

## 2. My core story (the 5-step spine)

Everything I say comes back to these five beats. If I get lost, I go back to the beat I am on.

1. **Problem** — One big prompt cannot plan a trip. It invents flight prices, it does not know
   today's weather, and it cannot check itself. Travel splits cleanly into flights, hotels,
   weather and budget, and each one needs a different live data source.
2. **Solution** — A supervisor agent reads the request and picks only the specialists that are
   needed. Each specialist pulls live data through MCP. Then one agent merges everything into a
   draft plan, the human approves or gives feedback, and a final agent writes the real plan.
3. **Key decisions** — LangGraph for durable pause and resume. Guardrail and supervisor fail
   *open*. MCP tools isolated per server. Every specialist degrades instead of crashing.
4. **What went wrong** — `nest_asyncio` hangs, one shared DB connection corrupting checkpoints,
   a guardrail that turned into an outage, one missing binary on PATH breaking three agents.
5. **Outcome** — It works, it is containerised, it survives a server restart mid-approval, and
   narrow requests cost 4 LLM calls instead of 7. The API contract survived a full rewrite of
   the internals with zero frontend changes.

### The 2-minute spoken version

> TripMate AI is a travel-planning assistant. You type "plan a 5-day trip to Japan under three
> thousand dollars" and you get back flights, hotels, weather, a budget and a day-by-day plan.
>
> The reason I built it was to find out what it actually takes to move a multi-agent LLM system
> from a demo to something that behaves like real software.
>
> Under the hood it is not one prompt. A supervisor agent first checks the request is about
> travel, then decides which specialists to run. If you only ask about weather in Lisbon, it
> does not waste money running the flight and hotel agents. Each specialist gets live data
> through MCP, which is an open protocol for connecting models to tools.
>
> The part I am most proud of is the human approval step. Before the system commits to a final
> plan, it pauses and shows you a draft. You approve it, or you say "add a free day". The whole
> workflow state is saved to Postgres at that pause. So the approval can come minutes later, or
> after the server restarts, and it picks up exactly where it stopped.
>
> The lesson for me was that the agent logic is maybe a third of the work. The other two thirds
> is state, failure handling, concurrency, and making the thing testable.

Then stop. Ask: "Where would you like me to go deeper?" This is a dialogue, not a monologue.

---

## 3. Which opener they use does not matter

All nine opener questions in the guide want the same story. I use the same spine and just change
the first sentence to match the question.

| If they ask | My first sentence |
|---|---|
| Walk me through an AI project you built end-to-end | "I'll take TripMate AI, a multi-agent travel planner I built solo, end to end." |
| Walk me through your most technically challenging project | "The hardest one was TripMate AI, and the hard part was not the prompts, it was durable state and concurrency." |
| A project you're most proud of, and your role | "TripMate AI. I was the only engineer, so every decision in it is mine to defend." |
| Tell me about a recent project and the difficulties | "TripMate AI. I'll be upfront, there were five real failures in it, and the fixes taught me more than the build did." |
| Describe a time you optimised a process for efficiency or scalability | "In TripMate AI I cut LLM calls on narrow requests from 7 to 4 by making the supervisor route selectively." |
| Describe a challenging prompt engineering problem | "Getting reliable JSON out of the supervisor, and then deciding what to do when it still failed." |
| Greatest accomplishment of your career | Same story, but weight the *ownership*: I designed it, broke it, and rebuilt it as v2. |

---

## 4. Business problem and context

**Q: What business problem were you solving? Why was it a priority?**

> I'll be straight with you: this was a learning project, not a product with a revenue target.
> So the honest framing is the *engineering* problem I set myself.
>
> The user-facing problem is real though. Planning a trip means checking four or five different
> sources and then stitching them together yourself. A single LLM prompt cannot do it, because
> it hallucinates prices and it does not know today's weather.
>
> The engineering problem I actually cared about was this: can I build an agentic system where a
> human stays in control of the final output, where one flaky external API does not take down
> the whole system, and where the code is good enough that I would hand it to a teammate? Those
> three things are what separate a notebook demo from a service.

**Q: Who was the customer? Who benefited from this work?**

> The end user is someone planning a trip who wants one coherent plan instead of eight browser
> tabs. But I designed for a second user too, and that shaped more decisions: the *operator*.
> That is why `llm_calls` is returned in every API response, why the supervisor's reasoning and
> chosen agents come back to the UI, and why every fallback is logged. Someone running this
> needs to see what it decided and what it cost.

**Q: What was your actual role in building this?**

> Solo. Architecture, agents, API, the MCP weather server, the Docker build, the tests, all of
> it. That means I cannot hide behind a team on anything you ask me, which is fair.
>
> The role I am proudest of is the v1 to v2 call. v1 worked, but it was one script with global
> state and a `nest_asyncio` patch, and it was not testable. I decided to restructure it rather
> than keep adding features on top, and I kept the HTTP contract fixed while I did it, so the
> frontend never changed.

**Q: How did you communicate technical decisions to stakeholders?**

> No stakeholders on this one, so I'll answer it two ways.
>
> On this project, my stand-in for stakeholder communication was making decisions visible in the
> product itself. The UI shows which agents the supervisor picked and why. The README documents
> every trade-off. An architecture doc explains the layering rules. If someone joins, the
> decisions are readable, not folklore.
>
> In a real team, the way I explain something like the fail-open guardrail is not "we parse JSON
> leniently". It is: "if the guardrail breaks, do you want the app to refuse everyone, or to let
> a few off-topic questions through? I chose the second, and here is the log line that tells us
> how often it happens." Framed as a business choice, not a code detail.

---

## 5. Decisions and trade-offs

**Q: Why did you choose that particular approach over alternatives?**

> The main choice was LangGraph over a hand-rolled agent loop.
>
> I needed three things. Explicit control over routing, so the system decides which agents run.
> Durable state, so a pause can outlive an HTTP request. And a real pause-and-resume primitive.
>
> LangGraph gives me all three. `interrupt()` plus a pluggable checkpointer is exactly the
> hardest piece to build by hand, because you have to get checkpoint serialisation and resume
> semantics right. Plain LangChain chains do not have the pause concept at all. Writing my own
> loop would have meant reinventing the checkpointer.
>
> The cost is real: framework lock-in, and the API surface moves fast between versions. I took
> that trade because the pause-and-resume machinery was the whole point of the project.

**Q: Why a supervisor instead of one big prompt, or a fixed pipeline?**

> One prompt cannot call a different tool per sub-problem, and it hallucinates.
>
> A fixed pipeline would work, but it runs all four specialists every single time. "What's the
> weather in Lisbon?" would cost the same as a full 5-day plan.
>
> The supervisor writes a `selected_agents` list into state. There is a fixed `AGENT_ORDER` list,
> and each specialist's edge just looks for the next selected agent in that order. Agents that
> were not selected are skipped at zero cost. That is the 7-calls-to-4-calls saving.
>
> One detail worth mentioning: the itinerary agent is always force-added to that list, even if
> the supervisor leaves it out. It is the integration point, so the graph has no valid path
> without it. I did not want a model formatting mistake to produce a plan with no plan in it.

**Q: What were the trade-offs, and are you still comfortable with them?**

Four I name. I am comfortable with three.

1. **Fail open on the guardrail and supervisor.** Comfortable. Reasoning below.
2. **Sequential specialists.** *Not* comfortable. Flight, hotel and weather are independent and
   should run in parallel. I kept them sequential to keep the routing logic simple. It leaves
   about half the wall-clock latency on the table. This is my number one code fix.
3. **Truncating MCP payloads to 3,000 characters.** Comfortable as a stopgap, but it is blunt.
   The right fix is to filter airports by the extracted origin and destination before prompting,
   not to chop the string.
4. **Find-first-brace JSON parsing instead of structured output.** Acceptable only *because*
   failures fail open. If a failure were expensive, I would have used Pydantic and the provider's
   JSON mode from the start.

**Q: Why fail open on the guardrail? Isn't that a security risk?**

> Good challenge, and the answer depends entirely on what the guardrail is *for*.
>
> Mine is a scope filter: travel, or not travel. It is not a security boundary. So compare the
> two failure modes. A false allow costs me one wasted LLM call. A false block means the product
> refuses a real customer. The second is much worse.
>
> And I learned this the hard way. An early version treated any JSON parse error as "blocked".
> The model had a formatting hiccup and the app refused *every* request for a while. A safety
> feature had become an availability bug. That is where fail-open came from.
>
> Every fallback logs a warning with a traceback, so a spike is visible rather than silent.
>
> If the guardrail were stopping something with real harm potential, I would flip it: fail
> closed, and add a retry with a repair prompt before giving up.

**Q: Why MCP instead of writing three API clients?**

> Standard tool discovery and invocation, so swapping search providers is a config change rather
> than a rewrite. And I got to reuse a community AviationStack server, and write my own weather
> server in about 90 lines with FastMCP.
>
> The important design detail is isolation. Each helper loads tools from *exactly one* server per
> call. Early on I loaded all tools from all servers at once, and a missing `uvx` binary on PATH
> broke weather and hotel lookups too, even though neither needs `uvx`. Per-server loading shrank
> the blast radius to the one agent that is actually affected.
>
> The cost: stdio servers spawn as subprocesses, which adds latency. Long-lived sessions are the
> next improvement there.

**Q: Why that tech stack — Groq, Postgres, FastAPI?**

> **Groq** because it is fast and cheap, and I was paying. Cheap inference is also part of why I
> could be relaxed about a fail-open retry.
>
> **Postgres** because the human approval pause has to survive a process restart, and LangGraph
> ships a `PostgresSaver`. I did not need a vector store. This is not retrieval, it is workflow
> state, which is relational and small. A free hosted instance was enough.
>
> **FastAPI** because I needed async endpoints and typed request and response models, and the
> approval flow is two plain HTTP calls, not a streaming session.
>
> **uv with a committed lockfile** so my machine, CI and the Docker image install exactly the
> same versions.

**Q: How would you handle different requirements or scale constraints?**

> Depends which constraint moves.
>
> **10x traffic:** the app is already mostly fine. Each graph run is on its own worker thread and
> borrows its own pooled connection, and all state is in Postgres, so any uvicorn worker can
> resume any thread. The real bottleneck is Groq rate limits and thread count, not my code. I
> would add a queue and move graph runs to background workers, returning a job id.
>
> **Latency matters more:** parallel fan-out of the independent specialists with LangGraph's
> `Send` API, and a smaller model for the two classification-shaped calls.
>
> **Cost must halve:** small model for the guardrail and destination extraction, merge guardrail
> and supervisor into one structured-output call, and cache MCP results per destination with a
> short TTL.
>
> **A real multi-tenant product:** this is the honest gap. Thread IDs are random UUIDs, so they
> are not guessable, but anyone holding one can resume that thread. There is no ownership check.
> I would bind the thread to an authenticated user id in the checkpoint config and verify it on
> resume.

---

## 6. Problems and debugging

**Q: What was the most challenging technical decision and how did you make it?**

> The concurrency boundary. Where do sync and async meet?
>
> FastAPI endpoints are async on one event loop. But `graph.invoke()` blocks for many seconds,
> because it is doing LLM and MCP calls. And the MCP client library is async, while my LangGraph
> nodes are sync functions.
>
> In v1 I solved it the lazy way, with `nest_asyncio`, which patches the loop so you can nest
> `asyncio.run` inside a running loop. It worked in testing. Then under concurrent requests I got
> hangs that were genuinely hard to debug, because the failure was inside a patched event loop
> rather than in my own code.
>
> The way I made the decision was to stop patching and name the actual boundary. The blocking
> work should not be on the event loop at all. So the planner dispatches the whole graph run with
> `asyncio.to_thread`. Inside that worker thread there is no running loop, so each MCP call can
> just use plain `asyncio.run()` and get its own short-lived loop. The patch went away.
>
> The lesson: `nest_asyncio` was not a fix, it was a symptom. I was mixing sync and async at the
> wrong layer.

**Q: What went wrong? What was harder than expected?**

Five real failures. I volunteer these, because they make the story credible.

1. **`nest_asyncio` hangs** under concurrency. Fixed by moving the blocking run off the loop.
2. **One shared DB connection.** Two overlapping requests corrupted each other's checkpoint
   writes. Switched to a psycopg `ConnectionPool`, which also gave me fail-fast startup via
   `pool.wait()` — if the database is unreachable the app refuses to boot, instead of failing on
   the first user request.
3. **The guardrail outage.** A parse error meant "blocked", so the app refused everything. This
   became the fail-open policy.
4. **Cross-server MCP failure.** A missing `uvx` on PATH broke three agents. Fixed with
   per-server tool loading, plus prerequisite checks that raise an actionable message, like
   "AVIATION_STACK_API_KEY is missing, add it to your .env", *before* any network call.
5. **Module-level globals blocked testing.** v1 connected to Postgres at import time, so you
   could not even import the module in CI. Fixed with an app factory and FastAPI lifespan: the
   pool, checkpointer, graph and planner are all built inside lifespan and stored on `app.state`.
   Nothing happens at import. That one change is what made the whole test strategy possible.

**Q: How did you debug production issues?**

> No production traffic, so I will not claim I did. Here is what I actually did, and what I would
> add.
>
> What I did: deliberate failure injection. I removed each API key in turn to confirm the right
> single agent degraded and the plan still completed. I killed the server in the middle of an
> approval pause and restarted it, to confirm the thread resumed from the Postgres checkpoint.
> Every fallback path logs a warning with a traceback, so the log tells me *which* fallback fired,
> not just that something went wrong. And `llm_calls`, `selected_agents` and
> `supervisor_reasoning` come back in every response, so I can see the decision and the cost from
> the UI.
>
> What is missing for real production: per-node tracing with token counts and latency, and
> structured logs with `thread_id` as the correlation key, so I can follow one user's plan across
> two separate HTTP requests. That second one matters specifically because of the approval pause,
> where one logical session is two disconnected requests.

---

## 7. Evaluation and results

**Q: Is there an actual eval framework here, or is it vibes-based?**

This is the question I must not bluff. Answer it directly.

> On the engineering side it is tested. On the LLM behaviour side, it is honestly closer to
> vibes, and I know that is the main gap.
>
> What is genuinely tested: 17 tests. Ten API contract tests covering every endpoint and every
> error path, including the exact error shape the frontend depends on. Seven unit tests over the
> routing and serialization functions, which are pure functions, so I can assert that a blocked
> request routes to the block node, that unselected agents are skipped, and that both the paused
> and the completed graph results serialize correctly. All of it runs with no database, no API
> keys and no network, because the tests inject a fake planner before startup.
>
> What is *not* tested is whether the supervisor picks the *right* agents, and whether the
> guardrail over-blocks. The mechanics of routing are tested. The judgement is not. Today my only
> mitigation is that the decision comes back in every response, so it is at least inspectable.
>
> What I would build, and it is my number one priority if I continued: a golden set of about 100
> labelled prompts, each with the expected agents and the expected guardrail verdict. Run it
> nightly. Report routing accuracy, and guardrail precision and recall. Precision and recall
> separately, because over-blocking and under-blocking are different business problems.
>
> For itinerary quality, LLM-as-judge against a rubric: does it respect the budget, respect the
> duration, use the weather advice, honour the human's feedback on a revision, and correctly
> label anything that is not live data. Plus pairwise comparison whenever I change a prompt or a
> model.

**Q: Did the solution actually work? How do you know? What metrics did you track?**

> It works, and here is what I can actually prove rather than assert.
>
> Selective routing measurably saves calls: a full plan is about 7 LLM calls, a narrow question
> like "weather in Lisbon" is about 4. I know because `llm_calls` is tracked in state and
> returned in the response.
>
> Durability works: I killed the server mid-approval and the thread resumed from its checkpoint
> after restart.
>
> Degradation works: with each provider key removed in turn, the affected section comes back
> labelled as non-live and the rest of the plan still completes.
>
> And one I like as a design signal: the v1-to-v2 internal restructure landed with zero frontend
> changes. The HTTP contract held. That tells me the API boundary was drawn in the right place.
>
> What I do not have: user metrics, satisfaction scores, or plan-accuracy numbers. No users.

**Q: What was the outcome? How did stakeholders react?**

> No stakeholders, so I will not invent a reaction. The outcome is a working containerised
> service with durable human approval, selective routing, and graceful degradation across three
> providers. For me the real outcome was the shift in how I think. I came in expecting the agents
> to be the hard part, and left understanding that state, concurrency and failure handling are
> the hard part.

**Q: How do you monitor the model post-deployment for drift or degradation?**

> Not solved here, and I would rather say that than invent something.
>
> What exists: `llm_calls` per request, and a logged warning on every fallback, so the rate of
> guardrail and supervisor parse failures is at least visible in the logs.
>
> What I would actually build — and note that "drift" for an agentic system is not the same as
> for a trained model. I have no weights drifting. What drifts is that the provider can change
> the model under me, and my prompts quietly stop working.
>
> - Run the golden set on a schedule and alert when routing accuracy drops. That is the real
>   drift detector, and it catches a provider-side model change.
> - Track the fallback rate per MCP server, and the guardrail block rate, as dashboards. A jump
>   in either is a signal before any user complains.
> - Track the approve-versus-revise ratio. If people start rejecting more drafts, plan quality
>   has degraded even though nothing errored.
> - Pin the model version in config instead of floating on a provider alias, and re-run the
>   golden set before moving it.

**Q: How did you handle data quality and preprocessing challenges?**

> There is no training data here, so the data question is really about what flows into each
> agent.
>
> Three real problems. First, tool payloads are huge and mostly irrelevant — the AviationStack
> airport and airline catalogues. I cap them at 3,000 characters each. That controls token cost,
> but I will admit it is a blunt instrument, and the right fix is filtering by the extracted
> origin and destination.
>
> Second, model output is not reliably JSON. My helper takes the first opening brace and the last
> closing brace and parses that slice, which tolerates markdown fences and preamble text. On any
> failure the caller falls open.
>
> Third, state shape. One `TravelState` TypedDict. The `messages` field uses an `operator.add`
> reducer so it accumulates as an audit trail; everything else is last-write-wins. Each node
> returns only the keys it changed, which is what keeps the nodes decoupled and unit-testable.
>
> And the one I care most about: quality *labelling*. When live data is missing, the fallback
> text explicitly says so, and the downstream agents are prompted to keep that label. So bad data
> never silently becomes a confident answer.

---

## 8. Learning and reflection

**Q: What would you do differently if you started over?**

> Build the eval harness first, before the agents.
>
> I built the system, then realised my confidence in every LLM-driven decision came from manual
> testing. If the golden set had existed from day one, every prompt change would have had a number
> attached to it instead of a feeling.
>
> Second, structured output from the start. Pydantic models with the provider's JSON mode, instead
> of my find-the-braces parser.
>
> Third, I would design the concurrency boundary before writing a single node, rather than
> reaching for `nest_asyncio` and paying for it later.
>
> Fourth, tracing from day one, so cost and latency per node were visible while I was still
> making decisions, not after.

**Q: What would you explore next if you had more time?**

In priority order, and I say the order out loud, because the ordering is the signal.

1. **Eval harness.** Golden set, routing accuracy, guardrail precision and recall, LLM-as-judge
   for plan quality. Everything else is guessing without it.
2. **Parallel specialists** via LangGraph's `Send` API, with a join before the budget agent.
   Roughly halves wall-clock latency. Budget depends on the other three, so it stays downstream.
3. **Structured outputs** with Pydantic and JSON mode.
4. **Multi-round revision.** Right now a rejected draft goes to the final agent once. I would add
   a conditional edge from final back to human approval when `approved` is false, with a
   max-iterations counter in state so it cannot loop forever.
5. **Tracing and auth.** Per-node tracing, and binding threads to an authenticated user id.

---

## 9. Weaknesses I volunteer before being asked

Saying these first is a strength. It shows I read my own code critically. Engineers who name
their gaps still get hired.

- No automated eval of LLM behaviour. Biggest gap, covered above.
- Specialists run sequentially when three of them are independent.
- The weather agent's destination-extraction LLM call sits *outside* its try/except, so an LLM
  failure there raises instead of degrading like every other failure in that node. Inconsistent
  with my own design rule.
- The hotel agent increments `llm_calls` even though that node makes no LLM call. My own cost
  metric is slightly wrong, which is a good reminder that a metric nobody tests will drift.
- The Tavily API key is passed as a URL query parameter, which can end up in logs. It should be
  a header.
- No auth or ownership check on `thread_id`.

---

## 10. How to signal what they are actually grading

| What they grade | How I show it |
|---|---|
| Technical leadership | "I made the v1 to v2 call myself, and I held the HTTP contract fixed while I rewrote the internals." |
| Decision-making insight | Never state a choice without the alternative I rejected and the cost I accepted. |
| Communication clarity | Plain words. One idea per sentence. Stop and ask "want me to go deeper?" every few minutes. |
| Impact orientation | Lead with 7 calls down to 4, survives a restart, degrades per section. Not "I used LangGraph and MCP". |
| Honest self-assessment | Section 9, said before they have to dig for it. And "it is vibes-based on the LLM side" when it is. |
| Depth of understanding | Be ready to go three levels down on `interrupt()`, on `asyncio.to_thread`, and on the routing edges. Those are the three places they will push. |

### The three deepest probes, and my one-line floor for each

- **"What does `interrupt()` actually do?"** — It raises internally. LangGraph checkpoints the
  full state to Postgres keyed by `thread_id`, and `invoke()` returns with an `__interrupt__`
  key. On resume with `Command(resume=...)`, LangGraph reloads the checkpoint, re-enters the
  node, and this time `interrupt()` *returns* the payload. Nothing lives in memory between the
  two HTTP requests, which is why a restart is survivable.
- **"Why `asyncio.to_thread` and not just async nodes?"** — The graph run blocks for seconds, so
  off the loop it goes. Inside the thread there is no running loop, so `asyncio.run` per MCP call
  is safe, and `nest_asyncio` becomes unnecessary.
- **"How does an agent get skipped for free?"** — The supervisor writes `selected_agents`. Each
  specialist's conditional edge scans the fixed `AGENT_ORDER` from its own position for the next
  *selected* agent, and falls through to the itinerary agent if there is none. Skipping is just an
  edge that never points at that node.

---

## 11. Final checklist before I walk in

Do:
- Open with the 2-minute version, then hand control back with a question.
- Say why, then say the cost. Every time.
- Use the numbers: 7 down to 4 calls, 17 tests, 9 nodes, 3 MCP servers, zero frontend changes.
- Say "I don't know" or "I didn't measure that" when it is true, then say how I would find out.
- Say "this was a solo learning project, so I have engineering metrics, not user metrics" early
  and once. Then stop apologising for it.

Don't:
- Monologue for ten minutes without pausing.
- List technology names as if they were achievements.
- Claim production traffic, users, or stakeholder reactions I did not have.
- Get defensive when challenged on fail-open or on sequential specialists. Both are trade-offs I
  chose. One I would keep, one I would change. Saying which is the whole point.
