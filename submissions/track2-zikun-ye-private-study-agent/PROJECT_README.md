# Private Study Agent

## Project Overview

Private Study Agent is a beginner-friendly AI study assistant for PDF learning materials. It extracts text from uploaded PDF documents with PyMuPDF and uses an AMD Radeon Cloud OpenAI-compatible shared model API to generate grounded study support.

Core capabilities include:

- Upload PDF documents
- Ask questions based on PDF content
- Generate PDF summaries
- Generate a 3-day study plan

## Features

1. **Grounded Question Answering** — answers questions using the extracted PDF content and clearly indicates when the document does not provide enough information.
2. **PDF Summary Generation** — produces a structured overview, key ideas, and important takeaways.
3. **3-Day Study Plan Generation** — creates a practical three-day plan with daily topics, activities, and learning goals.

## Tech Stack

- Python
- Streamlit
- PyMuPDF
- Requests
- python-dotenv
- AMD Radeon Cloud OpenAI-compatible API

## Project Structure

```text
private-study-agent-amd/
|-- app.py
|-- requirements.txt
|-- .env.example
|-- .gitignore
|-- README.md
|-- assets/
`-- docs/
    `-- project-specification.md
```

The detailed project specification is available in [`docs/project-specification.md`](docs/project-specification.md).

## Demo Screenshots

### 1. PDF Upload

![PDF Upload](assets/pdf-upload.png)

### 2. Grounded Question Answering

![Grounded Question Answering](assets/question-answering.png)

### 3. Unanswered Question Handling

![Unanswered Question Handling](assets/unanswered-question.png)

### 4. PDF Summary

![PDF Summary](assets/pdf-summary.png)

### 5. 3-Day Study Plan Part 1

![3-Day Study Plan Part 1](assets/study-plan-1.png)

### 6. 3-Day Study Plan Part 2

![3-Day Study Plan Part 2](assets/study-plan-2.png)

### 7. 3-Day Study Plan Part 3

![3-Day Study Plan Part 3](assets/study-plan-3.png)

The three study-plan images are consecutive screenshots of the same long result.

## AMD Radeon Cloud Deployment

The application was deployed and tested on AMD Radeon Cloud.

Deployment verification included:

- Creating a Radeon Cloud instance
- Uploading the project files
- Installing the required dependencies
- Launching the Streamlit service
- Checking the backend health endpoint

### Deployment Environment

- AMD Radeon Cloud instance
- Python environment
- Streamlit application
- PyMuPDF for PDF text extraction
- AMD Radeon Cloud OpenAI-compatible shared model API

### Deployment Steps

The following procedure was verified with a Windows computer connecting to an AMD Radeon Cloud instance through an SSH tunnel. The SSH host, port, and instance ID are temporary values supplied by Radeon Cloud; use the values shown for your own instance.

#### 1. Configure SSH access

Generate a dedicated SSH key on your Windows computer:

```powershell
ssh-keygen -t ed25519 -C "radeon-cloud" -f "$env:USERPROFILE\.ssh\radeon_cloud_ed25519"
```

Copy the public key to the Windows clipboard:

```powershell
Get-Content "$env:USERPROFILE\.ssh\radeon_cloud_ed25519.pub" | Set-Clipboard
```

In the Radeon Cloud Profile page, paste the public key into **SSH Public Key** and select **Save Key**. Edit the project template, enable **SSH Access (advanced)**, save the template, and launch a new instance. SSH settings apply to newly launched instances; they do not retrofit an already running instance.

When the instance becomes ready, record the SSH host and port displayed by Radeon Cloud. Never upload or share the private key file named `radeon_cloud_ed25519`.

#### 2. Prepare the project in Radeon Cloud

Select **Open Notebook**, open a JupyterLab Terminal, then clone the repository and enter the project directory:

```bash
git clone https://github.com/xmolly929/private-study-agent-amd.git
cd private-study-agent-amd
```

Create and activate a virtual environment, then install the required dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a `.env` file from the provided example:

```bash
cp .env.example .env
```

Write your API key into `.env` securely by running the following command:

```bash
python -c "import getpass; from pathlib import Path; Path('.env').write_text('AMD_API_KEY=' + getpass.getpass('Enter AMD API key: ') + '\n', encoding='utf-8')"
```

When `Enter AMD API key:` appears, type your own key and press Enter. The key will not be displayed while you type. Do not enter `AMD_API_KEY=...` directly as a separate shell command, and do not include the key in screenshots.

#### 3. Start SSH Server in the cloud instance

The tested Radeon Cloud container image did not start an SSH server automatically. In the JupyterLab Terminal, install and start it:

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server
mkdir -p /run/sshd
chmod 700 /root/.ssh
chmod 600 /root/.ssh/authorized_keys
pgrep -x sshd >/dev/null || /usr/sbin/sshd
```

Verify the internal SSH port without displaying the public key:

```bash
timeout 2 bash -c '</dev/tcp/127.0.0.1/22' && echo "port 22 open" || echo "port 22 closed"
```

Continue only when the command reports `port 22 open`.

#### 4. Start and verify Streamlit

Start the Streamlit application in the project Terminal:

```bash
python -m streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 8501
```

Keep this Terminal open. In a second JupyterLab Terminal, run the following command. Radeon Cloud uses the instance ID (the value beginning with `u-`) as the cloud hostname, so the command reads it automatically:

```bash
curl "http://127.0.0.1:8501/spaces/$(hostname)/8501/_stcore/health"
```

The expected response is `ok`.

#### 5. Create the SSH tunnel on Windows

In a local Windows PowerShell window, run the following commands. PowerShell will ask for the temporary SSH host and port shown by Radeon Cloud:

```powershell
$RadeonSshHost = Read-Host "Enter the SSH host shown by Radeon Cloud"
$RadeonSshPort = Read-Host "Enter the SSH port shown by Radeon Cloud"

