# CogniForge

CogniForge is a document-driven, multi-agent software factory that simulates a full software engineering organization.

It transforms product requirements into production-ready systems through a structured, deterministic workflow — without relying on RAG or fragile prompt chaining.

---

## 🚀 What is CogniForge?

CogniForge is not just an AI coding tool.

It is an **AI Software Organization**.

Instead of asking a single model to generate code, CogniForge orchestrates multiple specialized agents that mirror real-world engineering roles:

- PM → defines product requirements (PRD)
- Architect → designs system architecture (SAD)
- MDE → produces detailed design (LLD, data models)
- Tech Lead → plans, reviews, and governs execution
- Developers → implement code and tests
- Reviewer → enforces code quality and consistency
- QA → validates functionality and system behavior
- DevOps → prepares infrastructure and deployment

---

## 🧠 Core Philosophy

### 1. Document-Driven (Docs as State)

All knowledge is persisted as structured documents:

- PRD
- Architecture (SAD)
- Design (LLD)
- ADR (decisions)
- Tasks (WBS)
- Test cases & reports

No hidden memory. No black-box retrieval.

---

### 2. No RAG — Deterministic Context

CogniForge does **not** rely on vector search or embeddings.

Instead, it uses:

- structured wiki
- deterministic context loading
- module-based routing

This ensures:

- full controllability
- auditability
- reproducibility

---

### 3. Multi-Agent System

Each agent has a strict responsibility boundary.

No "god agent". No uncontrolled behavior.

---

### 4. DAG-Driven Execution

The entire lifecycle follows a strict engineering workflow:

PRD → Architecture → Design → WBS → Coding → Review → Testing → Release → Retrospective

---

## 🏗️ System Architecture

Orchestration Layer (OpenX)
↓
Multi-Agent Layer (PM / SE / MDE / TL / Dev / QA / Reviewer)
↓
Document Context Layer (Wiki / Specs)
↓
Execution Layer (Code / Test / CI)
↓
Storage Layer (Git)

---

## ⚙️ Key Features

- 🧩 Full lifecycle automation (PRD → production)
- 🧠 Persistent knowledge via structured wiki
- 🔁 Self-improving via documentation updates
- 🧱 Strong architecture enforcement (ADR-driven)
- 🔍 Fully auditable via Git history
- ⚡ Parallel execution with task DAG
- 🛡️ Built-in quality gates (CR / QA / UAT)

---

## 🧪 Why Not RAG?

RAG introduces:

- non-deterministic context
- hidden retrieval bias
- scaling complexity

CogniForge replaces it with:

- explicit knowledge structures
- deterministic loading rules
- document-level reasoning

---

## 🎯 Use Cases

- Medium-to-large software projects
- Long-running autonomous development
- Enterprise-grade system design & delivery
- AI-native development pipelines

---

## 🧩 Vision

CogniForge represents a shift:

> From "AI writes code"  
> → to "AI runs a software organization"

---

## 📌 Status

🚧 In active development

---

## 📜 License

MIT (or your choice)
