// Main JavaScript file for EduSmartBot

// Wait for document to be ready
document.addEventListener('DOMContentLoaded', function() {
    // Theme: load preference and apply
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const savedTheme = localStorage.getItem('theme');
    const isDark = savedTheme ? savedTheme === 'dark' : prefersDark;
    const root = document.documentElement;
    if (isDark) root.classList.add('dark-theme');

    const themeToggleBtn = document.getElementById('theme-toggle');
    const setThemeIcon = () => {
        if (!themeToggleBtn) return;
        const icon = themeToggleBtn.querySelector('i');
        if (!icon) return;
        if (root.classList.contains('dark-theme')) {
            icon.classList.remove('fa-moon');
            icon.classList.add('fa-sun');
        } else {
            icon.classList.remove('fa-sun');
            icon.classList.add('fa-moon');
        }
    };
    setThemeIcon();

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', function() {
            root.classList.toggle('dark-theme');
            const newTheme = root.classList.contains('dark-theme') ? 'dark' : 'light';
            localStorage.setItem('theme', newTheme);
            setThemeIcon();
        });
    }
    
    // Language selector: persist preference via API then reload
    const langSelect = document.getElementById('language-select');
    if (langSelect) {
        langSelect.addEventListener('change', function() {
            const lang = this.value;
            try {
                fetch('/set-language', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lang })
                }).then(() => {
                    // Reload to apply translations
                    window.location.reload();
                }).catch(() => window.location.reload());
            } catch (_) {
                window.location.reload();
            }
        });
    }
    
    // Add smooth scrolling to all anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href');
            if (targetId === '#') return;
            
            document.querySelector(targetId).scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        });
    });
    
    // Add shadow to navbar on scroll
    window.addEventListener('scroll', function() {
        const navbar = document.querySelector('.navbar');
        if (!navbar) return;
        if (window.scrollY > 10) {
            navbar.style.boxShadow = '0 8px 24px rgba(0,0,0,0.12)';
        } else {
            navbar.style.boxShadow = 'none';
        }
    });
    
    // Add custom file input handler for all file inputs
    document.querySelectorAll('input[type="file"]').forEach(input => {
        const fileLabel = input.nextElementSibling;
        
        if (fileLabel && fileLabel.classList.contains('custom-file-label')) {
            input.addEventListener('change', function() {
                if (this.files && this.files.length > 0) {
                    fileLabel.textContent = this.files[0].name;
                } else {
                    fileLabel.textContent = 'Choose file';
                }
            });
        }
    });
    
    // Initialize tooltips if Bootstrap is available
    if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
        const tooltipTriggerList = [].slice.call(
            document.querySelectorAll('[data-bs-toggle="tooltip"]')
        );
        
        tooltipTriggerList.map(function(tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }
    
    // Generic form validation
    document.querySelectorAll('form.needs-validation').forEach(form => {
        form.addEventListener('submit', event => {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            
            form.classList.add('was-validated');
        }, false);
    });
    
    // Add animation to feature cards on homepage
    const animateOnScroll = () => {
        const featureCards = document.querySelectorAll('.feature-card');
        
        featureCards.forEach(card => {
            const cardPosition = card.getBoundingClientRect();
            
            // If the card is in the viewport
            if (cardPosition.top < window.innerHeight && cardPosition.bottom > 0) {
                card.style.opacity = '1';
                card.style.transform = 'translateY(0)';
            }
        });
    };
    
    // Initial setup for feature cards
    document.querySelectorAll('.feature-card').forEach(card => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(20px)';
        card.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    });
    
    // Run animation on scroll and on load
    window.addEventListener('scroll', animateOnScroll);
    animateOnScroll();

    // Toast utility using Bootstrap 5
    (function initToastHelper() {
        const container = document.getElementById('toast-container');
        function showToast(message, opts) {
            try {
                const options = Object.assign({
                    title: 'EduSmartBot',
                    variant: 'info', // info | success | warning | danger
                    delay: 4000,
                }, opts || {});
                if (!container) return alert(message);
                const toastEl = document.createElement('div');
                const headerBg = {
                    info: 'bg-primary',
                    success: 'bg-success',
                    warning: 'bg-warning text-dark',
                    danger: 'bg-danger'
                }[options.variant] || 'bg-secondary';
                toastEl.className = 'toast align-items-center show overflow-hidden shadow';
                toastEl.setAttribute('role', 'status');
                toastEl.setAttribute('aria-live', 'polite');
                toastEl.setAttribute('aria-atomic', 'true');
                toastEl.innerHTML = `
                    <div class="toast-header ${headerBg} text-white">
                        <strong class="me-auto">${options.title}</strong>
                        <small>now</small>
                        <button type="button" class="btn-close btn-close-white ms-2 mb-1" data-bs-dismiss="toast" aria-label="Close"></button>
                    </div>
                    <div class="toast-body">${message}</div>
                `;
                container.appendChild(toastEl);
                // Use Bootstrap Toast if available for timing, otherwise manual
                if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
                    const t = new bootstrap.Toast(toastEl, { delay: options.delay, autohide: true });
                    t.show();
                    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
                } else {
                    setTimeout(() => toastEl.remove(), options.delay);
                }
            } catch (_) {
                alert(message);
            }
        }
        window.ESBToast = {
            info: (m, o) => showToast(m, Object.assign({}, o, { variant: 'info' })),
            success: (m, o) => showToast(m, Object.assign({}, o, { variant: 'success' })),
            warn: (m, o) => showToast(m, Object.assign({}, o, { variant: 'warning' })),
            error: (m, o) => showToast(m, Object.assign({}, o, { variant: 'danger' }))
        };
    })();
}); 