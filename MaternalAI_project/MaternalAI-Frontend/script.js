document.addEventListener("DOMContentLoaded", function () {

    loadUsers();
      console.log("SAVE USER CALLED");
    // START BUTTON (Backend test)
    document.getElementById("startBtn").addEventListener("click", function () {
        
        fetch("http://localhost:8080/api/users")
            .then(res => res.json())
            .then(data => {
                console.log(data);
                showToast("Backend Connected Successfully!");
            })
            .catch(err => {
                console.error(err);
                showToast("Backend Connection Failed!");
            });
    });

    // REGISTER USER
    document.getElementById("registerBtn").addEventListener("click", function () {
        saveUser();
    });  
    });
function loadUsers() {
  
   console.log("GET USERS");
   fetch("http://localhost:8080/api/users?_=" + new Date().getTime())
        .then(res => res.json())
        .then(data => {
            console.log(data);

            document.getElementById("totalUsers").innerText = data.length;

            if (data.length === 0) {
                document.getElementById("userTable").innerHTML =
                    "<tr><td colspan='5'>No users found</td></tr>";
                return;
            }

            let rows = "";

            data.forEach(user => {
                rows += `
<tr>
    <td>${user.id}</td>
    <td>${user.name}</td>
    <td>${user.email}</td>
    <td>${user.password}</td>
    <td>
        <button onclick="editUser(${user.id}, '${user.name}', '${user.email}', '${user.password}')">
          Edit
       </button>
        <button onclick="deleteUser(${user.id})">Delete</button>
    </td>
</tr>
`;
            });

            document.getElementById("userTable").innerHTML = rows;
        })
        .catch(err => console.log(err));
}


// ================= SEARCH USERS =================
function searchUsers() {

    let input = document.getElementById("searchInput").value.toLowerCase();
    let rows = document.querySelectorAll("#userTable tr");

    rows.forEach(row => {
        let text = row.innerText.toLowerCase();
        row.style.display = text.includes(input) ? "" : "none";
    });
}


// ================= DELETE USER =================
function deleteUser(id) {

    if (!confirm("Are you sure you want to delete this user?")) return;
    console.log("DELETE USER");
    console.log("ID:", id);

    fetch(`http://localhost:8080/api/users/${id}`, {
        method: "DELETE"
    })
    .then(res => {
        if (!res.ok) throw new Error("Delete failed");
        showToast("User Deleted Successfully");
        loadUsers();
    })
    .catch(err => {
        console.log(err);
        showToast("Delete failed");
    });
}

function editUser(id, name, email, password) {
  document.getElementById("userId").value = id;
  document.getElementById("name").value = name;
  document.getElementById("email").value = email;
  document.getElementById("password").value = password;
  document.getElementById("registerBtn").innerText = "Update";

   showToast("User loaded for editing");
}


// ================= TOAST =================
function showToast(message) {
    const toast = document.getElementById("toast");
    toast.innerText = message;
    toast.className = "toast show";

    setTimeout(() => {
        toast.className = "toast";
    }, 2000);
}


// ================= SPEECH =================
function speak(message) {
    let speech = new SpeechSynthesisUtterance(message);
    speech.lang = "en-US";
    window.speechSynthesis.speak(speech);
}


// ================= VOICE RECOGNITION =================
function startVoice() {

    const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        alert("Speech Recognition not supported");
        return;
    }

    const recognition = new SpeechRecognition();

    recognition.lang = "en-US";
    recognition.continuous = false;

    recognition.onstart = () => {
        console.log("Voice started...");
    };

    recognition.onresult = (event) => {
        let text = event.results[0][0].transcript;
        console.log("Heard:", text);
        processVoiceCommand(text);
    };

    recognition.onerror = (event) => {

    console.log("Voice error:", event.error);

    if (event.error === "network") {
        showToast("Check internet connection and microphone permission");
    }
    else if (event.error === "not-allowed") {
        showToast("Microphone permission denied");
    }
    else {
        showToast("Voice recognition error: " + event.error);
    }
};

    recognition.start();
}


// ================= VOICE COMMAND =================
function processVoiceCommand(text) {

    text = text.toLowerCase();

    let emailMatch = text.match(
        /([a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+\.[a-zA-Z0-9._-]+)/gi
    );

    let email = emailMatch ? emailMatch[0] : "";

    let passwordMatch = text.match(/(password|pass)\s*[:\-]?\s*(\w+)/i);
    let password = passwordMatch ? passwordMatch[2] : "";

    let name = text
        .replace("register", "")
        .replace(email, "")
        .replace(/password\s*[:\-]?\s*\w+/i, "")
        .trim();

    if (!name || !email || !password) {
        alert("Could not understand voice properly");
        return;
    }

    registerFromVoice(name, email, password);
}


// ================= VOICE REGISTER =================
function registerFromVoice(name, email, password) {

    fetch("http://localhost:8080/api/users", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ name, email, password })
    })
    .then(res => {
        if (!res.ok) throw new Error("Register failed");
        return res.json();
    })
    .then(() => {
        showToast("User Registered Successfully");
        speak("User registered successfully");
        loadUsers();
    })
    .catch(err => {
        console.log(err);
        alert("Registration failed");
    });
}
function saveUser() {
    console.log("User ID:", document.getElementById("userId").value);

    let id = document.getElementById("userId").value;

   let name = document.getElementById("name").value.trim();
    let email = document.getElementById("email").value.trim();
    let password = document.getElementById("password").value.trim();

    // Validation
    if (name === "" || email === "" || password === "") {
        showToast("Please fill all fields");
        return;
    }

    let user = {
        name: name,
        email: email,
        password: password
    };


    // 👉 CREATE
    if (id === "") {

        fetch("http://localhost:8080/api/users", {
    method: "POST",
    headers: {
        "Content-Type": "application/json"
    },
    body: JSON.stringify(user)
})
.then(res => {
    if (!res.ok) {
        throw new Error("Registration failed");
    }
    return res.json();
})
.then(() => {
    showToast("User Added Successfully");
    loadUsers();
    clearForm();
})
.catch(err => {
    console.error(err);
    showToast("Email already exists or registration failed");
});

    } 
    // 👉 UPDATE
    else {
      console.log("UPDATE USER");
      console.log("ID:", id);
      console.log("DATA:", user);

        fetch(`http://localhost:8080/api/users/${id}`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(user)
        })
        .then(res => {
            if (!res.ok) throw new Error("Update failed");

            showToast("User Updated Successfully");
            loadUsers();
            clearForm();
        })
        .catch(err => {
            console.log(err);
            showToast("Update failed");
        });
    }
}
function clearForm() {
    document.getElementById("userId").value = "";
    document.getElementById("name").value = "";
    document.getElementById("email").value = "";
    document.getElementById("password").value = "";
}

function registerUser() {
   // your existing POST code
}

function updateUser() {
   // your PUT code
}