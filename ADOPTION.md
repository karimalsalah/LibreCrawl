# ADOPTION — LibreCrawl (STEADYWRK estate)

Fork of [`PhialsBasement/LibreCrawl`](https://github.com/PhialsBasement/LibreCrawl). Adopted 2026-08-23 by the `moat` lane.
Estate record: `docs/strategy/OSS-ADOPTION-2026-08-23.md` in `karimalsalah/steadywrk` (PR #1465).

## What it is (verified live 2026-08-23)

MIT · 873★ · last push 2026-08-18 · not archived · upstream is not itself a fork.
**Python** (`requirements.txt`), **999 KB** working tree. `src/` contains `core/`, `crawl_db.py`, `auth_db.py` — a **web crawler** with persistent storage and an auth layer.

## Why we took it

Store Guard audits storefronts against `/store-guard/standard/v1`. Live competitive research on 2026-08-23 found the depth gap explicitly: **most scanners deliberately sample** — 20 product pages, 20 products, 50 products, or in one case a single page. The white space is *"whole-catalog depth at audit price"*, between "sample 20 products" and an enterprise PIM.

Sampling is also an **honesty problem**, not just a depth one: a score computed from 20 sampled pages and presented as a store-level grade overstates its own confidence. `STANDARD-v1.md` §6 requires a conforming report to let a third party recompute the score from the receipt — that is far more defensible over a full catalog than a sample.

**What we take:** the crawl/queue/fetch engine and its persistence layer. Not the auth layer, not any UI.

## Sequencing

**Fourth of five.** After the controls are proven on lower-risk forks. **First dry-run runs against a storefront we own — never a third party's.**

## Isolation — this fork touches the outside world by design

| Control | This fork |
|---|---|
| **Sandbox root** | `D:\forks\LibreCrawl`. Never `C:`, never `~/.claude`, never `~/.cursor`. |
| **Python env** | A **dedicated virtualenv inside the sandbox**. Never `pip install` into the system or user Python — dependency installs are the classic way a "sandboxed" Python tool escapes its sandbox. |
| **Kill-switch** | Delete `D:\forks\LibreCrawl` **and** its virtualenv **and** any crawl/auth SQLite databases the filesystem diff reveals outside the sandbox. |
| **Credentials** | **None.** `auth_db.py` exists — it must never hold a real steadywrk credential, and never a merchant's. |
| **Egress** | **Extensive and by design** — it fetches whatever it is pointed at. This is the fork whose target restriction matters most. |
| **Crawl politeness** | Must respect `robots.txt`, set an identifying user-agent, and rate-limit. We publish a standard that grades how sites treat crawlers; crawling badly while selling that standard would be indefensible. |

## Required before any integration — the dry-run gate

1. **Filesystem diff.** Before/after snapshot of `~/.claude`, `~/.cursor/mcp.json` (hash), and the home root. Python tools commonly write to `~/.cache` and `~/.local` — check both.
2. **Dependency review.** `requirements.txt` read before install. A crawler's dependency tree is a supply-chain surface, and it is being installed to audit other people's stores.
3. **Target restriction proof.** First crawl targets **a storefront we own**. Confirm it cannot wander off-domain — verify link-scope containment explicitly rather than assuming it.
4. **Politeness proof.** Confirm `robots.txt` is honoured and rate limits apply, **observed on the wire**, not read from documentation.
5. **Capability proof.** Crawl a known catalog and confirm the page set is complete. **README claims are NOT verified** — only license, liveness, and non-archived status are.

## The rule this fork must never break

**Never crawl a third party's storefront without authorisation.** Store Guard audits are performed for merchants who ask, on their own stores. An unauthorised crawl is a third-party action, and the estate's no-third-party rule covers it. Convenience is not a reason, and "it is only a read" is not an exception.

## Why the filesystem diff is still mandatory

On 2026-08-23 the estate adopted a tool whose **five documented isolation flags each failed** to contain a home-directory write; only a before/after diff caught it. **Documented isolation is not proof of isolation.**

## Never

- Crawl a store we do not own or have written authorisation for.
- `pip install` outside the sandbox virtualenv.
- Point it at the live `C:\Users\youso\dev\steadywrk` checkout.
- Merge upstream blindly — re-run the full gate after every version bump.

## Upstream

`upstream` = `PhialsBasement/LibreCrawl`. This checkout has no upstream remote yet (only `origin`), so add one with `git remote add upstream https://github.com/PhialsBasement/LibreCrawl.git` before tracking it. We do not push to upstream. Contributions go upstream as normal PRs under MIT.

2026-10-16: merged upstream `PhialsBasement/LibreCrawl` at `05a1372` (Zoho OAuth login, XLSX/XML exports, External tab) and upgraded the pinned dependencies (requests, urllib3, flask, bcrypt and others; pip-audit clean). Local tests and a boot smoke passed. The dry-run gate above has NOT been re-run for this bump and still needs running before any integration.