ssh -i "$env:USERPROFILE\.ssh\radeon_cloud_ed25519" `
  -p $RadeonSshPort `
  -N `
  -L 18501:127.0.0.1:8501 `
  "root@$RadeonSshHost"
```

At the first prompt, enter only the SSH host, such as `36.150.116.206`, without `root@`. At the second prompt, enter only the numeric SSH port, such as `31412`. Use the current values displayed for your own Radeon Cloud instance; they may change whenever an instance is relaunched.

On the first connection, verify that the host and port match the Radeon Cloud instance, then enter `yes` when SSH asks whether to trust the host key. A blank PowerShell window after connection is normal and means the tunnel is running. Keep both the PowerShell tunnel and the cloud Streamlit Terminal open.

#### 6. Open and use the agent

Keep the SSH tunnel PowerShell window open. Open a second local Windows PowerShell window and run:

```powershell
do {
  $RadeonInstanceId = (Read-Host "Enter the Radeon Cloud instance ID shown in Profile (starts with u-)").Trim()
} until ($RadeonInstanceId -match '^u-[a-zA-Z0-9-]+$')

$AgentUrl = "http://localhost:18501/spaces/$($RadeonInstanceId)/8501/"
Write-Host "Opening $AgentUrl"
Start-Process $AgentUrl
```

Enter only the instance ID, such as `u-9565-030a034a`, without `@`, `root@`, spaces, or a URL. Invalid input will be rejected and requested again. PowerShell will print and open the correct tunneled URL in the default browser.

The browser runs locally, while the Streamlit application, PDF processing, and API calls run from the Radeon Cloud instance. Upload a PDF and use any of the three study functions normally.

The direct Radeon Cloud public URL may return HTTP 502 or fail to establish a Streamlit WebSocket. The verified SSH tunnel procedure bypasses that reverse proxy limitation. This tunnel is available only on the computer holding the matching private SSH key; it is not a public application URL.

#### 7. Stop the deployment safely

When testing is complete:

1. Press `Ctrl+C` in the local PowerShell window running the SSH tunnel.
2. Press `Ctrl+C` in the Radeon Cloud Terminal running Streamlit.
3. Use **Destroy Instance** in Radeon Cloud when the instance is no longer needed to avoid consuming additional credits.

The `.env` file and SSH private key must not be shared or included in screenshots.

### 1. Radeon Cloud Instance

![Radeon Instance](assets/radeon-instance.png)

### 2. Environment Setup and Streamlit Launch

![Streamlit Launch](assets/radeon-streamlit-start.png)

### 3. Backend Health Check

![Health Check](assets/radeon-health-check.png)

### 4. External Access Limitation

![WebSocket Limitation](assets/radeon-websocket-limit.png)

## Architecture

```text
User uploads PDF
        ↓
PyMuPDF extracts text
        ↓
Task-specific instruction construction
        ↓
AMD Radeon Cloud OpenAI-compatible API
        ↓
Generated study support output
```

## Deployment Limitation

The application was successfully installed and started on Radeon Cloud.

The backend service was verified successfully through the health endpoint.

However, external Streamlit interaction was limited by the platform reverse proxy WebSocket handling.

This limitation affects the direct public browser route only and does not indicate a problem with the application implementation. Interactive PDF upload and model-backed question answering were successfully verified through the documented SSH tunnel.

The current MVP uses the OpenAI-compatible shared model API provided by AMD Radeon Cloud. It does not claim to perform complete model inference locally on a Radeon GPU.

## Local Development

### Requirements

- Python 3.11 or 3.12
- An AMD API key with access to `DeepSeek-V4-Flash`

Clone the repository and enter the project directory:

```powershell
git clone https://github.com/xmolly929/private-study-agent-amd.git
cd private-study-agent-amd
```

Create a virtual environment and install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

Open `.env` and replace the placeholder with your own API key:

```text
AMD_API_KEY=your_amd_api_key_here
```

Run the application on Windows:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Then open `http://localhost:8501` if the browser does not open automatically.

## API Configuration

The application uses:

- Base URL: `https://developer.amd.com.cn/radeon/api/v1`
- Endpoint: `/chat/completions`
- Model: `DeepSeek-V4-Flash`

The API key is read from the `AMD_API_KEY` environment variable. It is never hard-coded or displayed by the application.

## Security Notes

- The API key is stored locally in `.env`.
- `.env` and `.venv/` are excluded by `.gitignore`.
- No API keys, passwords, or other sensitive credentials are included in the repository.
- The SSH private key remains on the user's Windows computer and must never be uploaded to the repository or shared.
- Only the matching public key is saved in the Radeon Cloud Profile.

## Limitations

- Scanned PDFs are not supported because this minimal version does not include OCR.
- To limit model context usage, only the first 60,000 extracted characters are sent for large PDFs.
- Model generation uses a remote shared API rather than complete local Radeon GPU inference.
- The direct Radeon Cloud public route was affected by reverse proxy WebSocket handling. Interactive use was successfully verified through an SSH tunnel, which is available only from the computer holding the matching private key.

## Future Work

- Add ROCm-compatible local model serving.
- Improve Radeon GPU deployment and optimization.
- Build a more complete cloud deployment with reliable external WebSocket access.
