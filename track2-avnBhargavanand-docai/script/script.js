
function showResult() {
    document.getElementById("inputCard").style.display = "none";
    document.getElementById("resultCard").style.display = "block";

    document.getElementById("diseaseResult").innerText = "ML Disease";
    document.getElementById("confidence").innerText = "ML Confidence";
    document.getElementById("doctorType").innerText = "ML Doctor";

    const precautions = [
        "ML precaution 1",
        "ML precaution 2",
        "ML precaution 3"
    ];

    const precautionsList = document.getElementById("precautions");
    precautionsList.innerHTML = "";
    precautions.forEach(item => {
        const li = document.createElement("li");
        li.innerText = item;
        precautionsList.appendChild(li);
    });
}


function startOver() {
    document.getElementById("resultCard").style.display = "none";
    document.getElementById("inputCard").style.display = "block";
    document.getElementById("symptomsBox").value = "";
}


function findDoctor() {
    const doctor = document.getElementById("doctorType").innerText;

    if (doctor === "--" || doctor === "ML Doctor") {
        alert("after completed ml part");
        return;
    }

    const mapsUrl = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(doctor + " near me")}`;
    window.open(mapsUrl, "_blank");
}

let sessions = {};
let currentSessionId = null;
let finalReport = null;


function startChat() {
    const input = document.getElementById("symptomsBox").value.trim();
    if (!input) return;

    document.getElementById("inputCard").style.display = "none";
    document.getElementById("chatPage").style.display = "block";

    createNewSession(input);

    document.getElementById("inputBox").value = input;
    sendMessage();
}

async function sendMessage() {
    const inputBox = document.getElementById("inputBox");
    const message = inputBox.value.trim();
    if (!message) return;

    const session = sessions[currentSessionId];

    addMessage(message, "user");
    inputBox.value = "";

    const botId = addMessage("...", "bot");

    session.messages.push({ role: "user", content: message });

    try {
        const res = await fetch("http://127.0.0.1:8000/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                history: session.messages
            })
        });

        const data = await res.json();
        const reply = data.reply;

        document.getElementById(botId).innerHTML = formatText(reply);

        session.messages.push({ role: "assistant", content: reply });

        if (reply.toLowerCase().includes("generate your report")) {
            enableReportMode(reply);
        }

    } catch {
        document.getElementById(botId).innerText = "❌ Server Error";
    }
}


function formatText(text) {
    if (!text) return "";

    text = text.replace(/\r\n/g, "\n");

    text = text.replace(/(\d+\.)\s*/g, "\n$1 ");

    text = text.replace(/\n{2,}/g, "\n\n");

    return text.trim().replace(/\n/g, "<br>");
}

function addMessage(text, sender) {
    const chat = document.getElementById("chatContainer");

    const row = document.createElement("div");
    row.className = "chat-row " + (sender === "user" ? "user-row" : "bot-row");

    const bubble = document.createElement("div");
    bubble.className = sender === "user" ? "user-msg" : "bot-msg";
    bubble.innerHTML = text;

    const avatar = document.createElement("div");
    avatar.className = "avatar " + (sender === "user" ? "user-avatar" : "bot-avatar");
    avatar.innerText = sender === "user" ? "🧑" : "⚕️";

    if (sender === "user") {
        row.appendChild(bubble);
        row.appendChild(avatar);
    } else {
        row.appendChild(avatar);
        row.appendChild(bubble);
    }

    const id = "msg-" + Date.now();
    bubble.id = id;

    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;

    return id;
}


function createNewSession(title = "New Session") {
    const id = "session-" + Date.now();

    sessions[id] = {
        messages: [],
        title: title.length > 25 ? title.substring(0, 25) + "..." : title
    };

    currentSessionId = id;

    document.getElementById("chatContainer").innerHTML = "";

    renderSessions();
}


function renderSessions() {
    const list = document.getElementById("historyList");
    list.innerHTML = "";

    Object.keys(sessions).forEach(id => {
        const item = document.createElement("div");

        item.className = "history-item";
        if (id === currentSessionId) item.classList.add("active-session");

        item.innerText = sessions[id].title;

        item.onclick = () => loadSession(id);

        list.appendChild(item);
    });
}


function loadSession(id) {
    currentSessionId = id;

    const chat = document.getElementById("chatContainer");
    chat.innerHTML = "";

    sessions[id].messages.forEach(msg => {
        addMessage(msg.content, msg.role === "user" ? "user" : "bot");
    });

    renderSessions();
}


async function enableReportMode() {
    const session = sessions[currentSessionId];

    try {
        const res = await fetch("http://127.0.0.1:8000/report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                history: session.messages
            })
        });

        const data = await res.json();

        finalReport = data.report;

        addMessage("✅ Report Generated. You can download it now.", "bot");

        document.querySelector(".report-btn").classList.add("enabled");

    } catch {
        addMessage("❌ Failed to generate report", "bot");
    }
}


function generatePDF() {
    if (!finalReport) {
        alert("⚠️ Report not generated yet!");
        return;
    }

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF();

    // Strip markdown formatting (**, ##, etc.) since jsPDF renders raw text only
    function stripMarkdown(text) {
        return text
            .replace(/\*\*(.*?)\*\*/g, "$1")   // **bold** -> bold
            .replace(/\*(.*?)\*/g, "$1")       // *italic* -> italic
            .replace(/#{1,6}\s?/g, "")         // ## headers -> plain text
            .trim();
    }

    let y = 15;

    // Header bar - plain text only, no emoji (jsPDF default font can't render them)
    doc.setFillColor(30, 60, 150);
    doc.rect(0, 0, 210, 22, "F");

    doc.setTextColor(255, 255, 255);
    doc.setFontSize(18);
    doc.setFont(undefined, "bold");
    doc.text("Doc.AI", 12, 14);

    doc.setFontSize(10);
    doc.setFont(undefined, "normal");
    doc.text("Medical Report", 165, 14);

    y = 32;

    // Patient info box
    doc.setDrawColor(200);
    doc.setFillColor(248, 250, 255);
    doc.rect(10, y, 190, 20, "FD");

    doc.setTextColor(0);
    doc.setFontSize(11);

    const date = new Date().toLocaleString();
    doc.text(`Patient Name: Not Specified`, 15, y + 8);
    doc.text(`Date: ${date}`, 15, y + 15);

    y += 30;

    function addSection(title, content) {
        if (!content.trim()) return;

        if (y > 260) {
            doc.addPage();
            y = 20;
        }

        // Section header bar
        doc.setFillColor(230, 235, 255);
        doc.rect(10, y, 190, 9, "F");

        doc.setFontSize(12);
        doc.setFont(undefined, "bold");
        doc.setTextColor(30, 60, 150);
        doc.text(title, 13, y + 6.5);

        y += 13;

        // Section body
        doc.setFontSize(10);
        doc.setFont(undefined, "normal");
        doc.setTextColor(20, 20, 20);

        const cleanContent = stripMarkdown(content);
        const lines = doc.splitTextToSize(cleanContent, 184);

        // Page-break check for long sections
        for (const line of lines) {
            if (y > 275) {
                doc.addPage();
                y = 20;
            }
            doc.text(line, 13, y);
            y += 5.5;
        }

        y += 8;
    }

    const sections = {
        "Possible Condition": "",
        "Reasoning": "",
        "Precautions": "",
        "Recommended Doctor": ""
    };

    let current = "";

    finalReport.split("\n").forEach(line => {
        const lower = line.toLowerCase();
        if (lower.includes("possible condition")) current = "Possible Condition";
        else if (lower.includes("reasoning")) current = "Reasoning";
        else if (lower.includes("precaution")) current = "Precautions";
        else if (lower.includes("recommended doctor") || lower.includes("recommended follow")) current = "Recommended Doctor";

        if (current) sections[current] += line + "\n";
    });

    for (let key in sections) {
        addSection(key, sections[key]);
    }

    // Footer disclaimer
    if (y > 275) {
        doc.addPage();
        y = 20;
    }
    doc.setFontSize(8);
    doc.setTextColor(140);
    doc.text(
        "Disclaimer: AI-generated report. Consult a licensed medical professional.",
        10,
        290
    );

    doc.save("DocAI_Professional_Report.pdf");
}