# Behind the Curtain — Marketing & Automation Strategy

Sep 29, 2026 · @Umer Saqib

## Executive summary

Behind the Curtain should launch as a $15/month personal alert service for US retail traders, grown mainly through a free X account that posts every notable trade.

The product: a web app where you star the politicians and companies you care about, and a Telegram bot that pings you the moment one of them files a trade. Congress trades (House and Senate reports) and company insider trades (SEC Form 4) sit in one watchlist.

The market is proven but crowded. Quiver, Unusual Whales, Capitol Trades, TraderCongress and Autopilot already serve it. Behind the Curtain wins on one thing they do badly: fast, personal alerts inside Telegram, at a lower price, with a community on top.

The plan has two parts. Part 1 is the selling strategy (who, what to say, where, what price, when). Part 2 is a set of small AI agents you build in Claude Code that do most of the daily marketing work for you, rolled out in three phases so you stay in control.

## Fix before launch

Three things in the current plan will cause problems if they are not sorted out first.

**1. Skool cannot switch off access when someone cancels.** Skool has no official API, and its Zapier connection has no "member cancelled" trigger and no "remove member" action ([Zapier forum](https://community.zapier.com/how-do-i-3/sync-membership-access-between-skool-and-my-external-membership-website-49551), [unofficial API notes](https://github.com/ctala/skool-api-docs)). If Skool takes the payment, people who cancel keep getting Telegram alerts. Fix: take payment in the web app with a payment provider that sends cancel events. Then invite paying users into Skool automatically (Zapier can do "invite member"). Skool becomes the community, not the till.

**2. Congress trades are old news by the time they are public.** Members of Congress can take up to 45 days to report a trade. Company insiders must file Form 4 within 2 business days ([SEC filing example](https://www.sec.gov/Archives/edgar/data/1811972/000181197225000007/ex191insidertradingpolicy.htm)). So sell speed on filings ("you know within minutes of the filing"), never speed on the trade itself. Company insider alerts are the fresher, more useful half of the product.

**3. Pick a payment provider that accepts this product.** A merchant of record (Paddle, Lemon Squeezy, Polar) handles US sales tax and EU VAT for you, which matters when you sell from Belgium to the US. Paddle does not accept products that are mainly "community access" ([Paddle AUP](https://paddle.com/support/aup)). So sell Behind the Curtain as software (web app + alerts) with the community as a bonus. Ask the provider to approve the product before you build checkout. The word "insider trading" in public copy may slow that approval, so have a plain description ready ("alerts on public SEC and Congress trade filings").

## Target customer and positioning

The first customer is a US retail trader, 22–45, who already follows "Pelosi tracker"-style accounts on X and wants alerts on a few names, not a data terminal.

What they have in common:

- They trade individual stocks from a phone (Robinhood, Webull, Schwab) and already use Telegram or Discord for trading chatter.
- They find Quiver and Unusual Whales too complex or too expensive for what they need.
- They are motivated partly by anger ("politicians shouldn't beat the market") and partly by greed ("copy the smart money").

**Positioning line:** *The people with inside information have to show their trades. Behind the Curtain sends them to your phone.*

| Competitor | Price | What they do well | Where Behind the Curtain wins |
| --- | --- | --- | --- |
| [Capitol Trades](https://tradercongress.com/blog/how-to-track-congressional-stock-trades) | Free | Clean browsing of Congress trades | They have no real alerts; you do |
| [Quiver Quantitative](https://kapitol.ai/best-congress-stock-trackers) | Free / $25 per month | Deep data, backtests, API | Built for data people; you are built for phones |
| [Unusual Whales](https://barebone.ai/resources/best-apps-to-track-insider-congress-trades) | \~$40–60 per month | Options flow + Congress alerts | You cost a quarter of the price for the part most people want |
| [Capitol Gains](https://www.capitolgainsapp.com/) | Free / from $6.99 per month | Mobile app, watchlist push alerts | You add company insiders + Telegram + community |
| [Autopilot / Pelosi Tracker](https://www.salon.com/2025/03/17/pelosi-tracker-shows-us-how-to-trade-stocks-like-politicians/) | \~$100 per portfolio per year | Auto-copy trades into a brokerage | You leave the decision with the trader |

The honest gap you fill: nobody combines Congress + company insiders + a personal watchlist + Telegram delivery + a community at a mid price. That is the pitch.

## Messaging

Lead with one core pitch, then test three angles against each other on X and on the landing page.

**Core pitch:** Pick the politicians and CEOs you want to watch. The moment they file a trade, it lands in your Telegram. No dashboards to check.

| Angle | Hook example | Who it pulls in |
| --- | --- | --- |
| Outrage | "Congress keeps trading stocks they regulate. Watch every move." | Political, high-share audience; best for growth on X |
| Smart money | "When a CEO buys $2M of their own stock, you'll know first." | Serious traders; best for paid conversion |
| Simplicity | "Star a name. Get a ping. That's it." | People put off by Quiver and Unusual Whales |

Rules for all copy:

- Report what was filed, never tell people to buy or sell. "Rep. X filed a $250K purchase of NVDA" is fine; "Buy NVDA now" is not.
- Always show the filing date next to the trade date, so nobody feels misled about timing.
- Keep the brand name front and centre. "Behind the Curtain" carries the "hidden moves made visible" idea on its own.

## Channel strategy

X is the main channel; everything else feeds it or catches the people it brings in. This is the exact route the "Nancy Pelosi Stock Tracker" account took: it posts disclosures with short commentary and now has about 1.9 million followers ([X profile](https://x.com/pelositracker)).

| Rank | Channel | Why here | Owner |
| --- | --- | --- | --- |
| 1 | X (Twitter) account | Proven home of this audience; every new filing is free content | Content Agent + Poster Agent, you approve |
| 2 | Free public Telegram channel | Shows 1–2 delayed alerts a day as a sample; the paid bot gives the rest instantly | Alert Engine |
| 3 | Email list from the landing page | Weekly "Top 5 filings" digest; the list you own if X changes its rules | Digest Agent |
| 4 | Reddit (r/stocks, r/wallstreetbets, r/investing) | Big audience, but hates self-promotion; share useful data posts, not ads | You, with drafts from the Content Agent |
| 5 | YouTube Shorts / TikTok | Short "Senator X just sold..." videos; add once X works | Later phase |
| 6 | Paid ads | Skip for now: financial ads face strict rules and your budget is small | — |

Two warnings for X. An earlier Pelosi tracker account was permanently suspended for spam ([SFGate](https://www.sfgate.com/national-politics/article/Nancy-Pelosi-viral-stock-trades-16826801.php)), so don't post dozens of near-identical automated posts. And under X's API pricing, a post with a link costs $0.20 versus $0.015 without one ([OpenTweet](https://opentweet.io/how-to/x-api-pay-per-use-explained)), so keep the link in your bio and post plain text.

Timely angle: Nancy Pelosi has retired, so there is room for a new "who is the next Pelosi" story. Rank the top-trading members every month and make that a recurring post.

## Pricing and launch offer

Two plans, priced between the free trackers and Unusual Whales: Free, and Pro at $15 per month.

| Plan | Price | What you get |
| --- | --- | --- |
| Free | $0 | Follow 3 names, alerts delayed 24 hours, public Telegram channel |
| Pro | $15 per month or $120 per year | Unlimited follows, instant Telegram alerts, both Congress and company insiders, weekly digest, Skool community |
| Founding member | $9 per month, locked for life | First 100 Pro subscribers only |

Why $15: Quiver Premium is $25 and Unusual Whales is around $40–60, while Capitol Gains starts at $6.99 ([Quiver](https://kapitol.ai/best-congress-stock-trackers), [Unusual Whales](https://barebone.ai/resources/best-apps-to-track-insider-congress-trades), [Capitol Gains](https://www.capitolgainsapp.com/)). $15 is an easy "yes" and still leaves room for a higher tier later.

What you keep per $15 sale: a merchant of record charges about 5% + $0.50 ([Dodo Payments comparison](https://dodopayments.com/blogs/cheapest-merchant-of-record)), so about $1.25 goes in fees. Skool's Hobby plan costs $9 per month ([Kourses](https://kourses.com/skool-pricing/)); because members join free by invite, Skool's 10% payment fee never applies.

The free plan is the growth engine: it gets people into Telegram, where the upgrade prompt lives. Every delayed alert says "Pro members got this 24 hours ago."

## Launch plan

Start the X account now, while the app is still being built, so you launch to an audience instead of to silence.

1. **Pre-launch (while building, about 6–8 weeks)**
   - Open the X account and the free Telegram channel under the Behind the Curtain name.
   - Post 2–3 filings a day by hand, using the Content Agent's drafts.
   - Put a waitlist on your domain: "Get founding-member pricing."
   - Goal: 500 X followers, 150 waitlist emails.
2. **Days 1–30 after launch**
   - Email the waitlist the founding-member offer ($9 for life, first 100).
   - Open the Skool community with a welcome post and a weekly "filings review" live call.
   - Goal: 30 paying members, first feedback on which alerts people value.
3. **Days 31–60**
   - Start the monthly "Top traders in Congress" ranking post.
   - Add Reddit data posts (once a week, useful first).
   - Goal: 75 paying members, free-to-Pro upgrade rate above 5%.
4. **Days 61–90**
   - Close founding pricing, move new users to $15.
   - Test short videos on YouTube Shorts / TikTok.
   - Goal: 150 paying members (about $1,650 per month: 100 founders at $9 + 50 at $15).

**Numbers to watch every week:** X followers gained, waitlist or free sign-ups, Telegram bot connections, free-to-Pro upgrades, and cancellations. If cancellations pass 10% a month, fix the product before pushing more marketing.

## Agent roster

Seven small agents run the marketing; each one exists only because a piece of the strategy above needs it.

| Agent | What it does | Serves which part of the strategy | Runs |
| --- | --- | --- | --- |
| Filing Scout | Pulls new House, Senate and SEC Form 4 filings; scores each one as "notable" (big size, famous name, committee link, several insiders buying together) | Feeds the product alerts and all content | Every 10 minutes |
| Content Agent | Uses the Claude API to turn notable filings into X posts, threads and Reddit drafts, following the copy rules | Channel 1 (X) and 4 (Reddit), Messaging | When the Scout flags something |
| Poster Agent | Publishes approved posts to X, spaced out, capped at about 8 per day | Channel 1 (X), avoids spam suspension | On a schedule |
| Teaser Agent | Posts 1–2 alerts a day, 24 hours late, to the free Telegram channel, with an upgrade line | Channel 2, free plan as growth engine | Daily |
| Digest Agent | Sends the weekly "Top 5 filings" email and the monthly "Top traders in Congress" ranking | Channel 3 (email), Days 31–60 plan | Weekly / monthly |
| Onboarding Agent | On payment: turns on Pro, links Telegram, sends the Skool invite. On cancel: turns Pro off | Fix-before-launch #1, Pricing | On payment webhooks |
| Analytics Agent | Collects the weekly numbers and sends you a short report in a private Telegram chat | Numbers to watch | Every Monday |

## How the agents work together

&#91;embedded content: agent flow · data in, alerts and posts out, payments back\]

The Filing Scout feeds everything. Posts on X only go out after your approval, and followers who subscribe flow through Payments to the Onboarding Agent, which switches Pro alerts on or off and sends the Skool invite. The Analytics Agent (not drawn) reads all of these and reports to you weekly.

## Tools and monthly costs

The whole stack runs for roughly $30–40 per month before revenue (plus hosting you already pay for the app), with two paid tools as you asked: the Quiver API for Congress data and a merchant of record for payments.

| Tool | Job | Cost |
| --- | --- | --- |
| SEC EDGAR | Company insider filings (Form 4) | Free |
| [Quiver API](https://kapitol.ai/best-congress-stock-trackers) (paid tool 1) | Clean Congress trade data, instead of scraping PDFs | From $10 per month |
| Merchant of record: Paddle, Lemon Squeezy or Polar (paid tool 2) | Checkout, subscriptions, US sales tax, EU VAT, cancel webhooks | About 5% + $0.50 per sale, no monthly fee ([comparison](https://dodopayments.com/blogs/cheapest-merchant-of-record)) |
| Telegram Bot API | Alerts and the free channel | Free |
| [X API](https://opentweet.io/how-to/x-api-pay-per-use-explained) | Posting | Pay per use: $0.015 per text post; \~240 posts a month is under $5 |
| Claude API | Content Agent drafts | Approximate: $5–15 per month at this volume |
| Skool Hobby | Community | $9 per month ([Kourses](https://kourses.com/skool-pricing/)) |
| Zapier (free plan to start) | Sends the Skool invite after payment | Free at low volume |
| Email tool with a free tier (e.g. Brevo or Resend) | Waitlist and weekly digest | Free to start; check limits |
| Scheduler: cron jobs in your app, or self-hosted n8n | Runs the agents on time | Free |

**What upgrading unlocks later:** Skool Pro ($99 per month, 2.9% fee) only matters if you ever sell inside Skool; a paid social scheduler only if you add Instagram or LinkedIn; a faster Congress data feed if Quiver's timing becomes the bottleneck.

## Claude Code build plan

Build the agents inside the same repo as the web app, one at a time, and test each on its own before connecting them.

Suggested folder layout:

```
/agents
  /filing-scout      fetch + score filings, write to db
  /content           Claude API prompts + post drafts
  /poster            X publishing queue
  /teaser            free Telegram channel posts
  /digest            weekly + monthly emails
  /onboarding        payment webhooks, Telegram link, Skool invite
  /analytics         weekly report
  /shared            db client, Telegram client, config
/prompts             copy rules, post templates, the 3 angles
```

Build order:

1. **Filing Scout first.** Ask Claude Code to pull Form 4 filings from EDGAR and Congress trades from the Quiver API into one `filings` table, then add the "notable" score. Test: run it on last week's data and check the top 10 by hand.
2. **Onboarding Agent second**, because nobody can pay without it. Set up the merchant-of-record checkout and its webhooks (`subscription created`, `cancelled`, `payment failed`). On create: mark user Pro, send the Telegram link code, call a Zapier webhook that invites them to Skool. On cancel: remove Pro and stop alerts. Test with the provider's sandbox.
3. **Content Agent.** Store the copy rules and the three angles in `/prompts`. Output goes to a `drafts` table with status "waiting for approval", never straight to X. Test: generate 20 drafts from real filings and read them all.
4. **Approval step.** A simple Telegram message to you with each draft and two buttons: Approve / Skip. This is your control lever for Phases 1 and 2.
5. **Poster Agent.** Publishes approved drafts through the X API with a daily cap and spacing (for example, no more than one post per 90 minutes). Set a spending limit in the X developer console.
6. **Teaser and Digest Agents.** Both reuse the Scout's data; they are small once steps 1–5 work.
7. **Analytics Agent last**, once there is data worth reporting.

**Triggers:** cron for the Scout (every 10 minutes), Teaser (daily), Digest and Analytics (weekly); webhooks for Onboarding; the Scout's "notable" event for the Content Agent.

**Keys to keep out of the code:** Quiver, X, Claude API, Telegram bot token, payment webhook secret, Zapier hook URL. Store them in environment variables and ask Claude Code to add a `.env.example`.

## Phased rollout

Move to the next phase only when the current one runs a full month without a mistake you had to fix.

1. **Phase 1 — Assisted (pre-launch)**
   - Scout and Content Agent run; everything else is you.
   - You copy-paste the best drafts to X and Telegram yourself.
   - Move on when: 80% or more of drafts are good enough to post with light edits.
2. **Phase 2 — Semi-automated (launch to day 60)**
   - Poster, Teaser, Onboarding and Digest run on their own.
   - Every X post still waits for your Approve tap in Telegram.
   - Move on when: you approve almost everything without edits for 4 weeks.
3. **Phase 3 — Mostly automated (after day 60)**
   - Routine posts (single filings, daily teasers) go out without approval.
   - Threads, rankings and anything naming a politician in a strong way still wait for you.
   - You spend about 20 minutes a day: approvals, replies, and the weekly Skool call.

Payments and account access (Onboarding) are automated from day one, because doing them by hand does not scale and mistakes there cost money.

## Risks and compliance

The biggest legal line: report public filings to everyone the same way, and never give personal buy or sell advice. This is not legal advice; confirm it with a lawyer before launch.

In the US, the Supreme Court held in *Lowe v. SEC* that publications giving impersonal, regular, general-circulation information fall outside investment-adviser rules, while personalised advice falls inside them ([case summary](https://www.lexplug.com/casebrief/lowe_v_securities_exchange_commission_69162c0d4d372c08469b0a2a)). A watchlist the user builds themselves stays on the safe side; "we'll tell you what to buy" does not. You operate from Belgium, so also ask a Belgian adviser whether EU rules on investment recommendations apply to your posts.

- [ ] Terms and disclaimer on the site and in the bot: "information from public filings, not investment advice."
- [ ] No buy/sell language in the Content Agent's prompts; the copy rules forbid it.
- [ ] Show filing date and trade date on every alert.
- [ ] Payment provider approves the product before checkout is built.
- [ ] Plain public description ready for providers and platforms ("alerts on public SEC and Congress filings").
- [ ] X daily cap and spacing in the Poster Agent to avoid spam suspension.
- [ ] Data check: if the Scout finds an unusual filing (for example a $50M trade), hold it for your review before any alert goes out.
- [ ] Keep the email list growing so you are not dependent on X alone.
- [ ] Decide which company runs Behind the Curtain before taking the first payment.
