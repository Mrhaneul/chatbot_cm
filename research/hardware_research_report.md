# Lance Chatbot Hardware Recommendation Report

## Executive Summary

Lance currently runs on our development machine and responds too slowly when students ask questions that require the AI (12–25 seconds). We need dedicated hardware that's faster, always-on, and maintainable after my internship ends.

**Bottom Line Recommendation:** Purchase a **Mac mini M4 Pro with 48GB memory** for approximately **$1,450** (with education discount). This will make Lance **5–8 times faster** and cost only **$52/year in electricity** to run 24/7.

---

## Current Problem

**What's working:**
- 70–90% of student questions get instant answers (under 1 second) using our keyword system
- FAISS search and routing work perfectly

**What's NOT working:**
- 10–30% of questions need the AI to think, currently takes **12–25 seconds**
- When 5+ students use Lance at once during semester start, wait times can exceed **1 minute**
- Our current machine wasn't designed for 24/7 server operation

**Why it matters:**
- Students won't use a chatbot that takes 30+ seconds to respond
- Peak usage is during add/drop when students need help most
- After my internship, the system needs to be reliable without constant technical support

---

## Recommended Hardware Options (Ranked Best to Worst)

### ⭐ Option 1: Mac mini M4 Pro 48GB - *RECOMMENDED*

**Price:**
- Retail: $1,599
- With education discount: **~$1,450**

**Performance:**
- AI response time: **3–5 seconds** (vs current 12–25 seconds)
- Can handle **10–15 students simultaneously** without slowdown
- Runs quietly, fits on desk (5" × 5" footprint)

**Operating Cost:**
- Electricity: **$52/year** (runs 24/7)
- Expected lifespan: **5–7 years**

**Why this option:**
- ✅ Fast enough for students to actually use
- ✅ Room to upgrade to smarter AI models later
- ✅ Easy for non-technical staff to maintain (macOS)
- ✅ Best value, not the cheapest, but best price for what we get

---

### Option 2: Mac mini M4 Pro 24GB

**Price:** ~$1,260 (with education discount)

**Performance:**
- Same speed as 48GB version (3–5 seconds)
- Can handle **8–10 students simultaneously**

**Why NOT recommended:**
- Only $190 cheaper than 48GB version
- No room to grow if we want to add features later (like screenshot uploads)
- Might need replacement sooner

---

### Option 3: Mac Studio M4 Max 64GB

**Price:** ~$2,520 (with education discount)

**Performance:**
- AI response time: **2–4 seconds** (slightly faster)
- Can handle **15–20 students simultaneously**

**Why NOT recommended:**
- **$1,000+ more expensive** than Mac mini M4 Pro 48GB
- Same speed for our current AI model
- Only worth it if CBU plans to expand Lance beyond Campus Store (financial aid, registration, etc.)

---

### ❌ Option 4: Budget Mini PCs (Beelink, Intel NUC, etc.)

**Price:** ~$450–$550

**Performance:**
- AI response time: **10–15 seconds**
- Can handle **3–5 students simultaneously**

**Why NOT recommended:**
- Barely better than our current system
- Not worth the effort of migrating everything
- Less reliable for 24/7 operation

---

## Cost Comparison (3-Year Total)

| Option | Purchase Price | Electricity (3 years) | **Total Cost** |
|--------|----------------|-----------------------|----------------|
| **Mac mini M4 Pro 48GB** ⭐ | **$1,450** | **$156** | **$1,606** |
| Mac mini M4 Pro 24GB | $1,260 | $156 | $1,416 |
| Mac Studio M4 Max 64GB | $2,520 | $177 | $2,697 |
| Budget Mini PC | $500 | $216 | $716 |
| Keep current system | $0 | $984 | $984 |

**Note:** Current system uses $328/year in electricity. Mac mini saves $276/year, pays for itself over 5+ years just in power savings.

---

## What Happens After Purchase

**Immediate benefits:**

1. **Students get help faster** - 3–5 seconds instead of 12–25 seconds
2. **More students can use Lance at once** - no more queuing during busy periods
3. **Always available** - runs 24/7 without crashes or slowdowns

**Long-term benefits:** 

4. **Future upgrades possible** - can switch to smarter AI models without new hardware
5. **Easy maintenance** - macOS is simpler for non-technical staff than Windows/Linux
6. **Lower operating costs** - saves $276/year in electricity vs current system

---

## Questions to Discuss

Before purchasing, we need to decide:

### 1. Budget & Procurement
- Can this be purchased as a **Campus Store business expense**?
- Does CBU have **institutional Apple pricing** beyond the standard education discount?
- If so, we might get 15–20% off (saving another $170–$240)

### 2. IT Infrastructure Setup
- Should we schedule a meeting with **CBU IT** before purchasing?
- Need to plan: static IP address, DNS hostname, network security
- Current temporary solution (ngrok) should be replaced before going live

### 3. Timeline
- When do we need Lance fully operational?
- Semester starts in August, recommend having hardware by **June** for testing

### 4. Future Plans
- Will Lance stay Campus Store-only, or expand to other departments?
- If expanding: Mac Studio M4 Max worth considering
- If staying Campus Store: Mac mini M4 Pro 48GB is perfect

## Final Recommendation

**Purchase: Mac mini M4 Pro with 48GB memory**

**Expected Cost:** $1,450 (with education discount) or $1,280–$1,360 (if institutional pricing available)

**Why:** Best balance of speed, reliability, and cost for Lance's current needs and future growth. Students get fast responses, system runs 24/7 without issues, and non-technical staff can maintain it after internship ends.

