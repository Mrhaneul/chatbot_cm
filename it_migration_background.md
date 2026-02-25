# IT Background Knowledge — Replacing ngrok with CBU Infrastructure

> Reference document for the Lance chatbot network migration conversation with CBU IT.

---

## The Core Problem

ngrok is a temporary tunnel from your local machine to the public internet. It resets on restart,
the URL changes, and it requires your personal computer to stay on 24/7. The goal is to replace it
with a stable, permanent connection through CBU's own network.

---

## Key Concepts to Know

### Static IP vs. Dynamic IP
- Devices on a network get an IP address. By default it changes on restart (dynamic).
- A **static IP** is permanently assigned — your Firebase frontend always knows where to find the backend.
- Ask IT to assign a **static internal IP** or hostname to the Lance machine.

### DNS and Hostnames
- Instead of a raw IP like `192.168.1.45`, IT can set up a hostname like `lance-api.calbaptist.edu`.
- If the machine ever moves or the IP changes, IT updates DNS and nothing else breaks.
- Ask for a **subdomain** — something like `lance-api.calbaptist.edu`.

### Firewall and Port Exposure
- CBU's firewall controls what traffic enters and exits the network.
- FastAPI runs on **port 8000** — IT needs to allow inbound traffic to that port on the Lance machine.
- The cleaner approach is a **reverse proxy** (e.g., nginx) that sits in front of the app and
  forwards traffic. More secure, and it handles HTTPS automatically.

### HTTPS and SSL Certificates
- Firebase is served over HTTPS. Browsers will block calls from an HTTPS page to a plain HTTP
  backend — this is called a **mixed content error**.
- The backend must also be on HTTPS.
- CBU likely has a **wildcard SSL certificate** for `*.calbaptist.edu`, meaning they can issue a
  trusted cert for any subdomain. This is the key ask.

### Docker — Why It Matters for IT
- Docker packages the entire app (Python, FastAPI, all dependencies) into one portable unit.
- IT can start, stop, and restart it with a single command: `docker compose up -d`
- Mentioning Docker signals a professional, maintainable handoff — not a fragile script they have
  to babysit.

---

## What CBU's Stack Probably Looks Like

The portal sites (`insidecbu.calbaptist.edu`, `lancerlink.calbaptist.edu`) suggest a traditional
Windows Server / IIS setup, possibly with some Linux VMs. LancerLink appears to be third-party SaaS.
CBU IT likely has a small infrastructure team managing on-premise servers and some cloud resources.
They will recognize Docker even if they don't use it heavily.

---

## How to Frame the Ask

> *"We have a FastAPI backend that needs to be reachable from our Firebase-hosted frontend. We're
> looking to place a dedicated machine on the CBU network and need a static hostname with HTTPS —
> ideally a subdomain like `lance-api.calbaptist.edu` — with a firewall rule or reverse proxy
> forwarding traffic to port 8000. The app is containerized with Docker so deployment and restarts
> are straightforward."*

---

## Migration Order

1. **Now** — Begin IT conversation, understand their infrastructure and timeline
2. **After hardware upgrade** — Containerize backend with Docker
3. **Then** — Hand IT a clean Docker package to deploy on the new machine
4. **Finally** — Update `VITE_API_URL` in the Firebase frontend to point to the new CBU hostname

---

## What You Don't Need to Know

You don't need to configure nginx, issue SSL certs, or understand CBU's full network topology —
that's IT's job. You just need to know enough to ask the right questions and recognize whether
what they offer actually solves the problem.

---

*Last updated: February 2026*
