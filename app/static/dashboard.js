/**
 * Jarvis Remediation Dashboard - JavaScript
 * Phase 16.3B Implementation + Tier-2 Improvements
 *
 * Tier-2 Enhancements:
 * - Retry logic with exponential backoff
 * - Client-side rate limiting
 * - Request caching
 * - Debounced refresh
 * - Better error handling
 * - Loading states
 * - Accessibility improvements
 */

// Configuration
const CONFIG = {
    refreshInterval: 15000,         // 15 seconds for pending
    metricsRefreshInterval: 30000,  // 30 seconds for metrics
    apiBaseUrl: '',                 // Same origin
    maxActivityItems: 10,
    // Tier-2: Retry configuration
    maxRetries: 3,
    retryBaseDelay: 1000,           // 1 second base delay
    retryMaxDelay: 10000,           // 10 seconds max delay
    // Tier-2: Rate limiting
    rateLimitWindow: 60000,         // 1 minute window
    rateLimitMaxRequests: 30,       // Max 30 requests per minute
    // Tier-2: Cache TTL
    cacheTTL: 5000                  // 5 seconds cache
};

// State
let state = {
    pending: [],
    recent: [],
    stats: null,
    uncertainty: null,
    lastUpdate: null,
    isConnected: true,
    modalAction: null,
    modalRemediationId: null,
    // Tier-2: Extended state
    isLoading: false,
    requestCount: 0,
    requestWindowStart: Date.now(),
    cache: new Map(),
    lastError: null
};

// DOM Elements
const elements = {
    pendingList: document.getElementById('pending-list'),
    pendingCount: document.getElementById('pending-count'),
    emptyPending: document.getElementById('empty-pending'),
    activityList: document.getElementById('activity-list'),
    activityCount: document.getElementById('activity-count'),
    emptyActivity: document.getElementById('empty-activity'),
    playbookGrid: document.getElementById('playbook-grid'),
    emptyPlaybooks: document.getElementById('empty-playbooks'),
    lastUpdate: document.getElementById('last-update'),
    connectionStatus: document.getElementById('connection-status'),
    refreshBtn: document.getElementById('refresh-btn'),
    // Metrics
    metricPending: document.getElementById('metric-pending'),
    metricApproved: document.getElementById('metric-approved'),
    metricRejected: document.getElementById('metric-rejected'),
    metricSuccessRate: document.getElementById('metric-success-rate'),
    metricAvgLatency: document.getElementById('metric-avg-latency'),
    // Uncertainty
    uncertaintyLevel: document.getElementById('uncertainty-level'),
    uncertaintyScore: document.getElementById('uncertainty-score'),
    uncertaintySourceQuality: document.getElementById('uncertainty-source-quality'),
    uncertaintyReasons: document.getElementById('uncertainty-reasons'),
    uncertaintySuggestions: document.getElementById('uncertainty-suggestions'),
    uncertaintyUpdated: document.getElementById('uncertainty-updated'),
    uncertaintyQuery: document.getElementById('uncertainty-query'),
    // Modal
    modal: document.getElementById('approval-modal'),
    modalTitle: document.getElementById('modal-title'),
    modalMessage: document.getElementById('modal-message'),
    modalClose: document.getElementById('modal-close'),
    modalCancel: document.getElementById('modal-cancel'),
    modalConfirm: document.getElementById('modal-confirm'),
    actionReason: document.getElementById('action-reason'),
    // Toast
    toastContainer: document.getElementById('toast-container')
};

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

