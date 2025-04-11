// Main JavaScript file for EduSmartBot

// Wait for document to be ready
document.addEventListener('DOMContentLoaded', function() {
    
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
        if (window.scrollY > 10) {
            navbar.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.1)';
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
}); 