// Configuration
const WS_URL = "ws://localhost:8000/ws";

// DOM Elements
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const chatMessages = document.getElementById("chat-messages");
const connectionStatus = document.getElementById("connection-status");
const workflowSteps = {
    research: document.getElementById("workflow-step-1"),
    analysis: document.getElementById("workflow-step-2"),
    writing: document.getElementById("workflow-step-3"),
};

// WebSocket connection
let socket = null;
let reconnectAttempts = 0;
const maxReconnectAttempts = 5;
let reconnectTimeout = null;

// Initialize connection
function initializeWebSocket() {
    clearTimeout(reconnectTimeout);
    updateConnectionStatus("connecting");

    // Close existing socket if it exists
    if (socket) {
        socket.close();
    }

    try {
        socket = new WebSocket(WS_URL);

        // Connection opened
        socket.addEventListener("open", (event) => {
            console.log("WebSocket connection established");
            updateConnectionStatus("connected");
            sendButton.disabled = messageInput.value.trim() === "";
            addSystemMessage("Connecté au système multi-agents.");
            reconnectAttempts = 0; // Reset reconnect attempts on successful connection
        });

        // Listen for messages
        socket.addEventListener("message", (event) => {
            try {
                const data = JSON.parse(event.data);
                processIncomingMessage(data);
            } catch (error) {
                console.error("Error processing message:", error);
                addSystemMessage("Erreur lors du traitement du message reçu.");
            }
        });

        // Connection closed
        socket.addEventListener("close", (event) => {
            console.log(
                "WebSocket connection closed. Code:",
                event.code,
                "Reason:",
                event.reason
            );
            updateConnectionStatus("disconnected");
            sendButton.disabled = true;

            if (reconnectAttempts < maxReconnectAttempts) {
                reconnectAttempts++;
                const reconnectDelay = Math.min(
                    reconnectAttempts * 2000,
                    10000
                ); // Exponential backoff
                addSystemMessage(
                    `Déconnecté du serveur. Tentative de reconnexion dans ${
                        reconnectDelay / 1000
                    } secondes... (${reconnectAttempts}/${maxReconnectAttempts})`
                );

                reconnectTimeout = setTimeout(
                    initializeWebSocket,
                    reconnectDelay
                );
            } else {
                addSystemMessage(
                    "Impossible de se connecter au serveur après plusieurs tentatives. Veuillez recharger la page ou vérifier que le serveur est en ligne."
                );
            }
        });

        // Connection error
        socket.addEventListener("error", (event) => {
            console.error("WebSocket error occurred");
            updateConnectionStatus("disconnected");
        });
    } catch (error) {
        console.error("Error creating WebSocket:", error);
        updateConnectionStatus("disconnected");
        addSystemMessage(
            "Erreur lors de la création de la connexion WebSocket."
        );
    }
}

// Update connection status UI
function updateConnectionStatus(status) {
    const statusIcon = connectionStatus.querySelector(".status-icon");
    const statusText = connectionStatus.querySelector(".status-text");

    statusIcon.className = "status-icon " + status;

    switch (status) {
        case "connected":
            statusText.textContent = "Connecté";
            break;
        case "disconnected":
            statusText.textContent = "Déconnecté";
            break;
        case "connecting":
            statusText.textContent = "Connexion...";
            break;
    }
}

// Send a message to the server
function sendMessage() {
    const message = messageInput.value.trim();

    if (message && socket && socket.readyState === WebSocket.OPEN) {
        try {
            // Add user message to chat
            addUserMessage(message);

            // Send message to server
            socket.send(
                JSON.stringify({
                    message: message,
                })
            );

            // Clear input
            messageInput.value = "";
            sendButton.disabled = true;

            // Update workflow UI
            resetWorkflow();
            updateWorkflowStatus("research", "En cours");
            updateWorkflowStep("research", "active");
        } catch (error) {
            console.error("Error sending message:", error);
            addSystemMessage(
                "Erreur lors de l'envoi du message. Veuillez réessayer."
            );
        }
    } else if (socket && socket.readyState !== WebSocket.OPEN) {
        addSystemMessage(
            "Impossible d'envoyer le message. La connexion est fermée. Tentative de reconnexion..."
        );
        initializeWebSocket();
    }
}

