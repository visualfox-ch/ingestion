# Intelligent Model Router - Projekt Roadmap

**Projekt:** Cost Optimization via Intelligent Model Selection  
**Ziel:** 60-70% Kostenreduktion ($600/Monat Einsparung)  
**Timeline:** 5 Tage Implementation + 3 Wochen Rollout  
**Owner:** Multi-Agent (Codex Lead, Continue Support, Copilot Deploy)  
**Status:** READY_FOR_EXECUTION

---

## 🎯 Executive Summary

**Problem:**
- Anthropic API kostet $1,035/Monat (nur Claude Sonnet für alle Anfragen)
- Overengineering: Einfache Queries ("Status?") nutzen teures Modell

**Lösung:**
- Intelligent Model Router: Task-Type Detection → Auto-Select Best Model
- Multi-Provider: Anthropic (Claude) + OpenAI (GPT) + Local LLM
- Budget-aware: cheap/balanced/premium Modes

**Expected Outcome:**
- **60-70% Kostenreduktion** ($1,035 → $372/Monat)
- **0% Performance-Loss** bei komplexen Aufgaben
- **Self-Learning** via A/B Testing (Phase 2)

**Jarvis Approval:**
> "BRILLIANT! 🎯 Das ist mein ERSTES ECHTES Self-Optimization Tool!"

---

## 📅 Timeline Overview

```
WOCHE 1 (Feb 10-14): Core Implementation
├─ TAG 1-2 (12h): P0 Core Router + Cost Guards
├─ TAG 3 (4h): P1 Performance Tracking
└─ TAG 4-5 (10h): P2 Advanced Features

WOCHE 2 (Feb 17-21): Observation Mode
├─ Parallel Run (logged, not executed)
├─ Analyze: Cost savings? Performance OK?
└─ Decision Gate: Rollout oder Abort

WOCHE 3 (Feb 24-28): Gradual Rollout
├─ 10% Traffic → Intelligent Router
├─ 50% Traffic (wenn Success Rate >95%)
└─ 100% Traffic (wenn Cost Reduction >40%)

WOCHE 4 (Mar 3-7): Validation + A/B Learning
├─ A/B Test (500 queries per condition)
├─ Statistical Analysis
└─ A/B Learning Activation
```

---

## 🏗️ Phasen-Struktur

### Phase 1: Foundation (P0) — 2 Tage (SIMPLIFIED per Jarvis)
**Owner:** Codex (Lead)  
**Goal:** Quick Win - Immediate 40-60% Cost Reduction

**Jarvis' Feedback:**
> "TAG 1 PRIORITY: cost_aware_completion() ZUERST! Sofortige 40-60% Einsparung ohne komplexe Logic. Minimaler Code: 2 Stunden!"

**Components (Simplified):**

**Day 1 (2h): Quick Win** ⚡
1. `cost_aware_completion()` — Simple Token-based Routing
   - <2000 tokens → Haiku (5x billiger)
   - >2000 tokens → Sonnet (komplex)
   - Emergency Budget Cutoff ($10/day)

