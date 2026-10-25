# ReconAI product video: script

A 28-second overview of what ReconAI is. It does not walk through every feature. It answers three questions:
what problem it solves, what we built, and which sponsor tech it runs on.

- **Format:** 1920x1080, 30 fps, about 28 s, captions only (no voiceover).
- **Look:** ReconAI's own style: black background, white tiles, the Saira Stencil wordmark. From the reference video we
  borrow only the motion: numbers count up, lines draw in, the cursor moves on eased paths, hovers glow, toasts slide in
  with a check that draws itself, and the outro scales down.
- **Honesty rule:** every channel, logo and number shown exists in the product. No Discord, no Cartesia.

## One-line story

> Supplier bills arrive from everywhere and AP teams match them by hand. ReconAI pulls them into one place, checks
> every one before money moves, and lets you run it all from Slack.

## Storyboard

| # | Time | Scene | On screen | Caption |
| --- | --- | --- | --- | --- |
| 1 | 0:00 to 0:03 | Logo | The existing `LogoIntro`, trimmed to 3 s. The tile pops in, the ledger lines and check draw, and the wordmark slides out. | none |
| 2 | 0:03 to 0:07 | The problem | Invoice, PO and email cards drop in and pile up at angles. A counter ticks up to **$857k** in bad bills. | "Supplier bills are a mess." |
| 3 | 0:07 to 0:11 | Every channel in | Five channel icons sit around the edge: **Email, API, SFTP, ERP, Slack**. Documents fly from each one into a single ReconAI node in the centre. | "Every channel. One place." |
| 4 | 0:11 to 0:15 | It checks everything | One bill card. Check rows tick in: ✓ 3-way match, ✓ not a duplicate, ✗ bank details changed. The card border turns red and a "Held" badge drops on. | "Checks every bill before you pay." |
| 5 | 0:15 to 0:22 | All in Slack | A Slack channel with a supplier, who quotes a price. A grey **"Only visible to you"** message slides in with the counter, the walk-away price and the money at stake. The cursor clicks **Approve**. A toast slides in with a check that draws itself: "Paid · USDC". | "Negotiate, approve, pay. In Slack." |
| 6 | 0:22 to 0:28 | Built with + outro | Logos stagger in on a grid: **Claude, Factory Droid, SpacetimeDB, CRS, Coinbase, Slack, Odoo**. Under them: "48/48 test cases · never pays without a human sign-off". Everything scales down to the ReconAI logo. | "Built at Cal Hacks 13.0" |

## Scene notes

1. **Logo.** Reuse `LogoIntro` with `durationInFrames` cut to 90.
2. **Problem.** Cards spring in with slight random rotation and overlap more as the pile grows. The counter uses
   `interpolate` with an ease-out curve. $857k is the "caught before payment" figure from the README.
3. **Channels.** Icons sit on a ring. Each document is a small card that moves along a curved path into the centre
   node, which pulses once for each card it receives. Show only the five channels we support.
4. **Checks.** Three rows appear one after another, each with a stroke-drawn ✓ or ✗. The ✗ row is the bank change,
   the fraud case we lead with in the pitch.
5. **Slack.** Build a simplified Slack window (sidebar, channel header, messages), not a screenshot. The private
   message uses Slack's grey "Only visible to you" style, so the viewer sees that the supplier can't see it. Example
   numbers: quote $41.20/unit, counter $38.50, walk-away $39.75.
6. **Stack.** Logos are white monochrome tiles in a 4 + 3 grid. Stagger them by 3 frames each, then scale everything to
   0.6 and fade into the logo tile.

## Sponsor stack shown in the video

| Logo | What it does in ReconAI |
| --- | --- |
| Claude | Reader, reviewer, approver and controller role-play, Slack coach phrasing |
| Factory Droid | Investigator in a sandbox, skill evolution |
| SpacetimeDB | Live state: cases, traces, approvals, dashboard |
| CRS | Vendor onboarding identity and risk checks (sandbox API) |
| Coinbase | USDC payouts on Base Sepolia testnet |
| Slack | Negotiation coach, onboarding, approve and release |
| Odoo | ERP for POs and goods receipts |

Microsoft and Hyphenate are tracks we entered, not tech we use, so they go in the Devpost text, not the logo grid.

## Status

| Item | State |
| --- | --- |
| Remotion project (`video/`) | Done: Remotion 4.0.538, React 18, `npm run studio` / `render` / `still` |
| Scene 1: `LogoIntro` | Done and rendered to `out/logo-intro.mp4` (4 s, will be trimmed to 3 s) |
| Script (this file) | Done |
| Scenes 2 to 6 | To build |
| Full composition + render to `out/demo.mp4` | To do |
