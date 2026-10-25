# ReconAI product video: script

A 66-second story: one invoice takes 17.4 days today. ReconAI runs the whole bill lifecycle in one vendor chat, from
first quote to paid, and produces the three documents a 3-way match needs on the way.

- **Format:** 1920x1080, 30 fps, 66 s (1980 frames), captions only (no voiceover). Slightly slower than the 47.5 s cut.
- **Look:** the app's own brand and palette (`ui/src/styles.css`, `ui/src/review/main.tsx`): white-to-teal-wash
  gradient backdrop, light panels, Geist type, brand teal #0E6E76 for actions and in-progress, **green for anything
  completed** (steps, documents, checks, automated steps), red for the mismatch. Slack keeps Slack's light theme.
- **Logo:** the app's logo, not a tile: "RECON-AI" in Saira Stencil, brand teal, with three forward chevrons that pulse
  (`BrandLogo`). The intro brings the chevrons in alone, then the wordmark grows out of them; the outro repeats it.
- **Right panel:** an invoice→paid clock (split-flap), a PO → Receipt → Invoice stepper, the **three documents**, a 3-way
  match strip, and an **Automated** grid (Coach, Contract, Onboarding, PO in ERP, Receipt, Invoice read, 3-way match,
  Payment).
- **Animations** (React Bits, ported to run on Remotion frames): Split Flap Text (17.4 days, the clock), Stepper,
  Border Glow sweep (each document card as it lands; red on the mismatch; green on the match), Rotating Text (the
  invoice format pill), Blur Text (captions), Decrypted Text (document IDs), Click Spark (cursor clicks), Shiny Text
  (the Paid toast).
- **Transitions:** iris out of the logo, slide from the right into the chat (the fast-forward), clock wipe into the
  outro.
- **Music:** "Product Video" by SoundSurfer (Pixabay; free to use in the video, no standalone redistribution, so the
  audio files are gitignored). Cut to the timeline as `public/audio/soundtrack.wav` with ffmpeg: the first 58.75 s (its
  quiet breakdown sits under the corrected invoice and the all-clear DM), a 0.75 s crossfade into the track's last 8 s
  so the energy returns as the payout lands (58 s) and the song ends with the outro; loudness-normalised to -16 LUFS.
  Rebuild: `ffmpeg -i public/audio/soundsurfer-product-video-590799.mp3 -filter_complex "[0]atrim=0:58.75,asetpts=PTS-STARTPTS[a];[0]atrim=106.3:114.3,asetpts=PTS-STARTPTS[b];[a][b]acrossfade=d=0.75:c1=qsin:c2=qsin,afade=t=in:d=0.25,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100" -ac 2 public/audio/soundtrack.wav`
- **Cast:** "Vendor" (the supplier, unnamed on purpose) and the CTO at Helix (buyer and approver).
- **Honesty rule:** every command, button, status and bill shown exists in the product or `data/answer_key.json`,
  except what's marked illustrative below.

## Storyboard

