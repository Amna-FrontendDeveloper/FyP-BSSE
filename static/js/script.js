const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const chatWindow = document.getElementById("chat-window");
const sendButton = document.getElementById("send-button");
const usageIndicator = document.getElementById("usage-indicator");
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

function appendMessage(text, sender) {
    const bubble = document.createElement("div");
    bubble.className = `message ${sender}`;
    bubble.textContent = text;
    chatWindow.appendChild(bubble);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    return bubble;
}

chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const userText = messageInput.value.trim();
    if (!userText) return;

    appendMessage(userText, "user");
    messageInput.value = "";
    messageInput.disabled = true;
    sendButton.disabled = true;

    const loadingBubble = appendMessage("Thinking...", "assistant loading");
    let limitReached = false;

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": csrfToken,
            },
            body: JSON.stringify({ message: userText }),
        });

        const data = await response.json();
        loadingBubble.remove();

        if (!response.ok) {
            if (data.limit_reached) {
                limitReached = true;
                appendMessage(data.premium_info.message, "assistant limit");
                appendMessage(
                    `${data.premium_info.plan_name}: ${data.premium_info.plan_benefit}`,
                    "assistant limit"
                );
                sendButton.textContent = "Limit reached";
            } else {
                appendMessage(data.error || "Something went wrong. Please try again.", "assistant error");
            }
        } else {
            appendMessage(data.reply, "assistant");
        }

        if (data.messages_used_today !== undefined) {
            usageIndicator.textContent = `${data.messages_used_today} / ${data.daily_limit} free messages used today`;
        }
    } catch (error) {
        loadingBubble.remove();
        appendMessage("Unable to reach the server. Please check your connection and try again.", "assistant error");
    } finally {
        if (!limitReached) {
            messageInput.disabled = false;
            sendButton.disabled = false;
            messageInput.focus();
        }
    }
});