// Process incoming message from server
function processIncomingMessage(data) {
    if (data.sender === "crew") {
        // Extract agent parts from the message
        const message = data.message;

        // Simulate the workflow steps with delays
        setTimeout(() => {
            updateWorkflowStatus("research", "Complété");
            updateWorkflowStep("research", "completed");
            updateWorkflowStatus("analysis", "En cours");
            updateWorkflowStep("analysis", "active");
        }, 1000);

        setTimeout(() => {
            updateWorkflowStatus("analysis", "Complété");
            updateWorkflowStep("analysis", "completed");
            updateWorkflowStatus("writing", "En cours");
            updateWorkflowStep("writing", "active");
        }, 2000);

        setTimeout(() => {
            updateWorkflowStatus("writing", "Complété");
            updateWorkflowStep("writing", "completed");
            addAgentMessage(message);
        }, 3000);
    }
}

// Add a user message to the chat
function addUserMessage(text) {
    const messageDiv = document.createElement("div");
    messageDiv.className = "message user";

    messageDiv.innerHTML = `
        <div class="message-content">
            <p>${escapeHtml(text)}</p>
        </div>
    `;

    chatMessages.appendChild(messageDiv);
    scrollToBottom();
}

// Add an agent message to the chat
function addAgentMessage(text) {
    const messageDiv = document.createElement("div");
    messageDiv.className = "message agent";

    // Parse the message to highlight different agent roles
    const formattedText = text.replace(
        /\[([^\]]+)\]/g,
        "<strong>[$1]</strong>"
    );

    messageDiv.innerHTML = `
        <div class="message-sender">Multi-Agent Crew</div>
        <div class="message-content">${formattedText.replace(
            /\n/g,
            "<br>"
        )}</div>
    `;

    chatMessages.appendChild(messageDiv);
    scrollToBottom();
}

// Add a system message to the chat
function addSystemMessage(text) {
    const messageDiv = document.createElement("div");
    messageDiv.className = "message system";

    messageDiv.innerHTML = `
        <div class="message-content">
            <p>${text}</p>
        </div>
    `;

    chatMessages.appendChild(messageDiv);
    scrollToBottom();
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// Update workflow step status text
function updateWorkflowStatus(step, status) {
    let stepElement;

    switch (step) {
        case "research":
            stepElement = workflowSteps.research;
            break;
        case "analysis":
            stepElement = workflowSteps.analysis;
            break;
        case "writing":
            stepElement = workflowSteps.writing;
            break;
    }

    if (stepElement) {
        const statusElement = stepElement.querySelector(".step-status");
        if (statusElement) {
            statusElement.textContent = status;
        }
    }
}

// Update workflow step visual state
function updateWorkflowStep(step, state) {
    let stepElement;

    switch (step) {
        case "research":
            stepElement = workflowSteps.research;
            break;
        case "analysis":
            stepElement = workflowSteps.analysis;
            break;
        case "writing":
            stepElement = workflowSteps.writing;
            break;
    }

    if (stepElement) {
        // Reset all states
        stepElement.classList.remove("active", "completed");

        // Add new state
        if (state) {
            stepElement.classList.add(state);
        }
    }
}

// Scroll chat to bottom
function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Reset workflow display
function resetWorkflow() {
    updateWorkflowStatus("research", "En attente");
    updateWorkflowStatus("analysis", "En attente");
    updateWorkflowStatus("writing", "En attente");

    updateWorkflowStep("research", "");
    updateWorkflowStep("analysis", "");
    updateWorkflowStep("writing", "");
}

// Manual reconnect button handler
function manualReconnect() {
    addSystemMessage("Tentative de reconnexion manuelle...");
    reconnectAttempts = 0;
    initializeWebSocket();
}

// Event Listeners
sendButton.addEventListener("click", sendMessage);

messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
});

messageInput.addEventListener("input", () => {
    const isEmpty = messageInput.value.trim() === "";
    sendButton.disabled = isEmpty || socket?.readyState !== WebSocket.OPEN;
});

// Initialize application
document.addEventListener("DOMContentLoaded", () => {
    // Initialize the WebSocket connection
    initializeWebSocket();

    // Set initial states
    resetWorkflow();
});

// Ensure clean disconnect when page is unloaded
window.addEventListener("beforeunload", () => {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.close();
    }
});