| # | Time | Scene | On screen | Caption |
| --- | --- | --- | --- | --- |
| 1 | 0:00 to 0:03.5 | Logo | `LogoIntro`. Bokeh fades up. | none |
| 2 | 0:03 to 0:09 | 17.4 days | Visual only: a split-flap board flips up to **17.4 days** while one invoice limps between five tool icons (no labels), an hourglass at each stop, and never reaches the faded "paid" icon. A small source line in the corner. | "One invoice. 17.4 days." |
| 3 | 0:08.5 to 0:11.5 | Fast-forward | The 17.4 days streaks away; a ▶▶ glyph and speed lines. The Slack channel `🔒 vendor-deal` springs in; the right panel slides in with three empty document cards. | "ReconAI starts at the first quote." |
| 4 | 0:11.5 to 0:18.5 | The coach | Vendor: "We can do $1,520 per stack for 50, net 30." An "Only visible to you" ReconAI note: price gauge (their quote $1,520, walk away $1,460, aim $1,300, counter $1,180), **+$11,000 at the aim**, then cash-flow asks: "Ask 2/15 net 30 · worth $1,520" and "or net 45 instead of net 30". The Vendor avatar dims (it can't see it). | "Only your side sees this." then "Best price and cash flow, before you sign." |
| 5 | 0:18.5 to 0:24.5 | Signed, onboarded | CTO: "Agreed: 50 at $1,450, 2/15 net 30." Supply Agreement; the **Vendor** cursor clicks Accept & start onboarding. "✅ Vendor onboarded by policy: every check passed · 90-day probation" with sanctions, bank, domain, tax form ticking. Coach, Contract and Onboarding light in Automated. | "Signed. The vendor is onboarded automatically." |
| 6 | 0:24.5 to 0:29 | Document 1 | "📦 PO-7001 created in Helix ERP from the contract · 50 × HBM3E-12H-24G"; PO-7001 flies into card **1 Purchase order** (50 × $1,450 · Helix ERP · from the contract). PO in ERP lights. | "The contract becomes document 1: the purchase order." |
| 7 | 0:29 to 0:34 | Shipped | The Vendor types `/reconai shipped PO-7001 HBM3E-12H-24G=50` in the composer and sends. "🚚 Shipment notice logged: PO-7001 · 50 × HBM3E-12H-24G", tagged "claim · Helix counts it". | "The vendor tells ReconAI what shipped." |
| 8 | 0:34 to 0:40 | Document 2 | The channel blurs; a private ReconAI DM to the CTO: "🚚 Vendor says PO-7001 shipped: 50 × HBM3E-12H-24G. Nothing is received until someone at Helix counts it." The **CTO** cursor clicks **All 50 received** → "Recorded". Back in the channel: "✅ Goods receipt GRN-PO-7001-1"; it flies into card **2 Goods receipt** (50 received · counted by the CTO). Receipt lights. | "You confirm the count. Document 2: the receipt." |
| 9 | 0:40 to 0:48 | Document 3, mismatch | The Vendor drops `KM-INV-30118.xlsx` (PDF · CSV · XLSX shown, XLSX lit); it glows while ReconAI reads it and lands in card **3 Invoice** (50 × $1,520). The clock starts. "Received KM-INV-30118: reconciling against PO-7001 and GRN-PO-7001-1." Match strip: Qty 50 = 50 = 50 ✓, **Price ✗**, Bank ✓, No duplicate ✓; card 3 glows red. ReconAI posts "**@Vendor** We found a difference on KM-INV-30118; details emailed to your contact on file." | "Document 3: the invoice, reconciled on arrival." then "A mismatch? The vendor is tagged, right here." |
| 10 | 0:48 to 0:53.5 | Corrected | The Vendor drops `KM-INV-30118-R.pdf`; card 3 flips to KM-INV-30118-R · 50 × $1,450; Price turns ✓ and all three cards lock green. | "Corrected. All three documents agree." |
| 11 | 0:53.5 to 1:01.5 | All clear, paid | The channel blurs; a private DM to the CTO: "🟢 Ready to approve: KM-INV-30118-R · $72,500" with ✓ 3-way match, Price, Bank = vendor master, No duplicate, Sender verified; agent → you. The **CTO** cursor clicks **Approve & release payment**; a coin arcs into "Paid · $71,050 · 2% early-pay discount kept". Back in the channel: "💸 Payment sent: $71,050 for KM-INV-30118-R". Payment is shown generically, not tied to one rail. The clock stops at **31 min** vs 17.4 days. | "All clear, in a private DM." then "One click to pay. The chat updates too." |
| 12 | 1:01 to 1:06 | Outro | Panels: **3 / 3** documents matched, **Paid**, **31 min** invoice to paid. Logo, wordmark, fade. | "Built at Cal Hacks 13.0" |

## Data notes

- **17.4 days:** Ardent Partners, *The State of ePayables 2024: Money Never Sleeps*: "3.1 days vs. 17.4 days to process
  a single invoice" (best-in-class vs. other AP teams), as summarised by Bottomline
  (bottomline.com/us/resources/the-state-of-epayables-2024). The on-screen source line names the report.
- **The bill is case_01:** PO-7001, 50 × HBM3E-12H-24G at the MSA price $1,450 = KM-INV-30118, $72,500; terms 2/15 net
  30, so a timely release pays $71,050 (the app shows "Early-payment discount captured: $1,450.00").
- **The coach's numbers** are `backend/slack/market.py` `analyze()` for this SKU with a $1,520 quote at net 30:
  counter $1,180 (p25), aim $1,300 (median), walk away $1,460 (p75), $11,000 saved at the aim, and the term asks
  "2/15 net 30 (worth 1,520 at 2%)" and "net 45 instead of net 30".
- **Illustrative:** the $1,520 opening quote; the first invoice billing that quote instead of the agreed $1,450 (the
  Matcher's price check is real, e.g. case_03); the corrected invoice KM-INV-30118-R (corrections like case_02 → case_37
  INV-881-R are real); the message clock 10:02 → 10:33, so "31 min" is a scenario, not a measurement. The live
  workspace run went from invoice to the release prompt in about 7 minutes.
- **Product wording** (`backend/slack/cycle.py`, `bot.py`, `onboard.py`): PO created in the ERP from the contract;
  `/reconai shipped PO SKU=qty` is a claim; the received DM with **All N received / Different quantity…** creates the
  goods receipt; invoices are accepted in the chat as PDF, photo, CSV or XLSX; a green bill DMs "Ready to approve" with
  **Approve & release via Coinbase** to the CTO/controller/CFO; after release the channel gets "Payment sent".
- **One difference from the product:** on a mismatch the product posts "We found a difference on {invoice}; details
  emailed to {contact}" in the channel, without @-mentioning the vendor. The video adds the **@Vendor** tag. Make the
  product match (one line in `cycle.py` `notify_bill`) or drop the tag before submitting.
- "Vendor", "CTO", "Helix Silicon" and `#vendor-deal` are display names, not product data.

## Status

| Item | State |
| --- | --- |
| Scene 2 (`src/scenes/Tat.tsx`), scenes 3–11 (`src/scenes/Lifecycle.tsx`), outro (`Outro` variant v5) | Built |
| Full composition `Demo` (1980 frames) | Built. `npm run render` writes a new `out/demo-<timestamp>.mp4` and never overwrites |
| Previous cuts | `DemoV4` (47.5 s, `out/demo-20261025-024107.mp4`) and `DemoV3` (69 s, `out/demo-20261025-020857.mp4`) in the studio's "Previous-cut" folder |