function formatTimeAgo(dateString) {
    if (!dateString) return '--';
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return '--';

    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function formatDuration(seconds) {
    if (!seconds || seconds < 0) return '--';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
    return `${Math.round(seconds / 86400)}d`;
}

function generateUUID() {
    if (crypto.randomUUID) {
        return crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// Tier-2: Debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Tier-2: Sleep function for retry delays
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Tier-2: Escape HTML to prevent XSS
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =============================================================================
// TIER-2: RATE LIMITING
// =============================================================================

function checkRateLimit() {
    const now = Date.now();

    // Reset window if expired
    if (now - state.requestWindowStart > CONFIG.rateLimitWindow) {
        state.requestCount = 0;
        state.requestWindowStart = now;
    }

    // Check if under limit
    if (state.requestCount >= CONFIG.rateLimitMaxRequests) {
        const waitTime = Math.ceil((CONFIG.rateLimitWindow - (now - state.requestWindowStart)) / 1000);
        throw new Error(`Rate limited. Please wait ${waitTime}s`);
    }

    state.requestCount++;
    return true;
}

// =============================================================================
// TIER-2: CACHING
// =============================================================================

function getCachedData(key) {
    const cached = state.cache.get(key);
    if (!cached) return null;

    if (Date.now() - cached.timestamp > CONFIG.cacheTTL) {
        state.cache.delete(key);
        return null;
    }

    return cached.data;
}

function setCachedData(key, data) {
    state.cache.set(key, {
        data,
        timestamp: Date.now()
    });
}

// =============================================================================
// TOAST NOTIFICATIONS
// =============================================================================

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'polite');
    toast.textContent = message;
    elements.toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// =============================================================================
// TIER-2: API FUNCTIONS WITH RETRY LOGIC
// =============================================================================

async function fetchAPI(endpoint, options = {}, useCache = true) {
    // Check cache for GET requests
    const cacheKey = `${options.method || 'GET'}:${endpoint}`;
    if (useCache && (!options.method || options.method === 'GET')) {
        const cached = getCachedData(cacheKey);
        if (cached) {
            console.log(`Cache hit: ${endpoint}`);
            return cached;
        }
    }

    // Rate limiting
    try {
        checkRateLimit();
    } catch (error) {
        showToast(error.message, 'error');
        throw error;
    }

    let lastError;

    for (let attempt = 0; attempt < CONFIG.maxRetries; attempt++) {
        try {
            const response = await fetch(`${CONFIG.apiBaseUrl}${endpoint}`, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(error.detail || error.error || `HTTP ${response.status}`);
            }

            const data = await response.json();

            // Cache successful GET responses
            if (!options.method || options.method === 'GET') {
                setCachedData(cacheKey, data);
            }

            setConnectionStatus(true);
            state.lastError = null;
            return data;

        } catch (error) {
            lastError = error;
            console.error(`API Error (${endpoint}), attempt ${attempt + 1}:`, error);

            // Don't retry for client errors (4xx) except 429 (rate limit)
            if (error.message.includes('HTTP 4') && !error.message.includes('HTTP 429')) {
                break;
            }

            // Don't retry for rate limit errors from our own limiting
            if (error.message.includes('Rate limited')) {
                break;
            }

            // Calculate delay with exponential backoff + jitter
            if (attempt < CONFIG.maxRetries - 1) {
                const delay = Math.min(
                    CONFIG.retryBaseDelay * Math.pow(2, attempt) + Math.random() * 1000,
                    CONFIG.retryMaxDelay
                );
                console.log(`Retrying in ${Math.round(delay)}ms...`);
                await sleep(delay);
            }
        }
    }

    // All retries failed
    if (lastError.message.includes('fetch') || lastError.message.includes('network')) {
        setConnectionStatus(false);
    }
    state.lastError = lastError.message;
    throw lastError;
}

// =============================================================================
// DATA FETCHING FUNCTIONS
// =============================================================================

async function fetchPending() {
    setLoadingState(true, 'pending');
    try {
        const data = await fetchAPI('/remediate/pending');
        state.pending = data.pending_approvals || [];
        renderPending();
        updateLastUpdate();
    } catch (error) {
        // Don't show toast for every refresh failure, just update UI
        console.error('Failed to fetch pending:', error);
    } finally {
        setLoadingState(false, 'pending');
    }
}

async function fetchRecent() {
    setLoadingState(true, 'activity');
    try {
        const data = await fetchAPI('/remediate/recent');
        state.recent = data.remediations || [];
        renderActivity();
    } catch (error) {
        console.error('Failed to fetch recent:', error);
    } finally {
        setLoadingState(false, 'activity');
    }
}

async function fetchStats() {
    setLoadingState(true, 'metrics');
    try {
        const data = await fetchAPI('/remediate/stats');
        state.stats = data;
        renderMetrics();
        renderPlaybooks();
    } catch (error) {
        console.error('Failed to fetch stats:', error);
    } finally {
        setLoadingState(false, 'metrics');
    }
}

async function fetchUncertainty() {
    try {
        const data = await fetchAPI('/agent/uncertainty/latest');
        state.uncertainty = data || null;
        renderUncertainty();
    } catch (error) {
        console.error('Failed to fetch uncertainty snapshot:', error);
    }
}

async function approveRemediation(remediationId, reason) {
    setLoadingState(true, 'action');
    try {
        await fetchAPI(`/dashboard/api/approve/${remediationId}`, {
            method: 'POST',
            body: JSON.stringify({
                user_id: 'dashboard_user',
                reason: reason || 'Approved via dashboard',
                idempotency_key: generateUUID()
            })
        }, false); // Don't cache POST requests

        showToast('Remediation approved successfully', 'success');

        // Clear cache to force fresh data
        state.cache.clear();
        await refreshAll();
    } catch (error) {
        showToast(`Approval failed: ${error.message}`, 'error');
    } finally {
        setLoadingState(false, 'action');
    }
}

async function rejectRemediation(remediationId, reason) {
    setLoadingState(true, 'action');
    try {
        await fetchAPI(`/dashboard/api/reject/${remediationId}`, {
            method: 'POST',
            body: JSON.stringify({
                user_id: 'dashboard_user',
                reason: reason || 'Rejected via dashboard',
                idempotency_key: generateUUID()
            })
        }, false);

        showToast('Remediation rejected successfully', 'success');

        state.cache.clear();
        await refreshAll();
    } catch (error) {
        showToast(`Rejection failed: ${error.message}`, 'error');
    } finally {
        setLoadingState(false, 'action');
    }
}

// =============================================================================
// TIER-2: LOADING STATES
// =============================================================================

function setLoadingState(isLoading, section = 'all') {
    state.isLoading = isLoading;

    // Update refresh button
    if (elements.refreshBtn) {
        elements.refreshBtn.disabled = isLoading;
        elements.refreshBtn.textContent = isLoading ? 'Loading...' : 'Refresh';
        elements.refreshBtn.setAttribute('aria-busy', isLoading);
    }

    // Add loading class to specific sections
    const sectionMap = {
        'pending': elements.pendingList,
        'activity': elements.activityList,
        'metrics': document.querySelector('.metrics-section'),
        'all': document.body
    };

    const element = sectionMap[section];
    if (element) {
        element.classList.toggle('loading', isLoading);
    }
}

// =============================================================================
// RENDER FUNCTIONS
// =============================================================================

function renderPending() {
    const count = state.pending.length;
    elements.pendingCount.textContent = count;
    elements.metricPending.textContent = count;

    // Update ARIA
    elements.pendingCount.setAttribute('aria-label', `${count} pending approvals`);

    if (count === 0) {
        elements.emptyPending.style.display = 'block';
        elements.pendingList.innerHTML = '';
        elements.pendingList.appendChild(elements.emptyPending);
        return;
    }

    elements.emptyPending.style.display = 'none';
    elements.pendingList.innerHTML = state.pending.map((item, index) => `
        <div class="pending-card ${item.tier >= 3 ? 'tier-3' : ''}"
             role="article"
             aria-labelledby="pending-${index}-title">
            <div class="pending-card-header">
                <span class="pending-card-id" id="pending-${index}-title">${escapeHtml(item.remediation_id) || 'N/A'}</span>
                <span class="badge ${item.tier >= 3 ? 'tier-3' : 'tier-2'}"
                      aria-label="Priority tier ${item.tier || 'unknown'}">
                    Tier ${item.tier || '?'}
                </span>
            </div>
            <div class="pending-card-meta">
                <span class="playbook">${escapeHtml(item.playbook_type) || 'unknown'}</span>
                <span>Triggered: <time datetime="${item.triggered_at || item.created_at}">${formatTimeAgo(item.triggered_at || item.created_at)}</time></span>
            </div>
            ${item.trigger_reason ? `
                <div class="pending-card-reason">
                    ${escapeHtml(item.trigger_reason)}
                </div>
            ` : ''}
            <div class="pending-card-actions">
                <button class="btn btn-reject btn-sm"
                        onclick="openModal('reject', '${escapeHtml(item.remediation_id)}')"
                        aria-label="Reject remediation ${escapeHtml(item.remediation_id)}">
                    <span aria-hidden="true">✗</span> Reject
                </button>
                <button class="btn btn-approve btn-sm"
                        onclick="openModal('approve', '${escapeHtml(item.remediation_id)}')"
                        aria-label="Approve remediation ${escapeHtml(item.remediation_id)}">
                    <span aria-hidden="true">✓</span> Approve
                </button>
            </div>
        </div>
    `).join('');
}

function renderActivity() {
    const items = state.recent.slice(0, CONFIG.maxActivityItems);
    elements.activityCount.textContent = state.recent.length;
    elements.activityCount.setAttribute('aria-label', `${state.recent.length} recent activities`);

    if (items.length === 0) {
        elements.emptyActivity.style.display = 'block';
        elements.activityList.innerHTML = '';
        elements.activityList.appendChild(elements.emptyActivity);
        return;
    }

    elements.emptyActivity.style.display = 'none';
    elements.activityList.innerHTML = items.map(item => {
        const status = item.approval_status || item.execution_status || 'pending';
        const icon = getStatusIcon(status);
        const statusLabel = getStatusLabel(status);
        return `
            <div class="activity-item" role="listitem">
                <div class="activity-icon ${status}"
                     aria-label="${statusLabel}"
                     title="${statusLabel}">
                    ${icon}
                </div>
                <div class="activity-content">
                    <div class="activity-id">${escapeHtml(item.remediation_id) || 'N/A'}</div>
                    <div class="activity-detail">${escapeHtml(item.playbook_type) || 'unknown'} - ${statusLabel}</div>
                </div>
                <time class="activity-time" datetime="${item.approved_at || item.created_at}">
                    ${formatTimeAgo(item.approved_at || item.created_at)}
                </time>
            </div>
        `;
    }).join('');
}

function getStatusIcon(status) {
    switch (status) {
        case 'approved': return '✓';
        case 'rejected': return '✗';
        case 'executed':
        case 'completed': return '▶';
        case 'failed': return '!';
        default: return '○';
    }
}

function getStatusLabel(status) {
    switch (status) {
        case 'approved': return 'Approved';
        case 'rejected': return 'Rejected';
        case 'executed': return 'Executed';
        case 'completed': return 'Completed';
        case 'failed': return 'Failed';
        case 'pending': return 'Pending';
        default: return status || 'Unknown';
    }
}

function renderMetrics() {
    if (!state.stats) return;

    const stats = state.stats;

    // Count approved/rejected from recent
    let approved = 0;
    let rejected = 0;
    state.recent.forEach(item => {
        if (item.approval_status === 'approved') approved++;
        if (item.approval_status === 'rejected') rejected++;
    });

    elements.metricApproved.textContent = approved;
    elements.metricRejected.textContent = rejected;

    // ARIA labels for metrics
    elements.metricApproved.setAttribute('aria-label', `${approved} approved in last 7 days`);
    elements.metricRejected.setAttribute('aria-label', `${rejected} rejected in last 7 days`);

    // Success rate
    const successRate = stats.success_rate !== undefined
        ? `${Math.round(stats.success_rate * 100)}%`
        : '--';
    elements.metricSuccessRate.textContent = successRate;
    elements.metricSuccessRate.setAttribute('aria-label', `Success rate: ${successRate}`);

    // Average latency
    const avgLatency = stats.avg_approval_latency_seconds
        ? formatDuration(stats.avg_approval_latency_seconds)
        : '--';
    elements.metricAvgLatency.textContent = avgLatency;
    elements.metricAvgLatency.setAttribute('aria-label', `Average approval time: ${avgLatency}`);
}

function renderPlaybooks() {
    if (!state.stats || !state.stats.playbook_stats || state.stats.playbook_stats.length === 0) {
        elements.emptyPlaybooks.style.display = 'block';
        return;
    }

    elements.emptyPlaybooks.style.display = 'none';
    elements.playbookGrid.innerHTML = state.stats.playbook_stats.map(pb => `
        <div class="playbook-card" role="article" aria-label="Playbook: ${escapeHtml(pb.playbook_type)}">
            <div class="playbook-name">${escapeHtml(pb.playbook_type) || 'unknown'}</div>
            <div class="playbook-stats">
                <div class="playbook-stat">
                    <span class="playbook-stat-label">Total</span>
                    <span class="playbook-stat-value">${pb.total_attempts || 0}</span>
                </div>
                <div class="playbook-stat">
                    <span class="playbook-stat-label">Success</span>
                    <span class="playbook-stat-value success">${pb.successful || 0}</span>
                </div>
                <div class="playbook-stat">
                    <span class="playbook-stat-label">Rate</span>
                    <span class="playbook-stat-value">${pb.success_rate ? `${Math.round(pb.success_rate)}%` : '--'}</span>
                </div>
            </div>
        </div>
    `).join('');
}

function renderUncertainty() {
    const data = state.uncertainty || {};
    const score = data.confidence_score;
    const level = data.confidence_level || 'unknown';
    const sourceQuality = data.source_quality || 'none';
    const reasons = data.uncertainty_reasons || [];
    const suggestions = data.suggested_alternatives || [];
    const updatedAt = data.updated_at ? new Date(data.updated_at) : null;

    const scoreText = typeof score === 'number' ? `${Math.round(score * 100)}%` : '--';
    elements.uncertaintyScore.textContent = scoreText;
    elements.uncertaintySourceQuality.textContent = sourceQuality;
    elements.uncertaintyReasons.textContent = reasons.length ? reasons.join(', ') : '--';
    elements.uncertaintySuggestions.textContent = suggestions.length ? suggestions.join(' · ') : '--';
    elements.uncertaintyUpdated.textContent = `Last update: ${updatedAt ? updatedAt.toLocaleTimeString() : '--'}`;
    elements.uncertaintyQuery.textContent = `Query: ${data.query_preview || '--'}`;

    const badge = elements.uncertaintyLevel;
    badge.textContent = level;
    badge.classList.remove('uncertainty-low', 'uncertainty-medium', 'uncertainty-high');
    if (typeof score === 'number') {
        if (score < 0.5) {
            badge.classList.add('uncertainty-low');
        } else if (score < 0.7) {
            badge.classList.add('uncertainty-medium');
        } else {
            badge.classList.add('uncertainty-high');
        }
    }
}

// =============================================================================
// UI FUNCTIONS
// =============================================================================

function setConnectionStatus(connected) {
    state.isConnected = connected;
    elements.connectionStatus.textContent = connected ? 'Connected' : 'Disconnected';
    elements.connectionStatus.classList.toggle('disconnected', !connected);
    elements.connectionStatus.setAttribute('aria-label',
        connected ? 'Connection status: Connected' : 'Connection status: Disconnected');
}

function updateLastUpdate() {
    state.lastUpdate = new Date();
    const timeString = state.lastUpdate.toLocaleTimeString();
    elements.lastUpdate.textContent = `Last update: ${timeString}`;
    elements.lastUpdate.setAttribute('aria-label', `Data last updated at ${timeString}`);
}

function openModal(action, remediationId) {
    state.modalAction = action;
    state.modalRemediationId = remediationId;

    const isApprove = action === 'approve';
    elements.modalTitle.textContent = isApprove ? 'Approve Remediation' : 'Reject Remediation';
    elements.modalMessage.textContent = `Are you sure you want to ${action} remediation ${remediationId}?`;
    elements.modalConfirm.textContent = isApprove ? 'Approve' : 'Reject';
    elements.modalConfirm.className = `btn ${isApprove ? 'btn-approve' : 'btn-reject'}`;
    elements.actionReason.value = '';
    elements.actionReason.placeholder = isApprove
        ? 'Optional: Enter approval reason...'
        : 'Required: Enter rejection reason...';
    elements.actionReason.required = !isApprove;

    elements.modal.classList.add('active');
    elements.modal.setAttribute('aria-hidden', 'false');

    // Focus management for accessibility
    elements.actionReason.focus();

    // Trap focus in modal
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    elements.modal.classList.remove('active');
    elements.modal.setAttribute('aria-hidden', 'true');
    state.modalAction = null;
    state.modalRemediationId = null;
    document.body.style.overflow = '';

    // Return focus to trigger element
    elements.refreshBtn.focus();
}

async function confirmModal() {
    const reason = elements.actionReason.value.trim();

    // Validate rejection reason
    if (state.modalAction === 'reject' && reason.length < 3) {
        showToast('Please provide a reason for rejection (min 3 characters)', 'error');
        elements.actionReason.focus();
        return;
    }

    // Disable confirm button during action
    elements.modalConfirm.disabled = true;
    elements.modalConfirm.textContent = 'Processing...';

    try {
        if (state.modalAction === 'approve') {
            await approveRemediation(state.modalRemediationId, reason);
        } else if (state.modalAction === 'reject') {
            await rejectRemediation(state.modalRemediationId, reason);
        }
        closeModal();
    } finally {
        elements.modalConfirm.disabled = false;
        elements.modalConfirm.textContent = state.modalAction === 'approve' ? 'Approve' : 'Reject';
    }
}

// =============================================================================
// REFRESH FUNCTIONS (TIER-2: DEBOUNCED)
// =============================================================================

async function refreshAll() {
    if (state.isLoading) {
        console.log('Refresh already in progress, skipping...');
        return;
    }

    await Promise.all([
        fetchPending(),
        fetchRecent(),
        fetchStats(),
        fetchUncertainty()
    ]);
}

// Tier-2: Debounced refresh to prevent rapid clicking
const debouncedRefresh = debounce(() => {
    showToast('Refreshing...', 'info');
    refreshAll();
}, 500);

// =============================================================================
// EVENT LISTENERS
// =============================================================================

elements.refreshBtn.addEventListener('click', debouncedRefresh);

elements.modalClose.addEventListener('click', closeModal);
elements.modalCancel.addEventListener('click', closeModal);
elements.modalConfirm.addEventListener('click', confirmModal);

// Close modal on backdrop click
elements.modal.addEventListener('click', (e) => {
    if (e.target === elements.modal) {
        closeModal();
    }
});

// Keyboard shortcuts with accessibility
document.addEventListener('keydown', (e) => {
    // Escape to close modal
    if (e.key === 'Escape' && elements.modal.classList.contains('active')) {
        closeModal();
    }

    // Enter to confirm in modal
    if (e.key === 'Enter' && elements.modal.classList.contains('active') && e.target !== elements.actionReason) {
        e.preventDefault();
        confirmModal();
    }

    // 'r' to refresh (when not in modal or input)
    if (e.key === 'r' && !elements.modal.classList.contains('active') &&
        !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        debouncedRefresh();
    }
});

// Focus trap for modal
elements.modal.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
        const focusableElements = elements.modal.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey && document.activeElement === firstElement) {
            e.preventDefault();
            lastElement.focus();
        } else if (!e.shiftKey && document.activeElement === lastElement) {
            e.preventDefault();
            firstElement.focus();
        }
    }
});

// =============================================================================
// INITIALIZATION
// =============================================================================

async function init() {
    console.log('Jarvis Dashboard initializing (Tier-2 Enhanced)...');

    // Set initial ARIA states
    elements.modal.setAttribute('aria-hidden', 'true');
    elements.modal.setAttribute('role', 'dialog');
    elements.modal.setAttribute('aria-modal', 'true');
    elements.modal.setAttribute('aria-labelledby', 'modal-title');

    // Initial fetch
    await refreshAll();

    // Set up auto-refresh with staggered intervals to reduce server load
    setInterval(fetchPending, CONFIG.refreshInterval);
    setInterval(async () => {
        await fetchRecent();
        // Small delay between requests
        await sleep(500);
        await fetchStats();
    }, CONFIG.metricsRefreshInterval);
    setInterval(fetchUncertainty, CONFIG.metricsRefreshInterval);

    console.log('Dashboard initialized successfully');

    // Log configuration for debugging
    console.log('Config:', {
        refreshInterval: CONFIG.refreshInterval,
        maxRetries: CONFIG.maxRetries,
        rateLimitMaxRequests: CONFIG.rateLimitMaxRequests
    });
}

// Start
init();