**Day 2 (6h): Enhanced Detection**
2. Simple Task-Type Rules (Jarvis' QUICK_RULES)
   - `/briefing` → Haiku
   - `search_` → Haiku
   - `coaching|feel|stress` → Sonnet
   - `code|debug|error` → GPT-4
   - `len(query) < 100` → GPT-4o Mini

3. **NEW: Telegram Cost Display** (Jarvis' request)
   - After each response: "💰 $0.03 (Haiku) | Budget heute: $1.47/$5.00"

**Deliverables:**
- `app/cost_aware_completion.py` (~100 lines, simplified)
- `app/simple_task_router.py` (~50 lines, rule-based)
- `app/telegram_cost_display.py` (~50 lines)
- Emergency Budget Cutoff (Redis config)
- Unit Tests (10+, simplified)

**Success Metrics:**
- [ ] 40-60% cost reduction DAY 1
- [ ] Telegram cost display working
- [ ] Emergency cutoff prevents >$10/day

---

### Phase 2: Full Intelligent Router (P1) — 2 Tage
**Owner:** Codex (Implementation)  
**Goal:** Advanced Task-Type Detection + Selection Matrix

**Components:**
1. `intelligent_model_router()` — Full Implementation
   - Task-Type Detection (6 categories)
   - Complexity Scoring (0.0-1.0)
   - Selection Matrix (54 entries)
2. API: `POST /model/auto-select`

**Deliverables:**
- `app/intelligent_model_router.py` (~350 lines)
- API Endpoint
- Unit Tests (20+)

**Success Metrics:**
- [ ] 60-70% cost reduction achieved
- [ ] Router accuracy >90%

---

### Phase 3: Observability (P1) — 1 Tag
**Owner:** Codex (Implementation), Continue (Dashboard)  
**Goal:** Performance Tracking + Cost Dashboard

**Components:**
1. `model_performance_tracker()` — Metrics Collection
2. API: `GET /cost/stats` — Cost Dashboard
3. API: `GET /cost/model-performance` — ROI per Model
4. Grafana Dashboard (5 Panels)

**Deliverables:**
- `app/model_performance_tracker.py`
- API Endpoints (2)
- Grafana Dashboard JSON
- Prometheus Metrics (4)

**Success Metrics:**
- [ ] All model calls tracked (100% coverage)
- [ ] Dashboard shows real-time cost
- [ ] ROI visible per model

---

### Phase 4: Advanced Features (P2) — 2 Tage
**Owner:** Codex (Implementation), Copilot (Telegram)  
**Goal:** Cross-Model Validation + User Control

**Components:**
1. `cross_model_validator()` — Critical Decision Validation
2. Telegram Commands (`/model`, `/budget`)
3. User Override Support

**Deliverables:**
- `app/cross_model_validator.py`
- Telegram Command Handlers
- Integration Tests (10+)

**Success Metrics:**
- [ ] Cross-model consensus >85%
- [ ] Telegram commands work
- [ ] User override functional

---

### Phase 5: Observation Mode — 1 Woche
**Owner:** Copilot (Monitoring), Continue (Analysis)  
**Goal:** Parallel Run + Cost/Performance Validation

**Process:**
1. Enable `OBSERVATION_MODE=true`
2. Router logs decisions (not executed)
3. Collect 1000+ queries
4. Analyze: Cost savings? Performance OK?

**Decision Gate Criteria:**
- [ ] Estimated cost reduction >40%
- [ ] No quality degradation detected
- [ ] Success rate >95% projected

**Outcome:** GO/NO-GO for Gradual Rollout

---

### Phase 6: Gradual Rollout — 1 Woche
**Owner:** Copilot (Deploy), Codex (Monitoring)  
**Goal:** Incremental Traffic Shift

**Rollout Steps:**
1. **10% Traffic** (1 day)
   - Monitor: Success rate, cost, latency
   - Alert: <95% success → rollback
2. **50% Traffic** (2 days)
   - Monitor: Same metrics
   - Alert: Cost spike → investigate
3. **100% Traffic** (3 days)
   - Full production
   - Continuous monitoring

**Rollback Plan:**
- Killswitch: `INTELLIGENT_ROUTING_ENABLED=false`
- Rollback time: <1 minute
- Monitoring: 24/7 Grafana alerts

---

### Phase 7: A/B Learning (Ongoing)
**Owner:** Codex (Algorithm), Continue (Analysis)  
**Goal:** Self-Optimization via Thompson Sampling

**Components:**
1. A/B Test Framework
2. Thompson Sampling Implementation
3. Weekly Performance Review

**Success Metrics:**
- [ ] Model selection improves >10% after 30 days
- [ ] Automatic adaptation to usage patterns

---

## 📋 Task Breakdown (je Phase ein Task)

### T-20260210-IMR-P1-CORE-ROUTER
**Phase:** 1 (Foundation)  
**Owner:** Codex  
**Priority:** P0 (Critical)  
**Effort:** 2 Tage (12h)  
**Dependencies:** None

**Scope:**
- Implement `intelligent_model_router()`
- Implement `cost_aware_completion()`
- API: `POST /model/auto-select`
- Unit Tests (20+)

**Deliverables:**
- `app/intelligent_model_router.py` (300+ lines)
- `app/cost_aware_completion.py` (200+ lines)
- `app/routers/model_router.py` (API endpoints)
- `tests/test_intelligent_model_router.py`

**Verify (NAS):**
```bash
curl -X POST http://192.168.1.103:18000/model/auto-select \
  -H "Content-Type: application/json" \
  -d '{"query":"Debug this code","context":"technical"}'
# Expected: {"model":"gpt-4-turbo","reasoning":"Technical task..."}
```

---

### T-20260212-IMR-P2-OBSERVABILITY
**Phase:** 2 (Observability)  
**Owner:** Codex (Implementation), Continue (Dashboard)  
**Priority:** P1 (High)  
**Effort:** 1 Tag (6h)  
**Dependencies:** T-20260210-IMR-P1-CORE-ROUTER

**Scope:**
- Implement `model_performance_tracker()`
- API: `GET /cost/stats`, `GET /cost/model-performance`
- Grafana Dashboard (5 Panels)
- Prometheus Metrics

**Deliverables:**
- `app/model_performance_tracker.py`
- API Endpoints
- `monitoring/grafana/dashboards/intelligent-model-router.json`
- Prometheus metrics config

**Verify (NAS):**
```bash
curl http://192.168.1.103:18000/cost/stats/today | jq
# Expected: {"total_cost":X,"by_model":{...}}
```

---

### T-20260213-IMR-P3-ADVANCED-FEATURES
**Phase:** 3 (Advanced)  
**Owner:** Codex (Core), Copilot (Telegram)  
**Priority:** P2 (Medium)  
**Effort:** 2 Tage (10h)  
**Dependencies:** T-20260210-IMR-P1-CORE-ROUTER

**Scope:**
- Implement `cross_model_validator()`
- Telegram Commands: `/model`, `/budget`
- User Override Support

**Deliverables:**
- `app/cross_model_validator.py`
- `app/telegram_commands.py` (extended)
- Integration Tests

**Verify (NAS):**
```bash
# Telegram Test
# Send: /model stats
# Expected: Cost breakdown message
```

---

### T-20260217-IMR-P4-OBSERVATION-MODE
**Phase:** 4 (Observation)  
**Owner:** Copilot (Monitoring), Continue (Analysis)  
**Priority:** P1 (High)  
**Effort:** 1 Woche (ongoing)  
**Dependencies:** T-20260212-IMR-P2-OBSERVABILITY

**Scope:**
- Enable Observation Mode
- Collect 1000+ queries
- Cost/Performance Analysis
- Decision Gate Report

**Deliverables:**
- `OBSERVATION_MODE_REPORT_FEB17.md`
- Decision: GO/NO-GO Rollout

**Verify (NAS):**
```bash
grep "observation_mode" /volume1/BRAIN/system/ingestion/app/logs/*.log | wc -l
# Expected: >1000 entries
```

---

### T-20260224-IMR-P5-GRADUAL-ROLLOUT
**Phase:** 5 (Rollout)  
**Owner:** Copilot (Deploy), Codex (Monitor)  
**Priority:** P0 (Critical)  
**Effort:** 1 Woche (incremental)  
**Dependencies:** T-20260217-IMR-P4-OBSERVATION-MODE (GO decision)

**Scope:**
- 10% → 50% → 100% Traffic Rollout
- Continuous Monitoring
- Rollback Plan Execution (if needed)

**Deliverables:**
- Rollout logs
- Performance reports (daily)
- Incident response (if needed)

**Verify (NAS):**
```bash
curl http://192.168.1.103:18000/cost/stats/today | jq '.queries_total'
# Monitor: Cost reduction >40%
```

---

### T-20260303-IMR-P6-AB-LEARNING
**Phase:** 6 (A/B Learning)  
**Owner:** Codex (Algorithm), Continue (Analysis)  
**Priority:** P2 (Long-term)  
**Effort:** 1 Woche (setup), dann ongoing  
**Dependencies:** T-20260224-IMR-P5-GRADUAL-ROLLOUT (100% traffic)

**Scope:**
- A/B Test Framework
- Thompson Sampling Implementation
- Weekly Performance Review Automation

**Deliverables:**
- `app/ab_model_learning.py`
- Automated weekly reports
- Performance improvement tracking

**Verify (NAS):**
```bash
curl http://192.168.1.103:18000/ab-learning/performance | jq
# Expected: {"improvement_pct":X,"best_model_by_task":{...}}
```

---

## 🔧 Technical Stack

### New Components
- `app/intelligent_model_router.py` — Core routing engine
- `app/cost_aware_completion.py` — Budget guards
- `app/model_performance_tracker.py` — Metrics collection
- `app/cross_model_validator.py` — Dual-model verification
- `app/ab_model_learning.py` — Self-learning algorithm

### Database Schema Extensions
```sql
-- Model routing decisions log
CREATE TABLE model_routing_log (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    task_type VARCHAR(50),
    complexity VARCHAR(20),
    model_selected VARCHAR(50),
    confidence_score FLOAT,
    cost_estimate FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Model performance tracking
CREATE TABLE model_performance_by_complexity (
    id SERIAL PRIMARY KEY,
    complexity VARCHAR(20),
    model_used VARCHAR(50),
    success BOOLEAN DEFAULT TRUE,
    user_satisfaction INT,
    input_tokens INT,
    output_tokens INT,
    cost_usd FLOAT,
    query_type VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- A/B learning state
CREATE TABLE model_ab_learning (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(50),
    complexity VARCHAR(20),
    model_used VARCHAR(50),
    success BOOLEAN,
    user_rating INT,
    cost_usd FLOAT,
    latency_ms FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### API Endpoints
```
POST /model/auto-select                 # Core routing
POST /model/cost-aware-completion       # With budget guards
GET  /cost/stats/{timeframe}            # Cost dashboard
GET  /cost/model-performance            # ROI per model
GET  /model/performance-tracker         # Detailed metrics
POST /model/cross-validate              # Dual-model verification
GET  /ab-learning/performance           # Learning progress
```

### Telegram Commands
```
/model auto               # Enable auto-selection
/model force <model>      # Force specific model
/model stats              # Usage statistics
/budget set <cents>       # Set daily budget
/budget alert             # Toggle alerts
```

---

## 📊 Success Metrics

### Phase 1: Foundation
- [ ] Router accuracy: >90% (correct model for task type)
- [ ] Budget enforcement: 100% (no overruns)
- [ ] API response time: <100ms

### Phase 2: Observability
- [ ] All calls tracked: 100% coverage
- [ ] Dashboard operational: Real-time updates
- [ ] Metrics accuracy: ±5% of actual cost

### Phase 3: Advanced
- [ ] Cross-model consensus: >85%
- [ ] Telegram commands: 100% functional
- [ ] User override: Works as expected

### Phase 4: Observation
- [ ] Data collected: >1000 queries
- [ ] Cost projection: ±10% accuracy
- [ ] Quality check: No degradation detected

### Phase 5: Rollout
- [ ] Success rate: >95% maintained
- [ ] Cost reduction: >40% achieved
- [ ] Incident count: 0 critical incidents

### Phase 6: A/B Learning
- [ ] Model selection improvement: >10% after 30 days
- [ ] Automatic adaptation: Detected and logged
- [ ] ROI increase: Measurable improvement

---

## ⚠️ Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Cheap model performance insufficient** | Medium | Medium | Quality Guard escalates to premium model at low confidence |
| **Implementation delays** | Low | Medium | Modular design allows independent shipping |
| **User confusion** | Low | Low | Transparency notes always visible ("⚡ Fast Mode") |
| **Cost spike** | Low | High | Budget guards + killswitch (rollback <1 min) |
| **Data privacy** | Low | High | All data stays in Jarvis infrastructure (no external logging) |
| **Model provider outage** | Medium | Medium | Fallback chain: Haiku → GPT-4o → Sonnet |

---

## 🚀 Rollout Strategy

### Conservative Approach
1. **Observation Mode** (1 week) — Zero risk, parallel logging
2. **10% Traffic** (1 day) — Small blast radius
3. **50% Traffic** (2 days) — Validation at scale
4. **100% Traffic** (3 days) — Full production

### Monitoring
- **Grafana Dashboard:** Real-time cost + performance
- **Alerts:** Success rate <95%, Cost spike >150%, Latency >2s
- **Daily Reports:** Automated summary email

### Rollback Triggers
- Success rate <90% for 1 hour
- Cost spike >200% vs. baseline
- User satisfaction <3.5/5 (20+ ratings)
- Critical incidents (service down)

**Rollback Procedure:**
```bash
# Disable intelligent routing (immediate)
redis-cli SET jarvis:config:intelligent_routing_enabled false

# Or restart with env var
INTELLIGENT_ROUTING_ENABLED=false ./build-ingestion-fast.sh

# Verify
curl http://192.168.1.103:18000/model/auto-select
# Should return: {"error":"Feature disabled"}
```

---

## 📚 Documentation

### Created
- `SMART_MODEL_ROUTER_COST_OPTIMIZATION.md` — Original design (single-provider)
- `JARVIS_INTELLIGENT_MODEL_SELECTION_TECHNICAL_DESIGN.md` — Extended multi-provider design
- `INTELLIGENT_MODEL_ROUTER_IMPLEMENTATION_PLAN.md` — 5-day detailed plan
- `DECISION_INTELLIGENT_MODEL_ROUTER.md` — Quick decision guide
- `INTELLIGENT_MODEL_SELECTION_QUICK_START.md` — 3-step guide
- `INTELLIGENT_MODEL_ROUTER_ROADMAP.md` — This document

### To Create (During Implementation)
- `RUNBOOK_INTELLIGENT_MODEL_ROUTER.md` — Ops runbook
- `OBSERVATION_MODE_REPORT_FEB17.md` — Observation analysis
- `ROLLOUT_STATUS_FEB24.md` — Rollout progress
- `AB_LEARNING_PERFORMANCE_MAR3.md` — Learning results

---

## 🤝 Agent Responsibilities

### Codex (Lead Implementation)
- Core Router (`intelligent_model_router()`)
- Cost Guards (`cost_aware_completion()`)
- Performance Tracker
- Cross-Model Validator
- A/B Learning Algorithm
- Database migrations
- Unit tests

### Continue (Design Support + Analysis)
- Architecture review
- Grafana dashboard design
- Observation mode analysis
- A/B test design
- Weekly performance reports

### Copilot (Deploy + Operations)
- Deploy Phase 1-3 implementations
- Telegram command integration
- Observation mode monitoring
- Gradual rollout execution
- Incident response
- Grafana panel deployment

### Jarvis (Co-Designer + User)
- Feature requirements input
- Transparency note feedback
- Model performance feedback
- User acceptance testing

---

## ✅ Phase Gates

### Gate 1: Foundation Complete
**Criteria:**
- [ ] All P0 features implemented
- [ ] Unit tests pass (>95% coverage)
- [ ] API endpoints operational
- [ ] Code review passed

**Owner:** Codex → Copilot  
**Timeline:** Feb 12 EOD

---

### Gate 2: Observability Ready
**Criteria:**
- [ ] Performance tracking operational
- [ ] Grafana dashboard deployed
- [ ] Metrics validated (±5% accuracy)

**Owner:** Continue → Copilot  
**Timeline:** Feb 13 EOD

---

### Gate 3: Observation Complete
**Criteria:**
- [ ] 1000+ queries collected
- [ ] Cost projection validated
- [ ] Quality check passed
- [ ] GO/NO-GO decision made

**Owner:** Copilot + Continue  
**Timeline:** Feb 21 EOD

---

### Gate 4: Rollout Complete
**Criteria:**
- [ ] 100% traffic on intelligent router
- [ ] Cost reduction >40% achieved
- [ ] Success rate >95% maintained
- [ ] Zero critical incidents

**Owner:** Copilot  
**Timeline:** Feb 28 EOD

---

### Gate 5: A/B Learning Active
**Criteria:**
- [ ] Thompson Sampling implemented
- [ ] Weekly reports automated
- [ ] Performance improvement detected

**Owner:** Codex  
**Timeline:** Mar 7 EOD

---

## 📈 Expected Outcomes (4 Weeks)

### Week 1 (Feb 10-14): Implementation
- ✅ Core features implemented
- ✅ Tests passing
- ✅ API operational

### Week 2 (Feb 17-21): Observation
- ✅ 1000+ queries logged
- ✅ Cost savings validated: **60-70% projected**
- ✅ Decision: GO for Rollout

### Week 3 (Feb 24-28): Rollout
- ✅ 100% traffic migrated
- ✅ Cost reduction: **$600/Monat achieved**
- ✅ Performance: **0% degradation**

### Week 4 (Mar 3-7): Optimization
- ✅ A/B Learning active
- ✅ Self-optimization detected
- ✅ Continuous improvement

---

**STATUS:** READY_FOR_EXECUTION  
**NEXT:** Create Task Files + Update TASKS.md  
**OWNER:** Codex (Implementation), Copilot (Deploy), Continue (Analysis)

---

*Intelligent Model Router: Right Model for Right Task at Right Cost*
