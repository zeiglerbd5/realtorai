/**
 * RealtorAI - Client-side JavaScript
 * Minimal JS to enhance HTMX interactions
 */

// HTMX configuration
document.body.addEventListener('htmx:configRequest', (event) => {
    // Add CSRF token if needed
    // event.detail.headers['X-CSRF-Token'] = getCsrfToken();
});

// Handle HTMX errors
document.body.addEventListener('htmx:responseError', (event) => {
    console.error('HTMX error:', event.detail);
    showNotification('An error occurred. Please try again.', 'error');
});

// Handle HTMX after swap - scroll to new content if needed
document.body.addEventListener('htmx:afterSwap', (event) => {
    // If we added a message to chat, scroll to bottom
    if (event.detail.target.id === 'chat-messages') {
        event.detail.target.scrollTop = event.detail.target.scrollHeight;
    }
});

// Handle HTMX before request - add loading state
document.body.addEventListener('htmx:beforeRequest', (event) => {
    const target = event.detail.elt;
    if (target.classList.contains('btn')) {
        target.disabled = true;
    }
});

// Handle HTMX after request - remove loading state
document.body.addEventListener('htmx:afterRequest', (event) => {
    const target = event.detail.elt;
    if (target.classList.contains('btn')) {
        target.disabled = false;
    }
});

// Notification system
function showNotification(message, type = 'info') {
    const container = document.getElementById('notifications') || createNotificationContainer();

    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = `
        <span>${message}</span>
        <button onclick="this.parentElement.remove()">×</button>
    `;

    container.appendChild(notification);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        notification.classList.add('fade-out');
        setTimeout(() => notification.remove(), 300);
    }, 5000);
}

function createNotificationContainer() {
    const container = document.createElement('div');
    container.id = 'notifications';
    container.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 1000;
        display: flex;
        flex-direction: column;
        gap: 10px;
    `;
    document.body.appendChild(container);
    return container;
}

// Keyboard shortcuts
document.addEventListener('keydown', (event) => {
    // Cmd/Ctrl + K to focus chat input
    if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault();
        const chatInput = document.querySelector('.chat-input');
        if (chatInput) {
            chatInput.focus();
        }
    }

    // Escape to close modals/forms
    if (event.key === 'Escape') {
        const editingCard = document.querySelector('.task-card.editing');
        if (editingCard) {
            const cancelBtn = editingCard.querySelector('.btn-secondary');
            if (cancelBtn) {
                cancelBtn.click();
            }
        }
    }
});

// Mark active nav link based on current URL
document.addEventListener('DOMContentLoaded', () => {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-links a');

    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href === currentPath || (href !== '/' && currentPath.startsWith(href))) {
            link.classList.add('active');
        } else if (href === '/' && currentPath === '/') {
            link.classList.add('active');
        }
    });
});

// Time ago helper for task timestamps
function timeAgo(date) {
    const seconds = Math.floor((new Date() - new Date(date)) / 1000);

    const intervals = [
        { label: 'year', seconds: 31536000 },
        { label: 'month', seconds: 2592000 },
        { label: 'day', seconds: 86400 },
        { label: 'hour', seconds: 3600 },
        { label: 'minute', seconds: 60 }
    ];

    for (const interval of intervals) {
        const count = Math.floor(seconds / interval.seconds);
        if (count >= 1) {
            return `${count} ${interval.label}${count > 1 ? 's' : ''} ago`;
        }
    }

    return 'just now';
}

// Auto-resize textareas
document.addEventListener('input', (event) => {
    if (event.target.classList.contains('form-textarea')) {
        event.target.style.height = 'auto';
        event.target.style.height = event.target.scrollHeight + 'px';
    }
});

// Confirm dialogs with custom styling (future enhancement)
// For now, using native browser confirms via hx-confirm

// SSE connection for real-time updates (future enhancement)
// function connectSSE() {
//     const eventSource = new EventSource('/events');
//     eventSource.onmessage = (event) => {
//         const data = JSON.parse(event.data);
//         handleServerEvent(data);
//     };
//     eventSource.onerror = () => {
//         setTimeout(connectSSE, 5000);
//     };
// }

console.log('RealtorAI initialized');
