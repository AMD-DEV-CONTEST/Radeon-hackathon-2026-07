function initChatApp() {
    const chatWindow = document.getElementById('chat-window');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');

    if (!chatWindow || !userInput || !sendBtn) {
        console.error("Chat elements not found in DOM!");
        return;
    }

    // Create typing indicator element
    const typingIndicator = document.createElement('div');
    typingIndicator.className = 'typing-indicator';
    typingIndicator.innerHTML = '<span></span><span></span><span></span>';

    function addMessage(text, isUser = false) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${isUser ? 'user-message' : 'system-message'}`;
        msgDiv.innerHTML = text.replace(/\n/g, '<br>');
        
        chatWindow.appendChild(msgDiv);
        scrollToBottom();
    }

    function showTyping() {
        chatWindow.appendChild(typingIndicator);
        typingIndicator.style.display = 'flex';
        scrollToBottom();
    }

    function hideTyping() {
        if (typingIndicator.parentNode) {
            typingIndicator.parentNode.removeChild(typingIndicator);
        }
        typingIndicator.style.display = 'none';
    }

    function scrollToBottom() {
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;

        userInput.value = '';
        addMessage(text, true);
        showTyping();

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ message: text })
            });

            const data = await response.json();
            hideTyping();
            if (data.response) {
                addMessage(data.response);
            } else {
                addMessage("Error: Could not parse response from server.");
            }
        } catch (error) {
            hideTyping();
            addMessage("Network Error: Could not connect to the backend.");
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    console.log("SentinelDesk Web Chat initialized successfully.");
}

// Initialize immediately if DOM is already ready, otherwise wait for DOMContentLoaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initChatApp);
} else {
    initChatApp();
}
